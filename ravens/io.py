import glob
import io
import json
import os

from copy import deepcopy
import xml.etree.ElementTree as ET

import json_schema_for_humans.generate as JSFHGenerate
import pandas_access as mdb
import pandas as pd


_index_columns = {
    "t_object": "Object_ID",
    "t_connector": "Connector_ID",
    "t_attribute": "ID",
    "t_package": "Package_ID",
    "t_diagram": "Diagram_ID",
    "t_diagramlinks": "Instance_ID",
    "t_diagramobjects": "Instance_ID",
}


_attr_names = {
    "t_object": "objects",
    "t_connector": "connectors",
    "t_attribute": "attributes",
    "t_package": "packages",
    "t_diagram": "diagrams",
    "t_diagramlinks": "diagramlinks",
    "t_diagramobjects": "diagramobjects",
}


class UMLData:
    def __init__(self, file: str, filetype: str = "auto", set_index: bool = True):
        if (filetype == "auto" and file.endswith("eap")) or filetype == "eap":
            self.parse_eap_file(file, set_index=set_index)
        elif (filetype == "auto" and file.endswith("xmi")) or filetype == "xmi":
            self.parse_xmi_file(file, set_index=set_index)
        else:
            if filetype == "auto":
                raise Exception(f"Unable to detect filetype of '{file}'")
            else:
                raise Exception(f"Filetype '{filetype}' is unsupported. Use 'auto', 'eap', or 'xmi'.")

    def parse_xmi_file(self, file: str, set_index: bool = True):
        tree = ET.parse(file)
        root = tree.getroot()

        tables_data = {}

        for table in root.findall("Table"):
            table_name = table.attrib.get("name")
            if table_name not in _attr_names:
                continue

            rows_data = []

            for row in table.findall("Row"):
                row_data = {}

                for column in row.findall("Column"):
                    col_name = column.attrib.get("name")
                    col_value = column.attrib.get("value")
                    row_data[col_name] = col_value

                rows_data.append(row_data)

            df = pd.DataFrame(rows_data)
            if set_index:
                df = df.set_index(_index_columns[table_name])

            setattr(self, _attr_names[table_name], df)

    def parse_eap_file(self, file: str, set_index: bool = True):
        for table_name, attr_name in _attr_names.items():
            df = mdb.read_table(file, table_name, converters_from_schema=False)

            if set_index:
                df = df.set_index(_index_columns[table_name])

            setattr(self, attr_name, df)


def parse_eap_data(file: str, set_index: bool = True) -> UMLData:
    "Loads connector, object, attribute, package, diagram, diagramlinks, diagramobjects data from EAP file"
    return UMLData(file, filetype="eap", set_index=set_index)


def parse_xmi_data(file: str, set_index: bool = True) -> UMLData:
    "Loads connector, object, attribute, package, diagram, diagramlinks, diagramobjects data from Native XMI file"
    return UMLData(file, filetype="xmi", set_index=set_index)


def parse_uml_data(file: str, filetype: str = "auto", set_index: bool = True) -> UMLData:
    "Loads connector, object, attribute, package, diagram, diagramlinks, diagramobjects data from UML file (XMI or EAP)"
    return UMLData(file, filetype=filetype, set_index=set_index)


def write_schemas(schemas: dict, models_path: str = "models", cleanup_model_dir: bool = False, flatten: bool = False):
    "Helper function to write schema to file(s)"
    if cleanup_model_dir:
        for file in glob.glob(os.path.join(models_path, "*.json"), recursive=True):
            os.remove(file)

    for schema_name, schema in schemas.items():
        if not flatten and "tags" in schema.keys():
            save_path = os.path.join(models_path, schema["tags"][-1])
        else:
            save_path = models_path

        if not os.path.exists(save_path):
            os.mkdir(save_path)

        with open(os.path.join(save_path, f"{schema_name}.json"), "w") as f:
            json.dump(schema, f, indent=2)


def write_schema_docs(schema: dict, out_file: str):
    "Helper function to generate Schema documentation using json_schema_for_humans"
    f = io.StringIO(json.dumps(schema))

    JSFHGenerate.generate_from_file_object(f, out_file)
