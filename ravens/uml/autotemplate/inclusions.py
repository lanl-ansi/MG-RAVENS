import re

import pandas as pd

from ravens.uml import UMLData


class UMLInclusions:
    def __init__(
        self,
        uml_data: UMLData | None = None,
        packages: list[str] | None = None,
        exclude_inf_mkt_initial: bool = True,
        exclude_hidden_links: bool = True,
        hidden_scope_path: str | None = "SimplifiedDiagrams",
        drop_objects_without_visible_generalization: bool = True,
        auto_apply: bool = False,
    ):
        if uml_data is None:
            uml_data = UMLData()

        self.uml_data = uml_data

        self.packages = packages

        self.exclude_inf_mkt_initial = exclude_inf_mkt_initial
        self.exclude_hidden_links = exclude_hidden_links
        self.hidden_scope_path = hidden_scope_path
        self.drop_objects_without_visible_generalization = drop_objects_without_visible_generalization

        self.allowed_packages = set()
        self.allowed_diagrams = set()
        self.allowed_objects = set()
        self.allowed_connectors = set()
        self.allowed_link_instances = set()

        self.filtered_uml_data = None

        self._ensure_indexes()
        self._compute_allowed_sets()

        if auto_apply:
            self.filtered_uml_data = self.apply()

    def _ensure_indexes(self) -> None:
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

        uml.diagramlinks = getattr(uml, "diagramlinks", pd.DataFrame())
        uml.diagramobjects = getattr(uml, "diagramobjects", pd.DataFrame())

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

    def _compute_allowed_sets(self) -> None:
        uml = self.uml_data

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

        self.allowed_packages = set()
        self.allowed_diagrams = set()
        self.allowed_objects = set()
        self.allowed_connectors = set()
        self.allowed_link_instances = set()

        # 1) packages
        pkg_df = getattr(uml, "packages", pd.DataFrame())
        if isinstance(pkg_df, pd.DataFrame) and not pkg_df.empty:
            if self.packages:
                want = {str(x).strip().casefold() for x in self.packages if str(x).strip()}
                name_cf = pkg_df.get("Name", pd.Series("", index=pkg_df.index)).astype(str).str.casefold()
                path_cf = pkg_df.get("Path", pd.Series("", index=pkg_df.index)).astype(str).str.casefold()

                hit = pd.Series(False, index=pkg_df.index)
                for w in want:
                    hit |= name_cf == w
                    hit |= path_cf.str.contains(re.escape(w), na=False)

                self.allowed_packages = set(int(x) for x in _colser(pkg_df.loc[hit], "Package_ID").dropna().tolist())
            else:
                self.allowed_packages = set(int(x) for x in _colser(pkg_df, "Package_ID").dropna().tolist())

        # 2) diagrams in those packages
        dia_df = getattr(uml, "diagrams", pd.DataFrame())
        if isinstance(dia_df, pd.DataFrame) and not dia_df.empty and self.allowed_packages:
            did = _colser(dia_df, "Diagram_ID", "DiagramID")
            pkg = _ser_numeric(dia_df.get("Package_ID", pd.Series(pd.NA, index=dia_df.index)))
            keep = pkg.isin(self.allowed_packages)

            if self.exclude_inf_mkt_initial:
                dname = dia_df.get("Name", pd.Series("", index=dia_df.index)).astype(str)
                keep &= ~dname.str.startswith(("Inf", "Mkt"), na=False)

            self.allowed_diagrams = set(int(x) for x in did.loc[keep].dropna().tolist())
        else:
            self.allowed_diagrams = set()

        # 2b) scope diagrams (optional)
        scope_diagrams = set(self.allowed_diagrams)
        if self.hidden_scope_path and isinstance(dia_df, pd.DataFrame) and not dia_df.empty and isinstance(pkg_df, pd.DataFrame) and not pkg_df.empty:
            needle = str(self.hidden_scope_path).strip().casefold()
            if needle:
                pkg_path = pkg_df.get("Path", pd.Series("", index=pkg_df.index)).astype(str).str.casefold()
                pkg_name = pkg_df.get("Name", pd.Series("", index=pkg_df.index)).astype(str).str.casefold()
                scope_pkgs = set(int(i) for i in pkg_df.index[((pkg_path.str.contains(re.escape(needle), na=False)) | (pkg_name.str.contains(re.escape(needle), na=False)))].tolist())

                if scope_pkgs:
                    dia_pkg = _ser_numeric(dia_df.get("Package_ID", pd.Series(pd.NA, index=dia_df.index)))
                    did = _colser(dia_df, "Diagram_ID", "DiagramID")
                    scope_hits = set(int(x) for x in did.loc[dia_pkg.isin(scope_pkgs)].dropna().tolist())
                    scope_diagrams = (scope_hits & self.allowed_diagrams) or set(self.allowed_diagrams)

        # 3) objects appearing on allowed diagrams
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

            if self.exclude_inf_mkt_initial:
                name_ser = obj_df.get("Name", pd.Series("", index=obj_df.index)).astype(str)
                keep_names = ~(name_ser.str.startswith(("Inf", "Mkt"), na=False))
                kept_ids = set(int(x) for x in _colser(obj_df.loc[keep_names], "Object_ID").dropna().tolist())
                allowed &= kept_ids

            self.allowed_objects = allowed
        else:
            self.allowed_objects = set()

        # 4) connectors
        con_df = getattr(uml, "connectors", pd.DataFrame())
        if not (isinstance(con_df, pd.DataFrame) and not con_df.empty and self.allowed_objects):
            self.allowed_connectors = set()
        else:
            s = _colser(con_df, "Start_Object_ID", "StartObjectID")
            e = _colser(con_df, "End_Object_ID", "EndObjectID")

            if "Connector_Type" in con_df.columns:
                ctype = con_df["Connector_Type"].astype(str).str.strip().str.casefold()
            elif "Type" in con_df.columns:
                ctype = con_df["Type"].astype(str).str.strip().str.casefold()
            else:
                ctype = pd.Series("", index=con_df.index, dtype="string")

            cid_val = _colser(con_df, "Connector_ID", "ConnectorID")
            if cid_val.empty:
                cid_val = _ser_numeric(con_df.index.to_series())

            dl_df = getattr(uml, "diagramlinks", pd.DataFrame())
            hidden_veto_cids = set()
            visible_cids_in_scope = set()

            if isinstance(dl_df, pd.DataFrame) and not dl_df.empty and "ConnectorID" in dl_df.columns and "DiagramID" in dl_df.columns:
                dl_cid = _ser_numeric(dl_df["ConnectorID"])
                dl_did = _ser_numeric(dl_df["DiagramID"])

                in_scope = dl_did.isin(scope_diagrams)

                visible = in_scope & (~dl_df.get("Hidden", False).astype(bool))
                hidden = in_scope & (dl_df.get("Hidden", False).astype(bool))

                visible_cids_in_scope = set(int(x) for x in dl_cid.loc[visible].dropna().unique().tolist())
                hidden_cids_in_scope = set(int(x) for x in dl_cid.loc[hidden].dropna().unique().tolist())

                hidden_veto_cids = hidden_cids_in_scope - visible_cids_in_scope

            # 4a) generalizations: include unless hidden-veto (optional)
            gen_mask = ctype == "generalization"
            gen_keep = gen_mask & s.isin(self.allowed_objects) & e.isin(self.allowed_objects)
            gen_ids = set(int(x) for x in cid_val.loc[gen_keep].dropna().tolist())
            if self.exclude_hidden_links and hidden_veto_cids:
                gen_ids -= hidden_veto_cids

            # 4b) associations must have a visible instance in scope
            assoc_mask = ctype.isin({"association", "aggregation", "composition"})
            assoc_keep = assoc_mask & s.isin(self.allowed_objects) & e.isin(self.allowed_objects)
            assoc_ids = set(int(x) for x in cid_val.loc[assoc_keep].dropna().tolist())
            if self.exclude_hidden_links and visible_cids_in_scope:
                assoc_ids &= visible_cids_in_scope

            self.allowed_connectors = gen_ids | assoc_ids

        # 4c) optional prune: objects without visible generalization
        if self.drop_objects_without_visible_generalization and self.allowed_connectors:
            con_df = getattr(uml, "connectors", pd.DataFrame())
            if isinstance(con_df, pd.DataFrame) and not con_df.empty:
                cid_val = _colser(con_df, "Connector_ID", "ConnectorID")
                if cid_val.empty:
                    cid_val = _ser_numeric(con_df.index.to_series())

                gen_mask = con_df.get("Connector_Type", pd.Series("", index=con_df.index)).astype(str).str.casefold() == "generalization"
                keep = gen_mask & cid_val.isin(self.allowed_connectors)

                s = _colser(con_df, "Start_Object_ID", "StartObjectID")
                e = _colser(con_df, "End_Object_ID", "EndObjectID")

                obj_ids = set(int(x) for x in pd.concat([s.loc[keep], e.loc[keep]]).dropna().tolist())
                if obj_ids:
                    self.allowed_objects &= obj_ids

        # 5) link instances that survive
        dl_df = getattr(uml, "diagramlinks", pd.DataFrame())
        if isinstance(dl_df, pd.DataFrame) and not dl_df.empty and self.allowed_diagrams and self.allowed_connectors:
            did_col = "Diagram_ID" if "Diagram_ID" in dl_df.columns else ("DiagramID" if "DiagramID" in dl_df.columns else None)
            cid_col = "Connector_ID" if "Connector_ID" in dl_df.columns else ("ConnectorID" if "ConnectorID" in dl_df.columns else None)
            if did_col and cid_col:
                keep = _ser_numeric(dl_df[did_col]).isin(self.allowed_diagrams) & _ser_numeric(dl_df[cid_col]).isin(self.allowed_connectors)
                inst_set = set(int(i) for i in _ser_numeric(dl_df.index.to_series().loc[keep]).dropna().tolist())
                self.allowed_link_instances = inst_set
            else:
                self.allowed_link_instances = set()
        else:
            self.allowed_link_instances = set()

    def apply(self):
        uml = self.uml_data

        out = UMLData.__new__(UMLData)

        # carry through attributes and tag tables unchanged
        out.attributes = getattr(uml, "attributes", pd.DataFrame())
        out.xrefs = getattr(uml, "xrefs", pd.DataFrame())
        out.objectproperties = getattr(uml, "objectproperties", pd.DataFrame())
        out.connectortags = getattr(uml, "connectortags", pd.DataFrame())

        pk_df = getattr(uml, "packages", pd.DataFrame())
        out.packages = pk_df.loc[pk_df.index.isin(self.allowed_packages)].copy() if isinstance(pk_df, pd.DataFrame) and not pk_df.empty else pk_df

        di_df = getattr(uml, "diagrams", pd.DataFrame())
        out.diagrams = di_df.loc[di_df.index.isin(self.allowed_diagrams)].copy() if isinstance(di_df, pd.DataFrame) and not di_df.empty else di_df

        ob_df = getattr(uml, "objects", pd.DataFrame())
        out.objects = ob_df.loc[ob_df.index.isin(self.allowed_objects)].copy() if isinstance(ob_df, pd.DataFrame) and not ob_df.empty else ob_df

        co_df = getattr(uml, "connectors", pd.DataFrame())
        out.connectors = co_df.loc[co_df.index.isin(self.allowed_connectors)].copy() if isinstance(co_df, pd.DataFrame) and not co_df.empty else co_df

        do_df = getattr(uml, "diagramobjects", pd.DataFrame())
        if isinstance(do_df, pd.DataFrame) and not do_df.empty and self.allowed_diagrams and self.allowed_objects:
            did_col = "Diagram_ID" if "Diagram_ID" in do_df.columns else ("DiagramID" if "DiagramID" in do_df.columns else None)
            oid_col = "Object_ID" if "Object_ID" in do_df.columns else ("ObjectID" if "ObjectID" in do_df.columns else None)
            if did_col and oid_col:
                keep = pd.to_numeric(do_df[did_col], errors="coerce").astype("Int64").isin(self.allowed_diagrams) & pd.to_numeric(do_df[oid_col], errors="coerce").astype("Int64").isin(self.allowed_objects)
                out.diagramobjects = do_df.loc[keep].copy()
            else:
                out.diagramobjects = do_df
        else:
            out.diagramobjects = do_df

        dl_df = getattr(uml, "diagramlinks", pd.DataFrame())
        if isinstance(dl_df, pd.DataFrame) and not dl_df.empty and self.allowed_diagrams and self.allowed_connectors:
            did_col = "Diagram_ID" if "Diagram_ID" in dl_df.columns else ("DiagramID" if "DiagramID" in dl_df.columns else None)
            cid_col = "Connector_ID" if "Connector_ID" in dl_df.columns else ("ConnectorID" if "ConnectorID" in dl_df.columns else None)
            if did_col and cid_col:
                keep = pd.to_numeric(dl_df[did_col], errors="coerce").astype("Int64").isin(self.allowed_diagrams) & pd.to_numeric(dl_df[cid_col], errors="coerce").astype("Int64").isin(self.allowed_connectors)
                out.diagramlinks = dl_df.loc[keep].copy()
            else:
                out.diagramlinks = dl_df
        else:
            out.diagramlinks = dl_df

        return out
