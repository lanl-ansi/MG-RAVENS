import os
import re
import glob
import pandas as pd
import networkx as nx
from typing import Literal, Iterable, Optional

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
        self._connector_role_map = (
            self.connector_tags["Value"].groupby(level="Connector_ID").last().apply(
                lambda v: self._normalize_role(v, kind="edge")
            ).to_dict()
        )

        self.graph = self.build_graph()
        self.subgraphs = {}

        if schema_template is not None:
            self._build_subgraphs_from_template(schema_template)


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

    @staticmethod
    def _looks_like_guid(s: str) -> bool:
        return isinstance(s, str) and len(s) >= 36 and "{" in s and "}" in s

    @staticmethod
    def _parse_xref_description_props(desc: str):
        """Extract [(tag, value)] from @PROP=...@ENDPROP; blocks in t_xref.Description."""
        if not isinstance(desc, str) or "@PROP=" not in desc:
            return []
        props = []
        for block in re.findall(r"@PROP=(.*?)@ENDPROP;", desc, flags=re.S):
            name_match = re.search(r"@NAME=(.*?)(?:@|$)", block, flags=re.S)
            valu_match = re.search(r"@VALU=(.*?)(?:@|$)", block, flags=re.S)
            if not name_match:
                continue
            tag  = name_match.group(1).strip()
            valu = (valu_match.group(1).strip() if valu_match else "")
            props.append((tag, valu))
        return props

    def _map_xref_clients_to_object_ids(self, objects_df: pd.DataFrame, xdf: pd.DataFrame) -> pd.Series:
        """
        Map xrefs.Client → Object_ID (int). Works if Object_ID is a column or the index.
        Uses objects.ea_guid when Client is a GUID.
        """
        if not isinstance(xdf, pd.DataFrame) or xdf.empty:
            return pd.Series(dtype="float64", index=xdf.index if isinstance(xdf, pd.DataFrame) else None, name="Object_ID")

        # Get a DataFrame with columns: Object_ID, ea_guid
        df2 = objects_df.reset_index()  # brings index (Object_ID) back as a column
        if "Object_ID" not in df2.columns and "ObjectID" in df2.columns:
            df2 = df2.rename(columns={"ObjectID": "Object_ID"})
        if "Object_ID" not in df2.columns:
            # last resort: fabricate from index if it's numeric
            df2["Object_ID"] = pd.to_numeric(objects_df.index, errors="coerce")

        oid_col = pd.to_numeric(df2["Object_ID"], errors="coerce")
        known_oids = set(oid_col.dropna().astype(int).tolist())

        guid_to_oid = {}
        if "ea_guid" in df2.columns:
            guid_to_oid = {g: int(o) for g, o in zip(df2["ea_guid"], oid_col) if isinstance(g, str) and pd.notna(o)}

        def try_int(v):
            try: return int(v)
            except: return None

        mapped = []
        for v in xdf["Client"]:
            oi = try_int(v)
            if oi is not None and oi in known_oids:
                mapped.append(oi)
                continue
            if isinstance(v, str) and v in guid_to_oid:
                mapped.append(guid_to_oid[v])
                continue
            mapped.append(None)

        return pd.Series(mapped, index=xdf.index, name="Object_ID")

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
        uml = self.uml_data
        frames = []

        # Preferred (if you ever load them)
        for name in ("t_objectproperties", "objectproperties", "object_tags", "element_tags"):
            df = getattr(uml, name, None)
            if isinstance(df, pd.DataFrame) and not df.empty:
                df = df.copy(); df._source_name = name
                if "Object_ID" not in df.columns and "ObjectID" in df.columns:
                    df = df.rename(columns={"ObjectID": "Object_ID"})
                frames.append(self._normalize_tag_rows(df, id_col="Object_ID"))

        # Fallback: parse ANY xrefs row that contains @PROP= and has a Client
        if not frames and isinstance(getattr(uml, "xrefs", None), pd.DataFrame) and not uml.xrefs.empty:
            xdf = uml.xrefs.copy()
            desc_has_props = xdf.get("Description", "").astype(str).str.contains("@PROP=")
            client_ok = xdf.get("Client", "").astype(str).ne("")
            xdf = xdf[desc_has_props & client_ok]
            if not xdf.empty:
                xdf["Object_ID"] = self._map_xref_clients_to_object_ids(uml.objects, xdf)
                xdf = xdf[xdf["Object_ID"].notna()].copy()
                xdf["Object_ID"] = xdf["Object_ID"].astype(int)

                want = self.tag_name_filter.casefold()
                rows = []
                for _, r in xdf.iterrows():
                    for tag, val in self._parse_xref_description_props(r.get("Description", "")):
                        if str(tag).casefold() != want:
                            continue
                        rows.append({
                            "Object_ID": r["Object_ID"],
                            "Tag": tag,
                            "Value": val,
                            "Notes": r.get("Notes", None) if "Notes" in xdf.columns else None,
                            "GUID":  r.get("ea_guid", None) if "ea_guid" in xdf.columns else None,
                            "Source": "xrefs",
                        })
                if rows:
                    df_props = pd.DataFrame(rows)
                    frames.append(
                        df_props.drop_duplicates(subset=["Object_ID", "Tag"], keep="last")
                                .set_index(["Object_ID", "Tag"])
                                .reindex(columns=["Value", "Notes", "GUID", "Source"])
                    )

        if not frames:
            return pd.DataFrame(columns=["Value", "Notes", "GUID", "Source"],
                                index=pd.MultiIndex.from_arrays([[], []], names=["Object_ID", "Tag"]))

        out = pd.concat(frames, axis=0) if len(frames) > 1 else frames[0]

        # Final filter (redundant if xref path used, but safe if objectproperties was used)
        if isinstance(out, pd.DataFrame) and not out.empty:
            tag_idx = out.index.get_level_values("Tag")
            out = out[tag_idx.str.casefold() == self.tag_name_filter.casefold()]

        # Restrict to known objects (handles index-as-ID)
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

    def role_for_connector(self, connector_id: int):
        return self._connector_role_map.get(int(connector_id))

    # Quick selectors that validation can use
    def nodes_by_role(self, *roles: str):
        want = {self._normalize_role(r, kind="node") for r in roles}
        return [n for n, d in self.graph.nodes(data=True) if d.get("ravensRole") in want]

    def edges_by_role(self, *roles: str):
        want = {self._normalize_role(r, kind="edge") for r in roles}
        return [(u, v, k) for u, v, k, d in self.graph.edges(keys=True, data=True) if d.get("ravensRole") in want]

    def nodes_df(self):
        rows = [(n, d.get("Name"), d.get("ravensRole"), d.get("ravensType"), d.get("Package_ID"))
                for n, d in self.graph.nodes(data=True)]
        return pd.DataFrame(rows, columns=["Object_ID","Name","ravensRole","ravensType","Package_ID"])

    def edges_df(self):
        rows = [(u, v, d.get("ConnectorID"), d.get("ravensRole"), d.get("Connector_Type"), d.get("DiagramID"))
                for u, v, d in self.graph.edges(data=True)]
        return pd.DataFrame(rows, columns=["Start_Object_ID","End_Object_ID","Connector_ID","ravensRole","Connector_Type","Diagram_ID"])

    # -------------------- graph build --------------------
    def build_graph(self) -> nx.MultiDiGraph:
        G = nx.MultiDiGraph()
        G = self._add_enhanced_class_nodes_to_graph(G)
        G = self._add_enhanced_edges_to_graph(G)
        return G

    # Inclusion helpers
    IdKind = Literal["object", "obj_instance", "connector_instance", "connector", "package"]
    def _is_included(self, id_value, kind: IdKind) -> bool:
        try:
            container = self._include_sets[kind]
        except KeyError:
            raise ValueError(f"Unknown id kind: {kind!r}")
        return (not container) or (id_value in container)

    # -------------------- nodes --------------------
    def _add_enhanced_class_nodes_to_graph(self, G: nx.MultiDiGraph) -> nx.MultiDiGraph:
        # Optional perf: pre-group diagramobjects by Object_ID
        do = self.uml_data.diagramobjects
        by_obj = do.groupby("Object_ID", sort=False) if isinstance(do, pd.DataFrame) and "Object_ID" in do.columns else None

        for oid, row in self.uml_data.objects.iterrows():
            # Inclusion & type filter (keep only Classes; do NOT exclude by stereotype anymore)
            if (
                not self._is_included(oid, "object")
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

            ## REVISIT THIS when taxonomy is better-understood. Just a placeholder for now.
            if node_role in {"compoundClass", "yellowClass"}:
                node_attrs["ravensType"] = "container"
            else:
                node_attrs["ravensType"] = "object"

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
                    "ravensRole":     self.role_for_connector(int(cid)),
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

    # -------------------- schema (unchanged except for color dependency) --------------------
    def build_two_level_schema(self, root_id):
        # Helpers
        ARRAY_RE = re.compile(r"\*\s*$|(\d+)\s*\.\.\s*\*|(\d+)\s*\.\.\s*(\d+)")
        def cardinality_is_array(card):
            if not card:
                return False
            card = str(card).strip()
            if card == "*":
                return True
            m = ARRAY_RE.fullmatch(card)
            if not m:
                return False
            if card.endswith("*"):
                return True
            if m.group(3):
                return int(m.group(3)) > 1
            return False

        def edge_is_array(edge):
            return edge.get("DestCard") in {"0..*", "1..*", "*"}

        def build_prop(obj_id, edge):
            obj   = self.uml_data.objects.loc[obj_id]
            name  = str(obj["Name"]).split(" (")[0]

            # Tag-driven roles (no longer using colors)
            tags = self.graph.nodes[obj_id].get("tags", {})
            node_role = tags.get("ravens_role") or tags.get("role")  # adapt to your tag names

            # Decide $objectType from role (fallback: 'object')
            if node_role in {"container", "group", "aggregate"}:
                objtype = "container"
            elif node_role == "reference":
                objtype = "reference"
            else:
                objtype = "object"

            base = {
                "$objectType": objtype,
                "type": "object",
                "$objectId": name,       # may be altered below
                "properties": {},
            }

            # ---------- $objectId rules ----------
            if objtype == "container":
                base.pop("$objectId", None)
            elif objtype == "reference":
                base["$objectId"]      = name
                base["$referencePath"] = name
            else:  # object
                # You may want to gate this on a tag too (e.g., primary objects)
                base["$objectId"] = name if tags.get("primary", "").lower() in {"true","1","yes"} else None

            # ---------- hash fields for objects ----------
            if objtype == "object":
                if tags.get("primary", "").lower() in {"true","1","yes"}:
                    base["$primaryObjectHash"]   = "IdentifiedObject.name"
                    base["$secondaryObjectHash"] = "IdentifiedObject.mRID"
                else:
                    base["$primaryObjectHash"]   = None
                    base["$secondaryObjectHash"] = None

            # ---------- wrap in array if needed ----------
            return (
                {"type": "array", "items": {**base, "$arrayPosition": None}}
                if edge_is_array(edge) or cardinality_is_array(edge.get("DestCard"))
                else base
            )

        # Root
        root_obj  = self.uml_data.objects.loc[root_id]
        root_name = str(root_obj["Name"]).split(" (")[0]

        schema = {
            "title": root_name,
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"https://raw.githubusercontent.com/lanl-ansi/MG-RAVENS/refs/heads/schema/{root_name}.json",
            "type": "object",
            "$primaryObjectHash": "IdentifiedObject.name",
            "$secondaryObjectHash": "IdentifiedObject.mRID",
            "properties": {},
        }

        # depth-1 & depth-2
        for _, child_id, edge in self.graph.out_edges(root_id, data=True):
            child_name = str(self.uml_data.objects.loc[child_id]["Name"]).split(" (")[0]
            schema["properties"][child_name] = build_prop(child_id, edge)

            for _, grand_id, grand_edge in self.graph.out_edges(child_id, data=True):
                grand_name = str(self.uml_data.objects.loc[grand_id]["Name"]).split(" (")[0]
                schema["properties"][child_name]["properties"][grand_name] = build_prop(grand_id, grand_edge)

        return schema
    



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

    def build_generalization_graph(self) -> nx.MultiDiGraph:
        GG = nx.MultiDiGraph()
        GG = self._add_enhanced_class_nodes_to_graph(GG)
        for c in self.uml_data.connectors[self.uml_data.connectors["Connector_Type"] == "Generalization"].itertuples():
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
                GG.add_edge(
                    c.Start_Object_ID,
                    c.End_Object_ID,
                    Start_Object_ID=str(c.Start_Object_ID),
                    End_Object_ID=str(c.End_Object_ID),
                    Connector_ID="GEN_" + str(c.Index),
                    Connector_Type="Generalization",
                    weight=10.0,
                )
        return GG

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
