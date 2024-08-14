import networkx as nx
import pandas as pd

from ravens.io import CoreData
from ravens.cim_tools.template import collect_template_node_names


def add_class_nodes_to_graph(G, core_data: CoreData, exclude_packages: list = None, exclude_objects: list = None):
    if exclude_packages is None:
        exclude_packages = []

    if exclude_objects is None:
        exclude_objects = []

    attrs = {obj.Index: [attr.Index for attr in core_data.attributes[core_data.attributes["Object_ID"] == obj.Index].itertuples()] for obj in core_data.objects[core_data.objects["Object_Type"] == "Class"].itertuples() if pd.isnull(obj.Stereotype)}

    conns = {
        obj.Index: [c.Index for c in core_data.connectors[(core_data.connectors["Start_Object_ID"] == obj.Index) | (core_data.connectors["End_Object_ID"] == obj.Index)].itertuples()]
        for obj in core_data.objects[core_data.objects["Object_Type"] == "Class"].itertuples()
        if pd.isnull(obj.Stereotype)
    }

    gens = {node: [c for c in cs if core_data.connectors.loc[c]["Connector_Type"] == "Generalization"] for node, cs in conns.items()}

    assocs = {node: [c for c in cs if core_data.connectors.loc[c]["Connector_Type"] == "Association"] for node, cs in conns.items()}

    G.add_nodes_from(
        [
            (
                obj.Index,
                {
                    "Name": str(obj.Name) + f" ({len(attrs[obj.Index])}+{len(gens[obj.Index])}+{len(assocs[obj.Index])})",
                    "Object_ID": str(obj.Index),
                    "Note": str(obj.Note),
                    "Attributes": ", ".join([core_data.attributes.loc[i]["Name"] for i in attrs[obj.Index]]),
                    "Object_Type": "Class",
                },
            )
            for obj in core_data.objects[core_data.objects["Object_Type"] == "Class"].itertuples()
            if pd.isnull(obj.Stereotype) and obj.Package_ID not in exclude_packages and obj.Index not in exclude_objects
        ]
    )

    return G


def build_generalization_graph(core_data: CoreData, exclude_packages: list = None, exclude_objects: list = None) -> nx.MultiDiGraph:
    if exclude_packages is None:
        exclude_packages = []

    if exclude_objects is None:
        exclude_objects = []

    GG = nx.MultiDiGraph()
    GG = add_class_nodes_to_graph(GG, core_data, exclude_packages, exclude_objects)
    for c in core_data.connectors[core_data.connectors["Connector_Type"] == "Generalization"].itertuples():
        if (
            core_data.objects.loc[c.Start_Object_ID]["Object_Type"] == "Class"
            and core_data.objects.loc[c.End_Object_ID]["Object_Type"] == "Class"
            and core_data.objects.loc[c.Start_Object_ID]["Package_ID"] not in exclude_packages
            and core_data.objects.loc[c.End_Object_ID]["Package_ID"] not in exclude_packages
            and pd.isnull(core_data.objects.loc[c.Start_Object_ID]["Stereotype"])
            and pd.isnull(core_data.objects.loc[c.End_Object_ID]["Stereotype"])
            and c.Start_Object_ID not in exclude_objects
            and c.End_Object_ID not in exclude_objects
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


def build_attribute_graph(core_data: CoreData, exclude_packages: list = None, exclude_objects: list = None) -> nx.MultiDiGraph:
    if exclude_packages is None:
        exclude_packages = []

    if exclude_objects is None:
        exclude_objects = []

    AT = nx.MultiDiGraph()
    AT = add_class_nodes_to_graph(AT, core_data, exclude_packages, exclude_objects)
    for n in list(AT.nodes):
        for attr in core_data.attributes[core_data.attributes["Object_ID"] == n].itertuples():
            AT.add_edge(attr.Index, n, Connector_Type="Attribute", Connector_ID="ATTR_" + str(attr.Index), weight=100.0)
            AT.nodes[attr.Index].update({"Name": str(attr.Name), "Note": str(attr.Notes), "Object_Type": "Attribute", "Attribute_ID": str(attr.Index)})

    return AT


def build_association_graph(core_data: CoreData, exclude_packages: list = None, exclude_objects: list = None) -> nx.MultiDiGraph:
    if exclude_packages is None:
        exclude_packages = []

    if exclude_objects is None:
        exclude_objects = []

    AG = nx.MultiDiGraph()
    AG = add_class_nodes_to_graph(AG, core_data, exclude_packages, exclude_objects)
    for c in core_data.connectors[(core_data.connectors["Connector_Type"] == "Association") | (core_data.connectors["Connector_Type"] == "Aggregation")].itertuples():
        if (
            core_data.objects.loc[c.Start_Object_ID]["Object_Type"] == "Class"
            and core_data.objects.loc[c.End_Object_ID]["Object_Type"] == "Class"
            and core_data.objects.loc[c.Start_Object_ID]["Package_ID"] not in exclude_packages
            and core_data.objects.loc[c.End_Object_ID]["Package_ID"] not in exclude_packages
            and pd.isnull(core_data.objects.loc[c.Start_Object_ID]["Stereotype"])
            and pd.isnull(core_data.objects.loc[c.End_Object_ID]["Stereotype"])
            and c.Start_Object_ID not in exclude_objects
            and c.End_Object_ID not in exclude_objects
        ):
            AG.add_edge(
                c.End_Object_ID,
                c.Start_Object_ID,
                SourceCard=str(c.DestCard),
                DestCard=str(c.SourceCard),
                SourceRole=str(c.DestRole) if not pd.isnull(c.DestRole) else str(core_data.objects.loc[c.End_Object_ID]["Name"]),
                DestRole=str(c.SourceRole) if not pd.isnull(c.SourceRole) else str(core_data.objects.loc[c.Start_Object_ID]["Name"]),
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
                DestRole=str(c.DestRole) if not pd.isnull(c.DestRole) else str(core_data.objects.loc[c.End_Object_ID]["Name"]),
                SourceRole=str(c.SourceRole) if not pd.isnull(c.SourceRole) else str(core_data.objects.loc[c.Start_Object_ID]["Name"]),
                Connector_ID="ASC_FWD_" + str(c.Index),
                Start_Object_ID=str(c.Start_Object_ID),
                End_Object_ID=str(c.End_Object_ID),
                Connector_Type=str(c.Connector_Type),
                weight=1.0,
            )

    return AG


def build_template_cim_graphs(template, core_data, GG, AG, AT, clean_dir=False):
    id2name = {
        **{obj.Index: str(obj.Name) for obj in core_data.objects.itertuples()},
        **{attr.Index: str(attr.Name) for attr in core_data.attributes.itertuples()},
    }
    cls_name2id = {str(obj.Name): obj.Index for obj in core_data.objects[core_data.objects["Object_Type"] == "Class"].itertuples() if pd.isnull(obj.Stereotype)}

    template_names = []
    template_names = collect_template_node_names(template, template_names)

    if clean_dir:
        for file in glob.glob("out/template_graphs/*"):
            os.remove(file)

    for name in template_names:
        obj_id = cls_name2id[name]
        nodes = {at for n in [obj_id] + list(nx.ancestors(GG, obj_id)) + list(nx.descendants(GG, obj_id)) for a in list(AG.neighbors(n)) + [n] for at in [n, a] + list(AT.predecessors(a)) + list(AT.predecessors(n))}

        SG = nx.subgraph(GG_AT_AG, nodes)
        nx.write_graphml(SG, f"out/template_graphs/{name}.graphml")


if __name__ == "__main__":
    from ravens.cim_tools.common import build_package_exclusions, build_object_exclusions
    from ravens.cim_tools.template import CIMTemplate
    from ravens.io import parse_eap_data

    db_filename = "cim/iec61970cim17v40_iec61968cim13v13b_iec62325cim03v17b_CIM100.1.1.1_mgravens24v1.eap"

    core_data = parse_eap_data(db_filename)

    exclude_packages = build_package_exclusions(core_data.packages, lambda x: any(str(x.Name).startswith(k) for k in ["Inf", "Mkt"]))
    exclude_objects = build_object_exclusions(
        core_data.objects,
        lambda x: any(str(x.Name).startswith(k) for k in ["Inf", "Mkt"]),
        exclude_packages=exclude_packages,
    )

    GG = build_generalization_graph(core_data, exclude_packages, exclude_objects)
    # nx.write_graphml(GG, "out/CIM_graphs/GG.graphml")
    AT = build_attribute_graph(core_data, exclude_packages, exclude_objects)
    # nx.write_graphml(AT, "out/CIM_graphs/AT.graphml")
    AG = build_association_graph(core_data, exclude_packages, exclude_objects)
    # nx.write_graphml(AG, "out/CIM_graphs/AG.graphml")

    GG_AT_AG = nx.compose_all([GG, AT, AG])
    nx.write_graphml(GG_AT_AG, "out/CIM_graphs/GG_AT_AG.graphml", named_key_ids=True, edge_id_from_attribute="Connector_ID")
    # nx.write_gml(GG_AT_AG, "out/CIM_graphs/GG_AT_AG.gml")

    cim_template = CIMTemplate("ravens/cim_tools/cim_conversion_template.json")
    build_template_cim_graphs(cim_template.template, core_data, GG, AG, AT, clean_dir=True)
