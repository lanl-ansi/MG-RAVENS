import glob
import os
from typing import Literal, Optional

import networkx as nx
import pandas as pd

from . import common
from .data import UMLData
from .exclusions import UMLExclusions
from .selection import UMLSelection


class UMLGraphs:
    def __init__(
        self,
        uml_data: UMLData | None = None,
        exclusions: UMLExclusions | None = None,
        schema_template=None,
        selection: UMLSelection | None = None,
        inclusions=None,
    ):
        if selection is None:
            selection = inclusions
        build_autotemplate_graphs = selection is not None
        if uml_data is None:
            uml_data = selection.uml_data if selection is not None else UMLData()

        self.uml_data = uml_data
        self.exclusions = UMLExclusions(uml_data=uml_data) if exclusions is None else exclusions
        self.selection = selection or UMLSelection.from_exclusions(uml_data, self.exclusions)
        self.subgraphs = {}

        if not build_autotemplate_graphs:
            self.gen_graph = self.build_generalization_graph()
            self.attr_graph = self.build_attribute_graph()
            self.assoc_graph = self.build_association_graph()
            self.graph = nx.compose_all([self.gen_graph, self.attr_graph, self.assoc_graph])
            if schema_template is not None:
                self._build_subgraphs_from_template(schema_template)
        else:
            self._build_autotemplate_graphs()

    def _build_autotemplate_graphs(self):
        self._ensure_indexes()
        self.tag_name_filter = "ravensRole"
        self.object_tags = self._build_object_tags()
        self.connector_tags = self._build_connector_tags()
        self._object_role_map = (
            self.object_tags["Value"].groupby(level="Object_ID").last().apply(
                lambda v: self._normalize_role(v, kind="node")
            ).to_dict()
        )
        self.H = self.build_H()
        self.HR = self.H.reverse(copy=False)
        self.A = self.build_A()

    def _add_class_nodes_to_graph(self, G):
        attrs = {
            obj.Index: [attr.Index for attr in self.uml_data.attributes[self.uml_data.attributes["Object_ID"] == obj.Index].itertuples()]
            for obj in self.uml_data.objects[self.uml_data.objects["Object_Type"] == "Class"].itertuples()
            if pd.isnull(obj.Stereotype)
        }

        conns = {
            obj.Index: [c.Index for c in self.uml_data.connectors[(self.uml_data.connectors["Start_Object_ID"] == obj.Index) | (self.uml_data.connectors["End_Object_ID"] == obj.Index)].itertuples()]
            for obj in self.uml_data.objects[self.uml_data.objects["Object_Type"] == "Class"].itertuples()
            if pd.isnull(obj.Stereotype)
        }

        gens = {node: [c for c in cs if self.uml_data.connectors.loc[c]["Connector_Type"] == "Generalization"] for node, cs in conns.items()}

        assocs = {node: [c for c in cs if self.uml_data.connectors.loc[c]["Connector_Type"] == "Association"] for node, cs in conns.items()}

        G.add_nodes_from(
            [
                (
                    obj.Index,
                    {
                        "Name": str(obj.Name) + f" ({len(attrs[obj.Index])}+{len(gens[obj.Index])}+{len(assocs[obj.Index])})",
                        "Object_ID": str(obj.Index),
                        "Note": str(obj.Note),
                        "Attributes": ", ".join([self.uml_data.attributes.loc[i]["Name"] for i in attrs[obj.Index]]),
                        "Object_Type": "Class",
                    },
                )
                for obj in self.uml_data.objects[self.uml_data.objects["Object_Type"] == "Class"].itertuples()
                if pd.isnull(obj.Stereotype) and self._allow("object", obj.Index)
            ]
        )

        return G

    def build_generalization_graph(self) -> nx.MultiDiGraph:
        GG = nx.MultiDiGraph()
        GG = self._add_class_nodes_to_graph(GG)
        for c in self.uml_data.connectors[self.uml_data.connectors["Connector_Type"] == "Generalization"].itertuples():
            if (
                self.uml_data.objects.loc[c.Start_Object_ID]["Object_Type"] == "Class"
                and self.uml_data.objects.loc[c.End_Object_ID]["Object_Type"] == "Class"
                and pd.isnull(self.uml_data.objects.loc[c.Start_Object_ID]["Stereotype"])
                and pd.isnull(self.uml_data.objects.loc[c.End_Object_ID]["Stereotype"])
                and self._allow("object", c.Start_Object_ID)
                and self._allow("object", c.End_Object_ID)
                and self._allow("connector", c.Index)
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
        AT = self._add_class_nodes_to_graph(AT)
        for n in list(AT.nodes):
            for attr in self.uml_data.attributes[self.uml_data.attributes["Object_ID"] == n].itertuples():
                AT.add_edge(attr.Index, n, Connector_Type="Attribute", Connector_ID="ATTR_" + str(attr.Index), weight=100.0)
                AT.nodes[attr.Index].update({"Name": str(attr.Name), "Note": str(attr.Notes), "Object_Type": "Attribute", "Attribute_ID": str(attr.Index)})

        return AT

    def build_association_graph(self) -> nx.MultiDiGraph:
        AG = nx.MultiDiGraph()
        AG = self._add_class_nodes_to_graph(AG)
        for c in self.uml_data.connectors[(self.uml_data.connectors["Connector_Type"] == "Association") | (self.uml_data.connectors["Connector_Type"] == "Aggregation")].itertuples():
            if (
                self.uml_data.objects.loc[c.Start_Object_ID]["Object_Type"] == "Class"
                and self.uml_data.objects.loc[c.End_Object_ID]["Object_Type"] == "Class"
                and pd.isnull(self.uml_data.objects.loc[c.Start_Object_ID]["Stereotype"])
                and pd.isnull(self.uml_data.objects.loc[c.End_Object_ID]["Stereotype"])
                and self._allow("object", c.Start_Object_ID)
                and self._allow("object", c.End_Object_ID)
                and self._allow("connector", c.Index)
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

    def _allow(self, kind: str, id_value: int) -> bool:
        return self.selection.allow(kind, id_value)


    def build_H(self) -> nx.DiGraph:
        """
        Generalization H (child -> parent). If a selection is provided,
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

        for idx, crow in gen_rows.iterrows():
            # connector id: prefer column, else fall back to index
            cid_val = pd.to_numeric(crow.get(c_id), errors="coerce") if c_id is not None else pd.NA
            if pd.isna(cid_val):
                cid_val = pd.to_numeric(idx, errors="coerce")
            if pd.isna(cid_val):
                continue
            cid = int(cid_val)

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
        Association/Aggregation/Composition graph; honors the selection via:
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

        if not isinstance(dl, pd.DataFrame) or dl.empty:
            return A

        ASSOCIATION_TYPES = {"Association", "Aggregation", "Composition"}
        diagrams_df = self.uml_data.diagrams
        cid_col = "ConnectorID" if "ConnectorID" in dl.columns else ("Connector_ID" if "Connector_ID" in dl.columns else None)
        did_col = "DiagramID"   if "DiagramID"   in dl.columns else ("Diagram_ID"   if "Diagram_ID"   in dl.columns else None)
        if cid_col is None or did_col is None:
            return A

        for cid, crow in self.uml_data.connectors.iterrows():
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
