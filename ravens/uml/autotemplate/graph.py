from typing import Literal, Optional
import pathlib
import pandas as pd
import networkx as nx

from .clusions import UMLInclusions
from ravens.uml import common
from ravens.uml.data import UMLData


def _col(df, *cands):
    """Return the first existing column name from candidates, else None."""
    for c in cands:
        if c in df.columns:
            return c
    return None

def _hidden_connector_ids_from_diagramlinks(uml_data, path_contains: str | None = "SimplifiedDiagrams") -> set[int]:
    """
    Return ConnectorIDs that are hidden (Hidden == True) in uml_data.diagramlinks,
    optionally restricted to rows whose Path contains `path_contains`.
    """
    import re
    dl = getattr(uml_data, "diagramlinks", None)
    if dl is None or getattr(dl, "empty", True):
        return set()

    # Column names in your dump: ['DiagramID','ConnectorID','Geometry','Style','Hidden','Path']
    if "ConnectorID" not in dl.columns or "Hidden" not in dl.columns:
        return set()

    m = dl["Hidden"] == True
    if path_contains and "Path" in dl.columns:
        m &= dl["Path"].astype(str).str.contains(re.escape(path_contains), na=False)

    return {int(x) for x in dl.loc[m, "ConnectorID"].dropna().unique().tolist()}

class UMLGraphs:
    def __init__(self, uml_data=None, inclusions: Optional[UMLInclusions] = None):
        # If inclusions is provided and it has filtered_uml_data, prefer that and disable gating.
        if inclusions is not None and getattr(inclusions, "filtered_uml_data", None) is not None:
            self.uml_data = inclusions.filtered_uml_data
            self.inclusions = None  # graphs see only filtered world; no runtime allow()
        else:
            from ravens.uml.data import UMLData
            self.uml_data = uml_data if uml_data is not None else UMLData()
            self.inclusions = inclusions

        self._ensure_indexes()
        self.tag_name_filter = "ravensRole"
        self.object_tags    = self._build_object_tags()
        self.connector_tags = self._build_connector_tags()
        self._object_role_map = (
            self.object_tags["Value"].groupby(level="Object_ID").last().apply(
                lambda v: self._normalize_role(v, kind="node")
            ).to_dict()
        )
        self.H  = self.build_H()  # <-- use kwargs decided above
        self.HR = self.H.reverse(copy=False)
        self.A  = self.build_A()

    def _allow(self, kind: str, id_value: int) -> bool:
        inc = getattr(self, "inclusions", None)
        if inc is None:
            return True
        if hasattr(inc, "allow") and callable(getattr(inc, "allow")):
            return inc.allow(kind, int(id_value))
        # (fallback to dict-shaped behavior if you still support it)
        key_map = {
            "object":        "Object_ID",
            "connector":     "Connector_ID",
            "package":       "Package_ID",
            "diagram":       "Diagram_ID",
            "link_instance": "link_Instance_ID",
            "obj_instance":  "obj_Instance_ID",
        }
        vals = set(inc.get(key_map.get(kind), set()) or set())
        return (len(vals) == 0) or (int(id_value) in {int(v) for v in vals})


    def build_H(self) -> nx.DiGraph:
        """
        Generalization H (child -> parent). If inclusions is provided,
        nodes/edges are filtered via _allow().
        """
        H = nx.DiGraph()

        # --- nodes (Class only) ---
        for oid, row in self.uml_data.objects.iterrows():
            try:
                oid_i = int(oid)
            except Exception:
                continue
            if str(row.get("Object_Type", "")) != "Class":
                continue
            if not self._allow("object", oid_i):
                continue
            H.add_node(
                oid_i,
                Name=str(row.get("Name") or ""),
                ravensRole=self.role_for_object(oid_i),
                Package_ID=row.get("Package_ID"),
                Stereotype=row.get("Stereotype"),
            )

        if H.number_of_nodes() == 0:
            return H

        # --- edges (Generalization only) ---
        con = self.uml_data.connectors
        if con is None or con.empty:
            return H

        # tolerant column resolution
        c_type = "Connector_Type" if "Connector_Type" in con.columns else ("Type" if "Type" in con.columns else None)
        c_src  = "Start_Object_ID" if "Start_Object_ID" in con.columns else ("StartObjectID" if "StartObjectID" in con.columns else None)
        c_dst  = "End_Object_ID"   if "End_Object_ID"   in con.columns else ("EndObjectID"   if "EndObjectID"   in con.columns else None)
        c_id   = "Connector_ID"    if "Connector_ID"    in con.columns else ("ConnectorID"    if "ConnectorID"    in con.columns else None)
        if not all([c_type, c_src, c_dst]):
            return H  # cannot build edges without these

        # case-insensitive match for generalizations
        gen_mask = con[c_type].astype(str).str.strip().str.casefold() == "generalization"
        gen_rows = con.loc[gen_mask]

        # hidden labels
        hidden_cids = _hidden_connector_ids_from_diagramlinks(self.uml_data)

        for idx, crow in gen_rows.iterrows():
            # connector id: prefer column, else fall back to index
            cid_val = pd.to_numeric(crow.get(c_id), errors="coerce") if c_id is not None else pd.NA
            if pd.isna(cid_val):
                cid_val = pd.to_numeric(idx, errors="coerce")
            if pd.isna(cid_val):
                continue
            cid = int(cid_val)

            if cid in hidden_cids:
                continue  # skip hidden generalizations globally

            if not self._allow("connector", cid):
                continue

            child  = pd.to_numeric(crow.get(c_src), errors="coerce")
            parent = pd.to_numeric(crow.get(c_dst), errors="coerce")
            if pd.isna(child) or pd.isna(parent):
                continue
            child  = int(child)
            parent = int(parent)

            if child in H and parent in H and child != parent:
                H.add_edge(child, parent, Connector_ID=cid, Type="Generalization")

        return H

    # -------------------- A: associations --------------------
    def build_A(self) -> nx.MultiDiGraph:
        """
        Association/Aggregation/Composition graph; honors inclusions via:
          - nodes: 'object'
          - edges: 'connector'
          - link instances: 'link_instance'
          - diagrams: 'diagram'
        """
        A = nx.MultiDiGraph()

        # nodes
        for oid, row in self.uml_data.objects.iterrows():
            if str(row.get("Object_Type", "")) != "Class":
                continue
            if not self._allow("object", int(oid)):
                continue
            A.add_node(int(oid), **{
                "Name": str(row.get("Name") or ""),
                "ravensRole": self.role_for_object(int(oid)),
                "Package_ID": row.get("Package_ID"),
                "Stereotype": row.get("Stereotype"),
            })

        dl = getattr(self.uml_data, "diagramlinks", None)

        # hidden connectors
        hidden_cids = _hidden_connector_ids_from_diagramlinks(self.uml_data)

        if not isinstance(dl, pd.DataFrame) or dl.empty:
            return A

        ASSOCIATION_TYPES = {"Association", "Aggregation", "Composition"}
        diagrams_df = self.uml_data.diagrams
        cid_col = "ConnectorID" if "ConnectorID" in dl.columns else ("Connector_ID" if "Connector_ID" in dl.columns else None)
        did_col = "DiagramID"   if "DiagramID"   in dl.columns else ("Diagram_ID"   if "Diagram_ID"   in dl.columns else None)
        if cid_col is None or did_col is None:
            return A

        for cid, crow in self.uml_data.connectors.iterrows():
            # skip hidden associations
            if cid in hidden_cids:
                continue 

            ctype = str(crow.get("Connector_Type", ""))
            if ctype not in ASSOCIATION_TYPES:
                continue
            if not self._allow("connector", int(cid)):
                continue

            s_id, e_id = int(crow.Start_Object_ID), int(crow.End_Object_ID)
            if not (s_id in A and e_id in A):
                continue

            rows = dl.loc[dl[cid_col] == cid]
            if rows.empty:
                continue

            for iid, irow in rows.iterrows():
                # skip this connector instance if it's hidden on this diagram
                if bool(irow.get("Hidden", False)):
                    continue
                if not self._allow("link_instance", int(iid)):
                    continue
                did = int(irow[did_col])
                if not self._allow("diagram", did):
                    continue
                if did not in diagrams_df.index:
                    continue

                edge_attrs = {
                    "Diagram":        str(diagrams_df.loc[did].get("Name") or ""),
                    "DiagramID":      did,
                    "InstanceID":     int(iid),
                    "ConnectorID":    int(cid),
                    "Connector_Type": ctype,
                }

                label_info = common.parse_connector_label_info(irow, crow)
                mult_info = common.parse_multiplicity(label_info)
                start_mult = mult_info.get("start_mult", "")
                end_mult = mult_info.get("end_mult", "")

                try:
                    edges_w_dir = common.connector_directionality_from_labels(
                        label_info, connector_type=ctype, s_id=s_id, e_id=e_id
                    )
                except Exception:
                    edges_w_dir = [(s_id, e_id, ""), (e_id, s_id, "")]

                for u, v, lbl in edges_w_dir:
                    if u not in A or v not in A:
                        continue
                    oriented = common.orient_edge_attrs_for_direction(
                        edge_attrs.copy(),
                        u=u,
                        v=v,
                        s_id=s_id,
                        e_id=e_id,
                        start_mult=start_mult,
                        end_mult=end_mult,
                        objects_df=self.uml_data.objects,
                    )
                    oriented["label"] = lbl
                    A.add_edge(int(u), int(v), **oriented)

        return A

    # -------------------- utilities --------------------
    def _ensure_indexes(self):
        """Make sure core EA tables use their ID columns as index."""
        def set_idx(df, col):
            if isinstance(df, pd.DataFrame) and col in df.columns:
                return df if df.index.name == col else df.set_index(col, drop=False)
            return df

        uml = self.uml_data
        uml.objects = set_idx(getattr(uml, "objects", pd.DataFrame()), "Object_ID")
        uml.connectors = set_idx(getattr(uml, "connectors", pd.DataFrame()), "Connector_ID")
        uml.diagrams = set_idx(getattr(uml, "diagrams", pd.DataFrame()), "Diagram_ID")
        uml.packages = set_idx(getattr(uml, "packages", pd.DataFrame()), "Package_ID")
        uml.diagramlinks = getattr(uml, "diagramlinks", pd.DataFrame())
        uml.diagramobjects = getattr(uml, "diagramobjects", pd.DataFrame())

    @staticmethod
    def _first_col(df: pd.DataFrame, *candidates):
        """Return the first existing column name from candidates; else raise."""
        for c in candidates:
            if c in df.columns:
                return c
        raise KeyError(f"None of the columns {candidates!r} found in {list(df.columns)}")

    # -------------------- tags --------------------
    def _normalize_tag_rows(self, df: pd.DataFrame, id_col: str) -> pd.DataFrame:
        if df.empty:
            return pd.DataFrame(
                columns=[id_col, "Tag", "Value", "Notes", "GUID", "Source"]
            ).set_index([id_col, "Tag"])

        tag_col = self._first_col(df, "Property", "Tag", "Name")
        value_col = self._first_col(df, "Value", "VALUE", "TagValue", "TaggedValue")
        notes_col = "Notes" if "Notes" in df.columns else None
        guid_col = (
            self._first_col(df, "ea_guid", "EA_GUID", "Guid", "GUID")
            if any(c in df.columns for c in ("ea_guid", "EA_GUID", "Guid", "GUID"))
            else None
        )

        df = df[df[id_col].notna()].copy()

        out = pd.DataFrame(
            {
                id_col: pd.to_numeric(df[id_col], errors="coerce").astype("Int64"),
                "Tag": df[tag_col].astype(str).str.strip(),
                "Value": df[value_col].astype(str).str.strip(),
                "Notes": df[notes_col] if notes_col else pd.Series([None] * len(df)),
                "GUID": df[guid_col] if guid_col else pd.Series([None] * len(df)),
            }
        )
        out["Source"] = getattr(df, "_source_name", None) or "EA"

        memo_mask = out["Value"].str.strip().eq("<memo>")
        if memo_mask.any():
            out.loc[memo_mask & out["Notes"].notna(), "Value"] = out.loc[memo_mask, "Notes"]

        out[id_col] = pd.to_numeric(out[id_col], errors="coerce").astype("Int64")
        out = (
            out.dropna(subset=[id_col])
            .drop_duplicates(subset=[id_col, "Tag"], keep="last")
            .astype({id_col: "int64"}, copy=False)
            .set_index([id_col, "Tag"])
        )
        return out

    def _build_object_tags(self) -> pd.DataFrame:
        uml = self.uml_data
        frames = []
        for name in ("t_objectproperties", "objectproperties", "object_tags", "element_tags"):
            df = getattr(uml, name, None)
            if isinstance(df, pd.DataFrame) and not df.empty:
                df = df.copy()
                df._source_name = name
                if "Object_ID" not in df.columns and "ObjectID" in df.columns:
                    df = df.rename(columns={"ObjectID": "Object_ID"})
                frames.append(self._normalize_tag_rows(df, id_col="Object_ID"))

        if not frames:
            return pd.DataFrame(
                columns=["Value", "Notes", "GUID", "Source"],
                index=pd.MultiIndex.from_arrays([[], []], names=["Object_ID", "Tag"]),
            )

        out = pd.concat(frames, axis=0) if len(frames) > 1 else frames[0]

        # Keep only ravensRole
        if isinstance(out, pd.DataFrame) and not out.empty:
            tag_idx = out.index.get_level_values("Tag")
            out = out[tag_idx.str.casefold() == self.tag_name_filter.casefold()]

        # Restrict to known objects
        objs = uml.objects
        if isinstance(objs, pd.DataFrame) and not objs.empty:
            known = pd.to_numeric(objs.reset_index().get("Object_ID"), errors="coerce")
            out_ids = pd.to_numeric(out.index.get_level_values("Object_ID"), errors="coerce")
            out = out.loc[out_ids.isin(set(known.dropna().astype(int).tolist()))]

        return out.sort_index()

    def _build_connector_tags(self) -> pd.DataFrame:
        uml = self.uml_data
        frames = []
        for name in ("connectortags", "t_connectortag", "connector_tags"):
            df = getattr(uml, name, None)
            if isinstance(df, pd.DataFrame) and not df.empty:
                df = df.copy()
                df._source_name = name
                if "Connector_ID" not in df.columns and "ConnectorID" in df.columns:
                    df = df.rename(columns={"ConnectorID": "Connector_ID"})
                if "Connector_ID" not in df.columns and "ElementID" in df.columns:
                    df = df.rename(columns={"ElementID": "Connector_ID"})
                frames.append(self._normalize_tag_rows(df, id_col="Connector_ID"))

        if not frames:
            return pd.DataFrame(
                columns=["Value", "Notes", "GUID", "Source"],
                index=pd.MultiIndex.from_arrays([[], []], names=["Connector_ID", "Tag"]),
            )

        out = pd.concat(frames, axis=0) if len(frames) > 1 else frames[0]

        # Keep only ravensRole
        if isinstance(out, pd.DataFrame) and not out.empty:
            tag_idx = out.index.get_level_values("Tag")
            out = out[tag_idx.str.casefold() == self.tag_name_filter.casefold()]

        # Restrict to known connectors
        cons = uml.connectors
        if isinstance(cons, pd.DataFrame) and not cons.empty:
            known = pd.to_numeric(cons.reset_index().get("Connector_ID"), errors="coerce")
            out_ids = pd.to_numeric(out.index.get_level_values("Connector_ID"), errors="coerce")
            out = out.loc[out_ids.isin(set(known.dropna().astype(int).tolist()))]

        return out.sort_index()

    # -------------------- graph walks --------------------
    def walk(
        self,
        start_id: int,
        *,
        graph: str = "A",          # "A" (associations) or "H" (inheritance)
        direction: str | None = None,
        max_depth: int | None = None,
        include_start: bool = False,
        return_paths: bool = False,
        dedupe: bool = True,
        edge_pred=None,            # callable(u, v, edge_data) -> bool  | None
        node_pred=None,            # callable(n, node_data) -> bool     | None
    ):
        """
        BFS traversal that RETURNS A LIST.

        For graph="A": direction in {"out","in","undirected"} (default "undirected")
        For graph="H": direction in {"up","down","both"}      (default "down")
            - "up"   = to parents (H.successors)
            - "down" = to children (H.predecessors)
        """
        if graph == "A":
            G = getattr(self, "A", None)
            if G is None:
                raise RuntimeError("Association graph 'A' is not built on this instance.")
            direction = (direction or "undirected").lower()
            if direction not in ("out", "in", "undirected"):
                raise ValueError("direction must be 'out', 'in', or 'undirected' for graph='A'")
        elif graph == "H":
            G = getattr(self, "H", None)
            if G is None:
                raise RuntimeError("Inheritance graph 'H' is not built on this instance.")
            direction = (direction or "down").lower()
            if direction not in ("up", "down", "both"):
                raise ValueError("direction must be 'up', 'down', or 'both' for graph='H'")
        else:
            raise ValueError("graph must be 'A' or 'H'")

        if start_id not in G:
            return []

        from collections import deque

        def neighbors_A(n: int):
            if direction == "out":
                neighs = set(G.successors(n))
            elif direction == "in":
                neighs = set(G.predecessors(n))
            else:
                neighs = set(G.successors(n)) | set(G.predecessors(n))
            if edge_pred is None:
                return list(neighs)
            kept = []
            for v in neighs:
                ok = False
                if G.has_edge(n, v):
                    for _, d in G.get_edge_data(n, v).items():
                        if edge_pred(n, v, d):
                            ok = True
                            break
                if not ok and direction in ("in", "undirected") and G.has_edge(v, n):
                    for _, d in G.get_edge_data(v, n).items():
                        if edge_pred(v, n, d):
                            ok = True
                            break
                if ok:
                    kept.append(v)
            return kept

        def neighbors_H(n: int):
            up_parents = set(G.successors(n))     # to parents
            down_children = set(G.predecessors(n))  # to children
            if direction == "up":
                neighs = up_parents
            elif direction == "down":
                neighs = down_children
            else:
                neighs = up_parents | down_children
            if edge_pred is None:
                return list(neighs)
            kept = []
            for v in neighs:
                if edge_pred(n, v, {}):  # DiGraph; attributes not used here
                    kept.append(v)
            return kept

        get_neighbors = neighbors_A if graph == "A" else neighbors_H

        def node_name(x: int) -> str:
            try:
                return str(self.uml_data.objects.loc[int(x)]["Name"]) or ""
            except Exception:
                return ""

        q = deque()
        visited = set()
        results = []

        if include_start and (node_pred is None or node_pred(start_id, G.nodes.get(start_id, {}))):
            results.append((start_id, [start_id]) if return_paths else start_id)

        q.append((start_id, [start_id], 0))
        if dedupe:
            visited.add(start_id)

        while q:
            node, path, depth = q.popleft()

            if (max_depth is not None) and (depth >= max_depth):
                continue

            for v in sorted(get_neighbors(node), key=lambda x: node_name(x).casefold()):
                if dedupe and (v in visited):
                    continue
                if (node_pred is not None) and (not node_pred(v, G.nodes.get(v, {}))):
                    continue

                new_path = path + [v]
                results.append((v, new_path) if return_paths else v)

                q.append((v, new_path, depth + 1))
                if dedupe:
                    visited.add(v)

        return results

    # -------------------- reports on H/A --------------------
    def report_root_connections(self) -> list[tuple[str, str, str]]:
        """
        Find classes connected to 'Root' by association/aggregation in A.
        Returns list of (OtherClassName, ConnectorType, DiagramName).
        """
        root_ids = [int(i) for i, r in self.uml_data.objects["Name"].items() if str(r) == "Root"]
        if not root_ids:
            return []
        root_id = root_ids[0]

        out = []
        for u, v, k, d in self.A.edges(keys=True, data=True):
            if u == root_id or v == root_id:
                other = v if u == root_id else u
                out.append(
                    (
                        str(self.uml_data.objects.loc[other]["Name"]),
                        str(d.get("Connector_Type") or ""),
                        str(d.get("Diagram") or ""),
                    )
                )
        out = sorted(set(out), key=lambda t: (t[0].casefold(), t[1], t[2].casefold()))
        return out

    def report_container_neighborhood(self) -> list[tuple[str, list[str]]]:
        """
        For each rootClass, list the contiguous chain of notConcrete parents in H
        (closest first). Report-only to guide placement.
        """
        def role(n): 
            r = (self.role_for_object(int(n)) or "").strip()
            return self._normalize_role(r, kind="node") or ""

        roots = [n for n in self.H.nodes if role(n) == "rootClass"]

        not_concrete = {
            "containerClass",
            "substitutableClass",
            "inheritOnlyClass",
            "embeddedInheritOnlyClass",  # NEW
            "yellowClass",
            "compoundClass",
            "",
        }

        rows = []
        for r in sorted(roots, key=lambda n: str(self.uml_data.objects.loc[n]["Name"]).casefold()):
            chain = []
            frontier = [r]
            seen = set([r])
            while frontier:
                cur = frontier.pop()
                for parent in self.H.successors(cur):  # child -> parent
                    if parent in seen:
                        continue
                    seen.add(parent)
                    if role(parent) in not_concrete:
                        chain.append(str(self.uml_data.objects.loc[parent]["Name"]))
                        frontier.append(parent)  # keep climbing only through notConcrete
            rows.append((str(self.uml_data.objects.loc[r]["Name"]), chain))
        return rows

    def report_substitutable_coverage(self) -> list[dict]:
        """
        For each substitutableClass node, list concrete descendants and whether each
        has a canonical definition under Root (i.e., is a rootClass).
        """
        def name(n): return str(self.uml_data.objects.loc[n]["Name"])
        def role(n): return (self.role_for_object(int(n)) or "").strip()

        concrete = {n for n in self.H.nodes if role(n) in ("rootClass", "embeddedClass")}
        roots    = {n for n in self.H.nodes if role(n) == "rootClass"}
        subs     = [n for n in self.H.nodes if role(n) == "substitutableClass"]

        rows = []
        for s in sorted(subs, key=lambda n: name(n).casefold()):
            desc = {d for d in nx.descendants(self.HR, s) if d in concrete}
            variants = []
            for d in sorted(desc, key=lambda n: name(n).casefold()):
                variants.append({
                    "variant": name(d),
                    "concreteRole": role(d),
                    "emittedAsCanonical": bool(d in roots),
                    "referencePathIfEmitted": f"Root/{name(d)}" if d in roots else ""
                })
            rows.append({
                "substitutable": name(s),
                "variant_count": len(variants),
                "variants": variants
            })
        return rows

    def validate_h_only_expectations(self) -> dict:
        """
        Lightweight H-only checks:
        - Walking down from any rootClass in HR should NOT pass through embeddedClass nodes.
        - Every substitutableClass has at least one concrete option (by H/HR).
        """
        def name(n): return str(self.uml_data.objects.loc[n]["Name"])
        def role(n): return (self.role_for_object(int(n)) or "").strip()

        issues = {"embedded_below_root": [], "substitutable_with_no_variants": []}

        roots    = [n for n in self.H.nodes if role(n) == "rootClass"]
        concrete = {n for n in self.H.nodes if role(n) in ("rootClass", "embeddedClass")}
        subs     = [n for n in self.H.nodes if role(n) == "substitutableClass"]

        # embedded below roots (in H-only)
        for r in roots:
            bad = []
            for d in nx.descendants(self.HR, r):
                if role(d) == "embeddedClass":
                    bad.append(name(d))
            if bad:
                issues["embedded_below_root"].append({"root": name(r), "embedded_found": sorted(set(bad))})

        # substitutable with no concrete variants
        for s in subs:
            has_variant = any(d in concrete for d in nx.descendants(self.HR, s))
            if not has_variant:
                issues["substitutable_with_no_variants"].append(name(s))

        return issues

    # -------------------- not-concrete role retagging (H/HR-based) --------------------
    def _role_of(self, oid: int) -> Optional[str]:
        try:
            return self.H.nodes[int(oid)].get("ravensRole")
        except Exception:
            return None

    def _name_of(self, oid: int) -> str:
        try:
            return str(self.H.nodes[int(oid)].get("Name") or "")
        except Exception:
            return ""

    def _concrete_set(self) -> set[int]:
        return {
            int(n)
            for n, d in self.H.nodes(data=True)
            if d.get("ravensRole") in ("rootClass", "embeddedClass")
        }

    def _notconcrete_pool(self) -> set[int]:
        concrete = self._concrete_set()
        def is_literal_root(n: int) -> bool:
            try:
                return (str(self.uml_data.objects.loc[int(n), "Name"]).strip() == "Root")
            except Exception:
                return False
        return {
            int(n)
            for n, d in self.H.nodes(data=True)
            if int(n) not in concrete and not is_literal_root(int(n))
        }

    def retag_notconcrete_roles(
        self,
        *,
        write_back: bool = False,
        require_two_leaf_variants: bool = True,
    ) -> dict:
        """
        Compute notConcrete roles from H/HR:

        • substitutableClass: notConcrete node with >= 2 concrete descendants
          (leaf-only if require_two_leaf_variants=True).
        • containerClass: notConcrete nodes on any contiguous chain above a rootClass (in H),
          minus substitutable.
        • inheritOnlyClass: (a) notConcrete ancestors of any embeddedClass (minus substitutable),
                            plus (b) remaining notConcrete with <= 1 concrete descendant.
        • Precedence: substitutable > container > inheritOnly.

        If write_back=True: updates node['ravensRole'] in H; (A is not mutated).
        """
        H, HR = self.H, self.HR

        concrete = self._concrete_set()
        notconcrete = self._notconcrete_pool()
        roots = {n for n in concrete if self._role_of(n) == "rootClass"}
        embedded = {n for n in concrete if self._role_of(n) == "embeddedClass"}

        def concrete_descendants(n: int) -> set[int]:
            if n not in HR:
                return set()
            ds = nx.descendants(HR, n)
            return {x for x in ds if x in concrete}

        def leaf_concrete_descendants(n: int) -> set[int]:
            leaves = set()
            for c in concrete_descendants(n):
                kids = {k for k in HR.successors(c) if k in concrete}
                if not kids:
                    leaves.add(c)
            return leaves

        substitutable = {
            n
            for n in notconcrete
            if len(leaf_concrete_descendants(n) if require_two_leaf_variants else concrete_descendants(n)) >= 2
        }

        # containers: contiguous notConcrete ancestors of roots
        containers = set()
        from collections import deque
        for r in roots:
            if r not in H:
                continue
            q, seen = deque([r]), {r}
            while q:
                cur = q.popleft()
                for p in H.successors(cur):  # child -> parent
                    if p in seen:
                        continue
                    seen.add(p)
                    if p in notconcrete and p not in substitutable:
                        containers.add(p)
                        q.append(p)

        # inheritOnly: (a) ancestors of embedded (minus substitutable)
        anc_of_embedded = set()
        for e in embedded:
            if e in H:
                anc_of_embedded |= nx.ancestors(H, e)
        inherit_from_embedded = (anc_of_embedded & notconcrete) - substitutable

        # (b) remaining with <= 1 concrete descendant
        remaining = notconcrete - substitutable - containers - inherit_from_embedded
        inherit_default = {n for n in remaining if len(concrete_descendants(n)) <= 1}

        inheritonly = inherit_from_embedded | inherit_default

        result_sets = {
            "substitutableClass": sorted(substitutable),
            "containerClass": sorted(containers),
            "inheritOnlyClass": sorted(inheritonly),
            "concrete": sorted(concrete),
            "notConcrete_pool": sorted(notconcrete),
        }

        if write_back:
            # clear & set on H (only pool)
            for n in notconcrete:
                self.H.nodes[n]["ravensRole"] = None
            for n in containers:
                self.H.nodes[n]["ravensRole"] = "containerClass"
            for n in inheritonly:
                self.H.nodes[n]["ravensRole"] = "inheritOnlyClass"
            for n in substitutable:
                self.H.nodes[n]["ravensRole"] = "substitutableClass"

            # refresh map from H (objects table remains unchanged)
            self._object_role_map = {
                int(n): d.get("ravensRole") for n, d in self.H.nodes(data=True)
            }

        return result_sets

    # -------------------- convenience accessors --------------------
    def tags_for_object(self, object_id: int) -> dict:
        if not isinstance(self.object_tags, pd.DataFrame) or self.object_tags.empty:
            return {}
        try:
            sub = self.object_tags.loc[int(object_id)]
        except Exception:
            return {}
        return {k: ("" if pd.isna(v) else str(v)) for k, v in sub["Value"].items()}

    def tags_for_connector(self, connector_id: int) -> dict:
        if not isinstance(self.connector_tags, pd.DataFrame) or self.connector_tags.empty:
            return {}
        try:
            sub = self.connector_tags.loc[int(connector_id)]
        except Exception:
            return {}
        return {k: ("" if pd.isna(v) else str(v)) for k, v in sub["Value"].items()}

    def _normalize_role(self, role: str, *, kind: Literal["node", "edge"]) -> Optional[str]:
        """
        Normalize ravensRole values coming from EA tagged values.
        - Accepts case-insensitive / underscore / space variants
        - Preserves unknown roles (so they stay visible for debugging)
        """
        if role is None:
            return None
        raw = str(role).strip()
        if not raw:
            return None

        # normalize for alias lookup
        key = raw.casefold().replace("_", "").replace(" ", "")

        if kind == "node":
            aliases = {
                # canonical concrete / structural roles
                "rootclass": "rootClass",
                "containerclass": "containerClass",
                "embeddedclass": "embeddedClass",
                "substitutableclass": "substitutableClass",

                # inherit-only semantics
                "inheritonlyclass": "inheritOnlyClass",
                "inheritonly": "inheritOnlyClass",

                # your new role
                "embeddedinheritonlyclass": "embeddedInheritOnlyClass",
                "embeddedinheritonly": "embeddedInheritOnlyClass",
                "embeddedinheritonlycls": "embeddedInheritOnlyClass",

                # legacy / misc roles you already use
                "compoundclass": "compoundClass",
                "yellowclass": "yellowClass",
                "white": "white",
            }
            return aliases.get(key, raw)

        # edge roles (keep what you already had, just normalize lookup)
        aliases = {
            "referenceconnector": "referenceConnector",
            "embeddedconnector": "embeddedConnector",
        }
        return aliases.get(key, raw)

    def role_for_object(self, object_id: int):
        return self._object_role_map.get(int(object_id))


    # -------------------- (optional) EA script export --------------------
    def export_ea_jscript_all(
        self,
        role_sets: dict | None = None,
        out_path: str | None = None,
        print_to_console: bool = True,
    ) -> str:
        """
        Emit a single EA JScript that updates ravensRole for *only* the IDs passed in.
        - Does NOT clear all not-concrete tags globally.
        - Clears only the union of (inheritOnly|container|substitutable) provided.
        - Skips 'Root' by name.
        - Does not overwrite concrete roles (rootClass / embeddedClass).
        - Assumes role_sets are already disjoint (overlap handled by guess function).
        """
        if role_sets is None:
            raise ValueError("export_ea_jscript_all: role_sets must be provided (disjoint).")

        inh_ids = sorted({int(x) for x in role_sets.get("inheritOnlyClass", []) if x is not None})
        con_ids = sorted({int(x) for x in role_sets.get("containerClass", []) if x is not None})
        sub_ids = sorted({int(x) for x in role_sets.get("substitutableClass", []) if x is not None})

        # Defensive overlap check (won't mutate; just warns in the script console)
        overlap_inh_con = set(inh_ids) & set(con_ids)
        overlap_inh_sub = set(inh_ids) & set(sub_ids)
        overlap_con_sub = set(con_ids) & set(sub_ids)

        all_ids = sorted(set(inh_ids) | set(con_ids) | set(sub_ids))

        def fmt_array(name, items):
            if not items:
                return f"var {name} = [];"
            CHUNK = 25
            lines = []
            for i in range(0, len(items), CHUNK):
                lines.append(", ".join(str(v) for v in items[i:i+CHUNK]))
            inner = ",\n    ".join(lines)
            return f"var {name} = [\n    {inner}\n];"

        script = f"""//!INC Local Scripts.EAConstants-JScript

    // Update ravensRole for selected elements only.
    // NOTE: This script *only* clears/sets IDs we pass in. It will not touch any others.

    {fmt_array("ALL_IDS", all_ids)}
    {fmt_array("INHERITONLY_IDS", inh_ids)}
    {fmt_array("CONTAINER_IDS",   con_ids)}
    {fmt_array("SUBSTITUTABLE_IDS", sub_ids)}

    // --- helpers ---
    function setMsg(label, arr) {{
        Session.Output(label + " (" + arr.length + "): " + (arr.length ? arr.slice(0, 10).join(", ") + (arr.length>10?" ...":"") : "[]"));
    }}

    function clearSelected(ids) {{
        for (var i=0; i<ids.length; i++) {{
            var el = Repository.GetElementByID(ids[i]);
            if (!el) continue;
            if (el.Name && el.Name === "Root") continue;

            var tv = null;
            try {{ tv = el.TaggedValues.GetByName("ravensRole"); }} catch(e) {{ tv = null; }}
            if (tv != null) {{
                // Only clear if it's one of the not-concrete roles we're managing
                if (tv.Value === "containerClass" || tv.Value === "substitutableClass" || tv.Value === "inheritOnlyClass") {{
                    tv.Value = "";
                    tv.Update();
                    el.TaggedValues.Refresh();
                }}
            }}
            el.Update();
        }}
    }}

    function setRoleByList(idList, roleValue) {{
        for (var i=0; i<idList.length; i++) {{
            var id = idList[i];
            var el = Repository.GetElementByID(id);
            if (!el) continue;
            if (el.Name && el.Name === "Root") continue;

            var tv = null;
            try {{ tv = el.TaggedValues.GetByName("ravensRole"); }} catch(e) {{ tv = null; }}
            if (tv == null) {{
                tv = el.TaggedValues.AddNew("ravensRole", "");
            }}

            // don't overwrite concrete roles
            if (tv.Value === "rootClass" || tv.Value === "embeddedClass") continue;

            // skip if already the desired value to minimize churn
            if (tv.Value === roleValue) continue;

            tv.Value = roleValue;
            tv.Update();
            el.TaggedValues.Refresh();
            el.Update();
        }}
    }}

    function main() {{
        Session.Output("Re-tagging selected not-concrete roles: starting...");
        setMsg("inheritOnly IDs", INHERITONLY_IDS);
        setMsg("container IDs", CONTAINER_IDS);
        setMsg("substitutable IDs", SUBSTITUTABLE_IDS);

        // Clear only those we will (re)set:
        clearSelected(ALL_IDS);

        // Because sets are expected disjoint, order is irrelevant; keep it stable.
        setRoleByList(INHERITONLY_IDS, "inheritOnlyClass");
        setRoleByList(CONTAINER_IDS,   "containerClass");
        setRoleByList(SUBSTITUTABLE_IDS, "substitutableClass");

        // Warn if overlaps (should be none if guess function enforces precedence)
        var warn = [];
        if ({'true' if overlap_inh_con else 'false'}) warn.push("inheritOnly ∩ container overlap exists");
        if ({'true' if overlap_inh_sub else 'false'}) warn.push("inheritOnly ∩ substitutable overlap exists");
        if ({'true' if overlap_con_sub else 'false'}) warn.push("container ∩ substitutable overlap exists");
        if (warn.length) {{
            for (var i=0; i<warn.length; i++) Session.Output("WARNING: " + warn[i]);
        }}

        Session.Output("Done. Updated " + ALL_IDS.length + " element(s).");
    }}

    main();
    """

        if print_to_console:
            print(script)
        if out_path:
            import pathlib
            p = pathlib.Path(out_path)
            p.write_text(script, encoding="utf-8")
        return script


