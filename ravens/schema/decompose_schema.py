from copy import deepcopy


class Schemas:
    def __init__(self, schema):
        self.schemas = {"__main__": {k: v for k, v in schema.items() if k != "$defs"}}

        self.decompose_schema(deepcopy(schema))
        self.decompose_defs(schema.get("$defs", {}))

        self.insert_refs()

    def decompose_schema(self, schema):
        if "patternProperties" in schema:
            for pattern, v in schema["patternProperties"].items():
                self.schemas[v["title"]] = v
                self.decompose_schema(v)
        elif "properties" in schema:
            for k, v in schema["properties"].items():
                try:
                    if ("$ref" not in v) and (v["type"] == "object" or (isinstance(v["type"], list) and "object" in v["type"])):
                        if "oneOf" in v:
                            self.schemas[v["title"]] = deepcopy(v)
                            for i, item in enumerate(v["oneOf"]):
                                self.schemas[item["title"]] = deepcopy(item)
                                self.decompose_schema(item)
                        elif "patternProperties" in v:
                            self.decompose_schema(v)
                        else:
                            self.schemas[v["title"]] = deepcopy(v)
                            self.decompose_schema(v)
                    elif ("$ref" not in v) and v["type"] == "array":
                        if v["items"]["type"] == "object":
                            if "oneOf" in v["items"]:
                                self.schemas[v["items"]["title"]] = deepcopy(v)
                                for i, item in enumerate(v["items"]["oneOf"]):
                                    self.schemas[item["title"]] = deepcopy(item)
                                    self.decompose_schema(item)
                            else:
                                self.schemas[v["items"]["title"]] = deepcopy(v["items"])
                                self.decompose_schema(v["items"])
                except Exception as msg:
                    print(k, v.keys(), msg)
        elif "oneOf" in schema:
            self.schemas[schema["title"]] = deepcopy(schema)
            for item in schema["oneOf"]:
                self.schemas[item["title"]] = deepcopy(item)
                self.decompose_schema(item)
        elif "items" in schema:
            print(schema["title"])
            self.schemas[schema["title"]] = deepcopy(schema)
            self.decompose_schema(schema["items"])

    def decompose_defs(self, defs):
        for k, v in defs.items():
            self.schemas[k] = v

    def insert_refs(self):
        for schema_key, schema in self.schemas.items():
            if "patternProperties" in schema:
                for pattern, json_object in schema["patternProperties"].items():
                    key = json_object.get("title", None)
                    if key in self.schemas:
                        self.schemas[schema_key]["patternProperties"][pattern] = {"$ref": f"./{key}.json"}
            elif "properties" in schema:
                for k, v in schema["properties"].items():
                    if v.get("type", "") == "object" or (isinstance(v.get("type", ""), list) and "object" in v["type"]):
                        key = v.get("title", k)
                        if key in self.schemas:
                            self.schemas[schema_key]["properties"][k] = {"$ref": f"./{key}.json"}

                    elif v.get("type", "") == "array" and v["items"].get("type", "") == "object":
                        key = v["items"].get("title", k)
                        if key in self.schemas:
                            self.schemas[schema_key]["properties"][k]["items"] = {"$ref": f"./{key}.json"}
                    elif v.get("$ref", "").startswith("#/$defs/"):
                        ref = v["$ref"].split("#/$defs/")[1]
                        if ref in self.schemas:
                            self.schemas[schema_key]["properties"][k]["$ref"] = f"./{ref}.json"
            elif "oneOf" in schema:
                for i, item in enumerate(schema["oneOf"]):
                    if item.get("$ref", "").startswith("#/$defs/"):
                        ref = v["$ref"].split("#/$defs/")[1]
                        if ref in self.schemas:
                            self.schemas[schema_key]["oneOf"][i]["$ref"] = f"./{ref}.json"
                    else:
                        key = item.get("title", "")
                        if key in self.schemas:
                            self.schemas[schema_key]["oneOf"][i] = {"$ref": f"./{key}.json"}
            elif "items" in schema:
                if "oneOf" in schema["items"]:
                    for i, item in enumerate(schema["items"]["oneOf"]):
                        if item.get("$ref", "").startswith("#/$defs/"):
                            ref = v["$ref"].split("#/$defs/")[1]
                            if ref in self.schemas:
                                self.schemas[schema_key]["items"]["oneOf"][i]["$ref"] = f"./{ref}.json"
                        else:
                            key = item.get("title", "")
                            if key in self.schemas:
                                self.schemas[schema_key]["items"]["oneOf"][i] = {"$ref": f"./{key}.json"}
                else:
                    key = schema["items"].get("title", "")
                    if key in self.schemas:
                        self.schemas[schema_key]["items"] = {"$ref": f"./{key}.json"}


if __name__ == "__main__":
    import json
    from ravens.io import parse_eap_data
    from ravens.cim_tools.common import build_package_exclusions, build_object_exclusions
    from ravens.cim_tools.graph import build_generalization_graph, build_attribute_graph
    from ravens.cim_tools.template import CIMTemplate
    from ravens.schema.build_definitions import build_definitions
    from ravens.schema.build_map import add_attributes_to_template
    from ravens.schema.build_schema import build_schema_from_map
    from ravens.schema.add_copyright_notice import add_cim_copyright_notice_to_decomposed_schemas
    import json_schema_for_humans.generate as Gen

    core_data = parse_eap_data("cim/iec61970cim17v40_iec61968cim13v13b_iec62325cim03v17b_CIM100.1.1.1_mgravens24v1.eap")

    exclude_packages = build_package_exclusions(core_data.packages, lambda x: any(str(x.Name).startswith(k) for k in ["Inf", "Mkt"]))
    exclude_objects = build_object_exclusions(
        core_data.objects,
        lambda x: any(str(x.Name).startswith(k) for k in ["Inf", "Mkt"]),
        exclude_packages=exclude_packages,
    )

    schema = build_schema_from_map(
        add_attributes_to_template(
            CIMTemplate("ravens/cim_tools/cim_conversion_template.json").template,
            CIMTemplate("ravens/cim_tools/cim_conversion_template.json").template,
            core_data,
            build_generalization_graph(core_data, exclude_packages, exclude_objects),
            build_attribute_graph(core_data, exclude_packages, exclude_objects),
        )
    )

    schema["$defs"] = build_definitions(core_data)

    a = Schemas(schema)

    add_cim_copyright_notice_to_decomposed_schemas(a.schemas, core_data)

    with open("out/schema/test_schemas.json", "w") as f:
        json.dump(a.schemas, f, indent=2)

    for k, v in a.schemas.items():
        with open(f"out/schema/separate/{k}.json", "w") as f:
            json.dump(v, f, indent=2)

    Gen.generate_from_filename("out/schema/separate/", "out/schema/docs/")
