import os

from ravens.io import parse_eap_data, parse_eap_diagrams
from ravens.uml.d3 import save_uml_diagrams_from_package_name


def build_uml_docs():
    eap_file = "../../cim/iec61970cim17v40_iec61968cim13v13b_iec62325cim03v17b_CIM100.1.1.1_mgravens24v1.eap"
    core_data = parse_eap_data(eap_file)
    diagram_data = parse_eap_diagrams(eap_file)

    current_dir = os.path.dirname(os.path.abspath(__file__))
    static_uml_path = os.path.join(current_dir, "../_static/uml")

    md_str = "# UML Diagrams for MG-RAVENS Schema\n"
    for package_name in ["EconomicDesign", "SimplifiedDiagrams"]:

        paths = save_uml_diagrams_from_package_name(core_data, diagram_data, package_name, static_uml_path)
        md_str = (
            md_str
            + f"\n## {package_name}\n"
            + "\n".join(
                [
                    f'\n### {p.split("/")[-1].replace(".svg", "").replace(f"{package_name}.", "")}\n\n<img src="../_static{p.split("_static")[-1]}" style="max-width: 100%; height: auto;" alt="{p.split("/")[-1].replace(".svg", "").replace(f"{package_name}.", "")} diagram">\n'
                    for p in paths
                ]
            )
        )

    with open("uml/index.md", "w") as f:
        f.write(md_str)
