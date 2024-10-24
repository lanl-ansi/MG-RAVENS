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

_expected_dtypes = {
    "t_package": {
        "Package_ID": int,
        "Name": str,
        "Parent_ID": int,
        "CreatedDate": "datetime",
        "ModifiedDate": "datetime",
        "Notes": str,
        "ea_guid": str,
        "IsControlled": bool,
        "LastLoadDate": "datetime",
        "LastSaveDate": "datetime",
        "Version": str,
        "Protected": bool,
        "UseDTD": bool,
        "LogXML": bool,
        "TPos": int,
        "BatchSave": int,
        "BatchLoad": int,
    },
    "t_object": {
        "Object_ID": int,
        "Object_Type": str,
        "Diagram_ID": int,
        "Name": str,
        "Author": str,
        "Version": str,
        "Package_ID": int,
        "NType": int,
        "Complexity": int,
        "Effort": int,
        "Backcolor": int,
        "BorderStyle": int,
        "BorderWidth": int,
        "Fontcolor": int,
        "Bordercolor": int,
        "CreatedDate": "datetime",
        "ModifiedDate": "datetime",
        "Status": str,
        "Abstract": int,
        "Tagged": int,
        "GenType": str,
        "Phase": str,
        "Scope": str,
        "Classifier": int,
        "ea_guid": str,
        "ParentID": int,
        "Classifier_guid": str,
        "IsRoot": bool,
        "IsLeaf": bool,
        "IsSpec": bool,
        "IsActive": bool,
    },
    "t_connector": {
        "Connector_ID": int,
        "Connector_Type": str,
        "SourceAccess": str,
        "DestAccess": str,
        "SourceIsAggregate": int,
        "SourceIsOrdered": int,
        "DestIsAggregate": int,
        "DestIsOrdered": int,
        "Start_Object_ID": int,
        "End_Object_ID": int,
        "Start_Edge": int,
        "End_Edge": int,
        "PtStartX": int,
        "PtStartY": int,
        "PtEndX": int,
        "PtEndY": int,
        "SeqNo": int,
        "HeadStyle": int,
        "LineStyle": int,
        "RouteStyle": int,
        "IsBold": int,
        "LineColor": int,
        "VirtualInheritance": int,
        "DiagramID": int,
        "ea_guid": str,
        "SourceIsNavigable": bool,
        "DestIsNavigable": bool,
        "IsRoot": bool,
        "IsLeaf": bool,
        "IsSpec": bool,
        "IsSignal": bool,
        "IsStimulus": bool,
        "Target2": int,
    },
    "t_attribute": {
        "Object_ID": int,
        "Name": str,
        "Scope": str,
        "Containment": str,
        "IsStatic": int,
        "IsCollection": int,
        "IsOrdered": int,
        "AllowDuplicates": int,
        "LowerBound": int,
        "UpperBound": int,
        "Notes": str,
        "Derived": int,
        "ID": int,
        "Pos": int,
        "Length": int,
        "Precision": int,
        "Scale": int,
        "Const": int,
        "Classifier": int,
        "Type": str,
        "ea_guid": str,
        "StyleEx": str,
    },
    "t_diagram": {
        "Diagram_ID": int,
        "Package_ID": int,
        "ParentID": int,
        "Diagram_Type": str,
        "Name": str,
        "Version": str,
        "Author": str,
        "ShowDetails": int,
        "Notes": str,
        "AttPub": bool,
        "AttPri": bool,
        "AttPro": bool,
        "Orientation": str,
        "cx": int,
        "cy": int,
        "Scale": float,
        "CreatedDate": "datetime",
        "ModifiedDate": "datetime",
        "ShowForeign": bool,
        "ShowBorder": bool,
        "ShowPackageContents": bool,
        "PDATA": str,
        "Locked": bool,
        "ea_guid": str,
        "TPos": int,
        "Swimlanes": str,
        "StyleEx": str,
    },
    "t_diagramobjects": {
        "Diagram_ID": int,
        "Object_ID": int,
        "RectTop": int,
        "RectLeft": int,
        "RectRight": int,
        "RectBottom": int,
        "Sequence": int,
        "ObjectStyle": str,
        "Instance_ID": int,
    },
    "t_diagramlinks": {
        "DiagramID": int,
        "ConnectorID": int,
        "Geometry": str,
        "Style": str,
        "Hidden": bool,
        "Instance_ID": int,
    },
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

            if table_name in _expected_dtypes:
                for col, dtype in _expected_dtypes[table_name].items():
                    if dtype == "datetime":
                        df[col] = pd.to_datetime(df[col], errors="coerce")
                    elif dtype == bool:
                        df[col] = df[col].map({"TRUE": True, "FALSE": False, "true": True, "false": False})
                    elif dtype == int or dtype == float:
                        df[col] = pd.to_numeric(df[col], errors="coerce")
                    else:
                        df[col] = df[col].astype(dtype)

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


if __name__ == "__main__":
    xmi_file = "cim/iec61970cim17v40_iec61968cim13v13b_iec62325cim03v17b_CIM100.1.1.1_mgravens24v1.xmi"

    uml_data = parse_uml_data(xmi_file)
