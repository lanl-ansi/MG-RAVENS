import html

import networkx as nx

from ravens.io import UMLData

cimPrimativesMap = {
    "Integer": "integer",
    "Float": "number",
    "Decimal": "number",
    "Boolean": "boolean",
    "String": "string",
    "Time": "string",
    "Date": "string",
    "Duration": "string",
    "DateTime": "string",
    "MonthDay": "string",
}


def convert_cim_type(cim_type: str) -> str:
    if cim_type in cimPrimativesMap:
        return cimPrimativesMap[cim_type]

    return cim_type


def add_cim_attributes_to_properties(properties: dict, k: str, v: dict, uml_data: UMLData, GG: nx.DiGraph, AT: nx.DiGraph) -> dict:
    try:
        if "$objectId" in v.keys():
            object_name = v["$objectId"]
        else:
            object_name = k

        object_id = uml_data.objects[(uml_data.objects["Name"] == object_name) & (uml_data.objects["Object_Type"] == "Class")].iloc[0]._name
    except:
        raise KeyError(f"Object {object_name} Object_ID not found in CIM UML")
    attribute_ids = {a for n in [object_id] + list(nx.ancestors(GG, object_id)) + list(nx.descendants(GG, object_id)) for a in list(AT.predecessors(n))}
    for attr_id in attribute_ids:
        attribute = uml_data.attributes.loc[attr_id]
        parent = uml_data.objects.loc[attribute.Object_ID]
        try:
            attribute_name = f"{parent.Name}.{attribute.Name}"

            attribute_data = {
                "title": str(attribute.Name),
                "type": convert_cim_type(str(attribute.Type)),
                "description": html.unescape(str(attribute.Notes).strip()),
            }
            if attribute_name in properties.keys():
                attribute_data.update(properties[attribute_name])

            properties[attribute_name] = attribute_data
        except:
            raise Exception(f"Failed to add attribute {attribute.Name} to {k}")

    return properties
