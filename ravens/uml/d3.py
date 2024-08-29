import json
import os
import subprocess

import pandas as pd

from ravens.io import parse_uml_data

ea_rgb_dec2hex = {z * 65536 + y * 256 + x: "#{:02x}{:02x}{:02x}".format(x, y, z) for x in range(256) for y in range(256) for z in range(256)}


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


def create_svg_data(uml_data, diagram_id: int):
    dobjects = uml_data.diagramobjects[uml_data.diagramobjects["Diagram_ID"] == diagram_id]
    if dobjects.empty:
        return {"cx": 0, "cy": 0, "nodes": [], "links": []}

    svg_data = {
        "cx": max([abs(o.RectRight) for o in dobjects.itertuples()]),
        "cy": max([abs(o.RectBottom) for o in dobjects.itertuples()]),
    }

    boxes_data = []
    nodes = []
    objs_in_diagram = [_o.Object_ID for _o in uml_data.diagramobjects[uml_data.diagramobjects["Diagram_ID"] == diagram_id].itertuples()]

    for o in uml_data.diagramobjects[uml_data.diagramobjects["Diagram_ID"] == diagram_id].itertuples():
        object_style = parse_object_style(str(o.ObjectStyle))
        obj = uml_data.objects.loc[o.Object_ID]

        text_lines = []
        if obj.Stereotype == "enumeration":
            text_lines.append({"text": f"<<{obj.Stereotype}>>", "align": "center"})
            text_lines.append({"text": f"{obj.Name}", "align": "center", "style": "bold"})
            text_lines.append({})
            text_lines.append({"text": "literals", "align": "center", "style": "italic"})
            for attr in uml_data.attributes[uml_data.attributes["Object_ID"] == o.Object_ID].itertuples():
                text_lines.append({"text": f"{attr.Name}", "align": "left"})
        elif obj.Stereotype == "CIMDatatype":
            text_lines.append({"text": f"<<{obj.Stereotype}>>", "align": "center"})
            text_lines.append({"text": f"{obj.Name}", "align": "center", "style": "bold"})
            if object_style.get("AttPub", "1") == "1":
                text_lines.append({})
                for attr in uml_data.attributes[uml_data.attributes["Object_ID"] == o.Object_ID].itertuples():
                    text_lines.append({"text": f"+   {attr.Name}: {attr.Type}", "align": "left"})
        else:
            gen_obj_id = None
            for c in uml_data.connectors[(uml_data.connectors["Start_Object_ID"] == o.Object_ID) & (uml_data.connectors["Connector_Type"] == "Generalization")].itertuples():
                gen_obj_id = c.End_Object_ID
                break

            if (gen_obj_id is not None) and (gen_obj_id not in objs_in_diagram):
                text_lines.append({"text": f"{uml_data.objects.loc[gen_obj_id].Name}", "align": "right", "style": "italic"})

            text_lines.append({"text": f"{obj.Name}", "align": "center", "style": "bold"})
            if object_style.get("AttPub", "1") == "1":
                text_lines.append({})
                for attr in uml_data.attributes[uml_data.attributes["Object_ID"] == o.Object_ID].itertuples():
                    text_lines.append({"text": f"+   {attr.Name}: {attr.Type}", "align": "left"})

        box_color = int(object_style.get("BCol", "-1"))
        if box_color == -1:
            if obj.Stereotype == "enumeration":
                box_color = 14941672
            else:
                box_color = 16251645  # default color of Classes

        box_data = {
            "id": o.Object_ID,
            "x": o.RectLeft,
            "y": -o.RectTop,
            "width": abs(o.RectRight - o.RectLeft),
            "height": abs(o.RectTop - o.RectBottom),
            "textLines": text_lines,
            "color": ea_rgb_dec2hex[box_color],
        }
        nodes.append(o.Object_ID)

        boxes_data.append(box_data)

    svg_data["nodes"] = boxes_data

    links_data = []
    for l in uml_data.diagramlinks[uml_data.diagramlinks["DiagramID"] == diagram_id].itertuples():
        if l.Hidden:
            continue

        link_style = parse_link_style(str(l.Geometry))

        connector = uml_data.connectors.loc[l.ConnectorID]
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
            "color": ea_rgb_dec2hex[line_color],
        }

        links_data.append(link_data)

    svg_data["links"] = links_data

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


def save_uml_diagram_from_package_and_diagram_name(uml_data, package_name, diagram_name, svg_dir_path):
    pkg_id = uml_data.packages[uml_data.packages["Name"] == package_name].iloc[0]._name
    diagram_id = uml_data.diagrams[(uml_data.diagrams["Package_ID"] == pkg_id) & (uml_data.diagrams["Name"] == diagram_name)].iloc[0]._name
    svg_data = create_svg_data(uml_data, diagram_id)
    path = os.path.join(svg_dir_path, f"{str(package_name)}.{str(diagram_name)}.svg")
    save_svg(svg_data, path)

    return path


def save_uml_diagrams_from_package_name(uml_data, package_name, svg_dir_path):
    paths = []
    pkg_id = uml_data.packages[uml_data.packages["Name"] == package_name].iloc[0]._name
    for diagram in uml_data.diagrams[uml_data.diagrams["Package_ID"] == pkg_id].itertuples():
        svg_data = create_svg_data(uml_data, diagram.Index)
        path = os.path.join(svg_dir_path, f"{str(package_name)}.{str(diagram.Name)}.svg")
        save_svg(svg_data, path)
        paths.append(path)

    return paths


def save_uml_diagrams_from_package_id(uml_data, package_id, svg_dir_path):
    paths = []
    package_name = str(uml_data.packages.loc[package_id].Name).strip()
    for diagram in uml_data.diagrams[uml_data.diagrams["Package_ID"] == package_id].itertuples():
        svg_data = create_svg_data(uml_data, diagram.Index)
        path = os.path.join(svg_dir_path, f"{str(package_name)}.{str(diagram.Name)}.svg")
        save_svg(svg_data, path)
        paths.append(path)

    return paths


def save_all_uml_diagrams(uml_data, svg_dir_path):
    paths = []
    for diagram in uml_data.diagrams[uml_data.diagrams["Diagram_Type"] == "Logical"].itertuples():
        package_name = str(uml_data.packages.loc[diagram.Package_ID].Name).strip()
        try:
            svg_data = create_svg_data(uml_data, diagram.Index)
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

    db_filename = "cim/iec61970cim17v40_iec61968cim13v13b_iec62325cim03v17b_CIM100.1.1.1_mgravens24v1.xmi"

    uml_data = parse_uml_data(db_filename, set_index=True)

    svg_data = create_svg_data(uml_data, 11103)

    create_svg(svg_data)

    save_svg(svg_data, "test.svg")

    save_uml_diagram_from_package_and_diagram_name(uml_data, "EconomicDesign", "ProposedAssetOptions", "out/uml_d3")
    save_uml_diagram_from_package_and_diagram_name(uml_data, "SimplifiedDiagrams", "Faults", "out/uml_d3")

    save_uml_diagrams_from_package_name(uml_data, "EconomicDesign", "docs/source/_static/uml")
    save_uml_diagrams_from_package_name(uml_data, "SimplifiedDiagrams", "docs/source/_static/uml")

    save_all_uml_diagrams(uml_data, "docs/source/_static/uml")
