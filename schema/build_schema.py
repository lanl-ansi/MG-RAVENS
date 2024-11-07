import glob
import json
import os

import json_schema_for_humans.generate as Gen

from ravens.io import parse_uml_data
from ravens.cim_tools.common import build_package_exclusions, build_object_exclusions
from ravens.cim_tools.graph import build_generalization_graph, build_attribute_graph
from ravens.cim_tools.template import CIMTemplate
from ravens.schema.build_definitions import build_definitions
from ravens.schema.build_map import add_attributes_to_template
from ravens.schema.build_schema import build_schema_from_map
from ravens.schema.add_copyright_notice import add_cim_copyright_notice_to_decomposed_schemas
from ravens.schema.decompose_schema import Schemas


def build_schema():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    template_path = os.path.join(current_dir, "../ravens/cim_tools/cim_conversion_template.json")
    xmi_path = os.path.join(current_dir, "../cim/iec61970cim17v40_iec61968cim13v13b_iec62325cim03v17b_CIM100.1.1.1_mgravens24v1.xmi")
    schema_dir = os.path.join(current_dir, "../schema")

    uml_data = parse_uml_data(xmi_path)

    exclude_packages = build_package_exclusions(uml_data.packages, lambda x: any(str(x.Name).startswith(k) for k in ["Inf", "Mkt"]))
    exclude_objects = build_object_exclusions(
        uml_data.objects,
        lambda x: any(str(x.Name).startswith(k) for k in ["Inf", "Mkt"]),
        exclude_packages=exclude_packages,
    )

    schema = build_schema_from_map(
        add_attributes_to_template(
            CIMTemplate(template_path).template,
            CIMTemplate(template_path).template,
            uml_data,
            build_generalization_graph(uml_data, exclude_packages, exclude_objects),
            build_attribute_graph(uml_data, exclude_packages, exclude_objects),
        )
    )

    schema["$defs"] = build_definitions(uml_data)

    a = Schemas(schema)

    add_cim_copyright_notice_to_decomposed_schemas(a.schemas, uml_data)

    for k, v in a.schemas.items():
        filename = k.split("/")[-1].replace(".json", "")
        with open(os.path.join(schema_dir, f"{filename}.json"), "w") as f:
            json.dump(v, f, indent=2)


if __name__ == "__main__":
    build_schema()
