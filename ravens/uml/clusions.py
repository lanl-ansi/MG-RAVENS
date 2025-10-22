# clusions.py
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Iterable, Optional, Set, Dict
import pandas as pd

from ravens.uml import UMLData

_NAME_EXCLUDE_RX = re.compile(r'^(?:Inf[A-Z]|Mkt[A-Z])')

def _as_series(df: pd.DataFrame, col: str) -> pd.Series:
    if df is None or df.empty:
        return pd.Series([], dtype="Int64")
    if col in df.columns:
        return pd.to_numeric(df[col], errors="coerce").astype("Int64")
    if df.index.name == col:
        return pd.to_numeric(df.index.to_series(), errors="coerce").astype("Int64")
    return pd.Series([], dtype="Int64")

@dataclass
class UMLInclusions:
    uml_data: UMLData
    packages: Optional[Iterable[str]] = None
    exclude_inf_mkt_initial: bool = False
    auto_apply: bool = True

    # filled on init
    allowed_packages: Set[int] = None
    allowed_diagrams: Set[int] = None
    allowed_objects: Set[int] = None
    allowed_connectors: Set[int] = None
    allowed_link_instances: Set[int] = None

    filtered_uml_data: UMLData = None  # subset view you can pass straight to graph builds

    def __post_init__(self):
        self._compute_allowed_sets()
        if self.auto_apply:
            self.filtered_uml_data = self.apply()

    # ---------- public helpers used by graph code (if needed) ----------
    def allow(self, kind: str, id_value: int) -> bool:
        k = kind.strip().lower()
        if k == "package":
            return int(id_value) in self.allowed_packages
        if k == "diagram":
            return int(id_value) in self.allowed_diagrams
        if k == "object":
            return int(id_value) in self.allowed_objects
        if k == "connector":
            return int(id_value) in self.allowed_connectors
        if k == "link_instance":
            return int(id_value) in self.allowed_link_instances
        return True

    # ---------- core ----------
    def _compute_allowed_sets(self):
        uml = self.uml_data

        # 1) packages by name (if provided)
        if self.packages:
            want = {str(x).strip() for x in self.packages if str(x).strip()}
            pkg_df = getattr(uml, "packages", pd.DataFrame())
            hits = pkg_df.loc[pkg_df["Name"].astype(str).isin(want)] if not pkg_df.empty else pd.DataFrame()
            self.allowed_packages = set(int(x) for x in _as_series(hits, "Package_ID").dropna().tolist())
        else:
            # if no package restriction, allow all packages that exist
            self.allowed_packages = set(int(x) for x in _as_series(getattr(uml, "packages", pd.DataFrame()), "Package_ID").dropna().tolist())

        # 2) diagrams in those packages
        dia_df = getattr(uml, "diagrams", pd.DataFrame())
        if dia_df.empty:
            self.allowed_diagrams = set()
        else:
            dser = _as_series(dia_df, "Diagram_ID")
            # filter by Package_ID ∈ allowed_packages
            keep = dia_df["Package_ID"].astype("Int64").isin(self.allowed_packages)
            self.allowed_diagrams = set(int(x) for x in dser[keep].dropna().tolist())

        # 3) objects appearing on those diagrams (diagramobjects table)
        do_df = getattr(uml, "diagramobjects", pd.DataFrame())
        if do_df.empty:
            objs_on_diagrams = set()
        else:
            did_col = "Diagram_ID" if "Diagram_ID" in do_df.columns else "DiagramID"
            oid_col = "Object_ID" if "Object_ID" in do_df.columns else "ObjectID"
            if did_col not in do_df.columns or oid_col not in do_df.columns:
                objs_on_diagrams = set()
            else:
                keep = pd.to_numeric(do_df[did_col], errors="coerce").astype("Int64").isin(self.allowed_diagrams)
                objs_on_diagrams = set(int(x) for x in pd.to_numeric(do_df.loc[keep, oid_col], errors="coerce").dropna().astype(int).tolist())

        # optionally remove InfX/MktX by name at this stage
        if self.exclude_inf_mkt_initial and objs_on_diagrams:
            obj_df = getattr(uml, "objects", pd.DataFrame())
            if not obj_df.empty:
                names = obj_df.loc[obj_df.index.isin(objs_on_diagrams), "Name"].astype(str)
                block = set(int(i) for i, nm in names.items() if _NAME_EXCLUDE_RX.match(nm))
                objs_on_diagrams -= block

        self.allowed_objects = objs_on_diagrams

        # 4) connectors
        # For H (Generalization): keep connector if both endpoints are allowed objects and type is Generalization.
        # For A (Association-like): we ALSO require a diagramlink into an allowed diagram, and keep only those connector IDs.
        con_df = getattr(uml, "connectors", pd.DataFrame())
        if con_df.empty:
            self.allowed_connectors = set()
        else:
            # endpoints
            s = pd.to_numeric(con_df.get("Start_Object_ID"), errors="coerce").astype("Int64")
            e = pd.to_numeric(con_df.get("End_Object_ID"), errors="coerce").astype("Int64")
            ctype = con_df.get("Connector_Type").astype(str)

            # connectors that appear on allowed diagrams (through diagramlinks)
            dl_df = getattr(uml, "diagramlinks", pd.DataFrame())
            if not dl_df.empty:
                cid_col = "Connector_ID" if "Connector_ID" in dl_df.columns else ("ConnectorID" if "ConnectorID" in dl_df.columns else None)
                did_col = "Diagram_ID"   if "Diagram_ID"   in dl_df.columns else ("DiagramID"   if "DiagramID"   in dl_df.columns else None)
            else:
                cid_col = did_col = None

            links_in_allowed = set()
            if cid_col and did_col:
                keep = pd.to_numeric(dl_df[did_col], errors="coerce").astype("Int64").isin(self.allowed_diagrams)
                links_in_allowed = set(int(x) for x in pd.to_numeric(dl_df.loc[keep, cid_col], errors="coerce").dropna().astype(int).tolist())

            # Association-like ⇒ must be in links_in_allowed AND both endpoints allowed
            assoc_mask = ctype.isin({"Association", "Aggregation", "Composition"})
            assoc_ids = set(int(i) for i in _as_series(con_df[assoc_mask], "Connector_ID").tolist())
            assoc_ids = {cid for cid in assoc_ids if cid in links_in_allowed}
            assoc_ids = {
                cid for cid in assoc_ids
                if int(s.loc[cid]) in self.allowed_objects and int(e.loc[cid]) in self.allowed_objects
            }

            # Generalization ⇒ both endpoints allowed
            gen_mask = (ctype == "Generalization")
            gen_ids = set(int(i) for i in _as_series(con_df[gen_mask], "Connector_ID").tolist())
            gen_ids = {
                cid for cid in gen_ids
                if int(s.loc[cid]) in self.allowed_objects and int(e.loc[cid]) in self.allowed_objects
            }

            self.allowed_connectors = assoc_ids | gen_ids

        # 5) link instances (diagramlinks rows that point to allowed diagrams AND allowed connectors)
        dl_df = getattr(uml, "diagramlinks", pd.DataFrame())
        if not dl_df.empty and self.allowed_diagrams and self.allowed_connectors:
            cid_col = "Connector_ID" if "Connector_ID" in dl_df.columns else ("ConnectorID" if "ConnectorID" in dl_df.columns else None)
            did_col = "Diagram_ID"   if "Diagram_ID"   in dl_df.columns else ("DiagramID"   if "DiagramID"   in dl_df.columns else None)
            if cid_col and did_col:
                keep = (
                    pd.to_numeric(dl_df[did_col], errors="coerce").astype("Int64").isin(self.allowed_diagrams)
                    & pd.to_numeric(dl_df[cid_col], errors="coerce").astype("Int64").isin(self.allowed_connectors)
                )
                self.allowed_link_instances = set(int(i) for i in _as_series(dl_df[keep], dl_df.index.name or "InstanceID").dropna().tolist())
            else:
                self.allowed_link_instances = set()
        else:
            self.allowed_link_instances = set()

    def apply(self) -> UMLData:
        """Return a *new* UMLData containing only allowed rows (packages/diagrams/objects/connectors/links)."""
        uml = self.uml_data
        out = UMLData()

        # Packages (only allowed)
        pk_df = getattr(uml, "packages", pd.DataFrame())
        out.packages = pk_df.loc[pk_df.index.isin(self.allowed_packages)].copy() if not pk_df.empty else pk_df

        # Diagrams
        di_df = getattr(uml, "diagrams", pd.DataFrame())
        out.diagrams = di_df.loc[di_df.index.isin(self.allowed_diagrams)].copy() if not di_df.empty else di_df

        # Objects
        ob_df = getattr(uml, "objects", pd.DataFrame())
        out.objects = ob_df.loc[ob_df.index.isin(self.allowed_objects)].copy() if not ob_df.empty else ob_df

        # Connectors
        co_df = getattr(uml, "connectors", pd.DataFrame())
        out.connectors = co_df.loc[co_df.index.isin(self.allowed_connectors)].copy() if not co_df.empty else co_df

        # DiagramObjects
        do_df = getattr(uml, "diagramobjects", pd.DataFrame())
        if not do_df.empty and self.allowed_diagrams and self.allowed_objects:
            did_col = "Diagram_ID" if "Diagram_ID" in do_df.columns else "DiagramID"
            oid_col = "Object_ID"  if "Object_ID"  in do_df.columns else "ObjectID"
            keep = (
                pd.to_numeric(do_df[did_col], errors="coerce").astype("Int64").isin(self.allowed_diagrams)
                & pd.to_numeric(do_df[oid_col], errors="coerce").astype("Int64").isin(self.allowed_objects)
            )
            out.diagramobjects = do_df.loc[keep].copy()
        else:
            out.diagramobjects = do_df

        # DiagramLinks
        dl_df = getattr(uml, "diagramlinks", pd.DataFrame())
        if not dl_df.empty and self.allowed_diagrams and self.allowed_connectors:
            cid_col = "Connector_ID" if "Connector_ID" in dl_df.columns else ("ConnectorID" if "ConnectorID" in dl_df.columns else None)
            did_col = "Diagram_ID"   if "Diagram_ID"   in dl_df.columns else ("DiagramID"   if "DiagramID"   in dl_df.columns else None)
            if cid_col and did_col:
                keep = (
                    pd.to_numeric(dl_df[did_col], errors="coerce").astype("Int64").isin(self.allowed_diagrams)
                    & pd.to_numeric(dl_df[cid_col], errors="coerce").astype("Int64").isin(self.allowed_connectors)
                )
                out.diagramlinks = dl_df.loc[keep].copy()
            else:
                out.diagramlinks = dl_df
        else:
            out.diagramlinks = dl_df

        # carry through other tables if you have them unchanged:
        out.t_objectproperties = getattr(uml, "t_objectproperties", pd.DataFrame())
        out.objectproperties   = getattr(uml, "objectproperties",   pd.DataFrame())
        out.object_tags        = getattr(uml, "object_tags",        pd.DataFrame())
        out.element_tags       = getattr(uml, "element_tags",       pd.DataFrame())
        out.connectortags      = getattr(uml, "connectortags",      pd.DataFrame())
        out.t_connectortag     = getattr(uml, "t_connectortag",     pd.DataFrame())
        out.connector_tags     = getattr(uml, "connector_tags",     pd.DataFrame())

        return out

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
