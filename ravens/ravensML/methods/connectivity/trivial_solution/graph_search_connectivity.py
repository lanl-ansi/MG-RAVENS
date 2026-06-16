import sys
import os
import re
import networkx as nx
from collections import Counter
from typing import List, Sequence, Tuple, Any, Dict

from pathlib import Path
import sys, os
rML_ROOT = Path(__file__).resolve().parents[3]
if str(rML_ROOT) not in sys.path:
    sys.path.insert(0, str(rML_ROOT))
from framework.dataset import MGRavensDataset


class GraphSearchConnectivity(object):
    """
    For each grid:
        1. Compute connected components.
        2. Detect dead nodes (names starting with NOT_FOUND_).
        3. Gather edges that involve at least one dead node -> errored edges.
        4. Count, per dead node, how many distinct errored edges reference it.
        5. Propose replacement edges for every dead node (k-nearest by edit distance,
           then choose the candidate that minimises the number of connected components).
        6. Produce a **single, pretty-printed report** that contains all of the
           above information, including the proposed edges.
    """

    def __init__(self):
        self.input_data = None
        self.output_data = []

    # ------------------------------------------------------------------
    # Callable entry point – now the report is built *after* corrections
    # ------------------------------------------------------------------
    def __call__(self, X):
        self.input_data = X
        for grid in self.input_data:
            # print(grid["file_name"])
            new_grid = grid.copy()

            # 1  Connected components
            new_grid["connected_components"] = self._find_cc(new_grid)

            # 2  Detect dead nodes
            dead_nodes = [
                node for node in new_grid["graph"].nodes
                if re.match(r'^NOT_FOUND_', node)
            ]

            # 3  Collect errored edges and per-node reference counts
            errored_edges, node_ref_counts = self._collect_errored_edges(
                new_grid["graph"], dead_nodes
            )

            # 4  Propose corrections
            corrected_dead_nodes = [node.strip("NOT_FOUND_") for node in dead_nodes]
            targets = [node for node in new_grid["graph"].nodes
                    if node not in dead_nodes]

            # full edit-distance matrix (NxM)
            edm = self.edit_distance(corrected_dead_nodes, targets)

            k = 3                                   # how many candidates per dead node
            nearest_names = []                      # Nxk matrix of candidate names
            for row in edm:
                paired = list(zip(row, targets))
                paired.sort(key=lambda x: x[0])    # sort by distance (ascending)
                names = [name for _, name in paired[:k]]
                # pad with None if we have fewer than k candidates
                if len(names) < k:
                    names.extend([None] * (k - len(names)))
                nearest_names.append(names)

            # original number of connected components (before any rewiring)
            orig_cc = len(new_grid["connected_components"])

            proposed_corrections: Dict[str, Dict[str, Any]] = {}
            for idx, dead_node in enumerate(dead_nodes):
                # neighbors of the dead node in the original graph
                neighbors = list(new_grid["graph"].neighbors(dead_node))

                best_candidate = None
                best_cc = None          # will hold the *improved* CC count
                best_edges = None

                for cand in nearest_names[idx]:
                    if cand is None:
                        continue
                    cc, new_edges = self._evaluate_candidate(
                        new_grid["graph"], dead_node, neighbors, cand
                    )
                    # **only accept a candidate that reduces the CC count**
                    if cc < orig_cc and (best_cc is None or cc < best_cc):
                        best_cc = cc
                        best_candidate = cand
                        best_edges = new_edges

                # if nothing improved, keep None / empty values
                if best_candidate is None:
                    best_cc = orig_cc          # or None – report will show no improvement
                    best_edges = []

                proposed_corrections[dead_node] = {
                    "replacement_node": best_candidate,
                    "new_edges": best_edges,
                    "connected_components_if_applied": best_cc,
                }


            # Any errored edge that still points to a dead node whose
            # replacement was not chosen is considered “missing”.  We add a
            # new node (the stripped name) and remember which existing node(s)
            # it should be connected to.
            #
            missing_nodes = []
            # print(errored_edges)
            # Check if errored_edges contains tuples with 3 elements (u, v, key)
            is_multigraph_edges = any(len(edge) == 3 for edge in errored_edges if isinstance(edge, tuple))

            if is_multigraph_edges:
                for u, v, key in errored_edges:
                    # The edge is directed – we do not know which side is the dead one.
                    # Check both ends.
                    for dead, other in ((u, v), (v, u)):
                        if dead in dead_nodes:
                            # Was a replacement found for this dead node?
                            repl = proposed_corrections[dead]["replacement_node"]
                            if repl is None:                     # no replacement -> truly missing
                                clean_name = dead.replace("NOT_FOUND_", "")
                                missing_nodes.append(clean_name)
                            # If a replacement *was* found we already plan to re-wire,
                            # so we ignore the edge here.
                            break
            else:
                for u, v in errored_edges:
                    # The edge is directed – we do not know which side is the dead one.
                    # Check both ends.
                    for dead, other in ((u, v), (v, u)):
                        if dead in dead_nodes:
                            # Was a replacement found for this dead node?
                            repl = proposed_corrections[dead]["replacement_node"]
                            if repl is None:                     # no replacement -> truly missing
                                clean_name = dead.replace("NOT_FOUND_", "")
                                missing_nodes.append(clean_name)
                            # If a replacement *was* found we already plan to re-wire,
                            # so we ignore the edge here.
                            break


            # ------------------------------------------------------
            # 5 Build the final report – now includes proposals
            # ------------------------------------------------------
            new_grid["connectivity_report"] = self._build_report(
                dead_nodes,
                errored_edges,
                node_ref_counts,
                new_grid["connected_components"],
                proposed_corrections,
                missing_nodes,        
            )

            missing_edges = [
                edge                  
                for proposal in proposed_corrections        
                for edge in  proposed_corrections[proposal]['new_edges']        
            ]

            new_grid["y_pred"] = {'Edges Needed':missing_edges,'Missing Nodes':missing_nodes}

            # ------------------------------------------------------
            # Final pretty-print
            # ------------------------------------------------------
            # print(new_grid["connectivity_report"])
            self.output_data.append(new_grid)

        return self.output_data


    # ------------------------------------------------------------------
    # Helper: connected components 
    # ------------------------------------------------------------------
    @staticmethod
    def _find_cc(grid):
        """Return a list of sets, each set being a connected component."""
        return list(nx.connected_components(grid["graph"]))

    # ------------------------------------------------------------------
    # Helper: collect errored edges and per-node counts 
    # ------------------------------------------------------------------
    @staticmethod
    def _collect_errored_edges(G, dead_nodes):
        dead_set = set(dead_nodes)                 # O(1) look-ups
        errored_edges = set()                      # store as unordered frozenset
        node_ref_counts = Counter()

        # Check if we're dealing with a multigraph
        if hasattr(G, 'is_multigraph') and G.is_multigraph():
            # For multigraphs, edges are (u, v, key) tuples
            for u, v, key in G.edges(keys=True):
                u_dead = u in dead_set
                v_dead = v in dead_set

                if u_dead or v_dead:
                    if u_dead != v_dead:
                        # Store edge with its key to uniquely identify it
                        errored_edges.add((u, v, key))

                        if u_dead:
                            node_ref_counts[u] += 1
                        if v_dead:
                            node_ref_counts[v] += 1
        else:
            # For regular graphs, edges are (u, v) pairs
            for u, v in G.edges:
                u_dead = u in dead_set
                v_dead = v in dead_set

                if u_dead or v_dead:
                    if u_dead != v_dead:
                        errored_edges.add(frozenset((u, v)))

                        if u_dead:
                            node_ref_counts[u] += 1
                        if v_dead:
                            node_ref_counts[v] += 1

        return errored_edges, node_ref_counts


    # ------------------------------------------------------------------
    # Helper: build the human-readable report (now also prints proposals)
    # ------------------------------------------------------------------
    @staticmethod
    def _build_report(
        dead_nodes,
        errored_edges,
        node_ref_counts,
        connected_components,
        proposed_corrections: Dict[str, Dict[str, Any]],
        missing_nodes: List
    ) -> str:
        """
        Assemble a multi-line string that mirrors the original layout **and**
        adds a section with the chosen replacement edges.
        """
        lines = []

        # ---- Header -------------------------------------------------
        lines.append("Connectivity Report")
        lines.append("-" * 30)
        lines.append(f"Total Connected Components : {len(connected_components)}")
        lines.append(f"Dead (Missing) Nodes       : {len(dead_nodes)}")
        lines.append(f"Distinct Errored Edges     : {len(errored_edges)}")
        lines.append("")

        # ---- Dead-node reference counts -----------------------------
        if dead_nodes:
            lines.append("Dead Node Reference Counts:")
            for node in sorted(dead_nodes):
                cnt = node_ref_counts.get(node, 0)
                lines.append(f"  {node!r} -> referenced by {cnt} edge(s)")
            lines.append("")

        # ---- List of distinct errored edges ------------------------
        if errored_edges:
            lines.append("Errored Edges (each listed once):")
            
            # Check if errored_edges contains tuples with 3 elements (u, v, key)
            is_multigraph_edges = any(isinstance(edge, tuple) and len(edge) == 3 for edge in errored_edges)
            
            if is_multigraph_edges:
                # Sort multigraph edges by (u, v, key)
                for u, v, key in sorted(errored_edges):
                    lines.append(f"  ({u!r}, {v!r}, {key!r})")
            else:
                # Sort regular edges by tuple(sorted(e))
                for edge in sorted(errored_edges, key=lambda e: tuple(sorted(e))):
                    if isinstance(edge, frozenset):
                        u, v = tuple(edge)
                        lines.append(f"  ({u!r}, {v!r})")
                    else:
                        # Handle the case where edge might already be a tuple
                        u, v = edge
                        lines.append(f"  ({u!r}, {v!r})")
            
            lines.append("")


        # ---- Proposed corrections ------------------------------------
        if proposed_corrections:
            lines.append(
                "Proposed Corrections (chosen by minimizing components):"
            )
            for dead_node, info in proposed_corrections.items():
                repl = info["replacement_node"]
                new_edges = info["new_edges"]
                comp = info["connected_components_if_applied"]

                lines.append(f"  {dead_node!r} -> replace with {repl!r}")

                if new_edges:
                    # pretty-print the edge list
                    edge_str = ", ".join(
                        f"({a!r}, {b!r})" for a, b in new_edges
                    )
                    lines.append(f"    New edges : {edge_str}")
                else:
                    lines.append("    No new edges (isolated node).")

                lines.append(
                    f"    Connected components after applying: {comp}"
                )
            lines.append("")

        if missing_nodes:
            lines.append("\nMissing Nodes:")
            for mn in missing_nodes:
                lines.append("  - " + mn)
            lines.append("")

        # ---- Fallback when nothing was found ------------------------
        if not dead_nodes and not errored_edges:
            lines.append("No dead nodes or errored edges were detected.")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Levenshtein implementation 
    # ------------------------------------------------------------------
    @staticmethod
    def _levenshtein(a: str, b: str) -> int:
        if len(a) > len(b):
            a, b = b, a

        previous = list(range(len(a) + 1))
        for j, bj in enumerate(b, start=1):
            current = [j]
            for i, ai in enumerate(a, start=1):
                cost = 0 if ai == bj else 1
                current.append(
                    min(previous[i] + 1,
                        current[i - 1] + 1,
                        previous[i - 1] + cost)
                )
            previous = current
        return previous[-1]

    # ------------------------------------------------------------------
    # Full NxM edit-distance matrix 
    # ------------------------------------------------------------------
    def edit_distance(self, src: Sequence[str], targets: Sequence[str]) -> List[List[int]]:
        src = list(src)
        targets = list(targets)

        n, m = len(src), len(targets)
        dist = [[0] * m for _ in range(n)]

        for i, s in enumerate(src):
            for j, t in enumerate(targets):
                dist[i][j] = self._levenshtein(s, t)

        return dist

    # ------------------------------------------------------------------
    # evaluate a single candidate replacement 
    # ------------------------------------------------------------------
    @staticmethod
    def _evaluate_candidate(
        G: nx.Graph,
        dead_node: str,
        neighbors: List[str],
        candidate: str,
    ) -> Tuple[int, List[Tuple[str, str]]]:
        """
        Return the number of connected components that would result if
        *dead_node* were removed and all its incident edges were rewired
        to *candidate*.

        Also returns the list of new edges that would be added.
        """
        G_tmp = G.copy()

        if dead_node in G_tmp:
            G_tmp.remove_node(dead_node)

        if candidate not in G_tmp:
            G_tmp.add_node(candidate)

        new_edges = [(candidate, nb) for nb in neighbors]
        G_tmp.add_edges_from(new_edges)

        cc = nx.number_connected_components(G_tmp)
        return cc, new_edges


# ----------------------------------------------------------------------
# Driver code 
# ----------------------------------------------------------------------
if __name__ == "__main__":
    MGR = MGRavensDataset(data_dir=rML_ROOT/"data/raw")
    MGR.process_for_ML()
    # MGR.visualize_graph(1)
    # MGR.visualize_graph(2)

    GSC = GraphSearchConnectivity()
    GSC(MGR.data())
