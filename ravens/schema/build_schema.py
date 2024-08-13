def build_schema_from_map(schema_map: dict) -> dict:
    schema = {}
    for k, v in schema_map.items():
        if k.startswith("$"):
            continue
        elif isinstance(v, dict):
            if "type" in v:
                if v["type"] == "object":
                    if "properties" in v:
                        if v.get("$primaryObjectHash", None) is None:
                            schema[k] = build_schema_from_map(v)
                        else:
                            schema[k] = {
                                "type": "object",
                                "title": v.get("title", ""),
                                "description": v.get("title", ""),
                                "patternProperties": {
                                    "^.+$": {
                                        **{_k: _v for _k, _v in v.items() if not _k.startswith("$") and _k != "properties"},
                                        **{"properties": build_schema_from_map(v["properties"])},
                                    }
                                },
                            }

                    elif "oneOf" in v:
                        if v.get("$primaryObjectHash", None) is None:
                            schema[k] = build_schema_from_map(v)
                        else:
                            schema[k] = {
                                "type": "object",
                                "patternProperties": {
                                    "^.+$": {
                                        **{_k: _v for _k, _v in v.items() if not _k.startswith("$") and _k != "oneOf"},
                                        **{"oneOf": [build_schema_from_map(item) for item in v["oneOf"]]},
                                    }
                                },
                            }

                elif v["type"] == "array":
                    schema[k] = {
                        **{_k: _v for _k, _v in v.items() if not _k.startswith("$") and _k != "items"},
                        **{"items": build_schema_from_map(v["items"])},
                    }
                else:
                    schema[k] = build_schema_from_map(v)
            else:
                schema[k] = build_schema_from_map(v)
        elif k == "oneOf" and isinstance(v, list):
            schema[k] = [build_schema_from_map(item) for item in v]
        elif k == "type" and v not in ["object", "string", "array", "boolean", "number", "null", "integer"]:
            schema["$ref"] = f"#/$defs/{v}"
        else:
            schema[k] = v

    return schema


if __name__ == "__main__":
    from copy import deepcopy
    import json
    from ravens.io import parse_eap_data, write_schema_docs
    from ravens.cim_tools.common import build_package_exclusions, build_object_exclusions
    from ravens.cim_tools.graph import build_generalization_graph, build_attribute_graph
    from ravens.cim_tools.template import CIMTemplate
    from ravens.schema.build_definitions import build_definitions
    from ravens.schema.build_map import add_attributes_to_template
    import json_schema_for_humans.generate as Gen

    db_filename = "cim/iec61970cim17v40_iec61968cim13v13b_iec62325cim03v17b_CIM100.1.1.1_mgravens24v1.eap"

    core_data = parse_eap_data(db_filename)

    exclude_packages = build_package_exclusions(core_data.packages, lambda x: any(str(x.Name).startswith(k) for k in ["Inf", "Mkt"]))
    exclude_objects = build_object_exclusions(
        core_data.objects,
        lambda x: any(str(x.Name).startswith(k) for k in ["Inf", "Mkt"]),
        exclude_packages=exclude_packages,
    )

    GG = build_generalization_graph(core_data, exclude_packages, exclude_objects)
    AT = build_attribute_graph(core_data, exclude_packages, exclude_objects)

    cim_template = CIMTemplate("ravens/cim_tools/cim_conversion_template.json")

    cim_template_with_attributes = add_attributes_to_template(deepcopy(cim_template.template), cim_template.template, core_data, GG, AT)

    with open("out/schema/cim_template_with_attributes.json", "w") as f:
        json.dump(cim_template_with_attributes, f, indent=2)

    schema = build_schema_from_map(cim_template_with_attributes)

    schema["$defs"] = build_definitions(core_data)

    with open("out/schema/test_schema_conversion.json", "w") as f:
        json.dump(schema, f, indent=2)

    Gen.generate_from_filename("out/schema/test_schema_conversion.json", "out/schema/test_schema_conversion.html")
