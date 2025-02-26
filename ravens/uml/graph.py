import glob
import os

import networkx as nx
import pandas as pd

from ravens.uml import UMLData, UMLExclusions


class UMLGraphs:
    def __init__(self, uml_data: UMLData | None = None, exclusions: UMLExclusions | None = None, schema_template=None):
        if uml_data is None:
            uml_data = UMLData()

        self.uml_data = uml_data

        self.exclusions = UMLExclusions() if exclusions is None else exclusions

        self.gen_graph = self.build_generalization_graph()
        self.attr_graph = self.build_attribute_graph()
        self.assoc_graph = self.build_association_graph()

        self.graph = nx.compose_all([self.gen_graph, self.attr_graph, self.assoc_graph])

        self.subgraphs = {}
        if schema_template is not None:
            self._build_subgraphs_from_template(schema_template)

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
                if pd.isnull(obj.Stereotype) and obj.Package_ID not in self.exclusions.package_ids and obj.Index not in self.exclusions.object_ids
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
                and self.uml_data.objects.loc[c.Start_Object_ID]["Package_ID"] not in self.exclusions.package_ids
                and self.uml_data.objects.loc[c.End_Object_ID]["Package_ID"] not in self.exclusions.package_ids
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
                and self.uml_data.objects.loc[c.Start_Object_ID]["Package_ID"] not in self.exclusions.package_ids
                and self.uml_data.objects.loc[c.End_Object_ID]["Package_ID"] not in self.exclusions.package_ids
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
