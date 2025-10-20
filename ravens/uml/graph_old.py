import os
import re
import glob
import pandas as pd
import networkx as nx
from typing import Literal, Iterable, Optional

from ravens.uml import clusions
from ravens.uml import UMLData, UMLExclusions, validate
from ravens.uml.visualize import UMLVisualizer
from ravens import jps


from typing import Literal
import pandas as pd
import networkx as nx
import re

class UMLGraphsEnhanced:
    """
    JPS rewrite of the UMLGraphs class that constructs the graphs in a way that is
    parseable for validation and ultimately JSON creation.
    Tag-driven: node/edge meaning should come from tags, not colors.
    """

    # -------------------- init --------------------
    def __init__(self, uml_data=None, exclusions=None, inclusions=None, schema_template=None):
        if uml_data is None:
            uml_data = UMLData()
        self.uml_data = uml_data
        self.exclusions = UMLExclusions() if exclusions is None else exclusions

        # inclusions has the following keys:
        # 'Object_ID', 'obj_Instance_ID', 'edge_Instance_ID', 'Connector_ID', 'Diagram_ID', 'Package_ID'
        if inclusions is not None:
            inclusions = inclusions or {}
            self.inclusions = inclusions
            self._include_sets = {
                "object":             set(inclusions.get("Object_ID", [])),
                "obj_instance":       set(inclusions.get("obj_Instance_ID", [])),
                "connector_instance": set(inclusions.get("edge_Instance_ID", [])),
                "connector":          set(inclusions.get("Connector_ID", [])),
                "package":            set(inclusions.get("Package_ID", [])),
            }

        # Only keep this tag
        self.tag_name_filter = "ravensRole"

        # Tag tables (built from uml_data’s EA tables)
        self._ensure_indexes()
        self.object_tags    = self._build_object_tags()
        self.connector_tags = self._build_connector_tags()

        self._object_role_map = (
            self.object_tags["Value"].groupby(level="Object_ID").last().apply(
                lambda v: self._normalize_role(v, kind="node")
            ).to_dict()
        )

        # self.graph = self.build_association_graph(inclusions=clusions.get_inclusions(uml_data, package='RAVENS'))

        self.H  = self.build_generalization_graph()          # child -> parent
        self.HR = self.H.reverse(copy=False)                 # parent -> child


        if schema_template is not None:
            self._build_subgraphs_from_template(schema_template)

    # -------------------- graph build --------------------
    def build_graph(self) -> nx.MultiDiGraph:
        G = nx.MultiDiGraph()
        G = self._add_enhanced_class_nodes_to_graph(G)
        G = self._add_enhanced_edges_to_graph(G)
        return G


    def _add_enhanced_class_nodes_to_graph(self, G: nx.MultiDiGraph) -> nx.MultiDiGraph:
        # Optional perf: pre-group diagramobjects by Object_ID
        do = self.uml_data.diagramobjects
        by_obj = do.groupby("Object_ID", sort=False) if isinstance(do, pd.DataFrame) and "Object_ID" in do.columns else None

        for oid, row in self.uml_data.objects.iterrows():
            # Inclusion & type filter 
            if (
                not self.inclusions is not None and self._is_included(oid, "object")
                or row.Object_Type != "Class"
                or oid in self.exclusions.object_ids
                or row.Package_ID in self.exclusions.package_ids
            ):
                continue

            node_attrs = {
                "Name": str(row.Name),
                "Object_Type": row.Object_Type,
                "Package_ID": row.Package_ID,
                "Stereotype": row.get("Stereotype", None),
            }
            node_role = self.role_for_object(int(oid))
            node_attrs["ravensRole"] = node_role

            # ---------- gather instance-level data ----------
            if by_obj is not None and oid in by_obj.groups:
                instances = by_obj.get_group(oid)
            else:
                instances = pd.DataFrame(columns=["Diagram_ID", "Object_ID", "InstanceID"])

            inst_attrs = {
                "Package_ID":   [],
                "Package_Name": [],
                "Instance_ID":  [],
                "DiagramName":  [],
            }

            for iid, inst in instances.iterrows():
                if not self._is_included(iid, "obj_instance"):
                    continue

                # Diagram id (compat for DiagramID vs Diagram_ID on diagramobjects)
                did = inst["Diagram_ID"] if "Diagram_ID" in inst.index else inst.get("DiagramID")
                if pd.isna(did):
                    continue
                did = int(did)

                if did not in self.uml_data.diagrams.index:
                    continue

                pkg_id = int(self.uml_data.diagrams.loc[did]["Package_ID"])
                if not self._is_included(pkg_id, "package"):
                    continue

                inst_attrs["Package_ID"].append(pkg_id)
                if pkg_id in self.uml_data.packages.index:
                    inst_attrs["Package_Name"].append(self.uml_data.packages.loc[pkg_id]["Name"])
                else:
                    inst_attrs["Package_Name"].append(None)
                inst_attrs["Instance_ID"].append(int(iid))
                inst_attrs["DiagramName"].append(self.uml_data.diagrams.loc[did]["Name"])

            # attach instance details only if any survived filtering
            if any(len(v) for v in inst_attrs.values()):
                node_attrs["instances"] = inst_attrs

            G.add_node(int(oid), **node_attrs)

        return G

    # -------------------- edges --------------------
    def _add_enhanced_edges_to_graph(self, G: nx.MultiDiGraph) -> nx.MultiDiGraph:
        dl = self.uml_data.diagramlinks
        if not isinstance(dl, pd.DataFrame) or dl.empty:
            return G
        cid_col = "ConnectorID" if "ConnectorID" in dl.columns else ("Connector_ID" if "Connector_ID" in dl.columns else None)
        if cid_col is None:
            return G
        did_col_cand = ("DiagramID", "Diagram_ID")

        for cid, crow in self.uml_data.connectors.iterrows():
            s_id, e_id = crow.Start_Object_ID, crow.End_Object_ID
            if not all(n in G for n in (s_id, e_id)):
                continue
            if not all(self._is_included(n, "object") for n in (s_id, e_id)):
                continue
            if not self._is_included(cid, "connector"):
                continue

            # All diagram instances for this connector
            do_insts = dl.loc[dl[cid_col] == cid]

            for iid, irow in do_insts.iterrows():  # iid is row index (instance id)
                # diagram id column on diagramlinks may vary
                did = None
                for dcol in did_col_cand:
                    if dcol in irow.index:
                        did = irow[dcol]
                        break
                if pd.isna(did):
                    continue
                did = int(did)

                if did not in self.uml_data.diagrams.index:
                    continue

                # Ensure instance occurs in included package
                pkg_id = int(self.uml_data.diagrams.loc[did]["Package_ID"])
                if not self._is_included(pkg_id, "package"):
                    continue

                # Base attrs (orientation-independent) - tag-first
                edge_attrs = {
                    "Diagram":        self.uml_data.diagrams.loc[did]["Name"],
                    "DiagramID":      did,
                    "InstanceID":     int(iid),
                    "ConnectorID":    int(cid),
                    "Connector_Type": crow.Connector_Type,
                    # "ravensRole":     self.role_for_connector(int(cid)),
                }

                # Parse labels & multiplicity once (relative to canonical Start/End)
                label_info   = jps.parse_connector_label_info(irow, crow)
                mult_info    = jps.parse_multiplicity(label_info)  # {'start_mult':..., 'end_mult':...}
                start_mult   = mult_info.get("start_mult", "")
                end_mult     = mult_info.get("end_mult", "")

                # Get directed edges from labels
                edges_w_dir = jps.connector_directionality_from_labels(
                    label_info,
                    connector_type=crow.Connector_Type,
                    s_id=s_id,
                    e_id=e_id,
                )

                for u, v, lbl in edges_w_dir:
                    oriented = jps.orient_edge_attrs_for_direction(
                        edge_attrs.copy(),  # copy to keep base attrs per edge
                        u=u, v=v,
                        s_id=s_id, e_id=e_id,
                        start_mult=start_mult, end_mult=end_mult,
                        objects_df=self.uml_data.objects,
                    )
                    oriented["label"] = lbl
                    G.add_edge(int(u), int(v), **oriented)

        return G


    def _ensure_indexes(self):
        """Make sure core EA tables use their ID columns as index."""
        def set_idx(df, col):
            if isinstance(df, pd.DataFrame) and col in df.columns:
                return df if df.index.name == col else df.set_index(col, drop=False)
            return df

        uml = self.uml_data
        uml.objects        = set_idx(getattr(uml, "objects",        pd.DataFrame()), "Object_ID")
        uml.connectors     = set_idx(getattr(uml, "connectors",     pd.DataFrame()), "Connector_ID")
        uml.diagrams       = set_idx(getattr(uml, "diagrams",       pd.DataFrame()), "Diagram_ID")
        uml.packages       = set_idx(getattr(uml, "packages",       pd.DataFrame()), "Package_ID")
        uml.diagramlinks   = getattr(uml, "diagramlinks",   pd.DataFrame())
        uml.diagramobjects = getattr(uml, "diagramobjects", pd.DataFrame())

    @staticmethod
    def _first_col(df: pd.DataFrame, *candidates):
        """Return the first existing column name from candidates; else raise."""
        for c in candidates:
            if c in df.columns:
                return c
        raise KeyError(f"None of the columns {candidates!r} found in {list(df.columns)}")
    
    def _is_literal_root(self, oid: int) -> bool:
        """True if this node's Name is exactly 'Root' (after stripping)."""
        try:
            return ((self.graph.nodes[int(oid)].get("Name") or "").strip() == "Root")
        except Exception:
            return False

    def _literal_root_ids(self) -> set[int]:
        """All Object_IDs whose Name is literally 'Root'."""
        return {int(n) for n, d in self.graph.nodes(data=True)
                if (d.get("Name") or "").strip() == "Root"}
    

    # -------------------- core builders --------------------
    def _normalize_tag_rows(self, df: pd.DataFrame, id_col: str) -> pd.DataFrame:
        if df.empty:
            return pd.DataFrame(
                columns=[id_col, "Tag", "Value", "Notes", "GUID", "Source"]
            ).set_index([id_col, "Tag"])

        tag_col   = self._first_col(df, "Property", "Tag", "Name")
        value_col = self._first_col(df, "Value", "VALUE", "TagValue", "TaggedValue")
        notes_col = "Notes" if "Notes" in df.columns else None
        guid_col  = self._first_col(df, "ea_guid", "EA_GUID", "Guid", "GUID") if any(
            c in df.columns for c in ("ea_guid", "EA_GUID", "Guid", "GUID")
        ) else None

        df = df[df[id_col].notna()].copy()

        out = pd.DataFrame({
            id_col : pd.to_numeric(df[id_col], errors="coerce").astype("Int64"),
            "Tag"  : df[tag_col].astype(str).str.strip(),
            "Value": df[value_col].astype(str).str.strip(),
            "Notes": df[notes_col] if notes_col else pd.Series([None]*len(df)),
            "GUID" : df[guid_col] if guid_col else pd.Series([None]*len(df)),
        })
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
        """
        Build a normalized (Object_ID, Tag) -> {Value, Notes, GUID, Source} table
        using ONLY EA's element tag tables (no xref fallback).
        Keeps only rows where Tag == self.tag_name_filter (e.g., "ravensRole").
        """
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
            # empty, correctly shaped DF
            return pd.DataFrame(
                columns=["Value", "Notes", "GUID", "Source"],
                index=pd.MultiIndex.from_arrays([[], []], names=["Object_ID", "Tag"])
            )

        out = pd.concat(frames, axis=0) if len(frames) > 1 else frames[0]

        # Keep only desired tag (e.g., ravensRole), case-insensitive
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
                df = df.copy(); df._source_name = name
                if "Connector_ID" not in df.columns and "ConnectorID" in df.columns:
                    df = df.rename(columns={"ConnectorID": "Connector_ID"})
                # Some exports use 'ElementID' instead of 'Connector_ID'
                if "Connector_ID" not in df.columns and "ElementID" in df.columns:
                    df = df.rename(columns={"ElementID": "Connector_ID"})
                frames.append(self._normalize_tag_rows(df, id_col="Connector_ID"))
        if not frames:
            return pd.DataFrame(columns=["Value", "Notes", "GUID", "Source"],
                                index=pd.MultiIndex.from_arrays([[], []], names=["Connector_ID", "Tag"]))
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
    
        # -------------------- generalization (H) --------------------
    def build_generalization_graph(self) -> nx.DiGraph:
        """
        Build H (Generalization only) as a DiGraph oriented child -> parent.
        We add ALL class nodes so graph ops never crash even if a node has no edges.
        """
        H = nx.DiGraph()
        # include all class nodes with the same attributes available in G
        H.add_nodes_from((n, dict(self.graph.nodes[n])) for n in self.graph.nodes())

        # EA convention: for Generalization connectors, Start_Object_ID = child, End_Object_ID = parent
        for cid, crow in self.uml_data.connectors.iterrows():
            if str(crow.Connector_Type) != "Generalization":
                continue
            child  = int(crow.Start_Object_ID)
            parent = int(crow.End_Object_ID)
            if child in H and parent in H:
                H.add_edge(child, parent, Connector_ID=int(cid))
        return H

    # -------------------- role re-tagging (notConcrete) --------------------
    def reclassify_not_concrete_roles(self, *, apply=True) -> dict:
        """
        Unset all existing notConcrete tags and recompute them from H/HR.
        Concrete roles (rootClass, embeddedClass) are treated as ground truth and preserved.

        Rules (tightened):
          • substitutableClass: any notConcrete node that is a descendant of a concrete node in HR.
          • containerClass: climb upward in H from EACH rootClass through contiguous notConcrete parents;
                            every such parent becomes containerClass (unless already substitutable).
          • inheritOnlyClass: (a) any notConcrete ancestor of an embeddedClass in H, except those marked substitutable;
                              (b) everything notConcrete that remains after the two rules above.

        Precedence when overlaps occur: substitutableClass > containerClass > inheritOnlyClass.

        Returns a dict with sets and counts for review. If apply=False, nothing is written back.
        """
        # Current roles
        roles = {int(n): (self.graph.nodes[n].get("ravensRole") or "").strip() for n in self.graph.nodes()}
        concrete_roles = {"rootClass", "embeddedClass"}
        notconcrete_roles = {"containerClass", "substitutableClass", "inheritOnlyClass", "yellowClass", "compoundClass", ""}

        # Partition
        concrete   = {n for n, r in roles.items() if r in concrete_roles}
        roots      = {n for n, r in roles.items() if r == "rootClass"}
        embeddeds  = {n for n, r in roles.items() if r == "embeddedClass"}

        # Candidates: everything that is NOT concrete (including untagged or legacy tags)
        candidates = {n for n, r in roles.items() if r in notconcrete_roles or r not in concrete_roles}

        # ---------- substitutableClass ----------
        # descendants in HR of any concrete node
        substitutable = set()
        for c in (concrete or set()):
            if self.HR.has_node(c):
                substitutable |= nx.descendants(self.HR, c)
        substitutable &= candidates

        # ---------- containerClass ----------
        # climb upward from each root THROUGH contiguous notConcrete parents
        containers = set()
        for r in roots:
            frontier = [r]
            visited_up = set()
            while frontier:
                cur = frontier.pop()
                if cur in visited_up:
                    continue
                visited_up.add(cur)
                for parent in self.H.successors(cur):  # child -> parent
                    if parent in candidates and parent not in substitutable:
                        containers.add(parent)
                        frontier.append(parent)  # continue climbing through notConcrete
        # (Note: parents-of-embedded are handled below for inheritOnly)

        # ---------- inheritOnlyClass ----------
        # (a) notConcrete ancestors of embedded classes
        inherit_from_embedded = set()
        for e in embeddeds:
            if self.H.has_node(e):
                inherit_from_embedded |= nx.ancestors(self.H, e)
        inherit_from_embedded &= candidates
        inherit_from_embedded -= substitutable  # precedence

        # (b) remaining notConcrete after removing substitutable & containers & (a)
        remaining = candidates - substitutable - containers - inherit_from_embedded
        inherit_only = set(remaining)

        # ---------- apply precedence & write back ----------
        new_roles = {}
        for n in candidates:
            if n in substitutable:
                new_roles[n] = "substitutableClass"
            elif n in containers:
                new_roles[n] = "containerClass"
            elif n in inherit_from_embedded or n in inherit_only:
                new_roles[n] = "inheritOnlyClass"
            else:
                # should not happen; leave unset
                new_roles[n] = ""

        if apply:
            for n in candidates:
                self.graph.nodes[n]["ravensRole"] = new_roles[n]
                self._object_role_map[int(n)] = new_roles[n]

        return {
            "counts": {
                "total_nodes": len(self.graph.nodes),
                "concrete": len(concrete),
                "candidates": len(candidates),
                "substitutable": len(substitutable),
                "containers": len(containers),
                "inherit_only": len(inherit_only),
                "inherit_from_embedded": len(inherit_from_embedded),
            },
            "sets": {
                "concrete": sorted(concrete),
                "candidates": sorted(candidates),
                "substitutable": sorted(substitutable),
                "containers": sorted(containers),
                "inherit_only": sorted(inherit_only),
                "inherit_from_embedded": sorted(inherit_from_embedded),
            },
        }

    # ---------- NEW: inheritance graph (+ reverse) ----------
    def build_inheritance_graph(self) -> tuple[nx.DiGraph, nx.DiGraph]:
        """
        Return (H, HR) where:
        • H is a DiGraph containing ONLY UML Generalization edges (child → parent).
        Assumes EA's connectors table encodes Generalization with Start = child, End = parent.
        (This is the default in EA. If your repository is different, flip the add_edge()).
        All classes present in self.graph are added as nodes to keep queries total.
        """

        H = nx.DiGraph()
        H.add_nodes_from(self.graph.nodes(data=True))
        for u, v, k, d in self.graph.edges(keys=True, data=True):
            if d.get("Connector_Type") == "Generalization" and u != v:
                H.add_edge(int(u), int(v))
        return H


    # ---------- NEW: helpers for role sets ----------
    def _role_of(self, oid: int) -> str | None:
        try:
            return self.graph.nodes[int(oid)].get("ravensRole")
        except Exception:
            return None

    def _name_of(self, oid: int) -> str:
        try:
            return str(self.graph.nodes[int(oid)].get("Name") or "")
        except Exception:
            return ""

    def _concrete_set(self) -> set[int]:
        """
        Concrete = {rootClass ∪ embeddedClass}
        """
        return {
            int(n) for n, d in self.graph.nodes(data=True)
            if (d.get("ravensRole") in ("rootClass", "embeddedClass"))
        }

    def _notconcrete_pool(self) -> set[int]:
        """
        Candidates we will (re)classify into notConcrete roles.
        Excludes all concrete nodes and any node literally named 'Root'.
        """
        concrete = self._concrete_set()
        roots_lit = self._literal_root_ids()
        return {
            int(n) for n, d in self.graph.nodes(data=True)
            if int(n) not in concrete and int(n) not in roots_lit
        }

    # Find concrete descendants using HR
    def _concrete_descendants(self, start: int, HR: nx.DiGraph, concrete: set[int]) -> set[int]:
        if start not in HR:
            return set()
        desc = set(nx.descendants(HR, start))
        return {n for n in desc if n in concrete}

    # For “containers above roots”: walk *up* from each root through contiguous notConcrete
    def _contiguous_notconcrete_ancestors_of_roots(self, H: nx.DiGraph, notconcrete: set[int], roots: set[int]) -> set[int]:
        out: set[int] = set()
        from collections import deque
        for r in roots:
            if r not in H:
                continue
            # BFS over ancestors but stop expanding past any concrete
            q = deque([r])
            visited = {r}
            while q:
                cur = q.popleft()
                for parent in H.successors(cur):  # child -> parent
                    if parent in visited:
                        continue
                    visited.add(parent)
                    if parent in notconcrete:
                        out.add(parent)
                        q.append(parent)  # keep climbing only through notConcrete
                    # if parent is concrete -> stop climbing that branch
        return out


    # ---------- NEW: main re-tagging (logic tightened) ----------
    def retag_notconcrete_roles(
        self,
        *,
        write_back: bool = False,
        require_two_leaf_variants: bool = True,
    ) -> dict:
        """
        Compute notConcrete roles with the tightened rules:
        • substitutableClass: notConcrete node with >= 2 concrete descendants (optionally: leaf variants only).
        • containerClass: notConcrete nodes on any contiguous chain above a rootClass (in H), minus substitutable.
        • inheritOnlyClass: (a) notConcrete ancestors of any embeddedClass (minus substitutable),
                            plus (b) remaining notConcrete with <= 1 concrete descendant.
        • Precedence: substitutable > container > inheritOnly.

        If write_back=True, updates node['ravensRole'] for candidates (never touches literal 'Root').
        """
        H, HR = self.H, self.HR

        concrete  = self._concrete_set()
        notconcrete = self._notconcrete_pool()           # already excludes literal 'Root'
        roots     = {n for n in concrete if self._role_of(n) == "rootClass"}
        embedded  = {n for n in concrete if self._role_of(n) == "embeddedClass"}

        # --- substitutableClass: need >= 2 concrete descendants (optionally: leaf concrete)
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

        substitutable = set()
        for n in notconcrete:
            variants = leaf_concrete_descendants(n) if require_two_leaf_variants else concrete_descendants(n)
            if len(variants) >= 2:
                substitutable.add(n)

        # --- containerClass: contiguous notConcrete ancestors of roots (minus substitutable)
        def contiguous_notconcrete_ancestors_of_roots() -> set[int]:
            out = set()
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
                            out.add(p)
                            q.append(p)  # only climb through notConcrete
            return out

        containers = contiguous_notconcrete_ancestors_of_roots()

        # --- inheritOnlyClass (a): ancestors of embedded (minus substitutable)
        anc_of_embedded = set()
        for e in embedded:
            if e in H:
                anc_of_embedded |= nx.ancestors(H, e)
        inherit_from_embedded = (anc_of_embedded & notconcrete) - substitutable

        # --- inheritOnlyClass (b): remaining with <= 1 concrete descendant
        remaining = notconcrete - substitutable - containers - inherit_from_embedded
        inherit_default = {n for n in remaining if len(concrete_descendants(n)) <= 1}

        inheritonly = inherit_from_embedded | inherit_default

        result_sets = {
            "substitutableClass": sorted(substitutable),
            "containerClass":     sorted(containers),
            "inheritOnlyClass":   sorted(inheritonly),
            "concrete":           sorted(concrete),
            "notConcrete_pool":   sorted(notconcrete),
        }

        if write_back:
            # Clear only in the pool (already excludes literal 'Root')
            for n in notconcrete:
                self.graph.nodes[n]["ravensRole"] = None

            # Apply precedence
            for n in containers:
                self.graph.nodes[n]["ravensRole"] = "containerClass"
            for n in inheritonly:
                self.graph.nodes[n]["ravensRole"] = "inheritOnlyClass"
            for n in substitutable:
                self.graph.nodes[n]["ravensRole"] = "substitutableClass"

            # Refresh internal map
            self._object_role_map = {
                int(n): d.get("ravensRole")
                for n, d in self.graph.nodes(data=True)
            }

        return result_sets


    # ---------- NEW: exports for EA (lists + ready-to-paste JScript) ----------
    def export_tagging_arrays_for_ea(self, role_sets: dict | None = None) -> dict:
        """
        Return pure Python lists of Object_IDs per role, plus a 'clear' list for the
        current notConcrete pool. You can JSON-dump these and paste into EA.
        """
        if role_sets is None:
            role_sets = self.retag_notconcrete_roles(write_back=False)

        notconcrete = set(role_sets.get("notConcrete_pool", []))
        ids_by_role = {
            "clear":               sorted(notconcrete),
            "substitutableClass":  role_sets.get("substitutableClass", []),
            "containerClass":      role_sets.get("containerClass", []),
            "inheritOnlyClass":    role_sets.get("inheritOnlyClass", []),
        }
        return ids_by_role


    def export_ea_jscripts(self, role_sets: dict | None = None, tag_name: str = "ravensRole") -> dict:
        """
        Produce small EA JScript snippets you can paste into the EA Script window.
        Each script clears/appends the tag on a list of element IDs.
        """
        ids = self.export_tagging_arrays_for_ea(role_sets)

        def mk_array(lst):
            return "[" + ",".join(str(int(x)) for x in lst) + "]"

        clear_js = f"""
    // Clear {tag_name} on these elements
    var ids = {mk_array(ids["clear"])};
    for (var i=0; i<ids.length; i++) {{
    var el = Repository.GetElementByID(ids[i]);
    if (!el) {{ continue; }}
    var tv = el.TaggedValues.GetByName("{tag_name}");
    if (tv) {{
        tv.Value = "";
        tv.Update();
    }}
    el.Update();
    }}
    Session.Output("Cleared {tag_name} on " + ids.length + " elements.");
    """.strip()

        def set_role_js(role):
            return f"""
    // Set {tag_name} = "{role}"
    var ids = {mk_array(ids[role])};
    for (var i=0; i<ids.length; i++) {{
    var el = Repository.GetElementByID(ids[i]);
    if (!el) {{ continue; }}
    var tv = el.TaggedValues.GetByName("{tag_name}");
    if (!tv) {{
        tv = el.TaggedValues.AddNew("{tag_name}", "");
    }}
    tv.Value = "{role}";
    tv.Update();
    el.Update();
    }}
    Session.Output("Set {tag_name}='{role}' on " + ids.length + " elements.");
    """.strip()

        return {
            "clear":              clear_js,
            "substitutableClass": set_role_js("substitutableClass"),
            "containerClass":     set_role_js("containerClass"),
            "inheritOnlyClass":   set_role_js("inheritOnlyClass"),
        }


    # ---------- convenience accessors ----------
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
    

    def _normalize_role(self, role: str, *, kind: Literal["node","edge"]) -> Optional[str]:
        
        _NODE_ROLE_ALIASES = {
            "rootclass":        "rootClass",
            "compoundclass":    "compoundClass",
            "embeddedclass":    "embeddedClass",
            "yellowclass":      "yellowClass",
        }
        _EDGE_ROLE_ALIASES = {
            "referenceconnector": "referenceConnector",
            "embeddedconnector":  "embeddedConnector",
        }

        if not role:
            return None
        key = str(role).strip().casefold()
        if kind == "node":
            return _NODE_ROLE_ALIASES.get(key, role)  # fall back to raw if unknown
        else:
            return _EDGE_ROLE_ALIASES.get(key, role)

    # Public-ish helpers for scalar lookups elsewhere
    def role_for_object(self, object_id: int):
        return self._object_role_map.get(int(object_id))


    # Quick selectors that validation can use
    def nodes_by_role(self, *roles: str):
        want = {self._normalize_role(r, kind="node") for r in roles}
        return [n for n, d in self.graph.nodes(data=True) if d.get("ravensRole") in want]

    def nodes_df(self):
        rows = [(n, d.get("Name"), d.get("ravensRole"), d.get("ravensType"), d.get("Package_ID"))
                for n, d in self.graph.nodes(data=True)]
        return pd.DataFrame(rows, columns=["Object_ID","Name","ravensRole","ravensType","Package_ID"])

    def edges_df(self):
        rows = [(u, v, d.get("ConnectorID"), d.get("ravensRole"), d.get("Connector_Type"), d.get("DiagramID"))
                for u, v, d in self.graph.edges(data=True)]
        return pd.DataFrame(rows, columns=["Start_Object_ID","End_Object_ID","Connector_ID","ravensRole","Connector_Type","Diagram_ID"])


    # Inclusion helpers
    IdKind = Literal["object", "obj_instance", "connector_instance", "connector", "package"]
    def _is_included(self, id_value, kind: IdKind) -> bool:
        try:
            container = self._include_sets[kind]
        except KeyError:
            raise ValueError(f"Unknown id kind: {kind!r}")
        return (not container) or (id_value in container)


    def export_ea_jscript_all(
        self,
        role_sets: dict | None = None,
        out_path: str | None = None,   # write to file only if you provide a path
        print_to_console: bool = True  # print the script for copy/paste by default
    ) -> str:
        """
        Recompute not-concrete role sets and emit ONE EA JScript that:
        1) clears existing ravensRole in {containerClass, substitutableClass, inheritOnlyClass}
            (uses EA-safe comma-join SQL to avoid "syntax error in FROM clause")
        2) assigns ravensRole per the arrays below
        3) SKIPS any element whose Name is exactly 'Root' when assigning

        Returns the JScript as a string. Optionally writes it to `out_path`.
        """
        if role_sets is None:
            role_sets = self.retag_notconcrete_roles(write_back=False)

        containers     = [int(x) for x in role_sets.get("containerClass", [])]
        substitutables = [int(x) for x in role_sets.get("substitutableClass", [])]
        inheritonly    = [int(x) for x in role_sets.get("inheritOnlyClass", [])]

        def fmt_array(name, items):
            if not items:
                return f"var {name} = [];"
            # split into readable chunks
            CHUNK = 25
            lines = []
            for i in range(0, len(items), CHUNK):
                lines.append(", ".join(str(v) for v in items[i:i+CHUNK]))
            inner = ",\n    ".join(lines)
            return f"var {name} = [\n    {inner}\n];"

        script = f"""//!INC Local Scripts.EAConstants-JScript

    // Single script to re-tag not-concrete classes in EA (skips literal 'Root').
    // Steps:
    //   1) Clear any existing ravensRole in {{containerClass, substitutableClass, inheritOnlyClass}}
    //   2) Assign new ravensRole per the arrays below
    // Paste into EA's Script window (JScript). Run main().

    {fmt_array("CONTAINER_IDS", containers)}
    {fmt_array("SUBSTITUTABLE_IDS", substitutables)}
    {fmt_array("INHERITONLY_IDS", inheritonly)}

    // --- helpers ---

    function parseIdsFromSQL(xmlText) {{
        var rx = /<Object_ID>(\\d+)<\\/Object_ID>/g, out=[], m=null;
        while ((m = rx.exec(xmlText)) != null) out.push(parseInt(m[1], 10));
        return out;
    }}

    // EA-safe: old-style comma-join (no JOIN ... ON) to avoid 'syntax error in FROM clause'
    function clearExistingNotConcrete() {{
        var sql =
            "SELECT o.Object_ID AS Object_ID\\n" +
            "FROM t_object o, t_objectproperties p\\n" +
            "WHERE p.Object_ID = o.Object_ID\\n" +
            "  AND p.Property = 'ravensRole'\\n" +
            "  AND (p.Value = 'containerClass' OR p.Value = 'substitutableClass' OR p.Value = 'inheritOnlyClass')";
        var xml = Repository.SQLQuery(sql);
        var ids = parseIdsFromSQL(xml);
        for (var i=0; i<ids.length; i++) {{
            var el = Repository.GetElementByID(ids[i]);
            if (!el) continue;
            var tv = null;
            try {{ tv = el.TaggedValues.GetByName("ravensRole"); }} catch(e) {{ tv = null; }}
            if (tv != null) {{ tv.Value = ""; tv.Update(); el.TaggedValues.Refresh(); }}
            el.Update();
        }}
    }}

    function setRoleByList(idList, roleValue) {{
        for (var i=0; i<idList.length; i++) {{
            var id = idList[i];
            var el = Repository.GetElementByID(id);
            if (!el) continue;
            // Root protection by name
            if (el.Name && el.Name === "Root") continue;

            var tv = null;
            try {{ tv = el.TaggedValues.GetByName("ravensRole"); }} catch(e) {{ tv = null; }}
            if (tv == null) {{
                tv = el.TaggedValues.AddNew("ravensRole", "");
            }}
            tv.Value = roleValue;
            tv.Update();
            el.TaggedValues.Refresh();
            el.Update();
        }}
    }}

    function main() {{
        Session.Output("Re-tagging not-concrete roles: starting...");
        clearExistingNotConcrete();

        setRoleByList(CONTAINER_IDS, "containerClass");
        setRoleByList(SUBSTITUTABLE_IDS, "substitutableClass");
        setRoleByList(INHERITONLY_IDS, "inheritOnlyClass");

        Session.Output("Re-tagging complete. Containers=" + CONTAINER_IDS.length
            + ", Substitutables=" + SUBSTITUTABLE_IDS.length
            + ", InheritOnly=" + INHERITONLY_IDS.length);
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


class UMLGraphs:
    def __init__(self, uml_data=None, exclusions=None, inclusions=None, schema_template=None):
        if uml_data is None:
            uml_data = UMLData()
        self.uml_data = uml_data
        self.exclusions = UMLExclusions() if exclusions is None else exclusions

        # inclusions has the following keys:
        # 'Object_ID', 'obj_Instance_ID', 'link_Instance_ID', 'Connector_ID', 'Diagram_ID', 'Package_ID'
        inclusions = inclusions or {}
        self.inclusions = inclusions
        self.included_object_ids = set(inclusions.get('Object_ID', []))
        self.included_obj_instance_ids = set(inclusions.get('obj_Instance_ID', []))
        self.included_link_instance_ids = set(inclusions.get('link_Instance_ID', []))
        # The rest (Connector_ID, Diagram_ID, Package_ID) can be added similarly as needed

        self.gen_graph = self.build_generalization_graph()
        self.attr_graph = self.build_attribute_graph()
        self.assoc_graph = self.build_association_graph()
        self.graph = nx.compose_all([self.gen_graph, self.attr_graph, self.assoc_graph])
        self.subgraphs = {}

        if schema_template is not None:
            self._build_subgraphs_from_template(schema_template)

    # Inclusion helpers
    def _is_object_included(self, object_id):
        # If not filtering by object_id, always include
        return (not self.included_object_ids) or (object_id in self.included_object_ids)

    def _is_obj_instance_included(self, instance_id):
        return (not self.included_obj_instance_ids) or (instance_id in self.included_obj_instance_ids)

    def _is_link_instance_included(self, instance_id):
        return (not self.included_link_instance_ids) or (instance_id in self.included_link_instance_ids)

    # Main node addition
    def _add_enhanced_class_nodes_to_graph(self, G):
        for oid, row in self.uml_data.objects.iterrows():
            if (
                not self._is_object_included(oid)
                or row.Object_Type != "Class"
                or pd.notnull(row.Stereotype)
                or oid in self.exclusions.object_ids
                or row.Package_ID in self.exclusions.package_ids
            ):
                continue

            node_attrs = {
                "Name": str(row.Name),
                "Object_Type": row.Object_Type,
                "Note": str(row.Note),
                "Package_ID": row.Package_ID,
            }

            # ---------- gather instance-level data ----------
            instances = self.uml_data.diagramobjects[
                self.uml_data.diagramobjects["Object_ID"] == oid
            ]

            inst_attrs = {
                "Package_ID": [],
                "Package_Name": [],
                "Instance_ID": [],
                "DiagramName": [],
            }

            for iid, inst in instances.iterrows():
                if not self._is_obj_instance_included(iid):
                    continue
                did = inst.Diagram_ID
                if did not in self.uml_data.diagrams.index:
                    continue

                pkg_id = int(self.uml_data.diagrams.loc[did]["Package_ID"])
                inst_attrs["Package_ID"].append(pkg_id)
                inst_attrs["Package_Name"].append(
                    self.uml_data.packages.loc[pkg_id]["Name"]
                )
                inst_attrs["Instance_ID"].append(iid)
                inst_attrs["DiagramName"].append(self.uml_data.diagrams.loc[did]["Name"])

            # attach instance details only if any survived filtering
            if any(len(v) for v in inst_attrs.values()):
                node_attrs["instances"] = inst_attrs

            G.add_node(oid, **node_attrs)

        return G

    def _add_enhanced_edges_to_graph(self, G, connector_types=("Association", "Aggregation", "Generalization")):
        for cid, row in self.uml_data.connectors.iterrows():
            if row.Connector_Type not in connector_types:
                continue
            s_id, e_id = row.Start_Object_ID, row.End_Object_ID
            if not all(n in G for n in [s_id, e_id]):
                continue
            if not all(self._is_object_included(n) for n in [s_id, e_id]):
                continue

            edge_attrs = {
                "Connector_ID": cid,
                "Connector_Type": row.Connector_Type,
                "SourceCard": row.SourceCard,
                "DestCard": row.DestCard,
                "SourceRole": row.SourceRole,
                "DestRole": row.DestRole,
                "startlabel": jps.parse_connector_labels(row)[0],
                "endlabel": jps.parse_connector_labels(row)[1],
            }

            # Connector/link instances (filter by included_link_instance_ids)
            insts = self.uml_data.diagramlinks[self.uml_data.diagramlinks["ConnectorID"] == cid]
            inst_attrs = {"iid": [], "did": [], "i_start_hidden": [], "i_end_hidden": []}
            for iid, inst_row in insts.iterrows():
                if not self._is_link_instance_included(iid):
                    continue
                inst_attrs["iid"].append(iid)
                inst_attrs["did"].append(inst_row["DiagramID"])
                sh, eh = jps.label_visibility(inst_row["Geometry"])
                inst_attrs["i_start_hidden"].append(sh)
                inst_attrs["i_end_hidden"].append(eh)

            if any(len(v) for v in inst_attrs.values()):
                edge_attrs["instances"] = inst_attrs

            directed = (row.Connector_Type != "Generalization")
            edge_attrs["directed"] = directed
            G.add_edge(s_id, e_id, **edge_attrs)
            if not directed:
                G.add_edge(e_id, s_id, **edge_attrs)
        return G

    def build_attribute_graph(self) -> nx.MultiDiGraph:
        AT = nx.MultiDiGraph()
        AT = self._add_enhanced_class_nodes_to_graph(AT)
        for n in list(AT.nodes):
            for attr in self.uml_data.attributes[self.uml_data.attributes["Object_ID"] == n].itertuples():
                AT.add_edge(attr.Index, n, Connector_Type="Attribute", Connector_ID="ATTR_" + str(attr.Index), weight=100.0)
                AT.nodes[attr.Index].update({
                    "Name": str(attr.Name),
                    "Note": str(attr.Notes),
                    "Object_Type": "Attribute",
                    "Attribute_ID": str(attr.Index)
                })
        return AT

    def build_association_graph(self) -> nx.MultiDiGraph:
        AG = nx.MultiDiGraph()
        AG = self._add_enhanced_class_nodes_to_graph(AG)
        for c in self.uml_data.connectors[
            (self.uml_data.connectors["Connector_Type"] == "Association")
            | (self.uml_data.connectors["Connector_Type"] == "Aggregation")
        ].itertuples():
            if (
                self.uml_data.objects.loc[c.Start_Object_ID]["Object_Type"] == "Class"
                and self.uml_data.objects.loc[c.End_Object_ID]["Object_Type"] == "Class"
                and self._is_object_included(c.Start_Object_ID)
                and self._is_object_included(c.End_Object_ID)
                and pd.isnull(self.uml_data.objects.loc[c.Start_Object_ID]["Stereotype"])
                and pd.isnull(self.uml_data.objects.loc[c.End_Object_ID]["Stereotype"])
                and c.Start_Object_ID not in self.exclusions.object_ids
                and c.End_Object_ID not in self.exclusions.object_ids
            ):
                AG.add_edge(
                    c.End_Object_ID,
                    c.Start_Object_ID,
                    SourceCard=str(c.DestCard),
                    DestCard=str(c.SourceCard),
                    SourceRole=str(c.DestRole) if not pd.isnull(c.DestRole) else str(self.uml_data.objects.loc[c.End_Object_ID]["Name"]),
                    DestRole=str(c.SourceRole) if not pd.isnull(c.SourceRole) else str(self.uml_data.objects.loc[c.Start_Object_ID]["Name"]),
                    Connector_ID="ASC_REV_" + str(c.Index),
                    End_Object_ID=str(c.Start_Object_ID),
                    Start_Object_ID=str(c.End_Object_ID),
                    Connector_Type=str(c.Connector_Type),
                    weight=1.0,
                )

                AG.add_edge(
                    c.Start_Object_ID,
                    c.End_Object_ID,
                    DestCard=str(c.DestCard),
                    SourceCard=str(c.SourceCard),
                    DestRole=str(c.DestRole) if not pd.isnull(c.DestRole) else str(self.uml_data.objects.loc[c.End_Object_ID]["Name"]),
                    SourceRole=str(c.SourceRole) if not pd.isnull(c.SourceRole) else str(self.uml_data.objects.loc[c.Start_Object_ID]["Name"]),
                    Connector_ID="ASC_FWD_" + str(c.Index),
                    Start_Object_ID=str(c.Start_Object_ID),
                    End_Object_ID=str(c.End_Object_ID),
                    Connector_Type=str(c.Connector_Type),
                    weight=1.0,
                )
        return AG
    
    def _build_subgraphs_from_template(self, template):
        id2name = {
            **{obj.Index: str(obj.Name) for obj in uml_data.objects.itertuples()},
            **{attr.Index: str(attr.Name) for attr in uml_data.attributes.itertuples()},
        }
        cls_name2id = {str(obj.Name): obj.Index for obj in uml_data.objects[uml_data.objects["Object_Type"] == "Class"].itertuples() if pd.isnull(obj.Stereotype)}

        template_names = template.nodes

        for name in template_names:
            obj_id = cls_name2id[name]
            nodes = {at for n in [obj_id] + list(nx.ancestors(GG, obj_id)) + list(nx.descendants(GG, obj_id)) for a in list(AG.neighbors(n)) + [n] for at in [n, a] + list(AT.predecessors(a)) + list(AT.predecessors(n))}

            self.subgraphs[name] = nx.subgraph(GG_AT_AG, nodes)

    def export_subgraphs(self, export_dir: str, clean_dir: bool = False):
        if clean_dir:
            for file in glob.glob(os.path.join(export_dir, "*")):
                os.remove(file)

        for k, v in self.subgraphs.items():
            nx.write_graphml(v, os.path.join(export_dir, f"{k}.graphml"))

    def export_graph(self, file_out: str):
        nx.write_graphml(self.graph, file_out, named_key_ids=True, edge_id_from_attribute="Connector_ID")

    def export_generalization_graph(self, file_out: str):
        nx.write_graphml(self.gen_graph, file_out)

    def export_attribute_graph(self, file_out: str):
        nx.write_graphml(self.attr_graph, file_out)

    def export_association_graph(self, file_out: str):
        nx.write_graphml(self.assoc_graph, file_out)


if __name__ == "__main__":
    import pathlib
    from ravens.schema import SchemaTemplate

    pathlib.Path("out/CIM_graphs").mkdir(parents=True, exist_ok=True)
    pathlib.Path("out/template_graphs").mkdir(parents=True, exist_ok=True)

    exclusions = UMLExclusions().exclude_by_name_startswith(["Inf", "Mkt"])

    graphs = UMLGraphs(exclusions=exclusions)
    graphs.export_graph("out/CIM_graphs/GG_AT_AG.graphml")

    graphs_with_subgraphs = UMLGraphs(exclusions=exclusions, schema_template=SchemaTemplate().loadf("cim/schema_template.json"))
    graphs.export_subgraphs("out/template_graphs")
