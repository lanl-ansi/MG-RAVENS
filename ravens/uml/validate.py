from __future__ import annotations
import json
import pandas as pd
import networkx as nx
from collections import OrderedDict, deque
from pprint import pprint
from ravens.uml.legend import ravens_colors
from openpyxl.utils import get_column_letter
from pathlib import Path

from typing import Dict, Set, Tuple, List, Optional, Union
import json
import re

from ravens.uml.graph import UMLGraphs

from ravens.data import _TEMPLATE_JSON_PATH, _TEMPLATE_AUTOJSON_PATH

import pandas as pd
import networkx as nx
from typing import Optional, Iterable, Dict, Set, Tuple

class ModelValidator:
    """
    RAVENS model validations for a directed NetworkX graph.

    Conventions
    -----------
    • Each check returns None (pass) or a DataFrame (fail).
    • validate() returns {check_id: df_or_None}.
    • Nodes/edges should carry 'ravensRole' attributes if applicable.
    • Root is resolved by node 'Name' == root_name.
    """

    def __init__(
        self,
        G: nx.MultiDiGraph,
        root_name: str = "Root",
        *,
        allowed_node_roles: Optional[Iterable[str]] = None,
        allowed_edge_roles: Optional[Iterable[str]] = None,
        edge_role_constraints: Optional[Iterable[Tuple[Optional[str], Set[str], Set[str]]]] = None,
        # ^ optional: list of constraints like
        #   (edge_role, allowed_src_roles, allowed_dst_roles)
        #   If edge_role is None, apply to all edges.
    ):
        self.G = G
        self.G_rev = G.reverse(copy=False)
        self.root_name = root_name

        # Build DataFrames from G
        self.df_edges = nx.to_pandas_edgelist(G)  # columns: source, target, <edge attrs...>
        self.df_nodes = self._to_pandas_nodelist(G)  # columns: node, <node attrs...>

        # Basic maps
        self.name_map: Dict[int, str] = (
            self.df_nodes.set_index("node")["Name"].astype(str).to_dict()
            if "Name" in self.df_nodes.columns else {}
        )
        self.node_role_map: Dict[int, Optional[str]] = (
            self.df_nodes.set_index("node")["ravensRole"].apply(lambda x: None if pd.isna(x) or str(x).strip()=="" else str(x)).to_dict()
            if "ravensRole" in self.df_nodes.columns else {}
        )

        # For context in reports: which diagrams a node appears in (based on edges)
        self.node_diagrams_map = (
            pd.concat(
                [
                    self.df_edges[["source", "Diagram"]].rename(columns={"source": "node"}),
                    self.df_edges[["target", "Diagram"]].rename(columns={"target": "node"}),
                ],
                ignore_index=True,
            )
            .dropna(subset=["node"])
            .groupby("node")["Diagram"]
            .apply(lambda x: sorted(set(x.dropna().astype(str))))
            .to_dict()
            if "Diagram" in self.df_edges.columns else {}
        )

        # Resolve root id from node DF
        if "Name" not in self.df_nodes.columns:
            raise ValueError("df_nodes has no 'Name' column; cannot resolve Root.")
        hits = self.df_nodes.loc[self.df_nodes["Name"] == self.root_name, "node"]
        if hits.empty:
            raise ValueError(f"No node named '{self.root_name}' in df_nodes.")
        if len(hits) > 1:
            raise ValueError(f"Multiple nodes named '{self.root_name}' in df_nodes.")
        self.root_id = int(hits.iloc[0])
        if self.root_id not in self.G:
            raise ValueError(f"Resolved root id {self.root_id} not present in graph.")

        # Allowed role vocabularies (optional)
        self.allowed_node_roles: Optional[Set[str]] = set(allowed_node_roles) if allowed_node_roles else None
        self.allowed_edge_roles: Optional[Set[str]] = set(allowed_edge_roles) if allowed_edge_roles else None

        # Optional role constraints for edges:
        # Each tuple: (edge_role or None, allowed_src_roles, allowed_dst_roles)
        # If list is empty/None, the check is a no-op.
        self.edge_role_constraints: Tuple[Tuple[Optional[str], Set[str], Set[str]], ...] = tuple(edge_role_constraints or ())

    @staticmethod
    def _to_pandas_nodelist(G: nx.MultiDiGraph) -> pd.DataFrame:
        """One row per node with attributes expanded."""
        rows = []
        for n, attrs in G.nodes(data=True):
            row = {"node": n}
            row.update(attrs or {})
            rows.append(row)
        return pd.DataFrame(rows) if rows else pd.DataFrame(columns=["node"])

    # ---------------- role presence / vocabulary ----------------
    def node_roles_missing(self) -> Optional[pd.DataFrame]:
        """Nodes that do not have a ravensRole (empty/None)."""
        if "ravensRole" not in self.df_nodes.columns:
            return self.df_nodes.assign(reason="nodes lack 'ravensRole' column") if not self.df_nodes.empty else pd.DataFrame([{"reason": "no nodes"}])
        mask = self.df_nodes["ravensRole"].isna() | (self.df_nodes["ravensRole"].astype(str).str.strip() == "")
        out = self.df_nodes.loc[mask, ["node", "Name", "ravensRole"]].copy()
        return None if out.empty else out.reset_index(drop=True)

    def edge_roles_missing(self) -> Optional[pd.DataFrame]:
        """Edges that do not have a ravensRole (empty/None)."""
        if "ravensRole" not in self.df_edges.columns:
            return self.df_edges.assign(reason="edges lack 'ravensRole' column") if not self.df_edges.empty else pd.DataFrame([{"reason": "no edges"}])
        mask = self.df_edges["ravensRole"].isna() | (self.df_edges["ravensRole"].astype(str).str.strip() == "")
        keep = ["source", "target", "ConnectorID", "Connector_Type", "Diagram", "ravensRole"]
        keep = [c for c in keep if c in self.df_edges.columns]
        out = self.df_edges.loc[mask, keep].copy()
        return None if out.empty else out.reset_index(drop=True)

    def node_roles_unknown(self) -> Optional[pd.DataFrame]:
        """Nodes whose ravensRole is not in the allowed vocabulary (if provided)."""
        if self.allowed_node_roles is None or "ravensRole" not in self.df_nodes.columns:
            return None
        mask = ~self.df_nodes["ravensRole"].isin(self.allowed_node_roles)
        out = self.df_nodes.loc[mask, ["node", "Name", "ravensRole"]].copy()
        return None if out.empty else out.reset_index(drop=True)

    def edge_roles_unknown(self) -> Optional[pd.DataFrame]:
        """Edges whose ravensRole is not in the allowed vocabulary (if provided)."""
        if self.allowed_edge_roles is None or "ravensRole" not in self.df_edges.columns:
            return None
        mask = ~self.df_edges["ravensRole"].isin(self.allowed_edge_roles)
        keep = ["source", "target", "ConnectorID", "Connector_Type", "Diagram", "ravensRole"]
        keep = [c for c in keep if c in self.df_edges.columns]
        out = self.df_edges.loc[mask, keep].copy()
        return None if out.empty else out.reset_index(drop=True)

    # ---------------- reachability (kept from your previous logic) ----------------
    def root_connectivity(self) -> Optional[pd.DataFrame]:
        """
        Strong (directional) connectivity: node is valid iff there exists a directed path
        node -> ... -> Root in G. Returns rows for nodes that CANNOT reach Root.
        """
        if "node" not in self.df_nodes.columns:
            return None
        nodes_to_check = set(self.df_nodes["node"]) & set(self.G.nodes())
        if not nodes_to_check:
            return None

        reachable_to_root = {self.root_id} | nx.descendants(self.G_rev, self.root_id)
        unreachable = sorted(nodes_to_check - reachable_to_root)
        if not unreachable:
            return None

        G_unreach = self.G.subgraph(unreachable).copy()
        chains = list(nx.weakly_connected_components(G_unreach))

        chain_id_map, chain_sizes = {}, {}
        for i, comp in enumerate(chains, start=1):
            for n in comp:
                chain_id_map[n] = i
            chain_sizes[i] = len(comp)

        in_deg = dict(G_unreach.in_degree())
        out_deg = dict(G_unreach.out_degree())

        level_map = {}
        for comp in chains:
            sub = G_unreach.subgraph(comp)
            tops = [n for n in sub if sub.in_degree(n) == 0] or list(sub.nodes())
            for t in tops:
                level_map[t] = max(level_map.get(t, 1), 1)
                for node, dist in nx.single_source_shortest_path_length(sub, t).items():
                    level_map[node] = max(level_map.get(node, 1), dist + 1)

        df = (
            self.df_nodes[self.df_nodes["node"].isin(unreachable)]
            .copy()
            .assign(
                chain_id=lambda d: d["node"].map(chain_id_map),
                chain_size=lambda d: d["chain_id"].map(chain_sizes),
                level=lambda d: d["node"].map(level_map).fillna(1).astype(int),
                in_deg_unreach=lambda d: d["node"].map(in_deg).fillna(0).astype(int),
                out_deg_unreach=lambda d: d["node"].map(out_deg).fillna(0).astype(int),
                Diagram=lambda d: d["node"].map(self.node_diagrams_map).apply(
                    lambda v: ", ".join(v) if isinstance(v, list) else None
                ),
            )
            .sort_values(["chain_id", "level", "Name", "node"])
            .reset_index(drop=True)
        )
        return df

    # ---------------- multiplicity / labels (role-agnostic, still useful) ----------------
    def label_requires_end_mult(self) -> Optional[pd.DataFrame]:
        """Edges with a label but missing end multiplicity."""
        need = {"label", "end_mult"}
        if not need.issubset(self.df_edges.columns):
            return None
        has_label = self.df_edges["label"].notna() & (self.df_edges["label"].astype(str).str.strip() != "")
        missing_end = self.df_edges["end_mult"].isna() | (self.df_edges["end_mult"].astype(str).str.strip() == "")
        invalid = self.df_edges[has_label & missing_end]
        return None if invalid.empty else invalid.reset_index(drop=True)

    # ---------------- basic graph hygiene ----------------
    def duplicate_node_names(self) -> Optional[pd.DataFrame]:
        """Detect duplicate node Names (often undesirable in schemas)."""
        if "Name" not in self.df_nodes.columns:
            return None
        counts = self.df_nodes["Name"].astype(str).value_counts()
        dups = counts[counts > 1].index
        out = self.df_nodes[self.df_nodes["Name"].isin(dups)][["node", "Name", "ravensRole"]].copy() \
              if "ravensRole" in self.df_nodes.columns else \
              self.df_nodes[self.df_nodes["Name"].isin(dups)][["node", "Name"]].copy()
        return None if out.empty else out.sort_values(["Name", "node"]).reset_index(drop=True)

    # ---------------- role coherence (skeleton) ----------------
    def edge_role_endpoint_constraints(self) -> Optional[pd.DataFrame]:
        """
        Skeleton check for endpoint-role constraints per edge role.

        Configure via __init__(edge_role_constraints=[(edge_role_or_None, src_roles, dst_roles), ...])

        Example policy idea (not enforced here by default):
          • ('referenceConnector', {'rootClass','compoundClass'}, {'embeddedClass','rootClass'})
          • (None, {'object','container'}, {'object','container'})  # global fallback

        Returns rows violating any provided constraint(s). If no constraints configured, returns None.
        """
        if not self.edge_role_constraints:
            return None

        # Build a quick lookup of node -> ravensRole
        get_role = self.node_role_map.get

        violations = []
        for idx, row in self.df_edges.iterrows():
            e_role = str(row.get("ravensRole", "")).strip() or None
            src, dst = row["source"], row["target"]
            s_role = get_role(src)
            d_role = get_role(dst)

            for rule_edge_role, allowed_src, allowed_dst in self.edge_role_constraints:
                if rule_edge_role is not None and e_role != rule_edge_role:
                    continue  # rule not applicable to this edge
                if (s_role is not None and s_role not in allowed_src) or (d_role is not None and d_role not in allowed_dst):
                    rec = {
                        "source": src,
                        "target": dst,
                        "source_Name": self.name_map.get(src),
                        "target_Name": self.name_map.get(dst),
                        "source_role": s_role,
                        "target_role": d_role,
                        "edge_role": e_role,
                    }
                    # keep common context columns if present
                    for c in ("ConnectorID","Connector_Type","Diagram","label","start_mult","end_mult"):
                        if c in self.df_edges.columns:
                            rec[c] = row.get(c)
                    violations.append(rec)
                    break  # one rule failure is enough to flag the edge

        return None if not violations else pd.DataFrame(violations)
    
    
    def yellow_role_misclassified(self):
        """
        Find all yellowClass nodes that should be container/substitutable/inheritOnly,
        plus any nodes already typed as one of those three but disagree with the computed type.

        Returns a DataFrame with columns including:
        status, node, Name, current_role, computed_role, Diagram, n_parents,
        is_desc_of_root_or_embedded, is_anc_of_embedded, is_container_chain,
        parents, children
        """
        import networkx as nx
        import pandas as pd

        # ---------- helpers ----------
        def _build_inheritance_graph(G):
            H = nx.DiGraph()
            H.add_nodes_from(G.nodes())
            for u, v, d in G.edges(data=True):
                if d.get("Connector_Type") == "Generalization" and u != v:
                    H.add_edge(int(u), int(v))  # child -> parent
            return H

        def _role_sets(G):
            role = nx.get_node_attributes(G, "ravensRole")
            yellow   = {n for n, r in role.items() if r == "yellowClass"}
            roots    = {n for n, r in role.items() if r == "rootClass"}
            embedded = {n for n, r in role.items() if r == "embeddedClass"}
            return yellow, roots, embedded, role

        def _yellow_descendants_of(H, seeds, restrict):
            if not seeds: return set()
            HR = H.reverse(copy=False)
            out = set()
            for s in seeds:
                if HR.has_node(s):
                    out |= nx.descendants(HR, s)
            return out & restrict

        def _yellow_ancestors_of(H, seeds, restrict):
            if not seeds: return set()
            out = set()
            for s in seeds:
                if H.has_node(s):
                    out |= nx.descendants(H, s)
            return out & restrict

        def _contiguous_yellow_parents_of_roots(H, roots, yellow):
            containers = set()
            for r in roots:
                if not H.has_node(r):
                    continue
                stack = [r]
                seen  = {r}
                while stack:
                    x = stack.pop()
                    for parent in H.successors(x):  # child->parent
                        if parent in seen:
                            continue
                        seen.add(parent)
                        if parent in yellow:
                            containers.add(parent)
                            stack.append(parent)  # continue only through yellow
            return containers

        def _diagram_str(n):
            # 1) from edges (precomputed map)
            names = []
            if hasattr(self, "node_diagrams_map"):
                v = self.node_diagrams_map.get(n)
                if isinstance(v, list):
                    names.extend(v)
            # 2) fallback: from node.instances
            inst = self.G.nodes[n].get("instances")
            if isinstance(inst, dict):
                v = inst.get("DiagramName") or []
                if isinstance(v, list):
                    names.extend(v)
            names = sorted({str(x) for x in names if x})
            return ", ".join(names) if names else None

        # ---------- compute classification ----------
        H = _build_inheritance_graph(self.G)
        yellow, roots, embedded, role_map = _role_sets(self.G)

        substitutable     = _yellow_descendants_of(H, roots | embedded, yellow)
        inherit_from_emb  = _yellow_ancestors_of(H, embedded, yellow) - substitutable
        containers        = _contiguous_yellow_parents_of_roots(H, roots, yellow) - substitutable
        remaining         = yellow - substitutable - inherit_from_emb - containers

        computed = {}
        computed.update({n: "inheritOnlyClass"  for n in inherit_from_emb})
        computed.update({n: "containerClass"    for n in containers})
        computed.update({n: "inheritOnlyClass"  for n in remaining})
        computed.update({n: "substitutableClass" for n in substitutable})

        if not computed:
            return pd.DataFrame(columns=[
                "status","node","Name","current_role","computed_role","Diagram",
                "n_parents","is_desc_of_root_or_embedded","is_anc_of_embedded","is_container_chain",
                "parents","children"
            ])

        df = self.df_nodes[self.df_nodes["node"].isin(computed.keys())][["node","Name"]].copy()

        # evidence flags
        df["is_desc_of_root_or_embedded"] = df["node"].isin(substitutable)
        df["is_anc_of_embedded"]          = df["node"].isin(inherit_from_emb)
        df["is_container_chain"]          = df["node"].isin(containers)

        # inheritance context
        n_parents = {n: (H.out_degree(n) if H.has_node(n) else 0) for n in computed.keys()}
        parents   = {n: (list(H.successors(n)) if H.has_node(n) else []) for n in computed.keys()}
        children  = {n: (list(H.predecessors(n)) if H.has_node(n) else []) for n in computed.keys()}
        df["n_parents"] = df["node"].map(n_parents)
        df["parents"]   = df["node"].map(parents)
        df["children"]  = df["node"].map(children)

        # roles
        df["current_role"]  = df["node"].map(role_map)
        df["computed_role"] = df["node"].map(computed)

        # diagram location
        df["Diagram"] = df["node"].apply(_diagram_str)

        # status
        df["status"] = None
        df.loc[df["current_role"].eq("yellowClass"), "status"] = "needs_update"
        already_specific = df["current_role"].isin(["containerClass","substitutableClass","inheritOnlyClass"])
        df.loc[already_specific & (df["current_role"] != df["computed_role"]), "status"] = "mismatch"

        out = df.dropna(subset=["status"]).copy()
        preferred = ["status","node","Name","current_role","computed_role","Diagram",
                    "n_parents","is_desc_of_root_or_embedded","is_anc_of_embedded","is_container_chain",
                    "parents","children"]
        cols = [c for c in preferred if c in out.columns] + [c for c in out.columns if c not in preferred]
        return out[cols].sort_values(["status","Name","node"]).reset_index(drop=True)


    # ---------------- run-all + summarize ----------------
    def validate(self, include_ok: bool = False, include: Optional[Iterable[str]] = None, exclude: Optional[Iterable[str]] = None):
        checks = {
            # Role presence / vocab
            "node_roles_missing": self.node_roles_missing,
            "edge_roles_missing": self.edge_roles_missing,
            "node_roles_unknown": self.node_roles_unknown,   # no-op if no allowed set given
            "edge_roles_unknown": self.edge_roles_unknown,   # no-op if no allowed set given

            # Structure / semantics
            "node_cant_reach_root": self.root_connectivity,
            "edge_label_requires_end_mult": self.label_requires_end_mult,
            "duplicate_node_names": self.duplicate_node_names,

            # Role coherence (policy-driven skeleton)
            "edge_role_endpoint_constraints": self.edge_role_endpoint_constraints,  # no-op if no constraints given
            "yellow_role_misclassified": self.yellow_role_misclassified,
        }
        sel = set(checks.keys())
        if include is not None:
            sel &= set(include)
        if exclude is not None:
            sel -= set(exclude)

        results = {}
        for cid in sorted(sel):
            df = checks[cid]()
            if df is not None or include_ok:
                results[cid] = df
        return results

    @staticmethod
    def summarize(results: Dict[str, Optional[pd.DataFrame]]) -> pd.DataFrame:
        rows = []
        for cid, df in results.items():
            status = "fail" if isinstance(df, pd.DataFrame) and not df.empty else "ok"
            n = int(len(df)) if isinstance(df, pd.DataFrame) else 0
            rows.append({"check_id": cid, "status": status, "n_rows": n})
        return pd.DataFrame(rows).sort_values(["status", "check_id"]).reset_index(drop=True)


def write_validation_report(path, results, include_ok=False, summary_first=True):
    """
    Write a validation report to Excel with autofit column widths.

    Parameters
    ----------
    path : str
        Output .xlsx file path.
    results : dict
        {check_id: DataFrame or None}, e.g., from ModelValidator.validate().
    include_ok : bool
        If True, include OK checks as empty sheets. Default False (only failing DFs).
    summary_first : bool
        Put Summary as the first sheet.
    """
    def _safe_sheet_name(name, existing):
        base = str(name)[:31] or "Sheet"
        cand = base
        i = 1
        while cand in existing:
            suffix = f"_{i}"
            cand = base[: (31 - len(suffix))] + suffix
            i += 1
        return cand

    # Summary table
    rows = []
    for cid, df in results.items():
        status = "fail" if isinstance(df, pd.DataFrame) and not df.empty else "ok"
        n = int(len(df)) if isinstance(df, pd.DataFrame) else 0
        rows.append({"check_id": cid, "status": status, "n_rows": n})
    summary_df = pd.DataFrame(rows).sort_values(["status", "check_id"]).reset_index(drop=True)

    preferred_order = ['violation_type', 'location', "Diagram", "Name", "Start_Object", "End_Object",
                       'chain_id', 'chain_size', 'level', 'in_deg_unreach', 'out_deg_unreach']

    with pd.ExcelWriter(path, engine="openpyxl") as xl:
        used = set()

        # 1) Summary sheet
        if summary_first:
            sname = _safe_sheet_name("Summary", used)
            summary_df.to_excel(xl, index=False, sheet_name=sname)
            used.add(sname)

        # 2) One sheet per check
        for cid, df in results.items():
            if df is None or (isinstance(df, pd.DataFrame) and df.empty):
                if not include_ok:
                    continue
                out = pd.DataFrame()
            else:
                out = df
                # Reorder columns so preferred ones (if present) come first
                cols = list(out.columns)
                front = [c for c in preferred_order if c in cols]
                rest = [c for c in cols if c not in front]
                if front:
                    out = out[front + rest]

            sname = _safe_sheet_name(cid, used)
            out.to_excel(xl, index=False, sheet_name=sname)
            used.add(sname)

        # --- Autofit column widths for all sheets ---
        workbook = xl.book
        for ws in workbook.worksheets:
            for i, col in enumerate(ws.columns, 1):
                max_len = 0
                col_letter = get_column_letter(i)
                for cell in col:
                    try:
                        val = str(cell.value) if cell.value is not None else ""
                    except Exception:
                        val = ""
                    max_len = max(max_len, len(val))
                # add padding
                adjusted_width = max_len + 2
                ws.column_dimensions[col_letter].width = adjusted_width

    return summary_df


def _find_root_obj(schema: dict, default_title: str = "Root") -> tuple[dict, str]:
    """Return (root_object, root_title)."""
    if isinstance(schema, dict):
        title = schema.get("title") or default_title
        if isinstance(schema.get("properties"), dict):
            return schema, title
    return schema, default_title

def _join(path_tuple: tuple[str, ...]) -> str:
    return "/".join(path_tuple)

def find_highest_belonging(schema: dict, target: str, root_title: str = "Root") -> dict:
    """
    Find the highest-level spot where `target` appears:
      - as a named property (category='property')
      - as an object anyOf variant under some property (category='object_anyOf')
      - as a reference anyOf variant under some property (category='ref_anyOf')
      - as a direct reference property (category='ref_property')
    Returns: {"category", "path", "depth"} (path joined with '/'), or {"category": None, ...} if not found.
    """
    root, title = _find_root_obj(schema, default_title=root_title)
    best = {"category": None, "path": None, "depth": None}

    def consider(category: str, path_tuple: tuple[str, ...]):
        nonlocal best
        depth = len(path_tuple)
        if best["path"] is None or depth < best["depth"]:
            best = {"category": category, "path": _join(path_tuple), "depth": depth}
        elif depth == best["depth"]:
            # Prefer property > object_anyOf > ref_anyOf > ref_property
            order = {"property": 0, "object_anyOf": 1, "ref_anyOf": 2, "ref_property": 3}
            if order.get(category, 99) < order.get(best["category"], 99):
                best = {"category": category, "path": _join(path_tuple), "depth": depth}

    q = deque([(root, (title,))])
    while q:
        node, path = q.popleft()
        if not isinstance(node, dict):
            continue

        props = node.get("properties")
        if isinstance(props, dict):
            for prop_name, child in props.items():
                ppath = path + (prop_name,)

                # A) Named property match
                if prop_name == target:
                    consider("property", ppath)

                # B) Direct ref or array-of-refs
                if isinstance(child, dict):
                    if child.get("$objectType") == "reference" and child.get("$objectId") == target:
                        consider("ref_property", ppath)

                    if child.get("type") == "array":
                        items = child.get("items")
                        if isinstance(items, dict):
                            if items.get("$objectType") == "reference" and items.get("$objectId") == target:
                                consider("ref_property", ppath)
                            if isinstance(items.get("anyOf"), list):
                                for ent in items["anyOf"]:
                                    if isinstance(ent, dict) and ent.get("$objectId") == target:
                                        consider("ref_anyOf" if ent.get("$objectType") == "reference" else "object_anyOf", ppath)

                    # C) anyOf under the property
                    if isinstance(child.get("anyOf"), list):
                        for ent in child["anyOf"]:
                            if isinstance(ent, dict) and ent.get("$objectId") == target:
                                consider("ref_anyOf" if ent.get("$objectType") == "reference" else "object_anyOf", ppath)

                    # D) Traverse deeper
                    if isinstance(child.get("properties"), dict):
                        q.append((child, ppath))
                    if isinstance(child.get("anyOf"), list):
                        # Traverse object-anyOf entries (they may have 'properties'); skip reference entries
                        for ent in child["anyOf"]:
                            if isinstance(ent, dict) and ent.get("$objectType") != "reference" and isinstance(ent.get("properties"), dict):
                                ent_name = ent.get("$objectId") or "<anon>"
                                q.append((ent, ppath + (f"[anyOf:{ent_name}]",)))

    return best

# ---------- Variant listing at a found path ----------

def _get_by_path(schema: dict, path: str) -> dict | None:
    """Return the object at 'A/B/C' where segments are property names from Root downward."""
    if not path:
        return None
    segs = path.split("/")
    node, title = _find_root_obj(schema, default_title=segs[0])
    if segs[0] != title:
        # if first segment isn't the real title, still try from top
        node, _ = _find_root_obj(schema)
    for seg in segs[1:]:
        props = node.get("properties", {})
        if seg in props:
            node = props[seg]
            continue
        # allow stepping onto an anyOf wrapper node via property segment
        # if a previous seg selected a property, its value is 'node' already
        # (we don't step into [anyOf:*] pseudo-nodes here)
        return None
    return node

def list_variants_at_path(schema: dict, path: str) -> dict:
    """
    From a property node at 'path', list anyOf variants that belong there.
    Returns:
      {
        "object_anyOf": [names...],   # $objectId from entries without $objectType:'reference'
        "ref_anyOf":    [names...],   # $objectId from entries with    $objectType:'reference'
        "has_properties": bool,
        "properties_keys": [keys...]  # only if a 'properties' dict exists
      }
    """
    out = {"object_anyOf": [], "ref_anyOf": [], "has_properties": False, "properties_keys": []}
    node = _get_by_path(schema, path)
    if not isinstance(node, dict):
        return out

    if isinstance(node.get("anyOf"), list):
        for ent in node["anyOf"]:
            if not isinstance(ent, dict):
                continue
            nm = ent.get("$objectId")
            if not nm:
                continue
            if ent.get("$objectType") == "reference":
                out["ref_anyOf"].append(nm)
            else:
                out["object_anyOf"].append(nm)

    props = node.get("properties")
    if isinstance(props, dict):
        out["has_properties"] = True
        out["properties_keys"] = sorted(props.keys(), key=str.casefold)

    out["object_anyOf"].sort(key=str.casefold)
    out["ref_anyOf"].sort(key=str.casefold)
    return out

# ---------- schema load / root helpers ----------

def _load_schema(p: str) -> dict:
    return json.loads(Path(p).read_text(encoding="utf-8"))

def _root_obj(schema: dict, default_title: str = "Root") -> tuple[dict, str]:
    """Return (root_object, root_title)."""
    if isinstance(schema, dict) and isinstance(schema.get("properties"), dict):
        return schema, schema.get("title", default_title) or default_title
    return schema, default_title

def _get_by_path(schema: dict, path: str) -> dict | None:
    """Follow 'A/B/C' through properties; returns node dict or None."""
    if not path:
        return None
    segs = path.split("/")
    node, title = _root_obj(schema, default_title=segs[0])
    # tolerate when first seg != actual title
    if segs[0] != title:
        node, _ = _root_obj(schema)
    for seg in segs[1:]:
        props = node.get("properties", {})
        if seg in props:
            node = props[seg]
        else:
            return None
    return node

# ---------- occurrence search (highest-level) ----------

def find_highest_occurrence(schema: dict, target: str, root_title: str = "Root") -> dict:
    """
    Return {'category','path','depth'} for the highest-level spot where `target` appears,
    preferring a *named property* if it exists anywhere (even if deeper than some anyOf).
      categories:
        - 'root'            (if target == root title)
        - 'property'        (named property: "... target ...": { ... })
        - 'object_anyOf'    (anyOf entry with $objectId == target and not a reference)
        - 'ref_anyOf'       (anyOf entry that's a reference)
        - 'ref_property'    (direct reference property or array-of-refs)
    """
    from collections import deque

    root, title = _root_obj(schema, default_title=root_title)

    # special case: the root object itself
    if target == title:
        return {"category": "root", "path": title, "depth": 1}

    # keep the shallowest hit per category
    best = {
        "property": None,
        "object_anyOf": None,
        "ref_anyOf": None,
        "ref_property": None,
    }

    def _consider(cat: str, path_tuple: tuple[str, ...]):
        d = len(path_tuple)
        curr = best.get(cat)
        if curr is None or d < curr["depth"]:
            best[cat] = {"category": cat, "path": "/".join(path_tuple), "depth": d}

    q = deque([(root, (title,))])
    while q:
        node, path = q.popleft()
        if not isinstance(node, dict):
            continue

        props = node.get("properties")
        if isinstance(props, dict):
            for pname, child in props.items():
                ppath = path + (pname,)

                # Named property match: "target": { ... }
                if pname == target:
                    _consider("property", ppath)

                if not isinstance(child, dict):
                    continue

                # anyOf under this property
                anyof = child.get("anyOf")
                if isinstance(anyof, list):
                    for ent in anyof:
                        if isinstance(ent, dict) and ent.get("$objectId") == target:
                            if ent.get("$objectType") == "reference":
                                _consider("ref_anyOf", ppath)
                            else:
                                _consider("object_anyOf", ppath)

                # direct reference (or array of references)
                if child.get("$objectType") == "reference" and child.get("$objectId") == target:
                    _consider("ref_property", ppath)
                if child.get("type") == "array" and isinstance(child.get("items"), dict):
                    it = child["items"]
                    if it.get("$objectType") == "reference" and it.get("$objectId") == target:
                        _consider("ref_property", ppath)
                    iany = it.get("anyOf")
                    if isinstance(iany, list):
                        for ent in iany:
                            if isinstance(ent, dict) and ent.get("$objectId") == target:
                                _consider("ref_anyOf" if ent.get("$objectType") == "reference" else "object_anyOf", ppath)

                # traverse deeper
                if isinstance(child.get("properties"), dict):
                    q.append((child, ppath))
                if isinstance(child.get("anyOf"), list):
                    for ent in child["anyOf"]:
                        if isinstance(ent, dict) and ent.get("$objectType") != "reference" and isinstance(ent.get("properties"), dict):
                            nm = ent.get("$objectId") or "<anon>"
                            q.append((ent, ppath + (f"[anyOf:{nm}]",)))

    # choose in strict priority order: property > object_anyOf > ref_anyOf > ref_property
    for cat in ("property", "object_anyOf", "ref_anyOf", "ref_property"):
        if best[cat] is not None:
            return best[cat]

    return {"category": None, "path": None, "depth": None}

# ---------- belonging enumeration ----------

def enumerate_belonging_levels(schema: dict, at_path: str) -> tuple[list[str], list[str]]:
    """
    Return (lev1, lev2plus) belonging sets for node at 'at_path'.
    Belonging includes:
      • immediate property names
      • object-anyOf variant names ($objectId), not references
    LEV2+ includes all deeper descendants’ property names and object-anyOf names (deduped),
    excluding items already in LEV1.
    """
    node = _get_by_path(schema, at_path) if at_path else None
    if not isinstance(node, dict):
        # special case: if at_path == 'Root' and _get_by_path failed, it means the schema root is the node
        root, title = _root_obj(schema)
        if at_path == title:
            node = root
        else:
            return [], []

    lev1 = set()
    lev2 = set()

    # collect level 1
    props = node.get("properties")
    if isinstance(props, dict):
        lev1.update(props.keys())

    anyof = node.get("anyOf")
    if isinstance(anyof, list):
        for ent in anyof:
            if isinstance(ent, dict) and ent.get("$objectType") != "reference":
                nm = ent.get("$objectId")
                if nm:
                    lev1.add(nm)

    # traverse deeper (BFS) to build LEV2+
    q = deque()

    # seed with immediate children nodes we can descend into
    if isinstance(props, dict):
        for pname, child in props.items():
            if isinstance(child, dict):
                q.append(child)
    if isinstance(anyof, list):
        for ent in anyof:
            if isinstance(ent, dict) and ent.get("$objectType") != "reference":
                q.append(ent)

    while q:
        cur = q.popleft()
        if not isinstance(cur, dict):
            continue

        cprops = cur.get("properties")
        if isinstance(cprops, dict):
            for pname, child in cprops.items():
                if pname not in lev1:
                    lev2.add(pname)
                if isinstance(child, dict):
                    q.append(child)

        cany = cur.get("anyOf")
        if isinstance(cany, list):
            for ent in cany:
                if isinstance(ent, dict) and ent.get("$objectType") != "reference":
                    nm = ent.get("$objectId")
                    if nm and nm not in lev1:
                        lev2.add(nm)
                    q.append(ent)

    lev1_list = sorted(lev1, key=str.casefold)
    lev2_list = sorted(lev2 - lev1, key=str.casefold)
    return lev1_list, lev2_list

# ---------- pretty diff & report ----------

def _diff_lists(a: list[str], b: list[str]) -> dict:
    return {
        "hand_only": sorted(set(a) - set(b), key=str.casefold),
        "auto_only": sorted(set(b) - set(a), key=str.casefold),
        "both":      sorted(set(a) & set(b), key=str.casefold),
    }

def compare_belonging_levels(
    object_name: str,
    root_title: str = "Root",
    max_lev: int = 1,
) -> Dict[int, pd.DataFrame]:
    """
    Compare 'belonging' for any object (incl. 'Root') up to max_lev.

    Returns:
      { level:int -> pandas.DataFrame(index=<names>, columns=['HAND','AUTO']) }

    Rules:
      • "Belonging" == immediate property keys + object-anyOf variant $objectId.
      • Reference-anyOf entries are ignored for belonging.
      • Each name is counted at its shallowest level only.
      • Cells are True if present at that level, else None (blank).
    """
    hand = _load_schema(_TEMPLATE_JSON_PATH)
    auto = _load_schema(_TEMPLATE_AUTOJSON_PATH)

    h_occ = find_highest_occurrence(hand, object_name, root_title=root_title)
    a_occ = find_highest_occurrence(auto, object_name, root_title=root_title)

    # Resolve the node paths where we start belonging enumeration
    h_path = (root_title if h_occ.get("category") == "root" else h_occ.get("path"))
    a_path = (root_title if a_occ.get("category") == "root" else a_occ.get("path"))

    # Enumerate belonging by level (empty dicts if not found)
    h_levels = enumerate_belonging_by_levels(hand, h_path, max_lev) if h_path else {lev: [] for lev in range(1, max_lev + 1)}
    a_levels = enumerate_belonging_by_levels(auto, a_path, max_lev) if a_path else {lev: [] for lev in range(1, max_lev + 1)}

    out: Dict[int, pd.DataFrame] = {}
    for lev in range(1, max_lev + 1):
        hset = set(h_levels.get(lev, []))
        aset = set(a_levels.get(lev, []))
        names = sorted(hset | aset, key=str.casefold)

        df = pd.DataFrame(index=names, columns=["HAND", "AUTO"])
        if names:
            df["HAND"] = [True if n in hset else '' for n in names]
            df["AUTO"] = [True if n in aset else '' for n in names]
        out[lev] = df

    return out

from typing import Dict, List, Set

def enumerate_belonging_by_levels(schema: dict, at_path: str, max_lev: int = 1) -> Dict[int, List[str]]:
    """
    Return {level -> [names]} for 1..max_lev, where names are:
      • if the node has object-anyOf entries at that level: the variants' $objectId
      • otherwise: the node's immediate property keys
    Reference-anyOf entries are ignored for belonging.

    Traversal is BFS over 'properties' and object-anyOf entries. Each name is
    recorded at its shallowest level only.
    """
    if max_lev < 1:
        max_lev = 1

    # locate the starting node (object_name's highest occurrence path was already found upstream)
    node = _get_by_path(schema, at_path) if at_path else None
    if not isinstance(node, dict):
        root, title = _root_obj(schema)
        if at_path == title:
            node = root
        else:
            return {lev: [] for lev in range(1, max_lev + 1)}

    by_level: Dict[int, Set[str]] = {lev: set() for lev in range(1, max_lev + 1)}
    seen_name_level: Dict[str, int] = {}
    visited_nodes: Set[int] = set()

    from collections import deque
    q = deque([(node, 0)])
    visited_nodes.add(id(node))

    def _enqueue(child, next_depth: int):
        if next_depth > max_lev:
            return
        if isinstance(child, dict):
            cid = id(child)
            if cid not in visited_nodes:
                visited_nodes.add(cid)
                q.append((child, next_depth))

    while q:
        cur, depth = q.popleft()
        if not isinstance(cur, dict):
            continue

        lev = depth + 1
        if lev > max_lev:
            continue

        # Gather object-anyOf variant names (non-reference entries only)
        variants = []
        anyof = cur.get("anyOf")
        if isinstance(anyof, list):
            for ent in anyof:
                if isinstance(ent, dict) and ent.get("$objectType") != "reference":
                    nm = ent.get("$objectId")
                    if nm:
                        variants.append(nm)

        # If object-anyOf exists at this node, we ONLY record those names at this level
        if variants:
            for nm in variants:
                if nm not in seen_name_level:
                    by_level[lev].add(nm)
                    seen_name_level[nm] = lev
            # enqueue variants for deeper traversal
            for ent in anyof:
                if isinstance(ent, dict) and ent.get("$objectType") != "reference":
                    _enqueue(ent, depth + 1)

            # still enqueue properties for deeper levels, but DO NOT record property names at this level
            props = cur.get("properties")
            if isinstance(props, dict):
                for _, child in props.items():
                    _enqueue(child, depth + 1)
            continue  # skip recording properties at this level

        # Otherwise (no object-anyOf here): record immediate property names at this level
        props = cur.get("properties")
        if isinstance(props, dict):
            for pname, child in props.items():
                if pname not in seen_name_level:
                    by_level[lev].add(pname)
                    seen_name_level[pname] = lev
                _enqueue(child, depth + 1)

        # Also traverse anyOf entries (if present) for deeper levels
        if isinstance(anyof, list):
            for ent in anyof:
                if isinstance(ent, dict) and ent.get("$objectType") != "reference":
                    _enqueue(ent, depth + 1)

    return {lev: sorted(by_level[lev], key=str.casefold) for lev in range(1, max_lev + 1)}


# --- helper: load (no guardrails) ---
def _load_schema(p: Path) -> dict:
    return json.loads(Path(p).read_text(encoding="utf-8"))

# --- helper: collect all object-anyOf property names across a schema ---
def _collect_anyof_object_names(schema: dict) -> set[str]:
    """
    Returns the set of property *names* for which the property's value
    contains an 'anyOf' with at least one non-reference entry.
    (Ignores reference-anyOfs and doesn't care about nesting depth.)
    """
    from collections import deque
    out: set[str] = set()
    q = deque([schema])
    seen_ids = {id(schema)}
    while q:
        node = q.popleft()
        if not isinstance(node, dict):
            continue

        props = node.get("properties")
        if isinstance(props, dict):
            for pname, child in props.items():
                if isinstance(child, dict):
                    anyof = child.get("anyOf")
                    if isinstance(anyof, list):
                        # object-anyOf if ANY entry is NOT a reference
                        if any(isinstance(ent, dict) and ent.get("$objectType") != "reference" for ent in anyof):
                            out.add(pname)
                    # traverse deeper
                    cid = id(child)
                    if cid not in seen_ids:
                        seen_ids.add(cid)
                        q.append(child)

        # also traverse object-anyOf entries (not refs) in case deeper properties contain more anyOfs
        anyof_here = node.get("anyOf")
        if isinstance(anyof_here, list):
            for ent in anyof_here:
                if isinstance(ent, dict) and ent.get("$objectType") != "reference":
                    eid = id(ent)
                    if eid not in seen_ids:
                        seen_ids.add(eid)
                        q.append(ent)

    return out

# --- main: compare object-anyOf presence across HAND vs AUTO ---
def compare_anyof_objects(
    hand_path: Path = _TEMPLATE_JSON_PATH,
    auto_path: Path = _TEMPLATE_AUTOJSON_PATH,
) -> pd.DataFrame:
    """
    Scan both templates and report which *property names* are defined as object-anyOf.
    Returns a single DataFrame with index = object name, columns ['HAND','AUTO'].
      • True if present as object-anyOf in that template
      • '' (empty string) otherwise
    """
    hand = _load_schema(hand_path)
    auto = _load_schema(auto_path)

    hand_names = _collect_anyof_object_names(hand)
    auto_names = _collect_anyof_object_names(auto)

    names = sorted(hand_names | auto_names, key=str.casefold)
    df = pd.DataFrame(index=names, columns=["HAND", "AUTO"])
    if names:
        df["HAND"] = [True if n in hand_names else "" for n in names]
        df["AUTO"] = [True if n in auto_names else "" for n in names]
    return df



# def con_colors_by_type(G):
#     """
#     Returns connector instances whose colors do not correspond to
#     their type. There are three types: 'Association', 'Aggregation', 'Generalization'.
#     Generalizations should be black; Associations and Aggregations can be red or green.
#     """
#     col_dict = {'Association' : ["#800000", "#2e8b57"],
#                 'Aggregation' : ["#800000", "#2e8b57"],
#                 'Generalization' : ["#000000", 'default']}
#     df = nx.to_pandas_edgelist(G)
#     mismatches = []
#     for _, row in df.iterrows():
#         if row['c_Connector_Type'] not in col_dict:
#             print(row['c_Connector_Type'])
#         else:
#             if row['c_linecolor'] not in col_dict[row['c_Connector_Type']]:
#                 mismatches.append(row) 

#     if len(mismatches) > 0:
#         mismatches = pd.DataFrame(mismatches)

#     return mismatches


def nominal_color(ea_hex):
    """
    Convert HEX format to a nominal color name.
    """

    if str(ea_hex) in ['None', 'default']:
        return str(ea_hex)
    
    if ea_hex not in ravens_colors:
        print(f"{ea_hex} not in dictionary.")
        return 'wrong'
    else:
        return ravens_colors[ea_hex]


def obj_colors_defaults_and_nones(G):
    """
    Returns a dictionary objects that have no assigned colors.
    """
    dns = {}
    for node_id, data in G.nodes(data=True):
        if 'instances' in data:
            for i in range(len(data['instances']['Package_ID'])):
                if data['instances']['ObjectColorHex'][i] in [None, 'None', 'default']:
                    this_obj_loc = '.'.join((data['instances']['Package_Name'][i], data['instances']['DiagramName'][i], data['Name']))
                    dns[this_obj_loc] = data['instances']['ObjectColor'][i]
    
    return dns


def reorder_like_template(source: dict):
    """
    Return a *new* dict where every nested `properties` object is reordered
    to match the template's key order (Python ≥3.7 keeps that order).
    Keys that don’t exist in the template are appended A-Z.
    """
    template = json.loads(_TEMPLATE_JSON_PATH.read_text()) # dict/list in `data````

    if not isinstance(source, dict):
        return source  # primitives / lists are unchanged

    # If this level has a `properties` member, reorder it
    if "properties" in source and "properties" in template:
        src_props = source["properties"]
        tmpl_props = template["properties"]

        # Desired order: first the keys that appear in the template (in order),
        # then any extra keys (alphabetically) so nothing is lost.
        ordered_keys = list(tmpl_props) + sorted(k for k in src_props if k not in tmpl_props)

        source = {
            **{k: v for k, v in source.items() if k != "properties"},
            "properties": OrderedDict(
                (k, reorder_like_template(src_props[k]))
                for k in ordered_keys if k in src_props
            ),
        }

    # Recurse into every value to catch nested `properties` blocks
    return {
        k: reorder_like_template(v)
        if isinstance(v, dict) else v
        for k, v in source.items()
    }


def save_auto_template(auto_template):
    path_auto_template = _TEMPLATE_JSON_PATH.parent / 'template_auto.json'
    auto_template = reorder_like_template(auto_template)

    with open(path_auto_template, "w") as f:
        json.dump(auto_template, f, indent=2)

    return

def compare_templates():
    from ravens.data import _TEMPLATE_AUTOJSON_PATH, _TEMPLATE_JSON_PATH

    # hand = curated reference; auto = freshly generated
    hand_path = _TEMPLATE_JSON_PATH
    auto_path = _TEMPLATE_AUTOJSON_PATH

    tpl_hand = json.loads(hand_path.read_text(encoding="utf-8"))
    tpl_auto = json.loads(auto_path.read_text(encoding="utf-8"))

    def walk(node, prefix=()):
        if len(prefix) >= 3:
            return
        if isinstance(node, dict) and node.get("type") == "array":
            node = node["items"]
        if isinstance(node, dict) and "$objectType" in node:
            yield prefix, node
        if isinstance(node, dict):
            for k, v in node.get("properties", {}).items():
                yield from walk(v, prefix + (k,))
            for v in node.get("anyOf", []):
                label = v.get("$objectId") or v.get("$objectType") or "?"
                yield from walk(v, prefix + (f"|{label}",))

    def flatten(tpl):
        out = {}
        for p, n in walk(tpl):
            sig = {
                "kind"      : n["$objectType"],
                "objectId"  : n.get("$objectId"),
                "primary"   : n.get("$primaryObjectHash"),
                "secondary" : n.get("$secondaryObjectHash"),
                "refPath"   : n.get("$referencePath"),
            }
            out["/".join(p)] = sig
        return out

    flat_hand = flatten(tpl_hand)
    flat_auto = flatten(tpl_auto)

    only_in_hand = flat_hand.keys() - flat_auto.keys()
    only_in_auto = flat_auto.keys() - flat_hand.keys()
    in_both      = flat_hand.keys() & flat_auto.keys()

    def sig_diff(a, b):
        diff = {}
        for k in a.keys() | b.keys():
            av, bv = a.get(k), b.get(k)
            if av != bv and not (av is None and bv is None):
                diff[k] = (av, bv)
        return diff

    changed = {p: sig_diff(flat_hand[p], flat_auto[p])
               for p in in_both
               if sig_diff(flat_hand[p], flat_auto[p])}

    print("="*60)
    print("🟢  EXACT MATCH:", len(in_both) - len(changed))
    print("➖  Missing in auto :", len(only_in_hand))
    print("➕  New in auto     :", len(only_in_auto))
    print("✏️  Signature diff  :", len(changed))
    print("="*60)

    def sample(paths, label, n=5):
        if not paths: return
        print(f"\n{label}  ({len(paths)}):")
        for p in sorted(list(paths)[:n]):
            print("   ", p)

    sample(only_in_hand, "➖  only in hand-crafted")
    sample(only_in_auto, "➕  only in auto")
    sample(changed.keys(), "✏️  changed signature")


# ------------------ Functions to match EA model to hand template  --------------

Json = Dict[str, object]

def _load_json(hand: Union[str, Json]) -> Json:
    if isinstance(hand, dict):
        return hand
    with open(str(hand), "r", encoding="utf-8") as f:
        return json.load(f)

def _label_for(node: dict, prop_name: Optional[str]) -> str:
    # Prefer explicit $objectId; else use the property name that introduced this node.
    return str(node.get("$objectId") or prop_name or "").strip()

def _iter_nodes(node: object, prop_name: Optional[str] = None):
    """
    Yield (prop_name, node_dict) for every object-bearing dict in the schema tree.
    This treats anything with a 'properties' or 'anyOf' as a node worth inspecting.
    """
    if not isinstance(node, dict):
        return
    yield (prop_name, node)

    # Dive into properties
    props = node.get("properties")
    if isinstance(props, dict):
        for k, v in props.items():
            _k = str(k)
            for item in _iter_nodes(v, _k):
                yield item

    # Dive into anyOf alternatives
    if isinstance(node.get("anyOf"), list):
        for v in node["anyOf"]:
            for item in _iter_nodes(v, prop_name):
                yield item

def _collect_reference_names(node: object) -> Set[str]:
    """
    Collect base-class names that appear inside $referencePath strings.
    We split on '/' and then strip any trailing '.Something' part.
    """
    names: Set[str] = set()

    def walk(n: object):
        if isinstance(n, dict):
            # capture any $referencePath if present
            rp = n.get("$referencePath")
            if isinstance(rp, str) and rp:
                for seg in rp.split("/"):
                    seg = seg.strip()
                    if not seg:
                        continue
                    base = seg.split(".", 1)[0]
                    if base:
                        names.add(base)
            # recurse
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)

    walk(node)
    return names

def _name_to_unique_id_map(ug: UMLGraphs) -> Dict[str, int]:
    """
    Build a name->Object_ID map, **only** for unique names.
    If a name maps to multiple IDs, we do not include it (we'll warn later).
    """
    name_to_ids: Dict[str, Set[int]] = {}
    objs = ug.uml_data.objects
    for oid, row in objs.iterrows():
        if str(row.get("Object_Type", "")) != "Class":
            continue
        nm = str(row.get("Name") or "").strip()
        if not nm:
            continue
        s = name_to_ids.setdefault(nm, set())
        s.add(int(oid))
    uniq: Dict[str, int] = {nm: next(iter(s)) for nm, s in name_to_ids.items() if len(s) == 1}
    return uniq

def guess_notconcrete_roles_from_hand(path_to_hand_template, ug) -> dict:
    """
    Infer notConcrete roles from the hand template.

    Rules:
      • $objectType == "container"  -> containerClass
      • node with "anyOf"           -> substitutableClass
      • otherwise                   -> inheritOnlyClass (default)
    Precedence: substitutable > container > inheritOnly.
    Nodes already concrete in EA (rootClass/embeddedClass) are skipped.
    """

    # Load hand template (path or dict)
    hand = (
        json.loads(path_to_hand_template.read_text(encoding="utf-8"))
        if not isinstance(path_to_hand_template, dict)
        else path_to_hand_template
    )

    # --- collect names from hand template ---
    names_container: set[str] = set()
    names_substitutable: set[str] = set()
    names_seen: set[str] = set()

    for prop_name, node in _iter_nodes(hand):
        if not isinstance(node, dict):
            continue
        label = _label_for(node, prop_name)  # prefers $objectId, falls back to prop name
        if not label:
            continue
        names_seen.add(label)
        if str(node.get("$objectType") or "") == "container":
            names_container.add(label)
        if isinstance(node.get("anyOf"), list):
            names_substitutable.add(label)

    # also pick up base names seen inside $referencePath (e.g., "Root/Versions.IEC61968CIMVersion")
    names_seen |= _collect_reference_names(hand)

    # default the rest to inheritOnly (and never try to tag literal Root)
    names_inheritonly: set[str] = set(n for n in names_seen if n not in names_container | names_substitutable and n != "Root")

    # --- resolve names -> unique Object_IDs ---
    uniq = _name_to_unique_id_map(ug)  # builds unique name->Object_ID map from EA objects

    def resolve(name_set: set[str], bucket_label: str) -> set[int]:
        ids, unresolved = set(), []
        for nm in sorted(name_set):
            oid = uniq.get(nm)
            if oid is None:
                unresolved.append(nm)
            else:
                ids.add(int(oid))
        if unresolved:
            print(f"[infer] Unresolved class names ({bucket_label}): " + ", ".join(unresolved))
        return ids

    raw_container_ids     = resolve(names_container,    "containerClass")
    raw_substitutable_ids = resolve(names_substitutable,"substitutableClass")
    raw_inheritonly_ids   = resolve(names_inheritonly,  "inheritOnlyClass")

    # --- skip anything already concrete in EA ---
    def is_concrete(oid: int) -> bool:
        r = (ug.role_for_object(oid) or "").strip()
        return r in ("rootClass", "embeddedClass")

    raw_container_ids     = {i for i in raw_container_ids     if not is_concrete(i)}
    raw_substitutable_ids = {i for i in raw_substitutable_ids if not is_concrete(i)}
    raw_inheritonly_ids   = {i for i in raw_inheritonly_ids   if not is_concrete(i)}

    # --- precedence & disjointness: substitutable > container > inheritOnly ---
    sub_ids = set(raw_substitutable_ids)
    con_ids = set(raw_container_ids) - sub_ids
    inh_ids = set(raw_inheritonly_ids) - sub_ids - con_ids

    return {
        "substitutableClass": sorted(sub_ids),
        "containerClass":     sorted(con_ids),
        "inheritOnlyClass":   sorted(inh_ids),
    }

def sync_ea_roles_to_hand_template(
    ug: UMLGraphs,
    *,
    hand: Union[str, Json],
    out_path: Optional[str] = None,
    print_to_console: bool = True,
) -> str:
    """
    One-shot convenience:
      1) Infer role sets from hand template
      2) Generate the EA JScript using ug.export_ea_jscript_all(role_sets=...)

    Returns the JScript string. Optionally writes it to out_path.
    """
    role_sets = guess_notconcrete_roles_from_hand(hand, ug)
    return ug.export_ea_jscript_all(role_sets=role_sets, out_path=out_path, print_to_console=print_to_console)




