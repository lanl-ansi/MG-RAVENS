import glob
import json
import os
import pathlib

from ravens.schema import RavensSchema, generate_schema_docs
from ravens.uml import UMLExclusions


def modify_schema_docs_resource_paths(static_schema_dir: pathlib.PosixPath):
    for file in glob.glob(os.path.join(static_schema_dir, "*.html")):
        with open(file, "r") as f:
            f_str = f.read()

        f_str = f_str.replace("schema_doc.min.js", "../../_static/schema/schema_doc.min.js")
        f_str = f_str.replace("schema_doc.css", "../../_static/schema/schema_doc.css")

        with open(file, "w") as f:
            f.write(f_str)


def build_markdown_file(schema_md_dir: pathlib.PosixPath, static_schema_dir: pathlib.PosixPath):
    md_file = """# Schema Documentation

## Root Schema

[Root Schema](../_static/schema/Root.html){.external}

## Individual Schema

"""

    for file in sorted(glob.glob("*.html", root_dir=static_schema_dir)):
        if file != "Root.html":
            md_file = md_file + f"[{file.split(".html")[0]}](../_static/schema/{file})" + "{.external}" + "\n\n"

    with open(os.path.join(schema_md_dir, "index.md"), "w") as f:
        f.write(md_file)


def build_schema_docs():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    tmp_dir = os.path.join(current_dir, "../tmp")
    static_schema_dir = os.path.join(current_dir, "../_static/schema")
    schema_md_dir = os.path.join(current_dir, "../schema")

    a = RavensSchema(uml_exclusions=UMLExclusions().exclude_by_name_startswith(["Mkt"]))

    a.export_schemas(tmp_dir)

    generate_schema_docs(tmp_dir, static_schema_dir)

    modify_schema_docs_resource_paths(static_schema_dir)

    build_markdown_file(schema_md_dir, static_schema_dir)
