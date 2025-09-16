import re
import os
import json
import pathlib
import networkx as nx
import pandas as pd
from ravens.uml.visualize import UMLVisualizer
from openpyxl import Workbook, load_workbook
from openpyxl.styles import PatternFill, Border, Side
from typing import Optional, Dict, Any, Tuple, List
import pandas as pd


# sets the order to display edge attributes when creating graph attributes
EDGE_ATTR_ORDER = [
    'Diagram', 'Start_Object',  'End_Object',
    'color', 'label',
    'start_mult', 'end_mult',
    # 'SourceRole', 'DestRole',  
    # 'SourceCard', 'DestCard', 'start_mult_text', 'start_mult_hidden',  'end_mult_text', 'end_mult_hidden', # multiplicity
    # 'start_role_text', 'start_role_hidden', 'end_role_text', 'end_role_hidden', 'name_text', 'name_hidden', 'hide_all_labels', # labels - 'name_text' refers to middle label
    # 'c_source_decor',  'c_dest_decor', # decorators (arrow, triangle, etc.)
    'Connector_Type', 'ConnectorID', 'InstanceID', 'DiagramID', 
    # 'stereotype_text', 'stereotype_hidden',
    ]


def lenG(G):
    """
    Computes number of subgraphs within a networkx graph object.
    """
    g_un = G.to_undirected()
    connected_components = list(nx.connected_components(g_un))
    return len(connected_components)


def package_graph(uml_data):
    """
    Returns a networkx graph of package relationships.
    Retains Name and Notes package attributes as node properties.
    """

    g = nx.DiGraph()
    valid_package_ids = set(uml_data.packages.index)
    for package, row in uml_data.packages.iterrows():
        node_attributes = {key: row[key] for key in ["Name", "Notes"] if key in row}
        g.add_node(package, **node_attributes)
        if pd.notna(row["Parent_ID"]):
            parent_id = row["Parent_ID"]
            if parent_id in valid_package_ids:
                parent_row = uml_data.packages.loc[parent_id]
                parent_attributes = {
                    key: parent_row[key]
                    for key in ["Name", "Notes"]
                    if key in parent_row
                }
                g.add_node(parent_id, **parent_attributes)
            else:
                g.add_node(parent_id)

            g.add_edge(parent_id, package)

    return g


def package_IDs(G, package="RAVENS"):
    """
    Returns all package node IDs. If a package is provided,
    returns that package node ID along with all its descendant
    packages.
    """
    package_node = None
    found = False
    for node, data in G.nodes(data=True):
        if data.get("Name") == package:
            package_node = node
            found = True
            break

    if found is False:
        raise KeyError(f"Could not find package named {package}.")
    nodes_below = list(nx.descendants(G, package_node))

    return [package_node] + nodes_below


def find_root_nodes(G):
    # Convert to undirected graph to find connected components
    g_undirected = G.to_undirected()
    connected_components = list(nx.connected_components(g_undirected))

    # Iterate over each subgraph
    for i, component in enumerate(connected_components, start=1):
        # Create a subgraph view for the current component
        subgraph = G.subgraph(component)

        # Find root node (nodes with in-degree 0)
        root_nodes = [
            node for node in subgraph.nodes() if subgraph.in_degree(node) == 0
        ]

        # Print subgraph info
        print(f"\nSubgraph {i}:")

        if root_nodes:
            for root in root_nodes:
                # Print root node and its properties
                print(f"  Root Node: {root}")
                print(f"    Properties: {subgraph.nodes[root]}")
        else:
            print("  No root node found (no node with in-degree 0).")

    return


def find_object(uml_data, otype, diagramname, obj1, obj2=None):

    dgid = uml_data.diagrams.index[uml_data.diagrams["Name"] == diagramname].tolist()
    if len(dgid) == 0:
        return f"No diagrams found with name {diagramname}."
    elif len(dgid) > 1:
        print("Need to implement multiple diagram name finds.")

    diag_objs = uml_data.diagramobjects[
        uml_data.diagramobjects["Diagram_ID"].isin(dgid)
    ]
    obj_names = [
        uml_data.objects["Name"].values[uml_data.objects.index == oid][0]
        for oid in diag_objs["Object_ID"].values
    ]

    if otype == "diagramobject":

        if obj1 in obj_names:
            do = diag_objs.iloc[obj_names.index(obj1)]
            return do
        else:
            return f"No object named {obj1} found in {diagramname}."

    elif otype in ("diagramlink", "connector"):

        diag_objs = diag_objs.copy()  # stupid warning
        diag_objs["Name"] = obj_names
        oid1 = diag_objs["Object_ID"].values[diag_objs["Name"] == obj1][0]
        if obj2 is not None:
            oid2 = diag_objs["Object_ID"].values[diag_objs["Name"] == obj2][0]

        if obj2 is None:
            conns = uml_data.connectors.index[
                (
                    (uml_data.connectors["Start_Object_ID"] == oid1)
                    | (uml_data.connectors["End_Object_ID"] == oid1)
                )
            ]
            dlinks = uml_data.diagramlinks[
                uml_data.diagramlinks["ConnectorID"].isin(conns)
                & uml_data.diagramlinks["DiagramID"].isin(dgid)
            ]

        else:
            conns = uml_data.connectors.index[
                (
                    (uml_data.connectors["Start_Object_ID"] == oid1)
                    & (uml_data.connectors["End_Object_ID"] == oid2)
                )
                | (
                    (uml_data.connectors["Start_Object_ID"] == oid2)
                    & (uml_data.connectors["End_Object_ID"] == oid1)
                )
            ]
            dlinks = uml_data.diagramlinks[
                uml_data.diagramlinks["ConnectorID"].isin(conns)
                & uml_data.diagramlinks["DiagramID"].isin(dgid)
            ]

        if len(dlinks) == 0:
            return f"No connectors found connected to both {obj1} and {obj2}."

        if otype == "connector":
            return uml_data.connectors[
                uml_data.connectors.index.isin(dlinks["ConnectorID"].tolist())
            ]
        else:
            return dlinks

    else:
        print(
            f"{otype} is not a supported object type to find. Choose from 'diagramobject', 'connector', or 'diagramlink'."
        )
        return ()


def ea_numeric_to_hex_color(color_code):
    """
    Convert a numeric color code (Enterprise Architect format)
    into a hex color string.

    Parameters:
        color_code (str): Color code as string.

    Returns:
        str: Hex color string (e.g., "#98fb98").
    """
    try:
        color_code = int(color_code)
    except ValueError:
        return None

    if color_code == -1:
        return "default"

    red = color_code % 256
    green = (color_code // 256) % 256
    blue = color_code // 65536

    return "#{:02x}{:02x}{:02x}".format(red, green, blue)


def parse_objectstyle(ObjectStyle):

    # ObjectStyle = instances['ObjectStyle'].values[6]
    if "BCol=" not in ObjectStyle:
        return None

    match = re.search(r"BCol=([^;]+);", ObjectStyle)
    return ea_numeric_to_hex_color(match.group(1)) if match else None


def obj_color_validation(G):
    """
    Returns a DataFrame of objects whose colors are not consistent.
    """

    mismatched_colors = []
    for node, data in list(G.nodes(data=True)):
        if len(set(data["instances"]["ObjectColorHex"])) > 1:
            mismatched_colors.append(data)

    # Put into DataFrame
    rows = []
    for entry in mismatched_colors:
        instances = entry["instances"]
        for i in range(len(instances["Package_ID"])):
            row = {
                "Name": entry["Name"],
                # 'Object_Type': entry['Object_Type'],
                "Package_ID": entry["Package_ID"],
                # 'Instance_Package_ID': instances['Package_ID'][i],
                "Package_Name": instances["Package_Name"][i],
                "Instance_ID": instances["Instance_ID"][i],
                "DiagramName": instances["DiagramName"][i],
                "BackgroundColorHex": instances["ObjectColorHex"][i],
            }
            rows.append(row)

    # Create DataFrame
    df = pd.DataFrame(rows)

    return df


def all_colors(G, otype):
    """
    Diagnostic tool. Returns all colors for either diagramobjects or
    diagramlinks.
    """
    colors = set()
    if otype == "diagramobjects":
        for node, data in list(G.nodes(data=True)):
            colors.update(set(data["instances"]["ObjectColorHex"]))

    elif otype == "diagramlinks":
        for _, _, data in list(G.edges(data=True)):
            print(data)
            colors.update(set(data["instances"]["i_color"]))

    return colors


def write_color_bugs(color_clashes, defs_nans, path_out):
    # Create a workbook and add a worksheet
    wb = Workbook()
    default_sheet = wb.active
    wb.remove(default_sheet)

    # Define a bold bottom border style
    thick_border = Border(bottom=Side(style="thick"))

    # Add the first sheet with styling
    ws1 = wb.create_sheet(title="same_object_different_color")

    # Determine the last column index based on headers
    last_col_idx = len(color_clashes.columns)  # The last column with a header

    # Write the headers for the first sheet
    for col_num, column_title in enumerate(color_clashes.columns, 1):
        ws1.cell(row=1, column=col_num, value=column_title)

    # Write the data and apply background colors and borders
    prev_name = None  # Track when the "Name" field changes
    name_col_idx = color_clashes.columns.get_loc("Name") + 1  # Get "Name" column index

    for row_num, row in enumerate(color_clashes.itertuples(index=False), 2):
        current_name = getattr(row, "Name")  # Get the "Name" value for this row

        for col_num, value in enumerate(row, 1):
            cell = ws1.cell(row=row_num, column=col_num, value=value)

            # Apply background color if in the 'BackgroundColorHex' column
            if col_num == color_clashes.columns.get_loc("BackgroundColorHex") + 1:
                color_hex = str(value).replace("#", "")
                if len(color_hex) == 6:  # Ensure valid hex format
                    cell.fill = PatternFill(
                        start_color=color_hex, end_color=color_hex, fill_type="solid"
                    )

        # Apply a thick border if the "Name" field changes
        if prev_name is not None and prev_name != current_name:
            for col_num in range(1, last_col_idx + 1):  # Only up to last header column
                ws1.cell(row=row_num - 1, column=col_num).border = thick_border

        prev_name = current_name  # Update previous name

    # Add the second sheet for defs_nans
    ws2 = wb.create_sheet(title="defaults_and_nans")

    # Write the headers for defs_nans
    for col_num, column_title in enumerate(defs_nans.columns, 1):
        ws2.cell(row=1, column=col_num, value=column_title)

    # Write the data for defs_nans
    for row_num, row in enumerate(defs_nans.itertuples(index=False), 2):
        for col_num, value in enumerate(row, 1):
            ws2.cell(row=row_num, column=col_num, value=value)

    # Save the file
    wb.save(path_out)


def find_isolates(G):
    isolates = list(nx.isolates(G))
    isolate_properties = {}
    for node in isolates:
        # Get all attributes/properties of the node
        isolate_properties[node] = G.nodes[node]

    instance_strings = []
    packages, diagrams, names, colors = [], [], [], []
    for node_id, properties in isolate_properties.items():
        # Get the Name from the top level
        name = properties.get("Name", "")

        # Get instances information
        instances = properties.get("instances", {})

        # Check if instances data exists and has the required fields
        if instances and "Package_Name" in instances and "DiagramName" in instances:
            # Loop through all instances (using the length of any list in instances)
            num_instances = len(instances["Package_Name"])

            for i in range(num_instances):
                packages.append(instances["Package_Name"][i])
                diagrams.append(instances["DiagramName"][i])
                colors.append(instances["ObjectColorHex"][i])
                names.append(name)

                # # Create the formatted string
                # instance_string = f"{package_name}.{diagram_name}.{name}.{color}"
                # instance_strings.append(instance_string)

    df = pd.DataFrame(
        data={"package": packages, "diagram": diagrams, "name": names, "color": colors}
    )

    return df


def write_isolates(df, path_out=None):
    """
    If path_out is an existing xlsx file, will add a sheet to it called 'isolates'.
    """
    # Ensure the dataframe has the expected 4 columns
    df = df[["package", "diagram", "name", "color"]]

    # Check if we're appending to an existing Excel file
    if path_out and os.path.exists(path_out):
        wb = load_workbook(path_out)
    else:
        wb = Workbook()
        default_sheet = wb.active
        wb.remove(default_sheet)

    ws = wb.create_sheet(title="isolates")

    # Write headers
    for col_num, column_title in enumerate(df.columns, 1):
        ws.cell(row=1, column=col_num, value=column_title)

    # Write data with color fills
    for row_num, row in enumerate(df.itertuples(index=False), 2):
        for col_num, value in enumerate(row, 1):
            cell = ws.cell(row=row_num, column=col_num, value=value)
            if df.columns[col_num - 1] == "color":
                if isinstance(value, str) and value.lower() not in ["default", "none"]:
                    hex_color = value.replace("#", "")
                    if len(hex_color) == 6:
                        cell.fill = PatternFill(
                            start_color=hex_color,
                            end_color=hex_color,
                            fill_type="solid",
                        )

    if path_out:
        wb.save(path_out)


def get_inclusions(uml_data, package=None):
    """
    Returns dictionary of various IDs that are only found within a
    specified package. Includes all packages (and objects) contained
    within the requested package.
    """

    inclusions = {}
    inclusions["Package_ID"] = package_IDs(package_graph(uml_data), package)
    inclusions["Diagram_ID"] = set(
        uml_data.diagrams.index[
            uml_data.diagrams["Package_ID"].isin(inclusions["Package_ID"])
        ].to_list()
    )
    inclusions["link_Instance_ID"] = set(
        uml_data.diagramlinks.index[
            uml_data.diagramlinks["DiagramID"].isin(inclusions["Diagram_ID"])
        ].tolist()
    )
    inclusions["Connector_ID"] = set(
        uml_data.diagramlinks["ConnectorID"][
            uml_data.diagramlinks["DiagramID"].isin(inclusions["Diagram_ID"])
        ].tolist()
    )
    inclusions["obj_Instance_ID"] = set(
        uml_data.diagramobjects.index[
            uml_data.diagramobjects["Diagram_ID"].isin(inclusions["Diagram_ID"])
        ].tolist()
    )
    inclusions["Object_ID"] = set(
        uml_data.diagramobjects["Object_ID"][
            uml_data.diagramobjects["Diagram_ID"].isin(inclusions["Diagram_ID"])
        ].tolist()
    )

    return inclusions


def objects_graph(uml_data, inclusions=None):

    def parse_connector_labels(row):
        """
        Determines which labels are associated with which objects for a given connector.
        Only considers Start and End labels (not Mid, not sure what Mid labels indicate).

        Multiplicities (e.g. 1..0) are removed via regex.
        """

        def process_labels(cols):
            labels = [row[c] for c in cols if not pd.isna(row[c])]
            labels = [
                lbl
                for lbl in labels
                if not re.fullmatch(r"\d+\.\.\d+|\d+\.\.\*|\d+|\*", lbl)
            ]
            return (
                labels[0]
                if len(labels) == 1
                else None if not labels else "MULTIPLE LABELS"
            )

        labelcols = [col for col in row.keys() if "label" in col.lower()]
        s_label = process_labels([col for col in labelcols if "start" in col.lower()])
        e_label = process_labels([col for col in labelcols if "end" in col.lower()])

        return s_label, e_label

    def label_visibility(geometry):
        """Determine if Start and End labels are hidden for diagramlinks
        using EDGE (from connectors table) to assign positions."""

        # Define which labels correspond to start based on EDGE
        edge_map = {
            "0": ("$LLB", "$LLT"),  # Left side
            "1": ("$LMT",),  # Top side
            "2": ("$LRT", "$LRB"),  # Right side
            "3": ("$LMB",),  # Bottom side
        }

        # Extract EDGE value
        edge_match = re.search(r"EDGE=(\d+)", geometry)
        edge_value = (
            edge_match.group(1) if edge_match else "0"
        )  # Default to left if EDGE is missing

        # Get label positions for this EDGE
        start_labels = edge_map.get(edge_value, ("$LLB", "$LLT"))  # Default to left
        end_labels = (
            "$LLB",
            "$LLT",
            "$LMT",
            "$LRT",
            "$LRB",
            "$LMB",
        )  # Any labels not in start are end

        # Check if start or end labels are hidden
        start_hidden = any(
            re.search(rf"{label}.*?HDN=1", geometry) for label in start_labels
        )
        end_hidden = any(
            re.search(rf"{label}.*?HDN=1", geometry)
            for label in end_labels
            if label not in start_labels
        )

        return start_hidden, end_hidden

    # Filtering
    if inclusions:
        useobjects = inclusions["Object_ID"]
        useobjinstance = inclusions["obj_Instance_ID"]
        uselinkinstance = inclusions["link_Instance_ID"]
        usediagrams = inclusions["Diagram_ID"]
        useconnectors = inclusions["Connector_ID"]
    else:
        useobjects = set(uml_data.objects.index)
        useobjinstance = set(uml_data.diagramobjects.index)
        uselinkinstance = set(uml_data.diagramlinks.index)
        usediagrams = set(uml_data.diagrams.index)
        useconnectors = set(uml_data.connectors.index)

    g = nx.MultiDiGraph()

    # Add nodes - need to change attributes to have an instances dictionary
    for oid, row in uml_data.objects.iterrows():
        if oid in useobjects:
            node_attributes = {
                key: row[key]
                for key in ["Name", "Object_Type", "Package_ID"]
                if key in row
            }

            # Find Instances of this Object across all diagrams; store as attributes
            instances = uml_data.diagramobjects[
                uml_data.diagramobjects["Object_ID"] == oid
            ]
            instances = instances[instances.index.isin(useobjinstance)]
            inst_attrs = {
                "Package_ID": [],
                "Package Name": [],
                "Instance_ID": [],
                "DiagramName": [],
                "ObjectColorHex": [],
            }
            if len(instances) > 0:
                package_IDs = [
                    int(
                        uml_data.diagrams["Package_ID"].values[
                            uml_data.diagrams.index == did
                        ][0]
                    )
                    for did in instances["Diagram_ID"]
                ]
                inst_attrs = {
                    "Package_ID": package_IDs,
                    "Package_Name": [
                        uml_data.packages["Name"].values[
                            uml_data.packages.index == did
                        ][0]
                        for did in package_IDs
                    ],
                    "Instance_ID": instances.index.tolist(),
                    "DiagramName": [
                        uml_data.diagrams["Name"].values[
                            uml_data.diagrams.index == did
                        ][0]
                        for did in instances["Diagram_ID"].values
                    ],
                    "ObjectColorHex": [
                        parse_objectstyle(
                            uml_data.diagramobjects.loc[iid, "ObjectStyle"]
                        )
                        for iid in instances.index
                    ],
                }
            node_attributes["instances"] = inst_attrs
            g.add_node(oid, **node_attributes)

    # Add edges
    uv = UMLVisualizer(uml_data)  # for parsing style strings
    for cid, row in uml_data.connectors.iterrows():
        if cid in useconnectors:

            # Ensure both start and end objects are in the graph
            if row["Start_Object_ID"] not in g or row["End_Object_ID"] not in g:
                raise KeyError("Missing nodes in graph.")

            edge_attrs = {
                "Connector_ID": cid,
                "Connector_Type": row["Connector_Type"],
                "SourceCard": row["SourceCard"],
                "DestCard": row["DestCard"],
                "SourceRole": row["SourceRole"],
                "DestRole": row["DestRole"],
            }

            # Determine if directionality is uni- or bi-
            if (
                row["Connector_Type"] == "Generalization"
            ):  # not sure if only generalizations are undirected
                edge_attrs["directed"] = False
            else:
                edge_attrs["directed"] = True

            # Determine the color of the connector - this can be overwritten by the diagramlink specs (i.e. instance)
            edge_attrs["linecolor"] = ea_numeric_to_hex_color(row["LineColor"])
            edge_attrs["startlabel"], edge_attrs["endlabel"] = parse_connector_labels(
                row
            )

            # Store attributes for each instance of this connector (i.e. diagramlink)
            this_instances = uml_data.diagramlinks[
                uml_data.diagramlinks["ConnectorID"].isin([cid])
            ]
            this_instances = this_instances[
                this_instances.index.isin(inclusions["link_Instance_ID"])
            ]
            inst_attrs = {
                ini: []
                for ini in ["iid", "did", "i_start_hidden", "i_end_hidden", "i_color"]
            }
            for iid, irow in this_instances.iterrows():
                inst_attrs["iid"].append(iid)  # Instance_ID
                inst_attrs["did"].append(irow["DiagramID"])

                # Label hidden-ness
                start_hidden, end_hidden = label_visibility(irow["Geometry"])
                inst_attrs["i_start_hidden"].append(start_hidden)
                inst_attrs["i_end_hidden"].append(end_hidden)

                # Line color (might override the connector line color)
                iid_style = uv._parse_link_style(irow["Style"])
                if "Color" in iid_style:
                    inst_attrs["i_color"].append(iid_style["Color"])
                else:
                    inst_attrs["i_color"].append("-1")  # EA's default color

            edge_attrs["instances"] = inst_attrs

            # Finally add the edge
            try:
                g.add_edge(row["Start_Object_ID"], row["End_Object_ID"], **edge_attrs)
                # Add reverse edge if the link has no direction
                if edge_attrs["directed"] is False:
                    g.add_edge(
                        row["End_Object_ID"], row["Start_Object_ID"], **edge_attrs
                    )
            except:
                import pdb
                pdb.set_trace()

    return g


def json_to_G(path_json):

    G = nx.DiGraph()

    def walk(node, parent=None):
        if isinstance(node, dict):
            if "$objectType" in node and node["$objectType"] == "reference":
                source = parent
                target = node.get("$objectId") or node.get("$referencePath")
                if source and target:
                    G.add_edge(source, target)
            for key, value in node.items():
                if key == "$objectId" and "$objectType" in node:
                    G.add_node(value)
                    parent = value  # update for downstream edges
                walk(value, parent)
        elif isinstance(node, list):
            for item in node:
                walk(item, parent)

    with open(path_json, "r") as f:
        json_data = json.load(f)

    walk(json_data)

    return G


def json_to_containment_G(path_json):
    "Builds a G based on containment in JSON, not references."

    # Load the JSON schema
    with open(path_json, "r") as f:
        schema = json.load(f)

    # Build a directed graph representing the containment hierarchy
    G_cleaned = nx.DiGraph()

    def add_clean_nodes(d, parent_key="Root"):
        if isinstance(d, dict):
            for key, value in d.items():
                # Special handling for "properties"
                if key == "properties" and isinstance(value, dict):
                    for prop_name, prop_value in value.items():
                        node_id = prop_value.get("$objectId", prop_name)
                        G_cleaned.add_edge(parent_key, node_id)
                        add_clean_nodes(prop_value, node_id)
                else:
                    if isinstance(value, dict):
                        node_id = value.get("$objectId", key)
                        G_cleaned.add_edge(parent_key, node_id)
                        add_clean_nodes(value, node_id)
                    elif isinstance(value, list):
                        for item in value:
                            add_clean_nodes(item, parent_key)

    # Run it on the schema
    add_clean_nodes(schema)

    return G_cleaned


def set_difference_df(set1, set2, name1="Set 1", name2="Set 2"):
    in_both = set1 & set2
    only_in_set1 = set1 - set2
    only_in_set2 = set2 - set1

    max_len = max(len(in_both), len(only_in_set1), len(only_in_set2))
    df_compare = pd.DataFrame(
        {
            "In Both": list(in_both) + [""] * (max_len - len(in_both)),
            f"Only in {name1}": list(only_in_set1)
            + [""] * (max_len - len(only_in_set1)),
            f"Only in {name2}": list(only_in_set2)
            + [""] * (max_len - len(only_in_set2)),
        }
    )

    return df_compare

def auto_template_paths():

    def walk_template(node, prefix=()):
        yield prefix, node
        if isinstance(node, dict):
            if node.get("type") == "array":
                node = node["items"]          # skip array wrapper
            for k, v in node.get("properties", {}).items():
                yield from walk_template(v, prefix + (k,))
            for v in node.get("anyOf", []):
                # label polymorphic branches with "|SubType"
                name = v.get("$objectId") or v.get("$objectType") or "?"
                yield from walk_template(v, prefix + (f"|{name}",))

    import json
    with open(pathlib.Path(r"X:\Research\Ravens\repo\MG-RAVENS\ravens\lib\template_auto.json"), encoding="utf-8") as f:
        template_json = json.load(f)        # <- this variable

    return { "/".join(p): n for p, n in walk_template(template_json) }
    


# def find_object_in_json(target_key, keys_only=False):
#     def load_json():
#         with open(pathlib.Path(r"X:\Research\Ravens\repo\MG-RAVENS\ravens\lib\template_auto.json"), encoding="utf-8") as f:
#             return json.load(f)

#     def find_paths(obj, target_key, current_path):
#         results = []
#         if isinstance(obj, dict):
#             for k, v in obj.items():
#                 new_path = current_path + [k]
#                 if target_key.lower() in k.lower():
#                     results.append("/".join(new_path))
#                 results.extend(find_paths(v, target_key, new_path))
#         elif isinstance(obj, list):
#             for i, item in enumerate(obj):
#                 new_path = current_path + [f"[{i}]"]
#                 results.extend(find_paths(item, target_key, new_path))
#         return results

#     def find_paths_in_keys_and_values(obj, target_str, current_path):
#         results = []
#         if isinstance(obj, dict):
#             for k, v in obj.items():
#                 new_path = current_path + [k]
#                 if target_str.lower() in k.lower():
#                     results.append("/".join(new_path))
#                 if isinstance(v, str) and target_str.lower() in v.lower():
#                     results.append("/".join(new_path))
#                 results.extend(find_paths_in_keys_and_values(v, target_str, new_path))
#         elif isinstance(obj, list):
#             for i, item in enumerate(obj):
#                 new_path = current_path + [f"[{i}]"]
#                 results.extend(find_paths_in_keys_and_values(item, target_str, new_path))
#         return results

#     data = load_json()
#     if keys_only:
#         return find_paths(data, target_key, [])
#     else:
#         return find_paths_in_keys_and_values(data, target_key, [])


import json
import pathlib
from collections import defaultdict

def find_object_in_json(target_key, keys_only=False):
    def load_json():
        with open(pathlib.Path(r"X:\Research\Ravens\repo\MG-RAVENS\ravens\lib\template.json"), encoding="utf-8") as f:
            return json.load(f)

    def walk(obj, path, results):
        if isinstance(obj, dict):
            for k, v in obj.items():
                current_path = path + [k]
                last_key = current_path[-1].lower()

                match = (
                    target_key.lower() in last_key
                    and not last_key.startswith("$")
                    and last_key.endswith(target_key.lower())
                )
                if match:
                    path_str = clean_path(current_path)
                    obj_type = v.get("$objectType", "unknown") if isinstance(v, dict) else "unknown"
                    results[obj_type].append(path_str)

                if not keys_only and isinstance(v, str):
                    if target_key.lower() in v.lower() and last_key.endswith(target_key.lower()):
                        path_str = clean_path(current_path)
                        results["string_match"].append(path_str)

                walk(v, current_path, results)

        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                current_path = path + [f"[{i}]"]
                walk(item, current_path, results)

    def clean_path(path_parts):
        return "/".join(p for p in path_parts if p != "properties")

    data = load_json()
    results = defaultdict(list)
    walk(data, [], results)
    return dict(results)




def parse_connector_label_info(dl_row, con_row, stereotype_text: Optional[str]=None) -> Dict[str, Any]:
    
    def _kv_semicolon(s: Optional[str]) -> Dict[str, str]:
        if not isinstance(s, str): return {}
        out = {}
        for part in s.split(";"):
            if "=" in part:
                k, v = part.split("=", 1)
                out[k] = v
        return out

    def parse_style(style: Optional[str]) -> Dict[str, Any]:
        kv = _kv_semicolon(style)
        def _to_int(x):
            try: return int(x)
            except: return None
        return {
            "hide_all": kv.get("HideLabels", "0") == "1",
            "color": _to_int(kv.get("Color")),   # EA BGR int; -1 means inherit/default
        }

    def parse_geom_hidden_flags(geometry: Optional[str]) -> Dict[str, int]:
        """Return {slot: HDN} for the known label slots. Missing slot => not in dict."""
        if not isinstance(geometry, str): return {}
        h = {}
        for code, block in re.findall(r'(L[A-Z]{2})=([^;]*);', geometry):
            # block is like 'CX=6:CY=13:OX=42:OY=9:HDN=0:CLR=-1'
            parts = dict(p.split('=',1) for p in block.split(':') if '=' in p)
            if 'HDN' in parts:
                try: h[code] = int(parts['HDN'])
                except: h[code] = 0
        return h

    style = parse_style(dl_row.get("Style"))
    hdn   = parse_geom_hidden_flags(dl_row.get("Geometry"))

    def is_hidden(slot: str) -> bool:
        return style["hide_all"] or bool(hdn.get(slot, 0))

    # texts from connector row (Series)
    def _s(key: str) -> str:
        val = con_row.get(key, "") if hasattr(con_row, "get") else con_row[key]
        return "" if val is None else str(val)

    if stereotype_text is None:
        stereotype_text = _s("Stereotype")  # often empty/NULL; OK

    return pd.Series({
        # middle labels
        "name_text": _s("Name"),
        "name_hidden": is_hidden("LMT"),
        "stereotype_text": stereotype_text,
        "stereotype_hidden": is_hidden("LMB"),
        # start (source) side
        "start_role_text": _s("SourceRole"),
        "start_role_hidden": is_hidden("LLT"),
        "start_mult_text": _s("SourceCard"),
        "start_mult_hidden": is_hidden("LLB"),
        # end (dest) side
        "end_role_text": _s("DestRole"),
        "end_role_hidden": is_hidden("LRT"),
        "end_mult_text": _s("DestCard"),
        "end_mult_hidden": is_hidden("LRB"),
        # style bits
        "hide_all_labels": style["hide_all"],
        # metadata
        'source' : con_row['Start_Object_ID'],
        'target' : con_row['End_Object_ID']
    })


def parse_connector_decorations(con_row):
    """
    Returns dict with end decorations:
      'triangle' | 'diamond_hollow' | 'diamond_filled' | 'arrow' | 'none'
    """

    def _kv(style_str):
        if not isinstance(style_str, str):
            return {}
        parts = [p.split("=", 1) for p in style_str.split(";") if "=" in p]
        return {k.strip(): v.strip() for k, v in parts}

    # ---- navigability --------------------------------------------------------
    def _nav_value(x):
        s = (str(x) if x is not None else "").strip().lower()
        if s in ("navigable", "true", "1", "yes", "y", "t"):
            return True
        if s in ("non-navigable", "non_navigable", "false", "0", "no", "n", "f"):
            return False
        if s in ("unspecified", "", "none", "null"):
            return None
        return None

    def _nav(end_style_dict, explicit_flag):
        # prefer explicit SourceIsNavigable/DestIsNavigable if provided
        v = _nav_value(explicit_flag)
        if v is not None:
            return v
        return _nav_value(end_style_dict.get("Navigable"))

    # ---- aggregation/composition (diamonds) ----------------------------------
    def _agg_from_style(style_dict):
        s = (style_dict.get("Aggregation") or "").strip().lower()
        if s in ("2", "composite", "filled"):
            return "composite"      # filled diamond
        if s in ("1", "shared", "hollow"):
            return "shared"         # hollow diamond
        return "none"

    def _agg_from_containment(val):
        s = (str(val) if val is not None else "").strip().lower()
        if s in ("composite", "composition"):
            return "composite"
        if s in ("shared", "aggregation", "agg"):
            return "shared"
        return "none"

    def _agg_from_isagg(flag):
        # EA sometimes uses 0/1/2 here: 0 none, 1 shared, 2 composite
        if flag is None:
            return "none"
        try:
            n = int(flag)
        except Exception:
            n = None
        if n == 2:
            return "composite"
        if n == 1:
            return "shared"
        return "none"

    def _agg_from_type(ctype):
        s = (ctype or "").strip().lower()
        if s in ("composition", "composite"):
            return "composite"
        if s in ("aggregation",):
            return "shared"
        return "none"

    def _diamond(agg_kind):
        return (
            "diamond_filled" if agg_kind == "composite"
            else "diamond_hollow" if agg_kind == "shared"
            else None
        )

    def _shape(is_triangle, agg_kind, has_arrow):
        if is_triangle:
            return "triangle"
        d = _diamond(agg_kind)
        if d:
            return d
        return "arrow" if has_arrow else "none"

    # ---- fields --------------------------------------------------------------
    ctype      = str(con_row.get("Connector_Type", "")).strip()
    direction  = str(con_row.get("Direction", "")).strip().lower()
    src_style  = _kv(con_row.get("SourceStyle"))
    dst_style  = _kv(con_row.get("DestStyle"))

    # navigability (arrows)
    src_nav = _nav(src_style, con_row.get("SourceIsNavigable"))
    dst_nav = _nav(dst_style, con_row.get("DestIsNavigable"))
    src_arrow = (src_nav is True)
    dst_arrow = (dst_nav is True)

    if src_nav is None and dst_nav is None and ctype in ("Association", "Aggregation", "Composition"):
        if direction.startswith("source") and "destination" in direction:
            dst_arrow = True
        elif direction.startswith("destination") and "source" in direction:
            src_arrow = True
        elif "bi-directional" in direction or "bi" in direction:
            src_arrow = dst_arrow = True

    # triangles for generalization-like connectors (dest end)
    src_tri = False
    dst_tri = (ctype in ("Generalization", "Realization", "Substitution"))

    # diamonds: prefer explicit signals in order: style → containment → IsAggregate → type
    src_agg = _agg_from_style(src_style)
    if src_agg == "none":
        src_agg = _agg_from_containment(con_row.get("SourceContainment"))
    if src_agg == "none":
        src_agg = _agg_from_isagg(con_row.get("SourceIsAggregate"))

    dst_agg = _agg_from_style(dst_style)
    if dst_agg == "none":
        dst_agg = _agg_from_containment(con_row.get("DestContainment"))
    if dst_agg == "none":
        dst_agg = _agg_from_isagg(con_row.get("DestIsAggregate"))

    if src_agg == "none" and dst_agg == "none":
        inferred = _agg_from_type(ctype)
        if inferred != "none":
            if "destination" in direction or direction in ("", "unspecified"):
                dst_agg = inferred
            elif "source" in direction:
                src_agg = inferred
            else:
                dst_agg = inferred

    return {
        "c_source_decor": _shape(src_tri, src_agg, src_arrow),
        "c_dest_decor":   _shape(dst_tri, dst_agg, dst_arrow),
    }



# Everything below here is related to parsing connector colors
import re
import pandas as pd
from typing import Dict, Optional

import pandas as pd
from typing import Dict

def _col(df: pd.DataFrame, *names):
    """Return the first existing column name from candidates, else None."""
    for n in names:
        if n in df.columns: return n
    return None

def build_instance_color_map_from_tags(uml_data, diagram_id: int, tag_name: str = "ravens_color") -> Dict[int, str]:
    """
    Build {InstanceID: color_string} for one diagram using ONLY t_connectortag.
    - InstanceID lives in the index of uml_data.diagramlinks (as required).
    - Connector ID comes from diagramlinks.ConnectorID / Connector_ID.
    - Tag table provides (ConnectorID|ElementID) -> VALUE (e.g., "red").
    """
    # 1) diagramlinks -> pairs (InstanceID, ConnectorID) for this diagram
    dl = getattr(uml_data, "diagramlinks", pd.DataFrame())
    if dl.empty: return {}

    did_col = _col(dl, "DiagramID", "Diagram_ID")
    cid_col = _col(dl, "ConnectorID", "Connector_ID")
    if not did_col or not cid_col: return {}

    sub = dl.loc[dl[did_col] == diagram_id].copy()
    if sub.empty: return {}

    pairs = pd.DataFrame({
        "InstanceID": pd.to_numeric(sub.index, errors="coerce"),
        "ConnectorID": pd.to_numeric(sub[cid_col], errors="coerce"),
    }).dropna().astype(int)

    # 2) t_connectortag -> map (ConnectorID) -> VALUE
    tags = getattr(uml_data, "connectortag", None)
    if tags is None or not isinstance(tags, pd.DataFrame) or tags.empty:
        tags = getattr(uml_data, "connectortags", pd.DataFrame())
    if tags.empty:
        return {iid: "default" for iid in pairs["InstanceID"].tolist()}

    key_col  = _col(tags, "ConnectorID", "ElementID")   # your DB uses ElementID for connector id
    val_col  = _col(tags, "VALUE", "Value")
    name_col = _col(tags, "Property", "Name")
    if not key_col or not val_col or not name_col:
        return {iid: "default" for iid in pairs["InstanceID"].tolist()}

    t = tags.loc[tags[name_col].astype(str).str.lower() == tag_name.lower(), [key_col, val_col]].copy()
    if t.empty:
        return {iid: "default" for iid in pairs["InstanceID"].tolist()}

    t[key_col] = pd.to_numeric(t[key_col], errors="coerce")
    t = t.dropna(subset=[key_col]).astype({key_col: int})
    t[val_col] = t[val_col].astype(str).str.strip()

    # last value per connector wins
    tag_by_cid = t.groupby(key_col, as_index=True)[val_col].last()

    # 3) join and build output
    merged = pairs.merge(tag_by_cid.rename("Color"), left_on="ConnectorID", right_index=True, how="left")
    out = {int(r.InstanceID): (r.Color if isinstance(r.Color, str) and r.Color != "" else "default")
           for r in merged.itertuples(index=False)}
    return out


def connector_directionality_from_labels(
    label_info: pd.Series,
    *,
    connector_type: str,
    s_id: Any,
    e_id: Any):
    """
    Decide direction(s) and label(s) for a connector instance.

    Returns a list of (u, v, label_text_or_None).

    Rules:
      • If connector_type ∈ {'Generalization','Aggregation'} → force one-way: s_id → e_id.
        - Label preference: end label if visible, else start label if visible, else None.
      • Otherwise, flow goes toward the visible endpoint label.
        - If no endpoint labels are visible OR hide_all_labels=True → bidirectional, no labels.
        - If only start label visible → (target → source) with that start label.
        - If only end label visible   → (source → target) with that end label.
        - If both visible             → add both directions with their respective labels.
    """
    def _label_visible(text, hidden) -> bool:
        """Visible iff not hidden AND text is non-empty (treat literal 'nan' as empty)."""
        if bool(hidden):
            return False
        if text is None or (isinstance(text, float) and pd.isna(text)):
            return False
        s = str(text).strip()
        return s != "" and s.lower() != "nan"
    
    ONE_WAY_TYPES = {"Generalization"}

    # Forced one-way types
    if connector_type in ONE_WAY_TYPES:
        end_text   = label_info.get("end_role_text")
        end_vis    = _label_visible(end_text,   label_info.get("end_role_hidden", False))
        start_text = label_info.get("start_role_text")
        start_vis  = _label_visible(start_text, label_info.get("start_role_hidden", False))
        lbl = (str(end_text).strip() if end_vis
               else (str(start_text).strip() if start_vis else None))
        return [(s_id, e_id, lbl)]

    # Label-driven direction
    if bool(label_info.get("hide_all_labels", False)):
        return [(s_id, e_id, None), (e_id, s_id, None)]

    start_text = label_info.get("start_role_text")
    end_text   = label_info.get("end_role_text")
    start_vis  = _label_visible(start_text, label_info.get("start_role_hidden", False))
    end_vis    = _label_visible(end_text,   label_info.get("end_role_hidden", False))

    if not start_vis and not end_vis:
        return [(s_id, e_id, None), (e_id, s_id, None)]
    if start_vis and not end_vis:
        return [(e_id, s_id, str(start_text).strip())]
    if end_vis and not start_vis:
        return [(s_id, e_id, str(end_text).strip())]
    # both visible → bidirectional with each side's label
    return [(s_id, e_id, str(end_text).strip()),
            (e_id, s_id, str(start_text).strip())]


def parse_multiplicity(label_info):
    """Return {'start_mult': str, 'end_mult': str}; empty string when hidden/none-ish."""
    hide_all = bool(label_info.get("hide_all_labels", False))

    def _clean(val):
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return ""
        s = str(val).strip()
        return "" if s.lower() in {"", "nan", "none", "null"} else s

    def _pick(txt_key: str, hid_key: str):
        if hide_all or bool(label_info.get(hid_key, False)):
            return ""
        return _clean(label_info.get(txt_key))

    return {
        "start_mult": _pick("start_mult_text", "start_mult_hidden"),
        "end_mult":   _pick("end_mult_text",   "end_mult_hidden"),
    }


def orient_edge_attrs_for_direction(base_attrs, *,
                                     u, v,            # the directed edge you’re adding (from connector_directionality_from_labels)
                                     s_id, e_id,      # connector’s canonical Start/End from t_connectors
                                     start_mult, end_mult,
                                     objects_df):
    """
    Return a copy of base_attrs with Start/End names and multiplicities
    re-mapped to match the actual direction u -> v.
    """
    out = base_attrs.copy()

    # 1) Names aligned to direction
    out["Start_Object"] = objects_df.loc[u]["Name"]
    out["End_Object"]   = objects_df.loc[v]["Name"]

    # 2) Multiplicity aligned to direction
    # If u==s_id, v==e_id: keep as-is. If flipped: swap.
    if u == s_id and v == e_id:
        out["start_mult"] = start_mult
        out["end_mult"]   = end_mult
    elif u == e_id and v == s_id:
        out["start_mult"] = end_mult
        out["end_mult"]   = start_mult
    else:
        # Fallback (shouldn’t happen unless nodes were remapped): pick by side match
        out["start_mult"] = start_mult if u == s_id else end_mult
        out["end_mult"]   = end_mult   if v == e_id else start_mult

    return out


def to_pandas_nodelist(G):
    """
    Convert a NetworkX graph's nodes (with attributes) into a pandas DataFrame.
    
    Parameters
    ----------
    G : networkx.Graph
        The input graph.
    
    Returns
    -------
    pandas.DataFrame
        DataFrame where each row is a node, with one column for the node id
        and one column per node attribute.
    """
    # Extract node data
    node_data = []
    for n, attrs in G.nodes(data=True):
        row = {"node": n}
        row.update(attrs)  # merge in attributes
        node_data.append(row)

    return pd.DataFrame(node_data)
