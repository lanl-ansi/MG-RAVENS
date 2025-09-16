import json
import os
import pathlib
import subprocess
import pandas as pd

from ravens.data import _SVG_RENDERER_PATH
from ravens.uml.data import UMLData


ROLE_TO_HEX_NODE = {
    "rootClass":          "#DDA0DD",
    "compoundClass":      "#87CEEB",
    "inheritonlyClass":   "#6495ED",
    "substitutableClass": "#FFB6C1",
    "containerClass":     "#FFE4C4",
}
ROLE_TO_HEX_EDGE = {
    "referenceconnector": "#DB0B35",
    "embeddedconnector":  "#20C920",
}
DEFAULT_NODE_HEX = "#EAE505"
DEFAULT_EDGE_HEX = "#000000"

# Case-insensitive views
NODE_MAP_CI = {k.casefold(): v for k, v in ROLE_TO_HEX_NODE.items()}
EDGE_MAP_CI = {k.casefold(): v for k, v in ROLE_TO_HEX_EDGE.items()}


def object_role_lookup(uml_data, tag_name: str = "ravensRole") -> pd.Series:
    """
    Returns a Series indexed by Object_ID with the latest ravensRole value (string),
    reading uml_data.t_objectproperties.
    """
    df = getattr(uml_data, "t_objectproperties", pd.DataFrame())
    if df is None or df.empty:
        return pd.Series(dtype=object)

    t = df.loc[
        df["Property"].astype(str).str.casefold() == tag_name.casefold(),
        ["Object_ID", "Value"]
    ].copy()
    if t.empty:
        return pd.Series(dtype=object)

    t["Object_ID"] = pd.to_numeric(t["Object_ID"], errors="coerce").astype("Int64")
    t["Value"] = t["Value"].astype(str).str.strip()
    t = t.dropna(subset=["Object_ID"]).astype({"Object_ID": int})

    s = t.groupby("Object_ID")["Value"].last()
    s.index.name = "Object_ID"
    s.name = tag_name
    return s


def connector_role_lookup(uml_data, tag_name: str = "ravensRole") -> pd.Series:
    """
    Returns a Series indexed by Connector_ID with the latest ravensRole value (string),
    reading uml_data.t_connectortag (normalizes owner ID column).
    """
    df = getattr(uml_data, "t_connectortag", pd.DataFrame())
    if df is None or df.empty:
        return pd.Series(dtype=object)

    if "Connector_ID" in df.columns:
        id_col = "Connector_ID"
    elif "ElementID" in df.columns:
        id_col = "ElementID"
    else:
        id_col = "ConnectorID" if "ConnectorID" in df.columns else None
    if id_col is None:
        return pd.Series(dtype=object)

    val_col = "Value" if "Value" in df.columns else ("VALUE" if "VALUE" in df.columns else None)
    if val_col is None:
        return pd.Series(dtype=object)

    t = df.loc[
        df["Property"].astype(str).str.casefold() == tag_name.casefold(),
        [id_col, val_col]
    ].copy()
    if t.empty:
        return pd.Series(dtype=object)

    t[id_col] = pd.to_numeric(t[id_col], errors="coerce").astype("Int64")
    t[val_col] = t[val_col].astype(str).str.strip()
    t = t.dropna(subset=[id_col]).astype({id_col: int})

    s = t.groupby(id_col)[val_col].last()
    s.index.name = "Connector_ID"
    s.name = tag_name
    return s


class UMLDiagramData:
    def __init__(self):
        pass


class UMLVisualizer:
    def __init__(self, uml_data: UMLData | None = None):
        if uml_data is None:
            uml_data = UMLData()

        self.uml_data = uml_data

        self._current_diagram = None
        self._current_svg_data = None
        self._current_svg = None

    @staticmethod
    def _parse_link_style(link_style_string: str):
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

        except Exception:
            raise Exception(link_style_string)

        return link_style

    @staticmethod
    def _parse_object_style(object_style_string: str):
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
        except ValueError:
            print(object_style_string)

        return object_style

    def _create_svg_data(self, diagram_id: int):
        dobjects = self.uml_data.diagramobjects[self.uml_data.diagramobjects["Diagram_ID"] == diagram_id]
        if dobjects.empty:
            return {"cx": 0, "cy": 0, "nodes": [], "links": []}

        svg_data = {
            "cx": max([abs(o.RectRight) for o in dobjects.itertuples()]),
            "cy": max([abs(o.RectBottom) for o in dobjects.itertuples()]),
        }

        # --- precompute role lookups once per diagram render ---
        node_roles = object_role_lookup(self.uml_data)       # Object_ID -> role (str)
        edge_roles = connector_role_lookup(self.uml_data)    # Connector_ID -> role (str)

        boxes_data = []
        nodes = []
        objs_in_diagram = [
            _o.Object_ID
            for _o in self.uml_data.diagramobjects[self.uml_data.diagramobjects["Diagram_ID"] == diagram_id].itertuples()
        ]

        for o in self.uml_data.diagramobjects[self.uml_data.diagramobjects["Diagram_ID"] == diagram_id].itertuples():
            object_style = self._parse_object_style(str(o.ObjectStyle))
            obj = self.uml_data.objects.loc[o.Object_ID]

            text_lines = []
            if obj.Stereotype == "enumeration":
                text_lines.append({"text": f"<<{obj.Stereotype}>>", "align": "center"})
                text_lines.append({"text": f"{obj.Name}", "align": "center", "style": "bold"})
                text_lines.append({})
                text_lines.append({"text": "literals", "align": "center", "style": "italic"})
                for attr in self.uml_data.attributes[self.uml_data.attributes["Object_ID"] == o.Object_ID].itertuples():
                    text_lines.append({"text": f"{attr.Name}", "align": "left"})
            elif obj.Stereotype == "CIMDatatype":
                text_lines.append({"text": f"<<{obj.Stereotype}>>", "align": "center"})
                text_lines.append({"text": f"{obj.Name}", "align": "center", "style": "bold"})
                if object_style.get("AttPub", "1") == "1":
                    text_lines.append({})
                    for attr in self.uml_data.attributes[self.uml_data.attributes["Object_ID"] == o.Object_ID].itertuples():
                        text_lines.append({"text": f"+   {attr.Name}: {attr.Type}", "align": "left"})
            else:
                gen_obj_id = None
                for c in self.uml_data.connectors[
                    (self.uml_data.connectors["Start_Object_ID"] == o.Object_ID)
                    & (self.uml_data.connectors["Connector_Type"] == "Generalization")
                ].itertuples():
                    gen_obj_id = c.End_Object_ID
                    break

                if (gen_obj_id is not None) and (gen_obj_id not in objs_in_diagram):
                    text_lines.append({"text": f"{self.uml_data.objects.loc[gen_obj_id].Name}", "align": "right", "style": "italic"})

                text_lines.append({"text": f"{obj.Name}", "align": "center", "style": "bold"})
                if object_style.get("AttPub", "1") == "1":
                    text_lines.append({})
                    for attr in self.uml_data.attributes[self.uml_data.attributes["Object_ID"] == o.Object_ID].itertuples():
                        text_lines.append({"text": f"+   {attr.Name}: {attr.Type}", "align": "left"})

            # --- node color from ravensRole tag ---
            role_node = node_roles.get(o.Object_ID, None)
            if isinstance(role_node, float) and pd.isna(role_node):
                role_node = None
            node_hex = NODE_MAP_CI.get(str(role_node).strip().casefold(), DEFAULT_NODE_HEX) if role_node else DEFAULT_NODE_HEX

            box_data = {
                "id": o.Object_ID,
                "x": o.RectLeft,
                "y": -o.RectTop,
                "width": abs(o.RectRight - o.RectLeft),
                "height": abs(o.RectTop - o.RectBottom),
                "textLines": text_lines,
                "color": node_hex,
            }
            nodes.append(o.Object_ID)
            boxes_data.append(box_data)

        svg_data["nodes"] = boxes_data

        links_data = []
        for l in self.uml_data.diagramlinks[self.uml_data.diagramlinks["DiagramID"] == diagram_id].itertuples():
            if l.Hidden:
                continue

            link_style = self._parse_link_style(str(l.Geometry))

            connector = self.uml_data.connectors.loc[l.ConnectorID]
            if connector.Start_Object_ID not in nodes or connector.End_Object_ID not in nodes:
                continue

            # --- edge color from ravensRole tag ---
            role_edge = edge_roles.get(l.ConnectorID, None)
            if isinstance(role_edge, float) and pd.isna(role_edge):
                role_edge = None
            edge_hex = EDGE_MAP_CI.get(str(role_edge).strip().casefold(), DEFAULT_EDGE_HEX) if role_edge else DEFAULT_EDGE_HEX

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
                "color": edge_hex,
            }

            links_data.append(link_data)

        svg_data["links"] = links_data

        self._current_diagram = diagram_id
        self._current_svg_data = svg_data

    def _create_svg(self):
        data_json = json.dumps(self._current_svg_data)

        # Call the Node.js script
        result = subprocess.run(["node", _SVG_RENDERER_PATH, data_json], capture_output=True, text=True)

        if result.stderr:
            raise Exception(result.stderr)

        # Get the SVG output
        self._current_svg = result.stdout

    def _save_current_svg(self, filename: str):
        self._current_svg_data["outputPath"] = filename
        self._create_svg()

    def save_uml_diagram_from_package_and_diagram_name(self, package_name: str, diagram_name: str, svg_dir_path: pathlib.PosixPath) -> str:
        pkg_id = self.uml_data.packages[self.uml_data.packages["Name"] == package_name].iloc[0]._name
        diagram_id = self.uml_data.diagrams[(self.uml_data.diagrams["Package_ID"] == pkg_id) & (self.uml_data.diagrams["Name"] == diagram_name)].iloc[0]._name
        self._create_svg_data(diagram_id)

        path = os.path.join(svg_dir_path, f"{str(package_name)}.{str(diagram_name)}.svg")
        self._save_current_svg(path)

        return path

    def save_uml_diagrams_from_package_name(self, package_name: str, svg_dir_path: pathlib.PosixPath) -> list:
        paths = []
        pkg_id = self.uml_data.packages[self.uml_data.packages["Name"] == package_name].iloc[0]._name
        for diagram in self.uml_data.diagrams[self.uml_data.diagrams["Package_ID"] == pkg_id].itertuples():
            self._create_svg_data(diagram.Index)

            path = os.path.join(svg_dir_path, f"{str(package_name)}.{str(diagram.Name)}.svg")
            self._save_current_svg(path)

            paths.append(path)

        return paths

    def save_uml_diagrams_from_package_id(self, package_id: str, svg_dir_path: pathlib.PosixPath) -> list:
        paths = []
        package_name = str(self.uml_data.packages.loc[package_id].Name).strip()
        for diagram in self.uml_data.diagrams[self.uml_data.diagrams["Package_ID"] == package_id].itertuples():
            self._create_svg_data(diagram.Index)  # fixed: no extra uml_data arg

            path = os.path.join(svg_dir_path, f"{str(package_name)}.{str(diagram.Name)}.svg")
            self._save_current_svg(path)

            paths.append(path)

        return paths

    def save_all_uml_diagrams(self, svg_dir_path: pathlib.PosixPath) -> list:
        paths = []
        for diagram in self.uml_data.diagrams[self.uml_data.diagrams["Diagram_Type"] == "Logical"].itertuples():
            package_name = str(self.uml_data.packages.loc[diagram.Package_ID].Name).strip()
            try:
                self._create_svg_data(diagram.Index)  # fixed: no extra uml_data arg

                path = os.path.join(svg_dir_path, f"{str(package_name)}.{str(diagram.Name)}.svg")
                self._save_current_svg(path)

                paths.append(path)
            except Exception as msg:
                print(f"{str(package_name)}.{str(diagram.Name)} :: {str(diagram.Index)}")
                print(msg)
                continue

        return paths


if __name__ == "__main__":
    pathlib.Path("out/uml_d3").mkdir(parents=True, exist_ok=True)

    uml_vis = UMLVisualizer()

    uml_vis._create_svg_data(11103)
    uml_vis._save_current_svg("out/test.svg")

    uml_vis.save_uml_diagram_from_package_and_diagram_name("EconomicDesign", "ProposedAssetOptions", "out/uml_d3")
    uml_vis.save_uml_diagram_from_package_and_diagram_name("SimplifiedDiagrams", "Faults", "out/uml_d3")

    uml_vis.save_uml_diagrams_from_package_name("EconomicDesign", "out/uml_d3")
    uml_vis.save_uml_diagrams_from_package_name("SimplifiedDiagrams", "out/uml_d3")

    uml_vis.save_all_uml_diagrams("out/uml_d3")