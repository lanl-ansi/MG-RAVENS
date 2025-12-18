# clusions.py
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Optional, Set
import pandas as pd

from ravens.uml import UMLData

# EA package/name prefixes you often exclude
_NAME_EXCLUDE_RX = re.compile(r"^(?:Inf[A-Z]|Mkt[A-Z])")


@dataclass
class UMLInclusions:
    uml_data: "UMLData"
    packages: Optional[Iterable[str]] = None
    auto_apply: bool = True  # runs apply() upon instantiation

    exclude_inf_mkt_initial: bool = True

    # If True, treat "Hidden==True" connector instances on diagrams in `hidden_scope_path`
    # as a veto condition (see _compute_allowed_sets()).
    exclude_hidden_links: bool = True
    hidden_scope_path: Optional[str] = "SimplifiedDiagrams"

    # If True, after building generalization set, prune allowed_objects to only those
    # that participate in at least one remaining generalization edge.
    drop_objects_without_visible_generalization: bool = True

    # populated by _compute_allowed_sets()
    allowed_packages: Set[int] = None  # type: ignore[assignment]
    allowed_diagrams: Set[int] = None  # type: ignore[assignment]
    allowed_objects: Set[int] = None   # type: ignore[assignment]
    allowed_connectors: Set[int] = None  # type: ignore[assignment]
    allowed_link_instances: Set[int] = None  # type: ignore[assignment]

    # populated by apply()
    filtered_uml_data: Optional[UMLData] = None

    def __post_init__(self):
        self._ensure_indexes()
        self._compute_allowed_sets()
        if self.auto_apply:
            self.filtered_uml_data = self.apply()

    # ---------- index hygiene ----------
    def _ensure_indexes(self) -> None:
        """
        Ensure the common EA tables are indexed by their ID columns so that
        `.loc[index.isin(...)]` filtering in apply() behaves correctly.
        """
        uml = self.uml_data

        def set_idx(df: pd.DataFrame, id_col: str) -> pd.DataFrame:
            if not isinstance(df, pd.DataFrame) or df.empty:
                return df
            if id_col in df.columns and df.index.name != id_col:
                return df.set_index(id_col, drop=False)
            return df

        uml.packages = set_idx(getattr(uml, "packages", pd.DataFrame()), "Package_ID")
        uml.diagrams = set_idx(getattr(uml, "diagrams", pd.DataFrame()), "Diagram_ID")
        uml.objects = set_idx(getattr(uml, "objects", pd.DataFrame()), "Object_ID")
        uml.connectors = set_idx(getattr(uml, "connectors", pd.DataFrame()), "Connector_ID")

        # diagramlinks/diagramobjects can be left alone (EA exports vary),
        # but we rely on their *columns* heavily in _compute_allowed_sets().
        uml.diagramlinks = getattr(uml, "diagramlinks", pd.DataFrame())
        uml.diagramobjects = getattr(uml, "diagramobjects", pd.DataFrame())

    # ---------- public helpers used by graph code ----------
    def allow(self, kind: str, id_value: int) -> bool:
        k = (kind or "").strip().lower()
        iv = int(id_value)
        if k == "package":
            return iv in (self.allowed_packages or set())
        if k == "diagram":
            return iv in (self.allowed_diagrams or set())
        if k == "object":
            return iv in (self.allowed_objects or set())
        if k == "connector":
            return iv in (self.allowed_connectors or set())
        if k == "link_instance":
            return iv in (self.allowed_link_instances or set())
        return True

    # ---------- core ----------
    def _compute_allowed_sets(self) -> None:
        """
        Compute allowed packages, diagrams, objects, connectors, and link instances.

        Visibility policy (scope-aware via hidden_scope_path):
          - Define a "scope diagram set" = diagrams whose package path/name contains
            `hidden_scope_path` (case-insensitive), intersected with allowed_diagrams.
            If hidden_scope_path is None OR no matches found, scope_diagrams = allowed_diagrams.

          - ASSOCIATIONS / AGGREGATION / COMPOSITION:
              keep only connectors that have at least one *visible* (Hidden==False) instance
              on a scope diagram, and whose endpoints are allowed objects.

          - GENERALIZATIONS:
              keep all generalization connectors whose endpoints are allowed objects,
              EXCEPT those that are hidden on *every* scope diagram where they appear:
                  hidden_veto = hidden_cids_in_scope - visible_cids_in_scope

          - OPTIONAL PRUNE:
              if drop_objects_without_visible_generalization is True, restrict allowed_objects
              to endpoints of remaining generalizations (then re-filter assoc connectors).

        Notes:
          - This does NOT use diagramlinks.Path at all.
          - Tolerant to connector IDs living either in a Connector_ID/ConnectorID column
            or in the connectors index.
        """
        uml = self.uml_data

        # --- helpers -------------------------------------------------------------
        def _ser_numeric(s):
            return pd.to_numeric(s, errors="coerce").astype("Int64")

        def _colser(df, *names):
            if not isinstance(df, pd.DataFrame) or df.empty:
                return pd.Series([], dtype="Int64")
            for n in names:
                if n in df.columns:
                    return _ser_numeric(df[n])
            if df.index.name in names:
                return _ser_numeric(df.index.to_series())
            return pd.Series([], dtype="Int64")

        # ---------- 0) init empty sets ----------
        self.allowed_packages = set()
        self.allowed_diagrams = set()
        self.allowed_objects = set()
        self.allowed_connectors = set()
        self.allowed_link_instances = set()

        # ---------------- 1) packages ----------------
        pkg_df = getattr(uml, "packages", pd.DataFrame())
        if isinstance(pkg_df, pd.DataFrame) and not pkg_df.empty:
            if self.packages:
                want = {str(x).strip().casefold() for x in self.packages if str(x).strip()}
                name_cf = pkg_df.get("Name", pd.Series("", index=pkg_df.index)).astype(str).str.casefold()
                path_cf = pkg_df.get("Path", pd.Series("", index=pkg_df.index)).astype(str).str.casefold()

                hit = pd.Series(False, index=pkg_df.index)
                for w in want:
                    hit |= (name_cf == w)
                    hit |= path_cf.str.contains(re.escape(w), na=False)

                self.allowed_packages = set(int(x) for x in _colser(pkg_df.loc[hit], "Package_ID").dropna().tolist())
            else:
                self.allowed_packages = set(int(x) for x in _colser(pkg_df, "Package_ID").dropna().tolist())

        # ---------------- 2) diagrams in those packages ----------------
        dia_df = getattr(uml, "diagrams", pd.DataFrame())
        if isinstance(dia_df, pd.DataFrame) and not dia_df.empty and self.allowed_packages:
            did = _colser(dia_df, "Diagram_ID", "DiagramID")
            pkg = _ser_numeric(dia_df.get("Package_ID", pd.Series(pd.NA, index=dia_df.index)))
            keep = pkg.isin(self.allowed_packages)
            self.allowed_diagrams = set(int(x) for x in did.loc[keep].dropna().tolist())
        else:
            self.allowed_diagrams = set()

        # ---------------- 2b) scope diagrams (for hidden/visible logic) ----------------
        scope_diagrams = set(self.allowed_diagrams)
        if self.hidden_scope_path and isinstance(dia_df, pd.DataFrame) and not dia_df.empty and isinstance(pkg_df, pd.DataFrame) and not pkg_df.empty:
            needle = str(self.hidden_scope_path).strip().casefold()
            if needle:
                pkg_path = pkg_df.get("Path", pd.Series("", index=pkg_df.index)).astype(str).str.casefold()
                pkg_name = pkg_df.get("Name", pd.Series("", index=pkg_df.index)).astype(str).str.casefold()
                scope_pkgs = set(int(i) for i in pkg_df.index[(pkg_path.str.contains(re.escape(needle), na=False)) | (pkg_name.str.contains(re.escape(needle), na=False))].tolist())

                if scope_pkgs:
                    dia_pkg = _ser_numeric(dia_df.get("Package_ID", pd.Series(pd.NA, index=dia_df.index)))
                    did = _colser(dia_df, "Diagram_ID", "DiagramID")
                    scope_hits = set(int(x) for x in did.loc[dia_pkg.isin(scope_pkgs)].dropna().tolist())
                    scope_diagrams = (scope_hits & self.allowed_diagrams) or set(self.allowed_diagrams)

        # ---------------- 3) objects appearing on allowed diagrams ----------------
        do_df = getattr(uml, "diagramobjects", pd.DataFrame())
        objs_on_diagrams = set()
        if isinstance(do_df, pd.DataFrame) and not do_df.empty and self.allowed_diagrams:
            dcol = "Diagram_ID" if "Diagram_ID" in do_df.columns else ("DiagramID" if "DiagramID" in do_df.columns else None)
            ocol = "Object_ID" if "Object_ID" in do_df.columns else ("ObjectID" if "ObjectID" in do_df.columns else None)
            if dcol and ocol:
                keep = _ser_numeric(do_df[dcol]).isin(self.allowed_diagrams)
                objs_on_diagrams = set(int(x) for x in _ser_numeric(do_df.loc[keep, ocol]).dropna().tolist())

        obj_df = getattr(uml, "objects", pd.DataFrame())
        if isinstance(obj_df, pd.DataFrame) and not obj_df.empty:
            all_obj_ids = set(int(x) for x in _colser(obj_df, "Object_ID").dropna().tolist())

            allowed = objs_on_diagrams if self.allowed_diagrams else all_obj_ids

            # Optional Inf*/Mkt* exclusion
            if self.exclude_inf_mkt_initial:
                name_ser = obj_df.get("Name", pd.Series("", index=obj_df.index)).astype(str)
                keep_names = ~(name_ser.str.startswith(("Inf", "Mkt"), na=False))
                kept_ids = set(int(x) for x in _colser(obj_df.loc[keep_names], "Object_ID").dropna().tolist())
                allowed &= kept_ids

            self.allowed_objects = allowed
        else:
            self.allowed_objects = set()

        # ---------------- 4) connectors ----------------
        con_df = getattr(uml, "connectors", pd.DataFrame())
        if not (isinstance(con_df, pd.DataFrame) and not con_df.empty and self.allowed_objects):
            self.allowed_connectors = set()
        else:
            # endpoints and normalized type
            s = _colser(con_df, "Start_Object_ID", "StartObjectID")
            e = _colser(con_df, "End_Object_ID", "EndObjectID")

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
                cid_val = _ser_numeric(con_df.index.to_series())

            # Build a mapping cid -> row-index (best-effort) to support pruning later
            cid_to_row = {}
            for idx in con_df.index:
                cv = cid_val.loc[idx]
                if pd.isna(cv):
                    continue
                cvi = int(cv)
                if cvi not in cid_to_row:
                    cid_to_row[cvi] = idx

            # diagramlinks: use DiagramID & Hidden ONLY
            dl_df = getattr(uml, "diagramlinks", pd.DataFrame())
            hidden_veto_cids: set[int] = set()
            visible_cids_in_scope: set[int] = set()

            if isinstance(dl_df, pd.DataFrame) and not dl_df.empty and "ConnectorID" in dl_df.columns and "DiagramID" in dl_df.columns:
                dl_cid = _ser_numeric(dl_df["ConnectorID"])
                dl_did = _ser_numeric(dl_df["DiagramID"])

                in_scope = dl_did.isin(scope_diagrams)

                hidden_rows = in_scope & (dl_df.get("Hidden", False) == True)
                visible_rows = in_scope & (dl_df.get("Hidden", False) == False)

                hidden_cids = set(int(x) for x in dl_cid.loc[hidden_rows].dropna().tolist())
                visible_cids_in_scope = set(int(x) for x in dl_cid.loc[visible_rows].dropna().tolist())

                if self.exclude_hidden_links:
                    # veto generalizations that are hidden everywhere in scope (never visible in scope)
                    hidden_veto_cids = hidden_cids - visible_cids_in_scope

            # --- collect association-like ids: must be visible in scope diagrams ---
            assoc_ids: set[int] = set()
            assoc_mask = ctype.isin({"association", "aggregation", "composition"})
            for idx in con_df.index[assoc_mask]:
                cv = cid_val.loc[idx]
                if pd.isna(cv):
                    continue
                cid = int(cv)
                if self.exclude_hidden_links:
                    if cid not in visible_cids_in_scope:
                        continue
                # endpoints must be allowed objects
                sv = s.loc[idx]
                ev = e.loc[idx]
                if pd.isna(sv) or pd.isna(ev):
                    continue
                if int(sv) in self.allowed_objects and int(ev) in self.allowed_objects:
                    assoc_ids.add(cid)

            # --- collect generalization ids with optional hidden veto (scope-aware) ---
            gen_ids: set[int] = set()
            gen_mask = (ctype == "generalization")
            for idx in con_df.index[gen_mask]:
                cv = cid_val.loc[idx]
                if pd.isna(cv):
                    continue
                cid = int(cv)
                if self.exclude_hidden_links and cid in hidden_veto_cids:
                    continue
                sv = s.loc[idx]
                ev = e.loc[idx]
                if pd.isna(sv) or pd.isna(ev):
                    continue
                if int(sv) in self.allowed_objects and int(ev) in self.allowed_objects:
                    gen_ids.add(cid)

            # --- optional prune by visible generalization participation ---
            if self.drop_objects_without_visible_generalization and gen_ids:
                gen_endpoints: set[int] = set()
                for cid in gen_ids:
                    idx = cid_to_row.get(cid)
                    if idx is None:
                        continue
                    sv = s.loc[idx]
                    ev = e.loc[idx]
                    if not pd.isna(sv):
                        gen_endpoints.add(int(sv))
                    if not pd.isna(ev):
                        gen_endpoints.add(int(ev))

                self.allowed_objects &= gen_endpoints

                # re-filter associations to keep consistent with pruned objects
                assoc_ids2: set[int] = set()
                for cid in assoc_ids:
                    idx = cid_to_row.get(cid)
                    if idx is None:
                        continue
                    sv = s.loc[idx]
                    ev = e.loc[idx]
                    if pd.isna(sv) or pd.isna(ev):
                        continue
                    if int(sv) in self.allowed_objects and int(ev) in self.allowed_objects:
                        assoc_ids2.add(cid)
                assoc_ids = assoc_ids2

            self.allowed_connectors = assoc_ids | gen_ids

        # ---------------- 5) link instances that survive --------------------------
        dl_df = getattr(uml, "diagramlinks", pd.DataFrame())
        if isinstance(dl_df, pd.DataFrame) and not dl_df.empty and self.allowed_diagrams and self.allowed_connectors:
            did_col = "Diagram_ID" if "Diagram_ID" in dl_df.columns else ("DiagramID" if "DiagramID" in dl_df.columns else None)
            cid_col = "Connector_ID" if "Connector_ID" in dl_df.columns else ("ConnectorID" if "ConnectorID" in dl_df.columns else None)
            if did_col and cid_col:
                keep = (
                    _ser_numeric(dl_df[did_col]).isin(self.allowed_diagrams)
                    & _ser_numeric(dl_df[cid_col]).isin(self.allowed_connectors)
                )

                # robust: include both index values and InstanceID column values if present
                inst_set = set()
                inst_set |= set(int(i) for i in _ser_numeric(dl_df.index.to_series().loc[keep]).dropna().tolist())
                if "InstanceID" in dl_df.columns:
                    inst_set |= set(int(i) for i in _ser_numeric(dl_df.loc[keep, "InstanceID"]).dropna().tolist())
                self.allowed_link_instances = inst_set
            else:
                self.allowed_link_instances = set()
        else:
            self.allowed_link_instances = set()

    def apply(self) -> UMLData:
        """Return a *new* UMLData containing only allowed rows (packages/diagrams/objects/connectors/links)."""
        uml = self.uml_data
        out = UMLData()

        # Packages
        pk_df = getattr(uml, "packages", pd.DataFrame())
        out.packages = pk_df.loc[pk_df.index.isin(self.allowed_packages)].copy() if isinstance(pk_df, pd.DataFrame) and not pk_df.empty else pk_df

        # Diagrams
        di_df = getattr(uml, "diagrams", pd.DataFrame())
        out.diagrams = di_df.loc[di_df.index.isin(self.allowed_diagrams)].copy() if isinstance(di_df, pd.DataFrame) and not di_df.empty else di_df

        # Objects
        ob_df = getattr(uml, "objects", pd.DataFrame())
        out.objects = ob_df.loc[ob_df.index.isin(self.allowed_objects)].copy() if isinstance(ob_df, pd.DataFrame) and not ob_df.empty else ob_df

        # Connectors
        co_df = getattr(uml, "connectors", pd.DataFrame())
        out.connectors = co_df.loc[co_df.index.isin(self.allowed_connectors)].copy() if isinstance(co_df, pd.DataFrame) and not co_df.empty else co_df

        # DiagramObjects
        do_df = getattr(uml, "diagramobjects", pd.DataFrame())
        if isinstance(do_df, pd.DataFrame) and not do_df.empty and self.allowed_diagrams and self.allowed_objects:
            did_col = "Diagram_ID" if "Diagram_ID" in do_df.columns else ("DiagramID" if "DiagramID" in do_df.columns else None)
            oid_col = "Object_ID" if "Object_ID" in do_df.columns else ("ObjectID" if "ObjectID" in do_df.columns else None)
            if did_col and oid_col:
                keep = (
                    pd.to_numeric(do_df[did_col], errors="coerce").astype("Int64").isin(self.allowed_diagrams)
                    & pd.to_numeric(do_df[oid_col], errors="coerce").astype("Int64").isin(self.allowed_objects)
                )
                out.diagramobjects = do_df.loc[keep].copy()
            else:
                out.diagramobjects = do_df
        else:
            out.diagramobjects = do_df

        # DiagramLinks (filter by allowed diagrams/connectors)
        dl_df = getattr(uml, "diagramlinks", pd.DataFrame())
        if isinstance(dl_df, pd.DataFrame) and not dl_df.empty and self.allowed_diagrams and self.allowed_connectors:
            did_col = "Diagram_ID" if "Diagram_ID" in dl_df.columns else ("DiagramID" if "DiagramID" in dl_df.columns else None)
            cid_col = "Connector_ID" if "Connector_ID" in dl_df.columns else ("ConnectorID" if "ConnectorID" in dl_df.columns else None)
            if did_col and cid_col:
                keep = (
                    pd.to_numeric(dl_df[did_col], errors="coerce").astype("Int64").isin(self.allowed_diagrams)
                    & pd.to_numeric(dl_df[cid_col], errors="coerce").astype("Int64").isin(self.allowed_connectors)
                )
                out.diagramlinks = dl_df.loc[keep].copy()
            else:
                out.diagramlinks = dl_df
        else:
            out.diagramlinks = dl_df

        # carry through tag tables unchanged
        out.t_objectproperties = getattr(uml, "t_objectproperties", pd.DataFrame())
        out.objectproperties = getattr(uml, "objectproperties", pd.DataFrame())
        out.object_tags = getattr(uml, "object_tags", pd.DataFrame())
        out.element_tags = getattr(uml, "element_tags", pd.DataFrame())
        out.connectortags = getattr(uml, "connectortags", pd.DataFrame())
        out.t_connectortag = getattr(uml, "t_connectortag", pd.DataFrame())
        out.connector_tags = getattr(uml, "connector_tags", pd.DataFrame())

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
        self.object_ids = (
            [obj.Index for obj in self.uml_data.objects.itertuples() if lambda_func(obj)]
            + [obj.Index for p in self.package_ids for obj in self.uml_data.objects[self.uml_data.objects["Package_ID"] == p].itertuples()]
        )


if __name__ == "__main__":
    exclusions = UMLExclusions().exclude_by_name_startswith(["Inf", "Mkt"])
    # Example:
    # inc = UMLInclusions(UMLData(), packages=["RAVENS"], auto_apply=True)
