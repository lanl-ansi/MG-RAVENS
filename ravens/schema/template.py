import html
import json
import pathlib

import networkx as nx
import pandas as pd

from copy import deepcopy

from ravens.data import _TEMPLATE_JSON_PATH, _CIM_PRIMATIVES
from ravens.io import UMLData
from ravens.uml.graph import UMLGraphs
from ravens.uml.exclusions import UMLExclusions


class SchemaTemplate:
    def __init__(self, uml_data: UMLData = None, uml_graphs: UMLGraphs = None, uml_exclusions: UMLExclusions = None):
        if uml_data is None:
            uml_data = UMLData()

        self.uml_data = uml_data
        self.uml_graphs = UMLGraphs(self.uml_data, exclusions=uml_exclusions) if uml_graphs is None else uml_graphs

        self.template = {}
        self.raw_template = {}
        self.nodes = []

        self.loadf(_TEMPLATE_JSON_PATH)

    def loadf(self, file: pathlib.PosixPath = _TEMPLATE_JSON_PATH) -> object:
        with open(file, "r") as f:
            return self.loadio(f)

    def loads(self, json_str: str) -> object:
        self.raw_template = json.loads(json_str)
        self.template = deepcopy(self.raw_template)
        self.nodes = self.collect_template_node_names(self.template)
        self.template = self.add_attributes_to_template(self.template, self.raw_template)

        return self

    def loadio(self, io):
        return self.loads(io.read())

    def add_attributes_to_template(self, data: dict, template: dict):
        GG = self.uml_graphs.gen_graph
        AT = self.uml_graphs.attr_graph

        if template["type"] == "object":
            for k, v in template.get("properties", {}).items():
                if v["type"] == "object":
                    try:
                        object_name = k
                        if "$objectId" in v.keys():
                            object_name = v["$objectId"]
                        obj = self.uml_data.objects[(self.uml_data.objects["Name"] == object_name) & (self.uml_data.objects["Object_Type"] == "Class")].iloc[0]

                        if "description" not in v and not pd.isnull(obj.Note):
                            data["properties"][k]["description"] = html.unescape(str(obj.Note).strip())
                        if "title" not in v:
                            data["properties"][k]["title"] = html.unescape(str(obj.Name).strip())

                    except Exception as msg:
                        raise Exception(f"Cannot find CIM object {object_name}: {msg}")

                if v.get("$objectType", "") == "container":
                    data["properties"][k] = self.add_attributes_to_template(data["properties"][k], v)
                elif v.get("$objectType", "") == "object":
                    if "oneOf" in v.keys():
                        for i, item in enumerate(v["oneOf"]):
                            if item.get("$objectType", "") == "object":
                                object_name = item["$objectId"]
                                obj = self.uml_data.objects[(self.uml_data.objects["Name"] == object_name) & (self.uml_data.objects["Object_Type"] == "Class")].iloc[0]
                                if "title" not in item:
                                    data["properties"][k]["oneOf"][i]["title"] = str(obj.Name)
                                if "description" not in item and not pd.isnull(obj.Note):
                                    data["properties"][k]["oneOf"][i]["description"] = html.unescape(str(obj.Note).strip())

                                data["properties"][k]["oneOf"][i]["properties"] = self.add_cim_attributes_to_properties(data["properties"][k]["oneOf"][i]["properties"], item["$objectId"], item)

                            data["properties"][k]["oneOf"][i] = self.add_attributes_to_template(data["properties"][k]["oneOf"][i], item)
                    else:
                        data["properties"][k]["properties"] = self.add_cim_attributes_to_properties(data["properties"][k]["properties"], k, v)

                        data["properties"][k] = self.add_attributes_to_template(data["properties"][k], v)

                elif v.get("$objectType", "") == "reference":
                    obj = self.uml_data.objects[(self.uml_data.objects["Name"] == v["$objectId"]) & (self.uml_data.objects["Object_Type"] == "Class")].iloc[0]
                    if "title" not in v:
                        data["properties"][k]["title"] = html.unescape(str(obj.Name).strip()) + "Pointer"
                    if "description" not in v:
                        data["properties"][k]["description"] = f"Pointer to {html.unescape(str(obj.Name).strip())} object"
                elif v["type"] == "array":
                    try:
                        if v["items"].get("type", "") == "array":
                            # do nothing
                            continue
                        elif v["items"].get("$objectType", "") == "reference":
                            obj = self.uml_data.objects[(self.uml_data.objects["Name"] == v["items"].get("$objectId", k)) & (self.uml_data.objects["Object_Type"] == "Class")].iloc[0]
                            data["properties"][k]["description"] = f"Pointers to {html.unescape(str(obj.Name).strip())} objects"
                            data["properties"][k]["title"] = html.unescape(str(obj.Name).strip()) + "PointerArray"
                            data["properties"][k]["items"]["title"] = html.unescape(str(obj.Name).strip()) + "Pointer"
                            data["properties"][k]["items"]["description"] = f"Pointer to {html.unescape(str(obj.Name).strip())} object"
                        else:
                            obj = self.uml_data.objects[(self.uml_data.objects["Name"] == v["items"].get("$objectId", k)) & (self.uml_data.objects["Object_Type"] == "Class")].iloc[0]

                            data["properties"][k]["title"] = html.unescape(str(obj.Name).strip()) + "Array"
                            data["properties"][k]["description"] = f"Array of {html.unescape(str(obj.Name).strip())} objects"
                            data["properties"][k]["items"]["title"] = html.unescape(str(obj.Name).strip())
                            if not pd.isnull(obj.Note):
                                data["properties"][k]["items"]["description"] = html.unescape(str(obj.Note).strip())

                            if "oneOf" in v["items"]:
                                for i, item in enumerate(v["items"]["oneOf"]):
                                    oneof_obj = self.uml_data.objects[(self.uml_data.objects["Name"] == item["$objectId"]) & (self.uml_data.objects["Object_Type"] == "Class")].iloc[0]
                                    data["properties"][k]["items"]["oneOf"][i]["title"] = html.unescape(str(oneof_obj.Name).strip())
                                    if not pd.isnull(oneof_obj.Note):
                                        data["properties"][k]["items"]["oneOf"][i]["description"] = html.unescape(str(oneof_obj.Note).strip())

                                    data["properties"][k]["items"]["oneOf"][i]["properties"] = self.add_cim_attributes_to_properties(data["properties"][k]["items"]["oneOf"][i]["properties"], k, item)
                                    data["properties"][k]["items"]["oneOf"][i] = self.add_attributes_to_template(data["properties"][k]["items"]["oneOf"][i], item)
                            else:
                                data["properties"][k]["items"]["properties"] = self.add_cim_attributes_to_properties(data["properties"][k]["items"]["properties"], k, v["items"])

                        data["properties"][k]["items"] = self.add_attributes_to_template(data["properties"][k]["items"], v["items"])

                    except KeyError as msg:
                        raise KeyError(f"Unabled to find {msg} in object {k} of type array")
                else:
                    raise Exception(f"Object {k} of $objectType '{v.get('$objectType', '')}' not recognized")

        return data

    def add_cim_attributes_to_properties(self, properties: dict, k: str, v: dict) -> dict:
        GG = self.uml_graphs.gen_graph
        AT = self.uml_graphs.attr_graph

        try:
            if "$objectId" in v.keys():
                object_name = v["$objectId"]
            else:
                object_name = k

            object_id = self.uml_data.objects[(self.uml_data.objects["Name"] == object_name) & (self.uml_data.objects["Object_Type"] == "Class")].iloc[0]._name
        except:
            raise KeyError(f"Object {object_name} Object_ID not found in CIM UML")
        attribute_ids = {a for n in [object_id] + list(nx.ancestors(GG, object_id)) + list(nx.descendants(GG, object_id)) for a in list(AT.predecessors(n))}
        for attr_id in attribute_ids:
            attribute = self.uml_data.attributes.loc[attr_id]
            parent = self.uml_data.objects.loc[attribute.Object_ID]
            try:
                attribute_name = f"{parent.Name}.{attribute.Name}"

                attribute_data = {
                    "title": str(attribute.Name),
                    "type": self.convert_cim_type(str(attribute.Type)),
                }
                if not pd.isnull(attribute.Notes):
                    attribute_data["description"] = html.unescape(str(attribute.Notes).strip())
                if attribute_name in properties.keys():
                    attribute_data.update(properties[attribute_name])

                properties[attribute_name] = attribute_data
            except:
                raise Exception(f"Failed to add attribute {attribute.Name} to {k}")

        return properties

    @staticmethod
    def convert_cim_type(cim_type: str) -> str:
        return _CIM_PRIMATIVES.get(cim_type, cim_type)

    @staticmethod
    def collect_template_node_names(template: dict, nodes: list = None, currentParent: str = None, parentObject: str = None):
        if nodes is None:
            nodes = []

        for k, v in template.items():
            if isinstance(v, dict) and v.get("type", "none") == "container":
                nodes = self.collect_template_node_names(v.get("properties", {}), nodes, parentObject=k)
            elif isinstance(v, dict) and v.get("type", "none") == "object":
                if currentParent is not None:
                    nodes.append(f"{currentParent}::{k}")
                    nodes = self.collect_template_node_names(v.get("properties", {}), nodes, currentParent=f"{currentParent}::{k}")
                else:
                    nodes.append(k)
                    nodes = self.collect_template_node_names(v.get("properties", {}), nodes, currentParent=k)
            elif isinstance(v, dict) and v.get("type", "none") == "ref":
                continue

        return nodes


if __name__ == "__main__":
    template = SchemaTemplate()

    template.template
