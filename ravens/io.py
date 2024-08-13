import glob
import io
import json
import os

from copy import deepcopy

import json_schema_for_humans.generate as JSFHGenerate
import pandas_access as mdb


class CoreData:
    def __init__(self, file, set_index: bool = True):
        self.connectors = mdb.read_table(file, "t_connector", converters_from_schema=False)
        self.objects = mdb.read_table(file, "t_object", converters_from_schema=False)
        self.attributes = mdb.read_table(file, "t_attribute", converters_from_schema=False)
        self.packages = mdb.read_table(file, "t_package", converters_from_schema=False)

        if set_index:
            self.connectors = self.connectors.set_index("Connector_ID")
            self.objects = self.objects.set_index("Object_ID")
            self.attributes = self.attributes.set_index("ID")
            self.packages = self.packages.set_index("Package_ID")


def parse_eap_data(file: str, set_index: bool = True) -> CoreData:
    "Loads connector, object, attribute, and package data from EAP file"
    return CoreData(file, set_index)


class DiagramData:
    def __init__(self, file, set_index: bool = True):
        self.diagrams = mdb.read_table(file, "t_diagram", converters_from_schema=False)
        self.links = mdb.read_table(file, "t_diagramlinks", converters_from_schema=False)
        self.objects = mdb.read_table(file, "t_diagramobjects", converters_from_schema=False)

        if set_index:
            self.diagrams = self.diagrams.set_index("Diagram_ID")
            self.links = self.links.set_index("Instance_ID")
            self.objects = self.objects.set_index("Instance_ID")


def parse_eap_diagrams(file: str, set_index: bool = True) -> DiagramData:
    "Loads diagram data from eap file"
    return DiagramData(file, set_index)


def write_schemas(schemas: dict, models_path: str = "models", cleanup_model_dir: bool = False, flatten: bool = False):
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
    f = io.StringIO(json.dumps(schema))

    JSFHGenerate.generate_from_file_object(f, out_file)
