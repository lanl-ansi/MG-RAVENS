import html

from copy import deepcopy

import networkx as nx

from ravens.io import UMLData
from ravens.cim_tools.conversion import add_cim_attributes_to_properties


def add_attributes_to_template(data: dict, template: dict, uml_data: UMLData, GG: nx.MultiDiGraph, AT: nx.MultiDiGraph):
    "adds attributes from UML"
    if template["type"] == "object":
        for k, v in template.get("properties", {}).items():
            if v["type"] == "object":
                try:
                    object_name = k
                    if "$objectId" in v.keys():
                        object_name = v["$objectId"]
                    obj = uml_data.objects[(uml_data.objects["Name"] == object_name) & (uml_data.objects["Object_Type"] == "Class")].iloc[0]

                    if "description" not in v:
                        data["properties"][k]["description"] = html.unescape(str(obj.Note).strip())
                    if "title" not in v:
                        data["properties"][k]["title"] = html.unescape(str(obj.Name).strip())

                except Exception as msg:
                    raise Exception(f"Cannot find CIM object {object_name}: {msg}")

            if v.get("$objectType", "") == "container":
                data["properties"][k] = add_attributes_to_template(data["properties"][k], v, uml_data, GG, AT)
            elif v.get("$objectType", "") == "object":
                if "oneOf" in v.keys():
                    for i, item in enumerate(v["oneOf"]):
                        if item.get("$objectType", "") == "object":
                            object_name = item["$objectId"]
                            obj = uml_data.objects[(uml_data.objects["Name"] == object_name) & (uml_data.objects["Object_Type"] == "Class")].iloc[0]
                            if "title" not in item:
                                data["properties"][k]["oneOf"][i]["title"] = str(obj.Name)
                            if "description" not in item:
                                data["properties"][k]["oneOf"][i]["description"] = html.unescape(str(obj.Note).strip())

                            data["properties"][k]["oneOf"][i]["properties"] = add_cim_attributes_to_properties(data["properties"][k]["oneOf"][i]["properties"], item["$objectId"], item, uml_data, GG, AT)

                        data["properties"][k]["oneOf"][i] = add_attributes_to_template(data["properties"][k]["oneOf"][i], item, uml_data, GG, AT)
                else:
                    data["properties"][k]["properties"] = add_cim_attributes_to_properties(data["properties"][k]["properties"], k, v, uml_data, GG, AT)

                    data["properties"][k] = add_attributes_to_template(data["properties"][k], v, uml_data, GG, AT)

            elif v.get("$objectType", "") in ["reference", "oneOfReference"]:
                # do nothing
                continue
            elif v["type"] == "array":
                try:
                    if v["items"].get("type", "") == "array":
                        # do nothing
                        # TODO
                        continue
                    elif v["items"].get("$objectType", "") == "reference":
                        # do nothing
                        # TODO
                        continue
                    else:
                        object_name = v["items"].get("$objectId", k)
                        obj = uml_data.objects[(uml_data.objects["Name"] == object_name) & (uml_data.objects["Object_Type"] == "Class")].iloc[0]

                        if "description" not in v:
                            data["properties"][k]["description"] = data["properties"][k]["items"]["description"] = html.unescape(str(obj.Note).strip())
                        if "title" not in v:
                            data["properties"][k]["title"] = data["properties"][k]["items"]["title"] = html.unescape(str(obj.Name).strip())

                        if "oneOf" in v["items"]:
                            for i, item in enumerate(v["items"]["oneOf"]):
                                data["properties"][k]["items"]["oneOf"][i]["properties"] = add_cim_attributes_to_properties(data["properties"][k]["items"]["oneOf"][i]["properties"], k, item, uml_data, GG, AT)
                                data["properties"][k]["items"]["oneOf"][i] = add_attributes_to_template(data["properties"][k]["items"]["oneOf"][i], item, uml_data, GG, AT)
                        else:
                            data["properties"][k]["items"]["properties"] = add_cim_attributes_to_properties(data["properties"][k]["items"]["properties"], k, v["items"], uml_data, GG, AT)

                    data["properties"][k]["items"] = add_attributes_to_template(data["properties"][k]["items"], v["items"], uml_data, GG, AT)

                except KeyError as msg:
                    raise KeyError(f"Unabled to find {msg} in object {k} of type array")
            else:
                raise Exception(f"Object {k} of $objectType '{v.get('$objectType', '')}' not recognized")

    return data


if __name__ == "__main__":
    import json
    from ravens.io import parse_uml_data
    from ravens.cim_tools.common import build_package_exclusions, build_object_exclusions
    from ravens.cim_tools.graph import build_generalization_graph, build_attribute_graph
    from ravens.cim_tools.template import CIMTemplate

    db_filename = "cim/iec61970cim17v40_iec61968cim13v13b_iec62325cim03v17b_CIM100.1.1.1_mgravens24v1.xmi"

    uml_data = parse_uml_data(db_filename)

    exclude_packages = build_package_exclusions(uml_data.packages, lambda x: any(str(x.Name).startswith(k) for k in ["Inf", "Mkt"]))
    exclude_objects = build_object_exclusions(
        uml_data.objects,
        lambda x: any(str(x.Name).startswith(k) for k in ["Inf", "Mkt"]),
        exclude_packages=exclude_packages,
    )

    GG = build_generalization_graph(uml_data, exclude_packages, exclude_objects)
    AT = build_attribute_graph(uml_data, exclude_packages, exclude_objects)

    cim_template = CIMTemplate("ravens/cim_tools/cim_conversion_template.json")

    cim_template_with_attributes = add_attributes_to_template(deepcopy(cim_template.template), cim_template.template, uml_data, GG, AT)

    with open("out/schema/cim_template_with_attributes.json", "w") as f:
        json.dump(cim_template_with_attributes, f, indent=2)
