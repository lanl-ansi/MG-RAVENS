from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

import pandas as pd

from .data import UMLData


_INF_MKT_RX = re.compile(r"^(?:Inf[A-Z]|Mkt[A-Z])")


def matches_name_prefix(name: str, prefix: str) -> bool:
    if prefix in {"Inf", "Mkt"}:
        return bool(re.match(rf"^{prefix}[A-Z]", str(name)))
    return str(name).startswith(prefix)


@dataclass
class UMLSelection:
    uml_data: UMLData
    packages: Iterable[str] | None = None
    exclude_inf_mkt_initial: bool = True
    exclude_hidden_links: bool = True
    hidden_scope_path: str | None = "SimplifiedDiagrams"
    drop_objects_without_visible_generalization: bool = True

    allowed_packages: set[int] = field(init=False, default_factory=set)
    allowed_diagrams: set[int] = field(init=False, default_factory=set)
    allowed_objects: set[int] = field(init=False, default_factory=set)
    allowed_connectors: set[int] = field(init=False, default_factory=set)
    allowed_link_instances: set[int] = field(init=False, default_factory=set)

    def __post_init__(self):
        self._ensure_indexes()
        self._build()

    @classmethod
    def from_exclusions(cls, uml_data: UMLData, exclusions) -> UMLSelection:
        selection = cls.__new__(cls)
        selection.uml_data = uml_data
        selection.packages = None
        selection.exclude_inf_mkt_initial = False
        selection.exclude_hidden_links = False
        selection.hidden_scope_path = None
        selection.drop_objects_without_visible_generalization = False
        selection.allowed_packages = set()
        selection.allowed_diagrams = set()
        selection.allowed_objects = set()
        selection.allowed_connectors = set()
        selection.allowed_link_instances = set()
        selection._ensure_indexes()
        selection._build_from_exclusions(exclusions)
        return selection

    def allow(self, kind: str, id_value: int) -> bool:
        values = {
            "package": self.allowed_packages,
            "diagram": self.allowed_diagrams,
            "object": self.allowed_objects,
            "connector": self.allowed_connectors,
            "link_instance": self.allowed_link_instances,
        }.get(str(kind).strip().lower())
        return True if values is None else int(id_value) in values

    @staticmethod
    def _numeric(series):
        return pd.to_numeric(series, errors="coerce").astype("Int64")

    @classmethod
    def _column(cls, df: pd.DataFrame, *names):
        if not isinstance(df, pd.DataFrame) or df.empty:
            return pd.Series([], dtype="Int64")
        for name in names:
            if name in df.columns:
                return cls._numeric(df[name])
        if df.index.name in names:
            return cls._numeric(df.index.to_series())
        return pd.Series([], dtype="Int64")

    def _ensure_indexes(self):
        def set_index(df, column):
            if isinstance(df, pd.DataFrame) and column in df.columns and df.index.name != column:
                return df.set_index(column, drop=False)
            return df

        uml = self.uml_data
        uml.packages = set_index(getattr(uml, "packages", pd.DataFrame()), "Package_ID")
        uml.diagrams = set_index(getattr(uml, "diagrams", pd.DataFrame()), "Diagram_ID")
        uml.objects = set_index(getattr(uml, "objects", pd.DataFrame()), "Object_ID")
        uml.connectors = set_index(getattr(uml, "connectors", pd.DataFrame()), "Connector_ID")
        uml.diagramlinks = getattr(uml, "diagramlinks", pd.DataFrame())
        uml.diagramobjects = getattr(uml, "diagramobjects", pd.DataFrame())

    def _build_from_exclusions(self, exclusions):
        uml = self.uml_data
        excluded_packages = set(exclusions.package_ids)
        excluded_objects = set(exclusions.object_ids)

        self.allowed_packages = set(map(int, self._column(uml.packages, "Package_ID").dropna())) - excluded_packages
        self.allowed_diagrams = set(map(int, self._column(uml.diagrams, "Diagram_ID", "DiagramID").dropna()))

        object_ids = self._column(uml.objects, "Object_ID")
        object_packages = self._numeric(uml.objects.get("Package_ID", pd.Series(pd.NA, index=uml.objects.index)))
        keep_objects = object_packages.isin(self.allowed_packages) & ~object_ids.isin(excluded_objects)
        self.allowed_objects = set(map(int, object_ids.loc[keep_objects].dropna()))

        start_ids = self._column(uml.connectors, "Start_Object_ID", "StartObjectID")
        end_ids = self._column(uml.connectors, "End_Object_ID", "EndObjectID")
        connector_ids = self._column(uml.connectors, "Connector_ID", "ConnectorID")
        keep_connectors = start_ids.isin(self.allowed_objects) & end_ids.isin(self.allowed_objects)
        self.allowed_connectors = set(map(int, connector_ids.loc[keep_connectors].dropna()))
        self.allowed_link_instances = self._link_instances(self.allowed_diagrams, self.allowed_connectors)

    def _build(self):
        self._build_packages()
        self._build_diagrams()
        self._build_objects()
        self._build_connectors()
        self.allowed_link_instances = self._link_instances(
            self.allowed_diagrams,
            self.allowed_connectors,
            visible_only=self.exclude_hidden_links,
        )

    def _build_packages(self):
        packages = self.uml_data.packages
        if not isinstance(packages, pd.DataFrame) or packages.empty:
            return

        package_ids = self._column(packages, "Package_ID")
        if self.packages is None:
            self.allowed_packages = set(map(int, package_ids.dropna()))
            return

        names = packages.get("Name", pd.Series("", index=packages.index)).astype(str).str.casefold()
        paths = packages.get("Path", pd.Series("", index=packages.index)).astype(str).str.casefold()
        keep = pd.Series(False, index=packages.index)
        for package in self.packages:
            value = str(package).strip().casefold()
            if value:
                keep |= names.eq(value) | paths.str.contains(re.escape(value), na=False)
        self.allowed_packages = set(map(int, package_ids.loc[keep].dropna()))

    def _build_diagrams(self):
        diagrams = self.uml_data.diagrams
        if not isinstance(diagrams, pd.DataFrame) or diagrams.empty:
            return

        package_ids = self._numeric(diagrams.get("Package_ID", pd.Series(pd.NA, index=diagrams.index)))
        keep = package_ids.isin(self.allowed_packages)
        if self.exclude_inf_mkt_initial:
            names = diagrams.get("Name", pd.Series("", index=diagrams.index)).astype(str)
            keep &= ~names.str.match(_INF_MKT_RX.pattern, na=False)
        self.allowed_diagrams = set(map(int, self._column(diagrams, "Diagram_ID", "DiagramID").loc[keep].dropna()))

    def _build_objects(self):
        objects = self.uml_data.objects
        diagramobjects = self.uml_data.diagramobjects
        if not isinstance(objects, pd.DataFrame) or objects.empty:
            return

        object_ids = self._column(objects, "Object_ID")
        if isinstance(diagramobjects, pd.DataFrame) and not diagramobjects.empty and self.allowed_diagrams:
            diagram_column = "Diagram_ID" if "Diagram_ID" in diagramobjects.columns else "DiagramID"
            object_column = "Object_ID" if "Object_ID" in diagramobjects.columns else "ObjectID"
            keep = self._numeric(diagramobjects[diagram_column]).isin(self.allowed_diagrams)
            self.allowed_objects = set(map(int, self._numeric(diagramobjects.loc[keep, object_column]).dropna()))
        else:
            self.allowed_objects = set(map(int, object_ids.dropna()))

        if self.exclude_inf_mkt_initial:
            names = objects.get("Name", pd.Series("", index=objects.index)).astype(str)
            kept_ids = set(map(int, object_ids.loc[~names.str.match(_INF_MKT_RX.pattern, na=False)].dropna()))
            self.allowed_objects &= kept_ids

    def _scope_diagrams(self):
        if not self.hidden_scope_path:
            return self.allowed_diagrams

        packages = self.uml_data.packages
        diagrams = self.uml_data.diagrams
        value = str(self.hidden_scope_path).strip().casefold()
        names = packages.get("Name", pd.Series("", index=packages.index)).astype(str).str.casefold()
        paths = packages.get("Path", pd.Series("", index=packages.index)).astype(str).str.casefold()
        scope_packages = set(map(int, self._column(packages.loc[names.str.contains(re.escape(value), na=False) | paths.str.contains(re.escape(value), na=False)], "Package_ID").dropna()))
        diagram_packages = self._numeric(diagrams.get("Package_ID", pd.Series(pd.NA, index=diagrams.index)))
        scope_diagrams = set(map(int, self._column(diagrams, "Diagram_ID", "DiagramID").loc[diagram_packages.isin(scope_packages)].dropna()))
        return (scope_diagrams & self.allowed_diagrams) or self.allowed_diagrams

    def _build_connectors(self):
        connectors = self.uml_data.connectors
        if not isinstance(connectors, pd.DataFrame) or connectors.empty or not self.allowed_objects:
            return

        connector_ids = self._column(connectors, "Connector_ID", "ConnectorID")
        start_ids = self._column(connectors, "Start_Object_ID", "StartObjectID")
        end_ids = self._column(connectors, "End_Object_ID", "EndObjectID")
        types = connectors.get("Connector_Type", connectors.get("Type", pd.Series("", index=connectors.index))).astype(str).str.casefold()
        endpoints_allowed = start_ids.isin(self.allowed_objects) & end_ids.isin(self.allowed_objects)

        hidden_connectors = set()
        visible_connectors = set()
        diagramlinks = self.uml_data.diagramlinks
        if isinstance(diagramlinks, pd.DataFrame) and not diagramlinks.empty:
            diagram_column = "DiagramID" if "DiagramID" in diagramlinks.columns else "Diagram_ID"
            connector_column = "ConnectorID" if "ConnectorID" in diagramlinks.columns else "Connector_ID"
            in_scope = self._numeric(diagramlinks[diagram_column]).isin(self._scope_diagrams())
            hidden = diagramlinks.get("Hidden", False) == True
            hidden_connectors = set(map(int, self._numeric(diagramlinks.loc[in_scope & hidden, connector_column]).dropna()))
            visible_connectors = set(map(int, self._numeric(diagramlinks.loc[in_scope & ~hidden, connector_column]).dropna()))

        generalizations = types.eq("generalization") & endpoints_allowed
        associations = types.isin({"association", "aggregation", "composition"}) & endpoints_allowed
        generalization_ids = set(map(int, connector_ids.loc[generalizations].dropna()))
        association_ids = set(map(int, connector_ids.loc[associations].dropna()))

        if self.exclude_hidden_links:
            generalization_ids -= hidden_connectors - visible_connectors
            association_ids &= visible_connectors

        if self.drop_objects_without_visible_generalization and generalization_ids:
            generalization_rows = connector_ids.isin(generalization_ids)
            endpoints = set(map(int, start_ids.loc[generalization_rows].dropna()))
            endpoints |= set(map(int, end_ids.loc[generalization_rows].dropna()))
            self.allowed_objects &= endpoints

            association_rows = connector_ids.isin(association_ids)
            association_rows &= start_ids.isin(self.allowed_objects) & end_ids.isin(self.allowed_objects)
            association_ids = set(map(int, connector_ids.loc[association_rows].dropna()))

        self.allowed_connectors = generalization_ids | association_ids

    def _link_instances(self, diagram_ids, connector_ids, visible_only=False):
        diagramlinks = self.uml_data.diagramlinks
        if not isinstance(diagramlinks, pd.DataFrame) or diagramlinks.empty:
            return set()

        diagram_column = "DiagramID" if "DiagramID" in diagramlinks.columns else "Diagram_ID"
        connector_column = "ConnectorID" if "ConnectorID" in diagramlinks.columns else "Connector_ID"
        keep = self._numeric(diagramlinks[diagram_column]).isin(diagram_ids)
        keep &= self._numeric(diagramlinks[connector_column]).isin(connector_ids)
        if visible_only:
            keep &= diagramlinks.get("Hidden", False) == False

        instances = set(map(int, self._numeric(diagramlinks.index.to_series()).loc[keep].dropna()))
        if "InstanceID" in diagramlinks.columns:
            instances |= set(map(int, self._numeric(diagramlinks.loc[keep, "InstanceID"]).dropna()))
        return instances
