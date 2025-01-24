import importlib


_CIM_PRIMATIVES = {
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
    # json type passthrough
    "integer": "integer",
    "number": "number",
    "string": "string",
    "boolean": "boolean",
    "null": "null",
    "object": "object",
    "array": "array",
}


_CIM_RGB_TO_HEX = {z * 65536 + y * 256 + x: "#{:02x}{:02x}{:02x}".format(x, y, z) for x in range(256) for y in range(256) for z in range(256)}

_DEFAULT_CIM_NAMESPACE = "http://iec.ch/TC57/CIM100"

_RAVENS_SCHEMA_BASE_URL = "https://raw.githubusercontent.com/lanl-ansi/MG-RAVENS/refs/heads/schema/schema"
_JSON_SCHEMA_URL = "https://json-schema.org/draft/2020-12/schema"

_LIB_FILES_PATH = importlib.resources.files("ravens.lib")

_TEMPLATE_JSON_PATH = _LIB_FILES_PATH.joinpath("template.json")

_UML_XML_PATH = _LIB_FILES_PATH.joinpath("iec61970cim17v40_iec61968cim13v13b_iec62325cim03v17b_CIM100.1.1.1_mgravens24v1.xml")

_SVG_RENDERER_PATH = _LIB_FILES_PATH.joinpath("svgRenderer.js")
