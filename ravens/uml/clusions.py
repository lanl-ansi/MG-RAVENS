from __future__ import annotations
import re
import pandas as pd
import networkx as nx
from typing import Optional, Iterable, Set

from ravens.uml import UMLData


def _col(df: pd.DataFrame, *candidates: str) -> str | None:
    for c in candidates:
        if c in df.columns:
            return c
    return None

class UMLInclusions:
    """
    Auto-populated inclusions:
      • Allowed packages: by name (plus optional subpackages)
      • Allowed diagrams: all diagrams inside allowed packages
      • Allowed objects: objects in allowed packages OR appearing on allowed diagrams
      • Allowed connectors: on allowed diagrams OR with both endpoints allowed
    Name filter (toggle): exclude objects whose Name matches ^(Inf[A-Z]|Mkt[A-Z]).
    Empty allow-sets mean 'no restriction' for that kind.
    """

    def __init__(
        self,
        uml_data,
        packages: Iterable[str] | None = None,          # alias for package_names
        package_names: Iterable[str] | None = None,
        include_subpackages: bool = True,
        exclude_inf_mkt: bool = False,
    ):
        self.uml = uml_data
        self.exclude_inf_mkt = bool(exclude_inf_mkt)
        self._name_rx = re.compile(r'^(Inf[A-Z]|Mkt[A-Z])')

        # Accept either arg name
        if package_names is None and packages is not None:
            package_names = packages

        # ---------- packages ----------
        self._allow_packages: Set[int] = set()
        if package_names:
            base = self._packages_by_name({str(n).strip() for n in package_names})
            subs = self._subpackages_of(base) if include_subpackages else set()
            self._allow_packages = base | subs

        # ---------- diagrams in allowed packages ----------
        self._allow_diagrams: Set[int] = set()
        if self._allow_packages and isinstance(self.uml.diagrams, pd.DataFrame) and not self.uml.diagrams.empty:
            d = self.uml.diagrams
            d_pkg = _col(d, "Package_ID", "PackageID", "PackageId")
            d_id  = _col(d, "Diagram_ID", "DiagramID", "DiagramId")
            if d_pkg and d_id:
                self._allow_diagrams = set(
                    d.loc[d[d_pkg].astype(int).isin(self._allow_packages), d_id].astype(int)
                )

        # ---------- objects: in allowed packages OR on allowed diagrams ----------
        self._allow_objects: Set[int] = set()
        if isinstance(self.uml.objects, pd.DataFrame) and not self.uml.objects.empty:
            o = self.uml.objects
            o_pkg = _col(o, "Package_ID", "PackageID", "PackageId")
            o_id  = _col(o, "Object_ID", "ObjectID", "ElementID", "Element_ID")
            if o_pkg and o_id and self._allow_packages:
                self._allow_objects |= set(
                    o.loc[o[o_pkg].astype(int).isin(self._allow_packages), o_id].astype(int)
                )
            if self._allow_diagrams:
                self._allow_objects |= self._objects_on_diagrams(self._allow_diagrams)

        # ---------- connectors: on allowed diagrams OR both endpoints allowed ----------
        self._allow_connectors: Set[int] = set()
        if self._allow_diagrams:
            self._allow_connectors |= self._connectors_on_diagrams(self._allow_diagrams)
        if isinstance(self.uml.connectors, pd.DataFrame) and not self.uml.connectors.empty and self._allow_objects:
            c = self.uml.connectors
            c_id  = _col(c, "Connector_ID", "ConnectorID", "ConnectorId", "ElementID")
            c_s   = _col(c, "Start_Object_ID", "StartObjectID", "StartElementID")
            c_e   = _col(c, "End_Object_ID", "EndObjectID", "EndElementID")
            if c_id and c_s and c_e:
                both_ok = c.loc[
                    c[c_s].astype(int).isin(self._allow_objects)
                    & c[c_e].astype(int).isin(self._allow_objects),
                    c_id
                ].astype(int)
                self._allow_connectors |= set(both_ok)

    # ---------------- allow API ----------------

    def allow(self, kind: str, id_value: int) -> bool:
        i = int(id_value)
        if kind == "package":
            return (not self._allow_packages) or (i in self._allow_packages)
        if kind == "diagram":
            return (not self._allow_diagrams) or (i in self._allow_diagrams)
        if kind == "connector":
            return (not self._allow_connectors) or (i in self._allow_connectors)
        if kind == "object":
            # scope check
            in_scope = (not self._allow_objects) or (i in self._allow_objects)
            if not in_scope:
                return False
            # optional name filter
            if self.exclude_inf_mkt:
                o = self.uml.objects
                o_id = _col(o, "Object_ID", "ObjectID", "ElementID", "Element_ID")
                o_nm = _col(o, "Name")
                try:
                    if o_id and o_nm:
                        name = str(o.loc[i, o_nm])
                    else:
                        name = ""
                except Exception:
                    name = ""
                if self._name_rx.match(name or ""):
                    return False
            return True
        if kind in ("link_instance", "obj_instance"):
            # gated via diagrams/objects already
            return True
        raise ValueError(f"Unknown inclusion kind: {kind!r}")

    # ---------------- helpers ----------------

    def _packages_by_name(self, names: Set[str]) -> Set[int]:
        if not isinstance(self.uml.packages, pd.DataFrame) or self.uml.packages.empty:
            return set()
        p = self.uml.packages
        p_id  = _col(p, "Package_ID", "PackageID", "PackageId", "ID")
        p_nm  = _col(p, "Name")
        if not p_id or not p_nm:
            return set()
        want = {n.casefold() for n in names}
        hits = p.loc[p[p_nm].astype(str).str.casefold().isin(want)]
        return set(hits[p_id].astype(int))

    def _subpackages_of(self, roots: Set[int]) -> Set[int]:
        if not isinstance(self.uml.packages, pd.DataFrame) or self.uml.packages.empty or not roots:
            return set()
        p = self.uml.packages
        p_id = _col(p, "Package_ID", "PackageID", "PackageId", "ID")
        p_parent = _col(p, "Parent_ID", "ParentID", "ParentId")
        if not p_id or not p_parent:
            return set()
        pk = p[[p_id, p_parent]].dropna()
        pk = pk.astype({p_id: int, p_parent: int})
        parents = set(roots)
        out: Set[int] = set()
        changed = True
        while changed:
            changed = False
            children = set(pk.loc[pk[p_parent].isin(parents), p_id].astype(int))
            children -= out
            if children:
                out |= children
                parents = children
                changed = True
        return out

    def _objects_on_diagrams(self, diagram_ids: Set[int]) -> Set[int]:
        if not isinstance(self.uml.diagramobjects, pd.DataFrame) or self.uml.diagramobjects.empty or not diagram_ids:
            return set()
        d = self.uml.diagramobjects
        d_id = _col(d, "Diagram_ID", "DiagramID", "DiagramId")
        o_id = _col(d, "Object_ID", "ObjectID", "ElementID", "Element_ID")
        if not d_id or not o_id:
            return set()
        return set(d.loc[d[d_id].astype(int).isin(diagram_ids), o_id].astype(int))

    def _connectors_on_diagrams(self, diagram_ids: Set[int]) -> Set[int]:
        if not isinstance(self.uml.diagramlinks, pd.DataFrame) or self.uml.diagramlinks.empty or not diagram_ids:
            return set()
        dl = self.uml.diagramlinks
        d_id  = _col(dl, "Diagram_ID", "DiagramID", "DiagramId")
        c_id  = _col(dl, "Connector_ID", "ConnectorID", "ConnectorId", "ElementID")
        if not d_id or not c_id:
            return set()
        return set(dl.loc[dl[d_id].astype(int).isin(diagram_ids), c_id].astype(int))


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

if __name__ == "__main__":
    # Example: exclusions class (unchanged)
    exclusions = UMLExclusions().exclude_by_name_startswith(["Inf", "Mkt"])

    # Example: inclusions built from uml_data with name prefix filter ON
    # inc = UMLInclusions.get_inclusions(UMLData(), package="RAVENS", exclude_inf_mkt_caps=True)
