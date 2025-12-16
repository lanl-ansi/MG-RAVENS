import html
import json
import os
import pathlib
from typing import Any

import json_schema_for_humans.generate as Gen
import markdownify
import pandas as pd

from copy import deepcopy

from ravens.data import _RAVENS_SCHEMA_BASE_URL, _JSON_SCHEMA_URL, _CIM_PRIMATIVES
from ravens.uml import UMLData, UMLGraphs, UMLExclusions
from ravens.schema.template import SchemaTemplate
from ravens.logging import logger


class RavensSchema:
    def __init__(
        self,
        schema_template: SchemaTemplate | None = None,
        base_id_uri: str = _RAVENS_SCHEMA_BASE_URL,
        uml_data: UMLData | None = None,
        uml_graphs: UMLGraphs | None = None,
        uml_exclusions: UMLExclusions | None = None,
        omit_file_extension: bool = False,
        omit_license: bool = False,
        omit_descriptions: bool = False,
    ):
        if uml_data is None:
            uml_data = UMLData()

        self.uml_data = uml_data

        self.schema_template = SchemaTemplate(uml_data=uml_data, uml_graphs=uml_graphs, uml_exclusions=uml_exclusions, omit_descriptions=omit_descriptions) if schema_template is None else schema_template

        self.omit_descr = omit_descriptions

        self.schema = self.build_schema_from_map(self.schema_template.template)
        self.schema["$defs"] = self.build_definitions(self.uml_data)
        self.schema["$id"] = f"{base_id_uri}/Root.json"
        self.schema["$schema"] = _JSON_SCHEMA_URL
        self.schema["additionalProperties"] = False

        self.schemas = {}
        self.base_id_uri = base_id_uri
        self.omit_file_extension = omit_file_extension

        self.decompose_schema(deepcopy(self.schema))
        self.decompose_defs(deepcopy(self.schema).get("$defs", {}))

        self.schemas[self.schema_path("Root")].pop("$defs")

        self.insert_refs()

        if not omit_license:
            self.add_cim_copyright_notice_to_decomposed_schemas(self.uml_data)

    def schema_path(self, schema_id):
        return "/".join(a for a in [self.base_id_uri, schema_id + (".json" if not self.omit_file_extension else "")] if a)

    def build_schema_from_map(self, schema_map: dict) -> dict:
        schema: dict[str, Any] = {}
        for k, v in schema_map.items():
            if k.startswith("$"):
                continue
            elif isinstance(v, dict):
                if "type" in v or "$objectType" in v:
                    if v.get("type", None) == "object" or v.get("$objectType", None) == "object":
                        if "properties" in v:
                            v["additionalProperties"] = False
                            if v.get("$primaryObjectHash", None) is None:
                                schema[k] = self.build_schema_from_map(v)
                                schema[k]["additionalProperties"] = False
                            else:
                                schema[k] = {
                                    "type": "object",
                                    "title": v.get("title", "") + "Container",
                                    "description": f"Hash table of {v.get('title', '')} objects",
                                    "patternProperties": {
                                        "^.+$": {
                                            **{_k: _v for _k, _v in v.items() if not _k.startswith("$") and _k != "properties"},
                                            **{"properties": self.build_schema_from_map(v["properties"])},
                                        }
                                    },
                                }

                                if self.omit_descr:
                                    schema[k].pop("description")

                        elif "anyOf" in v:
                            if v.get("$primaryObjectHash", None) is None:
                                schema[k] = self.build_schema_from_map(v)
                            else:
                                schema[k] = {
                                    "type": "object",
                                    "title": v.get("title", "") + "Container",
                                    "description": f"Hash table of {v.get('title', '')} objects",
                                    "patternProperties": {
                                        "^.+$": {
                                            **{_k: _v for _k, _v in v.items() if not _k.startswith("$") and _k != "anyOf"},
                                            **{"anyOf": [self.build_schema_from_map(item if "properties" not in item else {"additionalProperties": False, **item}) for item in v["anyOf"]]},
                                        }
                                    },
                                }

                                if self.omit_descr:
                                    schema[k].pop("description")

                    elif v.get("type", None) == "array":
                        schema[k] = {
                            **{_k: _v for _k, _v in v.items() if not _k.startswith("$") and _k != "items"},
                            **{"items": self.build_schema_from_map(v["items"])},
                        }
                    else:
                        schema[k] = self.build_schema_from_map(v)
                else:
                    schema[k] = self.build_schema_from_map(v)
            elif k == "anyOf" and isinstance(v, list):
                schema[k] = [self.build_schema_from_map(item) for item in v]
            elif k == "type" and v not in ["object", "string", "array", "boolean", "number", "null", "integer"]:
                schema["$ref"] = f"#/$defs/{v}"
            else:
                schema[k] = v

        return schema

    def build_definitions(self, uml_data: UMLData) -> dict:
        defs = {}
        for obj in uml_data.objects[uml_data.objects["Object_Type"] == "Class"].itertuples():
            if str(obj.Stereotype).strip() == "enumeration":
                defs[str(obj.Name).replace(" ", "")] = {
                    "title": str(obj.Name).replace(" ", ""),
                    "description": html.unescape(str(obj.Note)).strip(),
                    "type": "string",
                    "enum": [f"{str(obj.Name)}.{str(attr.Name)}" for attr in uml_data.attributes[uml_data.attributes["Object_ID"] == obj.Index].itertuples()],
                }
                if self.omit_descr:
                    defs[str(obj.Name).replace(" ", "")].pop("description")
            elif not pd.isnull(obj.Stereotype):
                defs[str(obj.Name).replace(" ", "")] = {
                    "title": str(obj.Name).replace(" ", ""),
                    "description": html.unescape(str(obj.Note)).strip(),
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        str(attr.Name): {
                            "type": str(attr.Type) if str(attr.Type) not in _CIM_PRIMATIVES else _CIM_PRIMATIVES[str(attr.Type)],
                            "description": str(attr.Notes),
                            "default": attr.Default if not pd.isnull(attr.Default) else "none" if str(attr.Type) == "UnitMultiplier" else None,
                        }
                        for attr in uml_data.attributes[uml_data.attributes["Object_ID"] == obj.Index].itertuples()
                    },
                }
                if self.omit_descr:
                    defs[str(obj.Name).replace(" ", "")].pop("description")
                    for v in defs[str(obj.Name).replace(" ", "")]["properties"].values():
                        v.pop("description")

                if all(v["default"] is not None for k, v in defs[str(obj.Name).replace(" ", "")]["properties"].items() if k != "value") and "value" in defs[str(obj.Name).replace(" ", "")]["properties"]:
                    defs[str(obj.Name).replace(" ", "")]["type"] = [
                        "object",
                        _CIM_PRIMATIVES[defs[str(obj.Name).replace(" ", "")]["properties"]["value"]["type"]],
                    ]

        for k, v in defs.items():
            if "properties" in v:
                for _k, _v in v["properties"].items():
                    if "type" in _v and _v["type"] in defs:
                        _v["$ref"] = f"#/$defs/{_v.pop("type")}"

        return defs

    def decompose_schema(self, schema: dict, debug_key: str | None = None) -> str | None:
        _schema = deepcopy(schema)

        if isinstance(_schema, dict):
            _schema["$schema"] = _JSON_SCHEMA_URL
            if "anyOf" not in _schema:
                _schema["additionalProperties"] = False

            title = _schema.get("title", None)
            if title is not None:
                if "patternProperties" in _schema:
                    title = f"{title}_Container"
                if "anyOf" in _schema:
                    title = f"{title}_anyOfContainer"
            else:
                logger.warning(f"When decomposing the schema, 'title' was not found on a {debug_key} object, only the following keys: {list(_schema.keys())}")

            _schema["$id"] = self.schema_path(title)

            if _schema.get("type", None) == "object":
                for n in ["properties", "patternProperties"]:
                    if n in _schema:
                        for k, v in _schema[n].items():
                            ref_id = self.decompose_schema(v, debug_key=k)
                            if ref_id is not None:
                                _schema[n][k] = {"$ref": ref_id}
            elif _schema.get("type", None) == "array":
                ref_id = self.decompose_schema(_schema["items"], debug_key=debug_key)
                if ref_id is not None:
                    _schema["items"] = {"$ref": ref_id}
            elif "anyOf" in _schema:
                _anyOf = []
                for item in _schema["anyOf"]:
                    ref_id = self.decompose_schema(item, debug_key=debug_key)
                    if ref_id is not None:
                        _anyOf.append({"$ref": ref_id})
                    else:
                        _anyOf.append(item)

                _schema["anyOf"] = _anyOf

            else:
                return None

            self.schemas[_schema["$id"]] = {**self.schemas.get(_schema["$id"], {}), **_schema}

            return _schema["$id"]

        return None

    def decompose_defs(self, defs: dict):
        for k, v in defs.items():
            _schema = deepcopy(v)
            _schema["$schema"] = _JSON_SCHEMA_URL
            _schema["$id"] = self.schema_path(_schema["title"])
            self.schemas[_schema["$id"]] = {**self.schemas.get(_schema["$id"], {}), **_schema}

    def insert_refs(self):
        for schema_key, schema in self.schemas.items():
            if "patternProperties" in schema.keys():
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
                        if self.schema_path(ref) in self.schemas:
                            self.schemas[schema_key]["properties"][k]["$ref"] = self.schema_path(ref)
            elif "anyOf" in schema:
                for i, item in enumerate(schema["anyOf"]):
                    if item.get("$ref", "").startswith("#/$defs/"):
                        ref = v["$ref"].split("#/$defs/")[1]
                        if self.schema_path(ref) in self.schemas:
                            self.schemas[schema_key]["anyOf"][i]["$ref"] = self.schema_path(ref)
                    else:
                        key = item.get("title", "")
                        if key in self.schemas:
                            self.schemas[schema_key]["anyOf"][i] = {"$ref": f"./{key}.json"}
            elif "items" in schema:
                if "anyOf" in schema["items"]:
                    for i, item in enumerate(schema["items"]["anyOf"]):
                        if item.get("$ref", "").startswith("#/$defs/"):
                            ref = v["$ref"].split("#/$defs/")[1]
                            if self.schema_path(ref) in self.schemas:
                                self.schemas[schema_key]["items"]["anyOf"][i]["$ref"] = self.schema_path(ref)
                        else:
                            key = item.get("$id", "")
                            if key in self.schemas:
                                self.schemas[schema_key]["items"]["anyOf"][i] = {"$ref": key}
                else:
                    key = schema["items"].get("$id", "")
                    if key in self.schemas:
                        self.schemas[schema_key]["items"] = {"$ref": key}

    @staticmethod
    def get_cim_copyright_notice(uml_data: UMLData, cim_copyright_notice_object_id: int = 29601) -> str:
        return "\n".join(markdownify.markdownify(html.unescape(str(uml_data.objects.loc[cim_copyright_notice_object_id].Note).strip())).splitlines()).strip()

    def add_cim_copyright_notice_to_decomposed_schemas(self, uml_data: UMLData):
        copyright_notice = self.get_cim_copyright_notice(uml_data)
        for k in self.schemas.keys():
            self.schemas[k]["license"] = copyright_notice

    def export_schema(self, file_out: pathlib.Path | str):
        with open(file_out, "w") as f:
            json.dump(self.schema, f)

    def export_schemas(self, out_dir: pathlib.Path | str):
        for k, v in self.schemas.items():
            filename = k.split("/")[-1].replace(".json", "")
            with open(os.path.join(out_dir, f"{filename}.json"), "w") as f:
                json.dump(v, f, indent=2)


def generate_schema_docs(schema_dir: pathlib.Path | str, out_dir: pathlib.Path | str, template_name: str = "js") -> None:
    Gen.generate_from_filename(schema_dir, out_dir, config=Gen.GenerationConfiguration(template_name=template_name))


if __name__ == "__main__":
    schema = RavensSchema(base_id_uri=f"file://{os.getcwd()}/out/schema/separate")

    schema.export_schema("out/schema/test_schema.json")

    schema.export_schemas("out/schema/separate/")

    generate_schema_docs("out/schema/separate", "out/schema/docs")
