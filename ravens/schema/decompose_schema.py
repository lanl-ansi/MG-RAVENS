from copy import deepcopy

_default_base_uri = "https://raw.githubusercontent.com/lanl-ansi/MG-RAVENS/refs/heads/schema/schema"
_schema_url = "https://json-schema.org/draft/2020-12/schema"


class Schemas:
    def __init__(self, schema, base_id_uri=_default_base_uri):
        self.schema = deepcopy(schema)
        self.schemas = {}
        self.base_id_uri = base_id_uri

        self.decompose_schema(deepcopy(self.schema))
        self.decompose_defs(deepcopy(self.schema).get("$defs", {}))
        self.schemas[f"{self.base_id_uri}/Root.json"].pop("$defs")

        self.insert_refs()

    def decompose_schema(self, schema: dict, debug_key: str = None) -> str:
        _schema = deepcopy(schema)

        if isinstance(_schema, dict):
            _schema["$schema"] = _schema_url
            _schema["additionalProperties"] = False

            title = _schema.get("title", None)
            if title is not None:
                if "patternProperties" in _schema:
                    title = f"{title}_Container"
            else:
                print(debug_key, _schema.keys())

            _schema["$id"] = f"{self.base_id_uri}/{title}.json"

            if _schema.get("type", None) == "object":
                for n in ["properties", "patternProperties"]:
                    if n in _schema:
                        for k, v in _schema[n].items():
                            ref_id = self.decompose_schema(v, debug_key=k)
                            if ref_id is not None:
                                _schema[n][k] = {"$ref": ref_id}

                if "oneOf" in _schema:
                    _oneOf = []
                    for item in _schema["oneOf"]:
                        ref_id = self.decompose_schema(item, debug_key=debug_key)
                        if ref_id is not None:
                            _oneOf.append({"$ref": ref_id})
                        else:
                            _oneOf.append(item)

                    _schema["oneOf"] = _oneOf

            elif _schema.get("type", None) == "array":
                ref_id = self.decompose_schema(_schema["items"], debug_key=debug_key)
                if ref_id is not None:
                    _schema["items"] = {"$ref": ref_id}
            else:
                return None

            self.schemas[_schema["$id"]] = _schema

            return _schema["$id"]

        return None

    def decompose_defs(self, defs: dict):
        for k, v in defs.items():
            _schema = deepcopy(v)
            _schema["$schema"] = _schema_url
            _schema["$id"] = f"{self.base_id_uri}/{_schema["title"]}.json"
            self.schemas[_schema["$id"]] = _schema

    def insert_refs(self):
        for schema_key, schema in self.schemas.items():
            # print(schema_key, schema.keys())
            if schema.get("patternProperties", None) is not None:
                for pattern, json_object in schema["patternProperties"].items():
                    key = json_object.get("$id", None)
                    if key in self.schemas.keys():
                        self.schemas[schema_key]["patternProperties"][pattern] = {"$ref": key}
            elif "properties" in schema.keys():
                for k, v in schema["properties"].items():
                    if v.get("type", "") == "object" or (isinstance(v.get("type", ""), list) and "object" in v["type"]):
                        key = v.get("$id", k)
                        if key in self.schemas:
                            self.schemas[schema_key]["properties"][k] = {"$ref": key}

                    elif v.get("type", "") == "array" and v["items"].get("type", "") == "object":
                        key = v["items"].get("$id", k)
                        if key in self.schemas:
                            self.schemas[schema_key]["properties"][k]["items"] = {"$ref": key}
                    elif v.get("$ref", "").startswith("#/$defs/"):
                        ref = v["$ref"].split("#/$defs/")[1]
                        if f"{self.base_id_uri}/{ref}.json" in self.schemas:
                            self.schemas[schema_key]["properties"][k]["$ref"] = f"{self.base_id_uri}/{ref}.json"
            elif "oneOf" in schema:
                for i, item in enumerate(schema["oneOf"]):
                    if item.get("$ref", "").startswith("#/$defs/"):
                        ref = v["$ref"].split("#/$defs/")[1]
                        if f"{self.base_id_uri}/{ref}.json" in self.schemas:
                            self.schemas[schema_key]["oneOf"][i]["$ref"] = f"{self.base_id_uri}/{ref}.json"
                    else:
                        key = item.get("title", "")
                        if key in self.schemas:
                            self.schemas[schema_key]["oneOf"][i] = {"$ref": f"./{key}.json"}
            elif "items" in schema:
                if "oneOf" in schema["items"]:
                    for i, item in enumerate(schema["items"]["oneOf"]):
                        if item.get("$ref", "").startswith("#/$defs/"):
                            ref = v["$ref"].split("#/$defs/")[1]
                            if f"{self.base_id_uri}/{ref}.json" in self.schemas:
                                self.schemas[schema_key]["items"]["oneOf"][i]["$ref"] = f"{self.base_id_uri}/{ref}.json"
                        else:
                            key = item.get("$id", "")
                            if key in self.schemas:
                                self.schemas[schema_key]["items"]["oneOf"][i] = {"$ref": key}
                else:
                    key = schema["items"].get("$id", "")
                    if key in self.schemas:
                        self.schemas[schema_key]["items"] = {"$ref": key}


if __name__ == "__main__":
    import json
    import os
    from ravens.io import parse_uml_data
    from ravens.cim_tools.common import build_package_exclusions, build_object_exclusions
    from ravens.cim_tools.graph import build_generalization_graph, build_attribute_graph
    from ravens.cim_tools.template import CIMTemplate
    from ravens.schema.build_definitions import build_definitions
    from ravens.schema.build_map import add_attributes_to_template
    from ravens.schema.build_schema import build_schema_from_map
    from ravens.schema.add_copyright_notice import add_cim_copyright_notice_to_decomposed_schemas
    import json_schema_for_humans.generate as Gen

    uml_data = parse_uml_data("cim/iec61970cim17v40_iec61968cim13v13b_iec62325cim03v17b_CIM100.1.1.1_mgravens24v1.xmi")

    exclude_packages = build_package_exclusions(uml_data.packages, lambda x: any(str(x.Name).startswith(k) for k in ["Inf", "Mkt"]))
    exclude_objects = build_object_exclusions(
        uml_data.objects,
        lambda x: any(str(x.Name).startswith(k) for k in ["Inf", "Mkt"]),
        exclude_packages=exclude_packages,
    )

    schema = build_schema_from_map(
        add_attributes_to_template(
            CIMTemplate("ravens/cim_tools/cim_conversion_template.json").template,
            CIMTemplate("ravens/cim_tools/cim_conversion_template.json").template,
            uml_data,
            build_generalization_graph(uml_data, exclude_packages, exclude_objects),
            build_attribute_graph(uml_data, exclude_packages, exclude_objects),
        )
    )

    schema["$defs"] = build_definitions(uml_data)

    a = Schemas(schema, base_id_uri=f"file://{os.getcwd()}/out/schema/separate")

    add_cim_copyright_notice_to_decomposed_schemas(a.schemas, uml_data)

    with open("out/schema/test_schema.json", "w") as f:
        json.dump(schema, f, indent=2)

    for k, v in a.schemas.items():
        filename = k.split("/")[-1].replace(".json", "")
        with open(f"out/schema/separate/{filename}.json", "w") as f:
            json.dump(v, f, indent=2)

    Gen.generate_from_filename("out/schema/separate/", "out/schema/docs/")
