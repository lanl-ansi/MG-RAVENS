import pandas as pd
import networkx as nx
from ravens.uml import UMLData


class UMLExclusions:
    def __init__(self, uml_data: UMLData | None = None):
        if uml_data is None:
            uml_data = UMLData()

        self.uml_data = uml_data
        self.package_ids = []
        self.object_ids = []

    def exclude_by_name_startswith(self, exclusions: list, skip_object_exclusion: bool = False, skip_package_exclusion: bool = False):
        lambda_func = lambda x: any(str(x.Name).startswith(k) for k in exclusions)

        return self.exclude_by_lambda_function(lambda_func, skip_object_exclusion=skip_object_exclusion, skip_package_exclusion=skip_package_exclusion)

    def exclude_by_lambda_function(self, lambda_func, skip_object_exclusion: bool = False, skip_package_exclusion: bool = False):
        if not skip_package_exclusion:
            self._build_package_exclusions(lambda_func)
        if not skip_object_exclusion:
            self._build_object_exclusions(lambda_func)

        return self

    def _build_package_exclusions(self, lambda_func):
        self.package_ids = [pkg.Index for pkg in self.uml_data.packages.itertuples() if lambda_func(pkg)]

    def _build_object_exclusions(self, lambda_func):
        self.object_ids = [obj.Index for obj in self.uml_data.objects.itertuples() if lambda_func(obj)] + [obj.Index for p in self.package_ids for obj in self.uml_data.objects[self.uml_data.objects["Package_ID"] == p].itertuples()]


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


if __name__ == "__main__":
    exclusions = UMLExclusions().exclude_by_name_startswith(["Inf", "Mkt"])
