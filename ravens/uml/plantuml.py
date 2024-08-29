import html
import json

import pandas as pd

from ravens.io import CoreData, DiagramData

connector_strings = {
    "Generalization": "-up-|>",
    "Association": "--",
    "Aggregation": "--o",
    "Dependency": ".up.|>",
    "NoteLink": "..",
    "Package": "..|>",
}


def build_package_paths(data: dict) -> dict:
    pkg_id2name = {pkg.Package_ID: pkg.Name for pkg in data.packages.itertuples()}
    pkg_parent = {pkg.Package_ID: pkg.Parent_ID for pkg in data.packages.itertuples() if not pd.isnull(pkg.Parent_ID)}

    pkg_paths = {pkg.Package_ID: str(pkg.Name) for pkg in data.packages.itertuples()}
    for pkg in data.packages.itertuples():
        parent_id = pkg_parent[pkg.Package_ID]
        while parent_id != 0:
            pkg_paths[pkg.Package_ID] = f"{pkg_id2name[parent_id]}/{pkg_paths[pkg.Package_ID]}"
            parent_id = pkg_parent[parent_id]

    return pkg_paths


def build_all_plantuml_diagrams(uml_data):
    package_paths = build_package_paths(uml_data)

    diagrams = {}
    for diagram in uml_data.diagrams.itertuples():
        diagrams[f"{diagram.Name}.{diagram.Diagram_ID}"] = "\n".join(build_plantuml_diagram(uml_data, diagram, package_paths))

    return diagrams


def build_plantuml_diagram(uml_data: UMLData, diagram, package_paths):
    uml = [f"@startuml {diagram.Name}", "", f"title {package_paths[diagram.Package_ID]}/{diagram.Name}", ""]

    for obj in uml_data.diagramobjects[uml_data.diagramobjects["Diagram_ID"] == diagram.Diagram_ID].itertuples():
        uml.extend(build_plantuml_class(data, obj))

    for link in uml_data.diagramlinks[uml_data.diagramlinks["DiagramID"] == diagram.Diagram_ID].itertuples():
        uml.extend(build_plantuml_link(uml_data, link))

    uml.append("@enduml")

    return uml


def build_plantuml_class(uml_data: UMLData, obj):
    uml = []

    attrs = []
    for attr in uml_data.attributes[uml_data.attributes["Object_ID"] == obj.Object_ID].itertuples():
        if not pd.isnull(attr.Type):
            attrs.append(f"\t{attr.Name}::{attr.Type}")
        else:
            attrs.append(f"\t{attr.Name}")

    obj = uml_data.objects[uml_data.objects["Object_ID"] == obj.Object_ID].iloc[0]
    obj_name = obj.Name
    obj_stereotype = obj.Stereotype
    if pd.isnull(obj_name):
        return []

    if obj_stereotype == "enumeration":
        uml_obj_type = "enum"
    else:
        uml_obj_type = "class"

    if attrs:
        uml.append(f"{uml_obj_type} {obj_name}" + " {")
        uml.extend(attrs)
        uml.append("}")
    else:
        uml.append(f"{uml_obj_type} {obj_name}")
    uml.append("")

    return uml


def build_plantuml_link(uml_data: UMLData, link):
    uml = []

    connector = uml_data.connectors[uml_data.connectors["Connector_ID"] == link.ConnectorID].iloc[0]
    start_object_name = uml_data.objects[uml_data.objects["Object_ID"] == connector.Start_Object_ID].iloc[0].Name
    end_object_name = uml_data.objects[uml_data.objects["Object_ID"] == connector.End_Object_ID].iloc[0].Name
    connector_string = connector_strings[connector.Connector_Type]

    start_labels = " ".join([k for k in [connector.Top_Start_Label, connector.Btm_Start_Label] if not pd.isnull(k)])
    end_labels = " ".join([k for k in [connector.Top_End_Label, connector.Btm_End_Label] if not pd.isnull(k)])

    if start_labels and end_labels:
        uml.append(f'{start_object_name} "{start_labels}" {connector_string} "{end_labels}" {end_object_name}')
    elif start_labels and not end_labels:
        uml.append(f'{start_object_name} "{start_labels}" {connector_string} {end_object_name}')
    elif end_labels and not start_labels:
        uml.append(f'{start_object_name} {connector_string} "{end_labels}" {end_object_name}')
    else:
        uml.append(f"{start_object_name} {connector_string} {end_object_name}")

    return uml


if __name__ == "__main__":
    from ravens.io import parse_uml_data

    db_filename = "cim/iec61970cim17v40_iec61968cim13v13b_iec62325cim03v17b_CIM100.1.1.1_mgravens24v1.xmi"

    data = parse_uml_data(db_filename, set_index=False)

    plantuml_diagrams = build_all_plantuml_diagrams(uml_data)

    for diagram_name, uml in plantuml_diagrams.items():
        with open(f"out/uml/{diagram_name}.plantuml", "w") as f:
            f.write(uml)
