import html
import json

import pandas as pd

from ravens.io import CoreData


cim_primitives_to_json = {
    "Integer": "integer",
    "Float": "number",
    "String": "string",
    "Boolean": "boolean",
    "Time": "string",
    "Decimal": "number",
    "Date": "string",
    "Duration": "string",
    "DateTime": "string",
    "MonthDay": "string",
    "integer": "integer",
    "number": "number",
    "string": "string",
    "boolean": "boolean",
    "null": "null",
    "object": "object",
    "array": "array",
}


def build_definitions(core_data: CoreData) -> dict:
    defs = {}
    for obj in core_data.objects[core_data.objects["Object_Type"] == "Class"].itertuples():
        if str(obj.Stereotype).strip() == "enumeration":
            defs[str(obj.Name).replace(" ", "")] = {
                "title": str(obj.Name).replace(" ", ""),
                "description": html.unescape(str(obj.Note)).strip(),
                "type": "string",
                "enum": [str(attr.Name) for attr in core_data.attributes[core_data.attributes["Object_ID"] == obj.Index].itertuples()],
            }
        elif not pd.isnull(obj.Stereotype):
            defs[str(obj.Name).replace(" ", "")] = {
                "title": str(obj.Name).replace(" ", ""),
                "description": html.unescape(str(obj.Note)).strip(),
                "type": "object",
                "properties": {
                    str(attr.Name): {
                        "type": str(attr.Type) if str(attr.Type) not in cim_primitives_to_json else cim_primitives_to_json[str(attr.Type)],
                        "description": str(attr.Notes),
                        "default": attr.Default if not pd.isnull(attr.Default) else "none" if str(attr.Type) == "UnitMultiplier" else None,
                    }
                    for attr in core_data.attributes[core_data.attributes["Object_ID"] == obj.Index].itertuples()
                },
            }

            if (
                all(v["default"] is not None for k, v in defs[str(obj.Name).replace(" ", "")]["properties"].items() if k != "value")
                and "value" in defs[str(obj.Name).replace(" ", "")]["properties"]
            ):
                defs[str(obj.Name).replace(" ", "")]["type"] = [
                    "object",
                    cim_primitives_to_json[defs[str(obj.Name).replace(" ", "")]["properties"]["value"]["type"]],
                ]


    for k, v in defs.items():
        if "properties" in v:
            for _k,_v in v["properties"].items():
                if "type" in _v and _v["type"] in defs:
                    _v["$ref"] = f"#/$defs/{_v.pop("type")}"

    return defs


if __name__ == "__main__":
    from ravens.io import parse_eap_data

    db_filename = "cim/iec61970cim17v40_iec61968cim13v13b_iec62325cim03v17b_CIM100.1.1.1.eap"

    core_data = parse_eap_data(db_filename)

    defs = build_definitions(core_data)

    with open("out/schema/definitions.json", "w") as f:
        json.dump({"title": "CIM definitions", "type": "object", "properties": {}, "$defs": defs}, f, indent=2)
