import pathlib

import pandas as pd
import xml.etree.ElementTree as ET

from ravens.data import _UML_XML_PATH

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
    def __init__(self):
        self.objects: pd.DataFrame = pd.DataFrame()
        self.connectors: pd.DataFrame = pd.DataFrame()
        self.attributes: pd.DataFrame = pd.DataFrame()
        self.packages: pd.DataFrame = pd.DataFrame()
        self.diagrams: pd.DataFrame = pd.DataFrame()
        self.diagramlinks: pd.DataFrame = pd.DataFrame()
        self.diagramobjects: pd.DataFrame = pd.DataFrame()

        dataframes: dict = self._create_dataframes()
        for table_name, df in dataframes.items():
            setattr(self, _attr_names[table_name], df)

    @classmethod
    def loadf(cls, file: pathlib.PosixPath = _UML_XML_PATH, set_index: bool = True) -> object:
        dataframes: dict = cls._create_dataframes(file, set_index=set_index)
        obj = cls()
        for table_name, df in dataframes.items():
            setattr(obj, _attr_names[table_name], df)

        return obj

    @staticmethod
    def _create_dataframes(file: pathlib.PosixPath = _UML_XML_PATH, set_index: bool = True) -> dict:
        tree = ET.parse(file)
        root = tree.getroot()

        dataframes = {}

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

            dataframes[table_name] = df

        return dataframes


if __name__ == "__main__":
    uml = UMLData()

    uml2 = UMLData.loadf(_UML_XML_PATH)
