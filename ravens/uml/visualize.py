import json
import os
import pathlib
import subprocess
import pandas as pd
import tempfile
import importlib

from ravens.uml.data import UMLData


ROLE_TO_HEX_NODE = {
    "rootClass": "#DDA0DD",
    "embeddedClass": "#7EF97E",
    "inheritOnlyClass": "#6495ED",
    "embeddedInheritOnlyClass": "#FFF200",
    "substitutableClass": "#FFB6C1",
    "containerClass": "#FFE4C4",
}
STEREO_TO_HEX_NODE = {
    "compound": "#F6EADE",
    "enumeration": "#D1FAC7",
}

ROLE_TO_HEX_EDGE = {
    "referenceconnector": "#DB0B35",
    "embeddedconnector": "#20C920",
}
DEFAULT_NODE_HEX = "#FFFFFF"
DEFAULT_EDGE_HEX = "#000000"

# Case-insensitive views
NODE_MAP_CI = {k.casefold(): v for k, v in ROLE_TO_HEX_NODE.items()}
EDGE_MAP_CI = {k.casefold(): v for k, v in ROLE_TO_HEX_EDGE.items()}
STEREO_MAP_CI = {k.casefold(): v for k, v in STEREO_TO_HEX_NODE.items()}


def _get_table(uml_data, candidates):
    for name in candidates:
        df = getattr(uml_data, name, None)
        if isinstance(df, pd.DataFrame) and not df.empty:
            return df
    return pd.DataFrame()


def object_role_lookup(uml_data, tag_name: str = "ravensRole") -> pd.Series:
    """
    Object_ID -> role (string), from element tagged values.
    Uses: objectproperties / t_objectproperties; Property|Name; Value|VALUE; Object_ID|ObjectID
    """
    df = _get_table(uml_data, ("t_objectproperties", "objectproperties"))
    if df.empty:
        return pd.Series(dtype=object)

    # columns we accept
    id_col = "Object_ID" if "Object_ID" in df.columns else ("ObjectID" if "ObjectID" in df.columns else None)
    propcol = "Property" if "Property" in df.columns else ("Name" if "Name" in df.columns else None)
    valcol = "Value" if "Value" in df.columns else ("VALUE" if "VALUE" in df.columns else None)
    if not all([id_col, propcol, valcol]):
        return pd.Series(dtype=object)

    t = df.loc[df[propcol].astype(str).str.casefold() == tag_name.casefold(), [id_col, valcol]].copy()
    if t.empty:
        return pd.Series(dtype=object)

    t[id_col] = pd.to_numeric(t[id_col], errors="coerce")
    t = t.dropna(subset=[id_col]).astype({id_col: int})
    t[valcol] = t[valcol].astype(str).str.strip()

    s = t.groupby(id_col, sort=False)[valcol].last()
    s.index.name = "Object_ID"
    s.name = tag_name
    return s


def connector_role_lookup(uml_data, tag_name: str = "ravensRole") -> pd.Series:
    """
    Connector_ID -> role (string), from connector tagged values.
    Uses: connectortags / t_connectortag; Property|Name; Value|VALUE; Connector_ID|ElementID|ConnectorID
    """
    df = _get_table(uml_data, ("t_connectortag", "connectortags", "connector_tags"))
    if df.empty:
        return pd.Series(dtype=object)

    # owner id column variants seen in exports
    if "Connector_ID" in df.columns:
        id_col = "Connector_ID"
    elif "ElementID" in df.columns:
        id_col = "ElementID"
    elif "ConnectorID" in df.columns:
        id_col = "ConnectorID"
    else:
        return pd.Series(dtype=object)

    propcol = "Property" if "Property" in df.columns else ("Name" if "Name" in df.columns else None)
    valcol = "Value" if "Value" in df.columns else ("VALUE" if "VALUE" in df.columns else None)
    if not all([propcol, valcol]):
        return pd.Series(dtype=object)

    t = df.loc[df[propcol].astype(str).str.casefold() == tag_name.casefold(), [id_col, valcol]].copy()
    if t.empty:
        return pd.Series(dtype=object)

    t[id_col] = pd.to_numeric(t[id_col], errors="coerce")
    t = t.dropna(subset=[id_col]).astype({id_col: int})
    t[valcol] = t[valcol].astype(str).str.strip()

    s = t.groupby(id_col, sort=False)[valcol].last()
    s.index.name = "Connector_ID"
    s.name = tag_name
    return s


class UMLDiagramData:
    def __init__(self):
        pass


class UMLVisualizer:
    def __init__(self, uml_data: UMLData | None = None, svg_renderer_path: str | None = None):
        self.uml_data = uml_data or UMLData()

        # Try explicit arg → env var → legacy ravens.data constant
        default_from_pkg = None
        try:
            DEFAULT = importlib.import_module("ravens.data")._SVG_RENDERER_PATH
            default_from_pkg = str(DEFAULT)
        except Exception:
            pass

        self._svg_renderer_path = str(svg_renderer_path or os.environ.get("SVG_RENDERER_PATH", "") or (default_from_pkg or ""))

        if not self._svg_renderer_path or not os.path.exists(self._svg_renderer_path):
            raise FileNotFoundError("svgRenderer.js not found. Pass svg_renderer_path=..., or set SVG_RENDERER_PATH, " "or ensure ravens.data._SVG_RENDERER_PATH points to the renderer.")

        # ---- caches (avoid per-diagram recompute) ----
        # roles as dicts
        self._node_role_by_oid = object_role_lookup(self.uml_data).to_dict()  # Object_ID -> role
        self._edge_role_by_cid = connector_role_lookup(self.uml_data).to_dict()  # Connector_ID -> role

        # object quick lookups
        objs = self.uml_data.objects
        self._obj_name = objs["Name"].astype(str).to_dict()
        self._obj_stereo = objs["Stereotype"].astype(str).fillna("").to_dict()

        # attributes grouped once (Object_ID -> [(Name, Type), ...])
        self._attrs_by_obj = {}
        if not self.uml_data.attributes.empty:
            for r in self.uml_data.attributes.itertuples(index=False):
                self._attrs_by_obj.setdefault(int(r.Object_ID), []).append((str(r.Name), str(r.Type)))

        # connectors dict and “generalization parent” map
        cons = self.uml_data.connectors
        self._con_by_id = cons[["Start_Object_ID", "End_Object_ID", "Connector_Type", "SourceRole", "DestRole", "SourceCard", "DestCard"]].to_dict("index")
        gen = cons[cons["Connector_Type"].astype(str) == "Generalization"]
        self._gen_parent = {int(r.Start_Object_ID): int(r.End_Object_ID) for r in gen.itertuples(index=False)}

        # working buffers
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

    @staticmethod
    def _parse_legend_style(style_ex_string: str):
        """Parse legend configuration from StyleEx column."""
        legend_config = {"show_nodes": False, "show_edges": False, "node_filter": None, "edge_filter": None}

        try:
            for item in style_ex_string.split(";"):
                if not item:
                    continue

                if item.startswith("LegendOpts="):
                    # LegendOpts is a bitmask: bit 0=nodes, bit 1=edges
                    opts = int(item.split("=", 1)[1])
                    legend_config["show_nodes"] = bool(opts & 1)
                    legend_config["show_edges"] = bool(opts & 2)

                elif item.startswith("LegendTypeObj"):
                    # Node/object legend filter
                    if "=" in item:
                        filter_part = item.split("=", 1)[1]
                        if "TaggedValue.ravensRole" in filter_part:
                            legend_config["node_filter"] = "ravensRole"

                elif item.startswith("LegendTypeConn"):
                    # Edge/connector legend filter
                    if "=" in item:
                        filter_part = item.split("=", 1)[1]
                        if "TaggedValue.ravensRole" in filter_part:
                            legend_config["edge_filter"] = "ravensRole"

        except Exception as e:
            print(f"Warning: Failed to parse legend style: {e}")

        return legend_config

    def _create_svg_data(self, diagram_id: int):
        dobj = self.uml_data.diagramobjects
        dlinks = self.uml_data.diagramlinks

        dobjects = dobj[dobj["Diagram_ID"] == diagram_id]
        if dobjects.empty:
            self._current_diagram = diagram_id
            self._current_svg_data = {"cx": 0, "cy": 0, "nodes": [], "links": []}
            return

        # canvas size
        cx = int(abs(dobjects["RectRight"]).max())
        cy = int(abs(dobjects["RectBottom"]).max())
        svg_data = {"cx": cx, "cy": cy}

        # nodes present on this diagram (set for quick membership checks)
        node_ids = set(int(r.Object_ID) for r in dobjects.itertuples(index=False))
        boxes_data = []
        legends_data = []

        for o in dobjects.itertuples(index=False):
            oid = int(o.Object_ID)

            # Check if this is a legend object - need to check the objects table
            obj_row = self.uml_data.objects.loc[oid]
            style_ex = str(getattr(obj_row, "StyleEx", ""))
            is_legend = "LegendOpts=" in style_ex

            if is_legend:
                # Parse legend configuration
                legend_config = self._parse_legend_style(style_ex)
                legends_data.append(
                    {
                        "id": oid,
                        "x": int(o.RectLeft),
                        "y": -int(o.RectTop),
                        "width": int(abs(o.RectRight - o.RectLeft)),
                        "height": int(abs(o.RectTop - o.RectBottom)),
                        "config": legend_config,
                    }
                )
                continue

            stereo = self._obj_stereo.get(oid, "")

            # text lines
            text_lines = []
            if stereo == "enumeration":
                text_lines.append({"text": f"<<{stereo}>>", "align": "center"})
                text_lines.append({"text": f"{self._obj_name.get(oid,'')}", "align": "center", "style": "bold"})
                text_lines.append({})
                text_lines.append({"text": "literals", "align": "center", "style": "italic"})
                for name, _type in self._attrs_by_obj.get(oid, []):
                    text_lines.append({"text": f"{name}", "align": "left"})
            elif stereo == "CIMDatatype":
                text_lines.append({"text": f"<<{stereo}>>", "align": "center"})
                text_lines.append({"text": f"{self._obj_name.get(oid,'')}", "align": "center", "style": "bold"})
                # show attributes if AttPub==1
                show_attrs = "1"
                try:
                    # parse once, cheap key lookup
                    for part in str(o.ObjectStyle).split(";"):
                        if part.startswith("AttPub="):
                            show_attrs = part.split("=", 1)[1]
                            break
                except Exception:
                    pass
                if show_attrs == "1":
                    text_lines.append({})
                    for name, _type in self._attrs_by_obj.get(oid, []):
                        text_lines.append({"text": f"+   {name}: {_type}", "align": "left"})
            else:
                # parent (generalization target) if not on diagram
                parent_id = self._gen_parent.get(oid)
                if parent_id and parent_id not in node_ids:
                    text_lines.append({"text": f"{self._obj_name.get(parent_id,'')}", "align": "right", "style": "italic"})
                text_lines.append({"text": f"{self._obj_name.get(oid,'')}", "align": "center", "style": "bold"})
                # show attributes if AttPub==1
                show_attrs = "1"
                try:
                    for part in str(o.ObjectStyle).split(";"):
                        if part.startswith("AttPub="):
                            show_attrs = part.split("=", 1)[1]
                            break
                except Exception:
                    pass
                if show_attrs == "1":
                    text_lines.append({})
                    for name, _type in self._attrs_by_obj.get(oid, []):
                        text_lines.append({"text": f"+   {name}: {_type}", "align": "left"})

            # node color from ravensRole (case-insensitive); fallback default
            # node color: tag first, then stereotype, then default
            role = self._node_role_by_oid.get(oid)
            role_key = str(role).strip().casefold() if role is not None else ""
            stereo_key = str(stereo or "").strip().casefold()

            node_hex = NODE_MAP_CI.get(role_key) or STEREO_MAP_CI.get(stereo_key) or DEFAULT_NODE_HEX

            boxes_data.append(
                {
                    "id": oid,
                    "x": int(o.RectLeft),
                    "y": -int(o.RectTop),
                    "width": int(abs(o.RectRight - o.RectLeft)),
                    "height": int(abs(o.RectTop - o.RectBottom)),
                    "textLines": text_lines,
                    "color": node_hex,
                }
            )

        svg_data["nodes"] = boxes_data
        svg_data["legends"] = legends_data

        svg_data["roleMappings"] = {"nodes": ROLE_TO_HEX_NODE, "edges": ROLE_TO_HEX_EDGE}

        # links
        links_data = []
        for l in dlinks[dlinks["DiagramID"] == diagram_id].itertuples(index=False):
            if getattr(l, "Hidden", False):
                continue
            cid = int(l.ConnectorID)
            c = self._con_by_id.get(cid)
            if not c:
                continue
            s = int(c["Start_Object_ID"])
            t = int(c["End_Object_ID"])
            if s not in node_ids or t not in node_ids:
                continue

            # parse link geometry once
            link_style = {}
            try:
                geom = str(l.Geometry)
                if "$" in geom:
                    pre, post = geom.split("$", 1)
                    if post:
                        for item in post.split(";"):
                            if not item:
                                continue
                            k, v = item.split("=", 1)
                            d = {}
                            for seg in v.split(":"):
                                if "=" in seg:
                                    a, b = seg.split("=", 1)
                                    d[a] = int(b)
                            link_style[k] = d
                else:
                    # not strictly needed, we only read HDN/CX/CY keys below
                    pass
            except Exception:
                pass

            role_e = self._edge_role_by_cid.get(cid)
            edge_hex = EDGE_MAP_CI.get(str(role_e).strip().casefold(), DEFAULT_EDGE_HEX) if role_e else DEFAULT_EDGE_HEX

            links_data.append(
                {
                    "source": str(s),
                    "target": str(t),
                    "type": str(c["Connector_Type"]).lower(),
                    "textStartTop": f"+{c['SourceRole']}" if pd.notna(c["SourceRole"]) else "",
                    "textStartTopHidden": link_style.get("LLT", {}).get("HDN", 0),
                    "textStartTopXPos": link_style.get("LLT", {}).get("CX", 0.0),
                    "textStartTopYPos": link_style.get("LLT", {}).get("CY", 0.0),
                    "textEndTop": f"+{c['DestRole']}" if pd.notna(c["DestRole"]) else "",
                    "textEndTopHidden": link_style.get("LRT", {}).get("HDN", 0),
                    "textEndTopXPos": link_style.get("LRT", {}).get("CX", 0.0),
                    "textEndTopYPos": link_style.get("LRT", {}).get("CY", 0.0),
                    "textStartBtm": f"{c['SourceCard']}" if pd.notna(c["SourceCard"]) else "",
                    "textStartBtmHidden": link_style.get("LLB", {}).get("HDN", 0),
                    "textStartBtmXPos": link_style.get("LLB", {}).get("CX", 0.0),
                    "textStartBtmYPos": link_style.get("LLB", {}).get("CY", 0.0),
                    "textEndBtm": f"{c['DestCard']}" if pd.notna(c["DestCard"]) else "",
                    "textEndBtmHidden": link_style.get("LRB", {}).get("HDN", 0),
                    "textEndBtmXPos": link_style.get("LRB", {}).get("CX", 0.0),
                    "textEndBtmYPos": link_style.get("LRB", {}).get("CY", 0.0),
                    "color": edge_hex,
                }
            )

        svg_data["links"] = links_data
        self._current_diagram = diagram_id
        self._current_svg_data = svg_data

    def _create_svg(self):
        # write the (possibly large) payload to a temp file instead of passing on CLI
        data_json = json.dumps(self._current_svg_data, ensure_ascii=False)
        tf = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        try:
            tf.write(data_json)
            tf.close()
            json_path = tf.name

            result = subprocess.run(["node", self._svg_renderer_path, json_path], capture_output=True, text=True)

            if result.returncode != 0:
                raise RuntimeError(f"Renderer failed ({result.returncode}):\n{result.stderr}")

            self._current_svg = result.stdout

        except FileNotFoundError as e:
            # Proper message when Node truly isn’t found
            raise FileNotFoundError("Node.js not found on PATH. Run `node -v` to verify, then reopen your shell.") from e
        finally:
            try:
                os.remove(tf.name)
            except Exception:
                pass

    def _save_current_svg(self, filename: str):
        self._current_svg_data["outputPath"] = filename
        self._create_svg()

    def save_uml_diagram_from_package_and_diagram_name(self, package_name: str, diagram_name: str, svg_dir_path: pathlib.PosixPath | str) -> str:
        pkg_id = self.uml_data.packages[self.uml_data.packages["Name"] == package_name].iloc[0]._name
        diagram_id = self.uml_data.diagrams[(self.uml_data.diagrams["Package_ID"] == pkg_id) & (self.uml_data.diagrams["Name"] == diagram_name)].iloc[0]._name
        self._create_svg_data(diagram_id)

        path = os.path.join(svg_dir_path, f"{str(package_name)}.{str(diagram_name)}.svg")
        self._save_current_svg(path)

        return path

    def save_uml_diagrams_from_package_name(self, package_name: str, svg_dir_path: pathlib.PosixPath | str) -> list:
        paths = []
        pkg_id = self.uml_data.packages[self.uml_data.packages["Name"] == package_name].iloc[0]._name
        for diagram in self.uml_data.diagrams[self.uml_data.diagrams["Package_ID"] == pkg_id].itertuples():
            self._create_svg_data(diagram.Index)

            path = os.path.join(svg_dir_path, f"{str(package_name)}.{str(diagram.Name)}.svg")
            self._save_current_svg(path)

            paths.append(path)

        return paths

    def save_uml_diagrams_from_package_id(self, package_id: str, svg_dir_path: pathlib.PosixPath | str) -> list:
        paths = []
        package_name = str(self.uml_data.packages.loc[package_id].Name).strip()
        for diagram in self.uml_data.diagrams[self.uml_data.diagrams["Package_ID"] == package_id].itertuples():
            self._create_svg_data(diagram.Index)  # fixed: no extra uml_data arg

            path = os.path.join(svg_dir_path, f"{str(package_name)}.{str(diagram.Name)}.svg")
            self._save_current_svg(path)

            paths.append(path)

        return paths

    def save_all_uml_diagrams(self, svg_dir_path: pathlib.PosixPath | str) -> list:
        paths = []
        for diagram in self.uml_data.diagrams[self.uml_data.diagrams["Diagram_Type"] == "Logical"].itertuples():
            try:
                package_name = str(self.uml_data.packages.loc[diagram.Package_ID].Name).strip()
            except Exception as e:
                print(f"Failed to get package name for diagram {diagram.Index}: {type(e).__name__}: {e}")
                continue

            diagram_name = str(diagram.Name).strip() if pd.notna(diagram.Name) else f"unnamed_{diagram.Index}"

            try:
                self._create_svg_data(diagram.Index)
                path = os.path.join(svg_dir_path, f"{package_name}.{diagram_name}.svg")
                self._save_current_svg(path)
                paths.append(path)
            except Exception as e:
                print(f"Failed to render: {package_name}.{diagram_name} (ID: {diagram.Index})")
                print(f"  Error: {type(e).__name__}: {e}")
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
