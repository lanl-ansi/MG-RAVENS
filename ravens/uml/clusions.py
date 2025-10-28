# clusions.py
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Iterable, Optional, Set, Dict
import pandas as pd

from ravens.uml import UMLData

_NAME_EXCLUDE_RX = re.compile(r'^(?:Inf[A-Z]|Mkt[A-Z])')

@dataclass
class UMLInclusions:
    uml_data: "UMLData"
    packages: Optional[Iterable[str]] = None
    auto_apply: bool = True  # runs apply() upon instantiation

    exclude_inf_mkt_initial: bool = True
    # To handle connectors that are invisible within "hidden_scope_path" package.
    exclude_hidden_links: bool = True
    hidden_scope_path: Optional[str] = "SimplifiedDiagrams"
    drop_objects_without_visible_generalization: bool = True

    def __post_init__(self):
        if self.auto_apply:
            self.apply()

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
        """
        Compute allowed packages, diagrams, objects, connectors, and link instances.

        Visibility policy:
        - ASSOCIATIONS: must appear on an allowed diagram AND be visible (Hidden==False)
            within hidden_scope_path (if provided).
        - GENERALIZATIONS: keep globally, EXCEPT those with a diagramlink that is
            Hidden==True within hidden_scope_path (global veto).
        - OPTIONAL OBJECT-LEVEL VETO: if exclude_objects_with_hidden_generalization is True,
            any object participating in a hidden-in-scope generalization is removed from
            allowed_objects (so it cannot leak in via other edges).
        - OPTIONAL PRUNE: if drop_objects_without_visible_generalization is True, keep only
            objects that are endpoints of the remaining (non-vetoed) generalizations.

        Tolerant to EA column variants and to connector IDs living on the index.
        """
        uml = self.uml_data
        # --- helpers -------------------------------------------------------------
        def _ser_numeric(s):
            return pd.to_numeric(s, errors="coerce").astype("Int64")

        def _colser(df, *names):
            for n in names:
                if n in df.columns:
                    return _ser_numeric(df[n])
            if df.index.name in names:
                return _ser_numeric(df.index.to_series())
            return pd.Series([], dtype="Int64")

        def _cid_series(df):
            if "Connector_ID" in df.columns:
                return _ser_numeric(df["Connector_ID"])
            if "ConnectorID" in df.columns:
                return _ser_numeric(df["ConnectorID"])
            # use index
            return _ser_numeric(df.index.to_series())

        # ---------------- 1) packages ----------------
        pkg_df = getattr(uml, "packages", pd.DataFrame())
        if self.packages:
            want = {str(x).strip().casefold() for x in self.packages if str(x).strip()}
            if not pkg_df.empty:
                name_cf = pkg_df.get("Name", pd.Series("", index=pkg_df.index)).astype(str).str.casefold()
                path_cf = pkg_df.get("Path", pd.Series("", index=pkg_df.index)).astype(str).str.casefold()
                hit = name_cf.isin(want)
                for w in want:
                    hit = hit | path_cf.str.contains(w, na=False)
                self.allowed_packages = set(int(x) for x in _colser(pkg_df.loc[hit], pkg_df.index.name or "Package_ID").dropna().tolist())
            else:
                self.allowed_packages = set()
        else:
            self.allowed_packages = set(int(x) for x in _colser(pkg_df, "Package_ID").dropna().tolist())

        # ---------------- 2) diagrams in those packages ----------------
        dia_df = getattr(uml, "diagrams", pd.DataFrame())
        if dia_df.empty or not self.allowed_packages:
            self.allowed_diagrams = set()
        else:
            dser = _colser(dia_df, "Diagram_ID", "DiagramID")
            keep = _ser_numeric(dia_df.get("Package_ID")).isin(self.allowed_packages)
            self.allowed_diagrams = set(int(x) for x in dser[keep].dropna().tolist())

        # ---------------- 3) objects appearing on those diagrams ----------------
        do_df = getattr(uml, "diagramobjects", pd.DataFrame())
        objs_on_diagrams = set()
        if not do_df.empty and self.allowed_diagrams:
            dcol = "Diagram_ID" if "Diagram_ID" in do_df.columns else ("DiagramID" if "DiagramID" in do_df.columns else None)
            ocol = "Object_ID"  if "Object_ID"  in do_df.columns else ("ObjectID"  if "ObjectID"  in do_df.columns else None)
            if dcol and ocol:
                keep = _ser_numeric(do_df[dcol]).isin(self.allowed_diagrams)
                objs_on_diagrams = set(int(x) for x in _ser_numeric(do_df.loc[keep, ocol]).dropna().tolist())

        obj_df = getattr(uml, "objects", pd.DataFrame())
        if obj_df.empty:
            self.allowed_objects = set()
        else:
            all_obj_ids = set(int(x) for x in _colser(obj_df, "Object_ID").dropna().tolist())
            if self.allowed_diagrams:
                allowed = objs_on_diagrams
            else:
                allowed = all_obj_ids

            # Optional Inf*/Mkt* exclusion
            if getattr(self, "exclude_inf_mkt_initial", False):
                name_ser = obj_df.get("Name", pd.Series("", index=obj_df.index)).astype(str)
                keep_names = ~(name_ser.str.startswith(("Inf", "Mkt"), na=False))
                kept_ids = set(int(x) for x in _colser(obj_df[keep_names], obj_df.index.name or "Object_ID").dropna().tolist())
                allowed = allowed & kept_ids

            self.allowed_objects = allowed

        # ---------------- 4) connectors ----------------
        con_df = getattr(uml, "connectors", pd.DataFrame())
        if con_df.empty or not self.allowed_objects:
            self.allowed_connectors = set()
        else:
            def _ser_numeric(s): return pd.to_numeric(s, errors="coerce").astype("Int64")
            def _colser(df, *names):
                for n in names:
                    if n in df.columns:
                        return _ser_numeric(df[n])
                if df.index.name in names:
                    return _ser_numeric(df.index.to_series())
                return pd.Series([], dtype="Int64")

            # endpoints and normalized type
            s = _colser(con_df, "Start_Object_ID", "StartObjectID")
            e = _colser(con_df, "End_Object_ID",   "EndObjectID")
            if "Connector_Type" in con_df.columns:
                ctype = con_df["Connector_Type"].astype(str).str.strip().str.casefold()
            elif "Type" in con_df.columns:
                ctype = con_df["Type"].astype(str).str.strip().str.casefold()
            else:
                ctype = pd.Series("", index=con_df.index, dtype="string")

            # connector-id value per row (column if present, else use index value)
            if "Connector_ID" in con_df.columns:
                cid_val = _ser_numeric(con_df["Connector_ID"])
            elif "ConnectorID" in con_df.columns:
                cid_val = _ser_numeric(con_df["ConnectorID"])
            else:
                cid_val = _ser_numeric(con_df.index.to_series())  # EA default: index = Connector_ID

            # diagramlinks: use DiagramID & Hidden ONLY (NEVER Path)
            dl_df = getattr(uml, "diagramlinks", pd.DataFrame())
            hidden_veto_cids: set[int] = set()
            links_in_allowed_visible: set[int] = set()

            if not dl_df.empty and "ConnectorID" in dl_df.columns and "DiagramID" in dl_df.columns:
                dl_cid = _ser_numeric(dl_df["ConnectorID"])
                dl_did = _ser_numeric(dl_df["DiagramID"])
                in_scope = dl_did.isin(self.allowed_diagrams)

                # Global VETO set for generalizations: any link Hidden==True on a scoped diagram
                if getattr(self, "exclude_hidden_links", True):
                    hidden_rows = in_scope & (dl_df.get("Hidden", False) == True)
                    hidden_veto_cids = set(int(x) for x in dl_cid.loc[hidden_rows].dropna().tolist())

                # For associations we still require a visible link on an allowed diagram
                vis_rows = in_scope & (dl_df.get("Hidden", False) == False)
                links_in_allowed_visible = set(int(x) for x in dl_cid.loc[vis_rows].dropna().tolist())

            # --- collect association ids (by iterating rows for ID safety) ---
            assoc_ids: set[int] = set()
            assoc_mask = ctype.isin({"association", "aggregation", "composition"})
            for idx in con_df.index[assoc_mask]:
                cid = cid_val.loc[idx]
                if pd.isna(cid): 
                    continue
                cid = int(cid)
                if cid not in links_in_allowed_visible:
                    continue
                if int(s.loc[idx]) in self.allowed_objects and int(e.loc[idx]) in self.allowed_objects:
                    assoc_ids.add(cid)

            # --- collect generalization ids with the "hidden in scoped diagrams" VETO ---
            gen_ids: set[int] = set()
            gen_mask = (ctype == "generalization")
            for idx in con_df.index[gen_mask]:
                cid = cid_val.loc[idx]
                if pd.isna(cid): 
                    continue
                cid = int(cid)
                if cid in hidden_veto_cids:
                    continue
                if int(s.loc[idx]) in self.allowed_objects and int(e.loc[idx]) in self.allowed_objects:
                    gen_ids.add(cid)

            # --- optional pruning: keep only objects that are endpoints of remaining gen edges
            if getattr(self, "drop_objects_without_visible_generalization", False) and gen_ids:
                gen_endpoints = {int(s.loc[idx]) for idx in con_df.index[gen_mask] if int(cid_val.loc[idx]) in gen_ids} | \
                                {int(e.loc[idx]) for idx in con_df.index[gen_mask] if int(cid_val.loc[idx]) in gen_ids}
                self.allowed_objects &= gen_endpoints
                # keep associations consistent with pruned object set
                assoc_ids = {
                    cid for cid in assoc_ids
                    if int(s.loc[cid_val.index[cid_val == cid][0]]) in self.allowed_objects
                    and int(e.loc[cid_val.index[cid_val == cid][0]]) in self.allowed_objects
                }

            self.allowed_connectors = assoc_ids | gen_ids

        # ---------------- 5) link instances that survive --------------------------
        dl_df = getattr(uml, "diagramlinks", pd.DataFrame())
        if not dl_df.empty and self.allowed_diagrams and self.allowed_connectors:
            cid_col = "Connector_ID" if "Connector_ID" in dl_df.columns else ("ConnectorID" if "ConnectorID" in dl_df.columns else None)
            did_col = "Diagram_ID"   if "Diagram_ID"   in dl_df.columns else ("DiagramID"   if "DiagramID"   in dl_df.columns else None)
            if cid_col and did_col:
                keep = (
                    _ser_numeric(dl_df[did_col]).isin(self.allowed_diagrams)
                    & _ser_numeric(dl_df[cid_col]).isin(self.allowed_connectors)
                )
                if "InstanceID" in dl_df.columns:
                    self.allowed_link_instances = set(int(i) for i in _ser_numeric(dl_df.loc[keep, "InstanceID"]).dropna().tolist())
                else:
                    self.allowed_link_instances = set(int(i) for i in _ser_numeric(dl_df.index.to_series().loc[keep]).dropna().tolist())
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
