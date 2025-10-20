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


class UMLInclusions:
    """
    Mirrors UMLExclusions but for allow-lists.
    Empty sets mean 'no restriction' for that kind.
    """
    def __init__(
        self,
        object_ids: set[int] | None = None,
        connector_ids: set[int] | None = None,
        package_ids: set[int] | None = None,
        diagram_ids: set[int] | None = None,
        link_instance_ids: set[int] | None = None,
        obj_instance_ids: set[int] | None = None,
    ):
        self.object_ids        = set(int(x) for x in (object_ids or set()))
        self.connector_ids     = set(int(x) for x in (connector_ids or set()))
        self.package_ids       = set(int(x) for x in (package_ids or set()))
        self.diagram_ids       = set(int(x) for x in (diagram_ids or set()))
        self.link_instance_ids = set(int(x) for x in (link_instance_ids or set()))
        self.obj_instance_ids  = set(int(x) for x in (obj_instance_ids or set()))

    @classmethod
    def from_dict(cls, d: dict):
        return cls(
            object_ids        = d.get("Object_ID"),
            connector_ids     = d.get("Connector_ID"),
            package_ids       = d.get("Package_ID"),
            diagram_ids       = d.get("Diagram_ID"),
            link_instance_ids = d.get("link_Instance_ID"),
            obj_instance_ids  = d.get("obj_Instance_ID"),
        )

    def allow(self, kind: str, id_value: int) -> bool:
        """
        Empty set => allow all. Otherwise require membership.
        kind ∈ {'object','connector','package','diagram','link_instance','obj_instance'}
        """
        sets = {
            "object":        self.object_ids,
            "connector":     self.connector_ids,
            "package":       self.package_ids,
            "diagram":       self.diagram_ids,
            "link_instance": self.link_instance_ids,
            "obj_instance":  self.obj_instance_ids,
        }
        s = sets.get(kind)
        if s is None:
            raise ValueError(f"Unknown inclusion kind: {kind!r}")
        return (len(s) == 0) or (int(id_value) in s)


def get_inclusions(uml_data, package=None) -> UMLInclusions:
    def col(df, *names):
        for n in names:
            if isinstance(df, pd.DataFrame) and n in df.columns:
                return n
        raise KeyError(f"None of {names} in {list(getattr(df, 'columns', []))}")

    pkg_ids = package_IDs(package_graph(uml_data), package)
    pkg_ids = set(int(x) for x in pkg_ids)

    d_pkg_col = col(uml_data.diagrams, "Package_ID")
    diagram_ids = set(
        uml_data.diagrams.index[uml_data.diagrams[d_pkg_col].isin(pkg_ids)].tolist()
    )

    dl = uml_data.diagramlinks
    dl_did = col(dl, "DiagramID", "Diagram_ID")
    dl_cid = col(dl, "ConnectorID", "Connector_ID")
    link_instance_ids = set(int(i) for i in dl.index[dl[dl_did].isin(diagram_ids)].tolist())
    connector_ids = set(int(x) for x in dl[dl_cid][dl[dl_did].isin(diagram_ids)].tolist())

    do = uml_data.diagramobjects
    do_did = col(do, "Diagram_ID", "DiagramID")
    do_oid = col(do, "Object_ID", "ObjectID", "ElementID")
    obj_instance_ids = set(int(i) for i in do.index[do[do_did].isin(diagram_ids)].tolist())
    object_ids = set(int(x) for x in do[do_oid][do[do_did].isin(diagram_ids)].tolist())

    return UMLInclusions(
        object_ids=object_ids,
        connector_ids=connector_ids,
        package_ids=pkg_ids,
        diagram_ids=diagram_ids,
        link_instance_ids=link_instance_ids,
        obj_instance_ids=obj_instance_ids,
    )


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
