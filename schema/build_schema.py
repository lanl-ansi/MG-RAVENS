import glob
import json
import os

from ravens.schema import RavensSchema
from ravens.uml import UMLExclusions


def build_schema():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    schema_dir = os.path.join(current_dir, "../schema")

    a = RavensSchema(uml_exclusions=UMLExclusions().exclude_by_name_startswith(["Mkt"]))

    a.export_schemas(schema_dir)


if __name__ == "__main__":
    build_schema()
