import json
import pandas as pd
import networkx as nx
from collections import OrderedDict
from pprint import pprint
from ravens.uml.legend import ravens_colors
from openpyxl.utils import get_column_letter

from ravens.data import _TEMPLATE_JSON_PATH

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
    # ------------------------------------------------------------------
    # 0.  Load files – adjust paths
    # ------------------------------------------------------------------
    hand_path = _TEMPLATE_AUTOJSON_PATH        # hand-crafted reference
    auto_path = _TEMPLATE_JSON_PATH   # freshly generated

    tpl_hand = json.loads(hand_path.read_text(encoding="utf-8"))
    tpl_auto = json.loads(auto_path.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------
    # 1.  Flatten each template into {path_str: signature_dict}
    # ------------------------------------------------------------------
    def walk(node, prefix=()):
        if len(prefix) >= 3:      # Root / Child / Grandchild
            return

        """Yield (path_tuple, leaf_dict) for every object / container / reference."""
        # unwrap array wrapper
        if isinstance(node, dict) and node.get("type") == "array":
            node = node["items"]

        # identify leaves we care about
        if isinstance(node, dict) and "$objectType" in node:
            yield prefix, node

        # traverse children
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
                "kind"      : n["$objectType"],                    # object / container / reference
                "objectId"  : n.get("$objectId"),
                "primary"   : n.get("$primaryObjectHash"),
                "secondary" : n.get("$secondaryObjectHash"),
                "refPath"   : n.get("$referencePath"),
            }
            out["/".join(p)] = sig
        return out

    flat_hand = flatten(tpl_hand)
    flat_auto = flatten(tpl_auto)

    # ------------------------------------------------------------------
    # 2.  Compare
    # ------------------------------------------------------------------
    only_in_hand = flat_hand.keys() - flat_auto.keys()
    only_in_auto = flat_auto.keys() - flat_hand.keys()
    in_both      = flat_hand.keys() & flat_auto.keys()

    # helper to diff signature dicts (ignores None == missing)
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


    # ------------------------------------------------------------------
    # 3.  Human-friendly report
    # ------------------------------------------------------------------
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




# class ModelValidator:
#     """
#     Runs RAVENS-specific validations on a directed NetworkX graph created from EA database tables.
#     - Each check returns None (pass) or a DataFrame (fail).
#     - validate() returns {check_id: df_or_None}.
#     """

#     def __init__(self, G, root_name="Root"):
#         self.G = G
#         self.G_rev = G.reverse(copy=False)
#         self.root_name = root_name

#         # Try to import ravens_colors (node/connector color definitions)
#         try:
#             from ravens.uml.legend import ravens_colors as _ravens_colors
#             self.ravens_colors = _ravens_colors
#         except Exception:
#             self.ravens_colors = {}

#         # Build DataFrames from G
#         self.df_edges = nx.to_pandas_edgelist(G)  # expects edge attrs already on G
#         self.df_nodes = self._to_pandas_nodelist(G)

#         # Caches from DFs
#         self.name_map = (
#             self.df_nodes.set_index("node")["Name"].to_dict()
#             if "Name" in self.df_nodes.columns else {}
#         )
#         self.node_color_map = (
#             self.df_nodes.set_index("node")["ObjectColor"]
#             .astype(str).str.strip().str.lower()
#             .to_dict()
#             if "ObjectColor" in self.df_nodes.columns else {}
#         )
#         self.node_diagrams_map = (
#             pd.concat(
#                 [
#                     self.df_edges[["source", "Diagram"]].rename(columns={"source": "node"}),
#                     self.df_edges[["target", "Diagram"]].rename(columns={"target": "node"}),
#                 ],
#                 ignore_index=True,
#             )
#             .dropna(subset=["node"])
#             .groupby("node")["Diagram"]
#             .apply(lambda x: sorted(set(x.dropna().astype(str))))
#             .to_dict()
#             if "Diagram" in self.df_edges.columns else {}
#         )

#         # Resolve root id from node DF
#         if "Name" not in self.df_nodes.columns:
#             raise ValueError("df_nodes has no 'Name' column; cannot resolve Root.")
#         hits = self.df_nodes.loc[self.df_nodes["Name"] == self.root_name, "node"]
#         if hits.empty:
#             raise ValueError("No node named '{}' in df_nodes.".format(self.root_name))
#         if len(hits) > 1:
#             raise ValueError("Multiple nodes named '{}' in df_nodes.".format(self.root_name))
#         self.root_id = int(hits.iloc[0])
#         if self.root_id not in self.G:
#             raise ValueError("Resolved root id {} not present in graph.".format(self.root_id))

#     @staticmethod
#     def _to_pandas_nodelist(G):
#         """Build a nodes DataFrame: one row per node with attributes expanded."""
#         rows = []
#         for n, attrs in G.nodes(data=True):
#             row = {"node": n}
#             row.update(attrs or {})
#             rows.append(row)
#         return pd.DataFrame(rows) if rows else pd.DataFrame(columns=["node"])

#     # ---------------- object color checks ----------------
#     def obj_colors_invalid(self):
#         """
#         1) Invalid instance colors (not in ravens_colors.values() or {'None','default'})
#         2) Uncolored nodes (no instance uses a valid ravens color)
#         -> emits one row per instance (location, color)
#         """
#         rows = []
#         valid_values = set(self.ravens_colors.values())
#         ok_for_invalid_check = valid_values | {"None", "default"}

#         for node_id, data in self.G.nodes(data=True):
#             instances = data.get("instances") or {}
#             name = data.get("Name")

#             pkgs  = instances.get("Package_Name", []) or []
#             diags = instances.get("DiagramName", []) or []
#             cols  = instances.get("ObjectColor", []) or []
#             hexes = instances.get("ObjectColorHex", []) or []

#             # 1) Instance-level invalid colors (exclude 'None'/'default' from being "invalid")
#             for i, c in enumerate(cols):
#                 if c not in ok_for_invalid_check:
#                     loc = "{}.{}.{}".format(
#                         pkgs[i] if i < len(pkgs) else None,
#                         diags[i] if i < len(diags) else None,
#                         name,
#                     )
#                     rows.append({
#                         "violation_type": "invalid_color_instance",
#                         "node": node_id,
#                         "Name": name,
#                         "location": loc,
#                         "color": c,
#                         "color_hex": hexes[i] if i < len(hexes) else None,
#                     })

#             # 2) Node-level uncolored: no valid RAVENS color across any instance
#             has_any_valid = any(c in valid_values for c in cols)
#             if not has_any_valid:
#                 if cols:
#                     m = max(len(pkgs), len(diags), len(cols))
#                     for i in range(m):
#                         loc = "{}.{}.{}".format(
#                             pkgs[i] if i < len(pkgs) else None,
#                             diags[i] if i < len(diags) else None,
#                             name,
#                         )
#                         rows.append({
#                             "violation_type": "uncolored_node",
#                             "node": node_id,
#                             "Name": name,
#                             "location": loc,
#                             "color": cols[i] if i < len(cols) else None,
#                             "color_hex": hexes[i] if i < len(hexes) else None,
#                         })
#                 else:
#                     # no instances at all
#                     rows.append({
#                         "violation_type": "uncolored_node",
#                         "node": node_id,
#                         "Name": name,
#                         "location": None,
#                         "color": None,
#                         "color_hex": None,
#                     })

#         return None if not rows else pd.DataFrame(rows)


#     def obj_colors_instance_mismatches(self):
#         """Objects with ≥2 instances colored differently; one row per instance."""
#         rows = []
#         for node_id, data in self.G.nodes(data=True):
#             instances = data.get("instances")
#             if not instances:
#                 continue
#             pkgs  = instances.get("Package_Name", []) or []
#             diags = instances.get("DiagramName", []) or []
#             cols  = instances.get("ObjectColor", []) or []
#             hexes = instances.get("ObjectColorHex", []) or []
#             distinct_hex = set([h for h in hexes if h is not None])
#             if len(distinct_hex) <= 1:
#                 continue
#             m = max(len(pkgs), len(diags), len(cols), len(hexes))
#             for i in range(m):
#                 rows.append({
#                     "node": node_id,
#                     "Name": data.get("Name"),
#                     "location": "{}.{}".format(
#                         pkgs[i] if i < len(pkgs) else None,
#                         diags[i] if i < len(diags) else None
#                     ),
#                     "ObjectColor": cols[i] if i < len(cols) else None,
#                     "ObjectColorHex": hexes[i] if i < len(hexes) else None,
#                     "instances_count": len(cols),
#                     "n_distinct_colors": len(distinct_hex),
#                 })
#         return None if not rows else pd.DataFrame(rows).sort_values(["Name", "location"]).reset_index(drop=True)

#     # ---------------- edge label/multiplicity ----------------
#     def colored_connectors_labeled(self):
#         need = {"color", "label"}
#         if not need.issubset(self.df_edges.columns):
#             return None
#         colored = self.df_edges[self.df_edges["color"].astype(str).str.lower().isin(["red", "green"])]
#         invalid = colored[colored["label"].isna() | (colored["label"].astype(str).str.strip() == "")]
#         return None if invalid.empty else invalid

#     def label_requires_end_mult(self):
#         need = {"label", "end_mult"}
#         if not need.issubset(self.df_edges.columns):
#             return None
#         has_label = self.df_edges["label"].notna() & (self.df_edges["label"].astype(str).str.strip() != "")
#         missing_end = self.df_edges["end_mult"].isna() | (self.df_edges["end_mult"].astype(str).str.strip() == "")
#         invalid = self.df_edges[has_label & missing_end]
#         return None if invalid.empty else invalid

#     # ---------------- reachability ----------------
#     def root_connectivity(self):
#         """
#         Strong (directional) connectivity: a node is valid iff there exists a
#         directed path node -> ... -> Root in G.

#         Returns
#         -------
#         None, or a DataFrame of nodes that CANNOT reach Root, with chain grouping,
#         simple levels, in/out degrees (within the unreachable subgraph), and Diagram.
#         """
#         if "node" not in self.df_nodes.columns:
#             return None

#         nodes_to_check = set(self.df_nodes["node"]) & set(self.G.nodes())
#         if not nodes_to_check:
#             return None

#         # Precompute: nodes that CAN reach Root (via reversed graph)
#         # In G_rev, descendants from Root are exactly the nodes that have a path to Root in G.
#         reachable_to_root = {self.root_id} | nx.descendants(self.G_rev, self.root_id)

#         unreachable = sorted(nodes_to_check - reachable_to_root)
#         if not unreachable:
#             return None

#         # Group unreachable nodes into "chains" (ignore direction for grouping visualization)
#         G_unreach = self.G.subgraph(unreachable).copy()
#         chains = list(nx.weakly_connected_components(G_unreach))

#         chain_id_map, chain_sizes = {}, {}
#         for i, comp in enumerate(chains, start=1):
#             for n in comp:
#                 chain_id_map[n] = i
#             chain_sizes[i] = len(comp)

#         # Degrees within the unreachable directed subgraph (for context)
#         in_deg  = dict(G_unreach.in_degree())
#         out_deg = dict(G_unreach.out_degree())

#         # Simple "level" within each chain:
#         #   start from local sources (zero in-degree *within the unreachable subgraph*)
#         #   and use shortest directed distance (+1) so tops are level=1.
#         level_map = {}
#         for comp in chains:
#             sub = G_unreach.subgraph(comp)
#             tops = [n for n in sub if sub.in_degree(n) == 0] or list(sub.nodes())  # handle cycles
#             for t in tops:
#                 # level for t is 1; descendants get dist+1
#                 level_map[t] = max(level_map.get(t, 1), 1)
#                 for node, dist in nx.single_source_shortest_path_length(sub, t).items():
#                     level_map[node] = max(level_map.get(node, 1), dist + 1)

#         df = (
#             self.df_nodes[self.df_nodes["node"].isin(unreachable)]
#             .copy()
#             .assign(
#                 chain_id=lambda d: d["node"].map(chain_id_map),
#                 chain_size=lambda d: d["chain_id"].map(chain_sizes),
#                 level=lambda d: d["node"].map(level_map).fillna(1).astype(int),
#                 in_deg_unreach=lambda d: d["node"].map(in_deg).fillna(0).astype(int),
#                 out_deg_unreach=lambda d: d["node"].map(out_deg).fillna(0).astype(int),
#                 Diagram=lambda d: d["node"].map(self.node_diagrams_map).apply(
#                     lambda v: ", ".join(v) if isinstance(v, list) else None
#                 ),
#             )
#             .sort_values(["chain_id", "level", "Name", "node"])
#             .reset_index(drop=True)
#         )
#         return df

#     # ---------------- connector color rules ----------------
#     def red_into_green_object(self):
#         if "color" not in self.df_edges.columns or "ObjectColor" not in self.df_nodes.columns:
#             return None
#         edge_col = self.df_edges["color"].astype(str).str.strip().str.lower()
#         tgt_color = self.df_edges["target"].map(self.node_color_map)
#         mask = (edge_col == "red") & (tgt_color == "green")
#         bad = self.df_edges.loc[mask].copy()
#         if bad.empty:
#             return None
#         if self.name_map:
#             bad["source_Name"] = bad["source"].map(self.name_map)
#             bad["target_Name"] = bad["target"].map(self.name_map)
#         bad["source_ObjectColor"] = bad["source"].map(self.node_color_map)
#         bad["target_ObjectColor"] = bad["target"].map(self.node_color_map)
#         return bad

#     def green_connector_rules(self):
#         if "color" not in self.df_edges.columns or "ObjectColor" not in self.df_nodes.columns:
#             return None
#         green_nodes = {n for n, c in self.node_color_map.items() if c == "green"} & set(self.G.nodes())
#         nodes_with_green_desc = set()
#         if green_nodes:
#             for g in green_nodes:
#                 nodes_with_green_desc |= {g} | nx.descendants(self.G_rev, g)

#         edge_col = self.df_edges["color"].astype(str).str.strip().str.lower()
#         tgt_color = self.df_edges["target"].map(self.node_color_map)

#         ruleA = (edge_col == "green") & (tgt_color == "magenta")
#         ruleB = (edge_col == "green") & (tgt_color == "yellow") & (~self.df_edges["target"].isin(nodes_with_green_desc))

#         violations = self.df_edges.loc[ruleA | ruleB].copy()
#         if violations.empty:
#             return None

#         violations.loc[ruleA[ruleA].index, "violation_type"] = "green_edge_to_magenta_object"
#         violations.loc[ruleB[ruleB].index, "violation_type"] = "green_edge_to_yellow_without_green_descendant"

#         if self.name_map:
#             violations["source_Name"] = violations["source"].map(self.name_map)
#             violations["target_Name"] = violations["target"].map(self.name_map)
#         violations["source_ObjectColor"] = violations["source"].map(self.node_color_map)
#         violations["target_ObjectColor"] = violations["target"].map(self.node_color_map)
#         violations["target_has_green_descendant"] = violations["target"].isin(nodes_with_green_desc)

#         cols = [
#             "violation_type", "ConnectorID", "Diagram", "Connector_Type", "label",
#             "source", "source_Name", "source_ObjectColor",
#             "target", "target_Name", "target_ObjectColor",
#             "target_has_green_descendant", "color"
#         ]
#         cols = [c for c in cols if c in violations.columns] + [c for c in violations.columns if c not in cols]
#         return violations[cols]

#     def con_colors_instance_mismatches(self):
#         """
#         Instances where connectors of the same id have different colors.
#         Looks for 'ConnectorID' (preferred) or falls back to 'connector_id'.
#         Color column searched in ['color','c_linecolor'].
#         """
#         id_col = "ConnectorID" if "ConnectorID" in self.df_edges.columns else (
#             "connector_id" if "connector_id" in self.df_edges.columns else None
#         )
#         if id_col is None:
#             return None

#         color_col = "color" if "color" in self.df_edges.columns else (
#             "c_linecolor" if "c_linecolor" in self.df_edges.columns else None
#         )
#         if color_col is None:
#             return None

#         groups = []
#         for _, insts in self.df_edges.groupby(id_col, dropna=False):
#             if len(insts) < 2:
#                 continue
#             if insts[color_col].astype(str).nunique() > 1:
#                 groups.append(insts)
#         return None if not groups else pd.concat(groups, ignore_index=True)

#     def con_colors_invalid(self):
#         """
#         Connector colors not in RAVENS connector color definitions.
#         Valid set composed from:
#         - 'default'
#         - keys containing 'connector' OR values containing 'connector'
#         Works with 'color' or 'c_linecolor'.
#         Also returns source/target object names from node attributes.
#         """
#         # pick the color column
#         color_col = "color" if "color" in self.df_edges.columns else (
#             "c_linecolor" if "c_linecolor" in self.df_edges.columns else None
#         )
#         if color_col is None:
#             return None

#         # valid set
#         valid = set([c[1].split(' ')[0] for c in self.ravens_colors.items() if 'connector' in c[1]])
#         valid |= {"default"}

#         # basic invalid selection
#         df = self.df_edges.rename(columns={color_col: "Color"}).copy()
#         keep_cols = [c for c in ["Color", "Diagram", "source", "target", "ConnectorID",
#                                 "Connector_Type", "label", "Start_Object", "End_Object"]
#                     if c in df.columns]
#         out = df[keep_cols].copy()
#         # import pdb
#         # pdb.set_trace()
#         out = out[~out["Color"].isin(valid)]
#         if out.empty:
#             return None

#         # add names from nodes
#         # (self.name_map built from df_nodes: node -> Name)
#         if getattr(self, "name_map", None):
#             out["source_Name"] = out["source"].map(self.name_map)
#             out["target_Name"] = out["target"].map(self.name_map)

#         # optional: include node colors (handy context)
#         if getattr(self, "node_color_map", None):
#             out["source_ObjectColor"] = out["source"].map(self.node_color_map)
#             out["target_ObjectColor"] = out["target"].map(self.node_color_map)

#         # reorder for readability
#         preferred = [
#             "Color", "Diagram", "ConnectorID", "Connector_Type", "label",
#             "source", "source_Name", "source_ObjectColor",
#             "target", "target_Name", "target_ObjectColor",
#             "Start_Object", "End_Object",
#         ]
#         cols = [c for c in preferred if c in out.columns] + [c for c in out.columns if c not in preferred]
#         return out[cols]

#     # ---------------- run-all + summarize ----------------
#     def validate(self, include_ok=False, include=None, exclude=None):
#         checks = {
#             "object_colors_invalid": self.obj_colors_invalid,
#             "object_instance_color_mismatch": self.obj_colors_instance_mismatches,
#             "object_cant_reach_root": self.root_connectivity,
#             "connector_unlabeled": self.colored_connectors_labeled,
#             "connector_color_invalid": self.con_colors_invalid,
#             "connector_instances_color_mismatch": self.con_colors_instance_mismatches,
#             "connector_lacks_multiplicity": self.label_requires_end_mult,
#             "connector_green_rule_violatons": self.green_connector_rules,
#             "red_connector_green_object": self.red_into_green_object,
#         }
#         sel = set(checks.keys())
#         if include is not None:
#             sel &= set(include)
#         if exclude is not None:
#             sel -= set(exclude)

#         results = {}
#         for cid in sorted(sel):
#             df = checks[cid]()
#             if df is not None or include_ok:
#                 results[cid] = df
#         return results

#     @staticmethod
#     def summarize(results):
#         rows = []
#         for cid, df in results.items():
#             status = "fail" if isinstance(df, pd.DataFrame) and not df.empty else "ok"
#             n = int(len(df)) if isinstance(df, pd.DataFrame) else 0
#             rows.append({"check_id": cid, "status": status, "n_rows": n})
#         return pd.DataFrame(rows).sort_values(["status", "check_id"]).reset_index(drop=True)
