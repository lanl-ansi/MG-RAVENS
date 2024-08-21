import
import os
import subprocess

import pandas as pd

from ravens.io import parse_eap_data, parse_eap_diagrams

ea_rgb_jsondec2hex = {z * 65536 + y * 256 + x: "{:02x}{:02x}{:02x}".format(x, y, z) for x in range(256) for y in range(256) for z in range(256)}


def parse_link_style(link_style_string: str):
    link_style = {}
    try:
        if "$" in link_style_string:
            pre, post = link_style_string.split("$")
            if pre:
                for item in pre.split(";"):
                    if "," in item:
                        link_style["link_geometry"] = [i for i in item.split(",") if i]
                    elif item:
                        key, value = item.split("=", 1)
                        link_style[key] = value

            if post:
                for item in post.split(";"):
                    if item:
                        outer_key, values = item.split("=", 1)
                        link_style[outer_key] = {}
                        if values:
                            for i in values.split(":"):
                                key, value = i.split("=")
                                link_style[outer_key][key] = int(value)
        else:
            for item in link_style_string.split(";"):
                if "," in item:
                    link_style["link_geometry"] = [i for i in item.split(",") if i]
                elif item:
                    key, value = item.split("=", 1)
                    link_style[key] = value

    except Exception as msg:
        raise Exception(link_style_string)

    return link_style


def parse_object_style(object_style_string: str):
    object_style = {}
    try:
        for item in object_style_string.split(";"):
            if item:
                if item.count("=") == 1:
                    key, value = item.split("=")
                    object_style[key] = value
                elif item.count("=") == 2:
                    key_outer, key_inner, value = item.split("=")
                    object_style[key_outer] = {key_inner: value}
                else:
                    raise ValueError
    except ValueError as msg:
        print(object_style_string)

    return object_style


def create_svg_data(core_data, diagram_data, diagram_id: int):
    dobjects = diagram_data.objects[diagram_data.objects["Diagram_ID"] == diagram_id]
    if dobjects.empty:
        return {"cx": 0, "cy": 0, "nodes": [], "links": []}

    svg_data = {
        "cx": max([abs(o.RectRight) for o in dobjects.itertuples()]),
        "cy": max([abs(o.RectBottom) for o in dobjects.itertuples()]),
    }

    boxes_data = []
    nodes = []
    for o in diagram_data.objects[diagram_data.objects["Diagram_ID"] == diagram_id].itertuples():
        object_style = parse_object_style(str(o.ObjectStyle))

        text_lines = [
            {
                "text": f'{str(core_data.packages.loc[core_data.objects.loc[o.Object_ID].Package_ID].Name) + "::" + str(core_data.objects.loc[o.Object_ID].Name)}',
                "align": "middle",
                "type": "title",
            }
        ] + [
            {"align": "start", "text": "+  " + str(attr.Name) + ": " + str(attr.Type) + " [" + str(attr.LowerBound) + ".." + str(attr.UpperBound) + "]"}
            for attr in core_data.attributes[core_data.attributes["Object_ID"] == o.Object_ID].itertuples()
            if object_style.get("AttPub", "1") == "1"
        ]

        box_color = int(object_style.get("BCol", "16251645"))
        if box_color == -1:
            box_color = 16251645  # default color of objects

        box_data = {
            "id": o.Object_ID,
            "x": o.RectLeft,
            "y": -o.RectTop,
            "width": abs(o.RectRight - o.RectLeft),
            "height": abs(o.RectTop - o.RectBottom),
            "textLines": text_lines,
            "color": f"#{ea_rgb_dec2hex[box_color]}",
        }
        nodes.append(o.Object_ID)

        boxes_data.append(box_data)

    svg_data["nodes"] = boxes_data

    links_data = []
    for l in diagram_data.links[diagram_data.links["DiagramID"] == diagram_id].itertuples():
        if l.Hidden:
            continue

        link_style = parse_link_style(str(l.Geometry))

        connector = core_data.connectors.loc[l.ConnectorID]
        if connector.Start_Object_ID not in nodes or connector.End_Object_ID not in nodes:
            continue

        line_color = int(connector.LineColor)
        if line_color == -1:
            line_color = 9204585  # default line color different than default object color

        link_data = {
            "source": str(connector.Start_Object_ID),
            "target": str(connector.End_Object_ID),
            "type": str(connector.Connector_Type).lower(),
            "textStartTop": f"+{connector.SourceRole}" if not pd.isnull(connector.SourceRole) else "",
            "textStartTopHidden": link_style.get("LLT", {}).get("HDN", 0),
            "textStartTopXPos": link_style.get("LLT", {}).get("CX", 0.0),
            "textStartTopYPos": link_style.get("LLT", {}).get("CY", 0.0),
            "textEndTop": f"+{connector.DestRole}" if not pd.isnull(connector.DestRole) else "",
            "textEndTopHidden": link_style.get("LRT", {}).get("HDN", 0),
            "textEndTopXPos": link_style.get("LRT", {}).get("CX", 0.0),
            "textEndTopYPos": link_style.get("LRT", {}).get("CY", 0.0),
            "textStartBtm": f"{connector.SourceCard}" if not pd.isnull(connector.SourceCard) else "",
            "textStartBtmHidden": link_style.get("LLB", {}).get("HDN", 0),
            "textStartBtmXPos": link_style.get("LLB", {}).get("CX", 0.0),
            "textStartBtmYPos": link_style.get("LLB", {}).get("CY", 0.0),
            "textEndBtm": f"{connector.DestCard}" if not pd.isnull(connector.DestCard) else "",
            "textEndBtmHidden": link_style.get("LRB", {}).get("HDN", 0),
            "textEndBtmXPos": link_style.get("LRB", {}).get("CX", 0.0),
            "textEndBtmYPos": link_style.get("LRB", {}).get("CY", 0.0),
            "color": f"#{ea_rgb_dec2hex[line_color]}",
        }

        links_data.append(link_data)

    svg_data["links"] = links_data

    # print(links_data)
    return svg_data


def create_svg(uml_data):
    data_json = json.dumps(uml_data)

    current_dir = os.path.dirname(os.path.abspath(__file__))
    js_file_path = os.path.join(current_dir, "js/svgRenderer.js")

    # Call the Node.js script
    result = subprocess.run(["node", js_file_path, data_json], capture_output=True, text=True)

    if result.stderr:
        raise Exception(result.stderr)

    # Get the SVG output
    svg_output = result.stdout
    return svg_output


def save_svg(uml_data, filename):
    uml_data["outputPath"] = filename
    svg_content = create_svg(uml_data)


def save_uml_diagram_from_package_and_diagram_name(core_data, diagram_data, package_name, diagram_name, svg_dir_path):
    pkg_id = core_data.packages[core_data.packages["Name"] == package_name].iloc[0]._name
    diagram_id = diagram_data.diagrams[(diagram_data.diagrams["Package_ID"] == pkg_id) & (diagram_data.diagrams["Name"] == diagram_name)].iloc[0]._name
    svg_data = create_svg_data(core_data, diagram_data, diagram_id)
    path = os.path.join(svg_dir_path, f"{str(package_name)}.{str(diagram_name)}.svg")
    save_svg(svg_data, path)

    return path


def save_uml_diagrams_from_package_name(core_data, diagram_data, package_name, svg_dir_path):
    paths = []
    pkg_id = core_data.packages[core_data.packages["Name"] == package_name].iloc[0]._name
    for diagram in diagram_data.diagrams[diagram_data.diagrams["Package_ID"] == pkg_id].itertuples():
        svg_data = create_svg_data(core_data, diagram_data, diagram.Index)
        path = os.path.join(svg_dir_path, f"{str(package_name)}.{str(diagram.Name)}.svg")
        save_svg(svg_data, path)
        paths.append(path)

    return paths


def save_uml_diagrams_from_package_id(core_data, diagram_data, package_id, svg_dir_path):
    paths = []
    package_name = str(core_data.packages.loc[package_id].Name).strip()
    for diagram in diagram_data.diagrams[diagram_data.diagrams["Package_ID"] == package_id].itertuples():
        svg_data = create_svg_data(core_data, diagram_data, diagram.Index)
        path = os.path.join(svg_dir_path, f"{str(package_name)}.{str(diagram.Name)}.svg")
        save_svg(svg_data, path)
        paths.append(path)

    return paths


def save_all_uml_diagrams(core_data, diagram_data, svg_dir_path):
    paths = []
    for diagram in diagram_data.diagrams[diagram_data.diagrams["Diagram_Type"] == "Logical"].itertuples():
        package_name = str(core_data.packages.loc[diagram.Package_ID].Name).strip()
        try:
            svg_data = create_svg_data(core_data, diagram_data, diagram.Index)
            path = os.path.join(svg_dir_path, f"{str(package_name)}.{str(diagram.Name)}.svg")
            save_svg(svg_data, path)
            paths.append(path)
        except Exception as msg:
            print(f"{str(package_name)}.{str(diagram.Name)} :: {str(diagram.Index)}")
            print(msg)
            continue

    return paths


if __name__ == "__main__":
    __file__ = os.path.join(os.getcwd(), "ravens/uml/d3.py")

    db_filename = "cim/iec61970cim17v40_iec61968cim13v13b_iec62325cim03v17b_CIM100.1.1.1_mgravens24v1.eap"

    core_data = parse_eap_data(db_filename, set_index=True)
    diagram_data = parse_eap_diagrams(db_filename, set_index=True)

    svg_data = create_svg_data(core_data, diagram_data, 11103)

    create_svg(svg_data)

    save_svg(svg_data, "test.svg")

    save_uml_diagram_from_package_and_diagram_name(core_data, diagram_data, "SimplifiedDiagrams", "Faults", "out/uml_d3")

    save_uml_diagrams_from_package_name(core_data, diagram_data, "EconomicDesign", "docs/source/_static/uml")
    save_uml_diagrams_from_package_name(core_data, diagram_data, "SimplifiedDiagrams", "docs/source/_static/uml")

    save_all_uml_diagrams(core_data, diagram_data, "docs/source/_static/uml")
