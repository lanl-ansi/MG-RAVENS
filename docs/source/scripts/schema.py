import glob
import json
import os

import json_schema_for_humans.generate as Gen

from ravens.io import parse_eap_data
from ravens.cim_tools.common import build_package_exclusions, build_object_exclusions
from ravens.cim_tools.graph import build_generalization_graph, build_attribute_graph
from ravens.cim_tools.template import CIMTemplate
from ravens.schema.build_definitions import build_definitions
from ravens.schema.build_map import add_attributes_to_template
from ravens.schema.build_schema import build_schema_from_map
from ravens.schema.add_copyright_notice import add_cim_copyright_notice_to_decomposed_schemas
from ravens.schema.decompose_schema import Schemas


def build_schema_docs():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    template_path = os.path.join(current_dir, "../../../ravens/cim_tools/cim_conversion_template.json")
    eap_path = os.path.join(current_dir, "../../../cim/iec61970cim17v40_iec61968cim13v13b_iec62325cim03v17b_CIM100.1.1.1_mgravens24v1.eap")
    tmp_dir = os.path.join(current_dir, "../tmp")
    static_schema_dir = os.path.join(current_dir, "../_static/schema")
    schema_md_dir = os.path.join(current_dir, "../schema")

    core_data = parse_eap_data(eap_path)

    exclude_packages = build_package_exclusions(core_data.packages, lambda x: any(str(x.Name).startswith(k) for k in ["Inf", "Mkt"]))
    exclude_objects = build_object_exclusions(
        core_data.objects,
        lambda x: any(str(x.Name).startswith(k) for k in ["Inf", "Mkt"]),
        exclude_packages=exclude_packages,
    )

    schema = build_schema_from_map(
        add_attributes_to_template(
            CIMTemplate(template_path).template,
            CIMTemplate(template_path).template,
            core_data,
            build_generalization_graph(core_data, exclude_packages, exclude_objects),
            build_attribute_graph(core_data, exclude_packages, exclude_objects),
        )
    )

    schema["$defs"] = build_definitions(core_data)

    a = Schemas(schema)

    add_cim_copyright_notice_to_decomposed_schemas(a.schemas, core_data)

    for k, v in a.schemas.items():
        with open(os.path.join(tmp_dir, f"{k}.json"), "w") as f:
            json.dump(v, f, indent=2)

    config = Gen.GenerationConfiguration(template_name="js")
    Gen.generate_from_filename(tmp_dir, static_schema_dir, config=config)

    for file in glob.glob(os.path.join(static_schema_dir, "*.html")):
        with open(file, "r") as f:
            f_str = f.read()

        f_str = f_str.replace("schema_doc.min.js", "../../_static/schema/schema_doc.min.js")
        f_str = f_str.replace("schema_doc.css", "../../_static/schema/schema_doc.css")

        with open(file, "w") as f:
            f.write(f_str)

    md_file = """# Schema Documentation

## Main Schema

[Main Schema](../_static/schema/__main__.html)

## Individual Schema

"""

    for file in sorted(glob.glob("*.html", root_dir=static_schema_dir)):
        if file != "__main__.html":
            md_file = md_file + f"[{file.split(".html")[0]}](../_static/schema/{file})\n\n"

    with open(os.path.join(schema_md_dir, "index.md"), "w") as f:
        f.write(md_file)
