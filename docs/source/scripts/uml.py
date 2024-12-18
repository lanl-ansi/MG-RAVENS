import os

from ravens.uml import UMLVisualizer


def build_uml_docs():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    static_uml_path = os.path.join(current_dir, "../_static/uml")
    uml_vis = UMLVisualizer()

    md_str = "# UML Diagrams for MG-RAVENS Schema\n"
    for package_name in ["EconomicDesign", "SimplifiedDiagrams", "EquipmentExtensions", "Software"]:

        paths = uml_vis.save_uml_diagrams_from_package_name(package_name, static_uml_path)
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
