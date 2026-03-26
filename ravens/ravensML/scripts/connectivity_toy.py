import sys
import os
import re
import networkx as nx
from collections import Counter
from typing import List, Sequence, Tuple, Any, Dict, Set
from pathlib import Path
import sys, os
rML_ROOT = Path(__file__).resolve().parents[1]
if str(rML_ROOT) not in sys.path:
    sys.path.insert(0, str(rML_ROOT))
from framework.dataset import MGRavensDataset
from methods.connectivity.trivial_solution.graph_search_connectivity import GraphSearchConnectivity
from methods.connectivity.gen_conn_error import gen_conn_error


def _norm_edge(e: Tuple[Any, Any]) -> Tuple[Any, Any]:
    """
    Return a *direction‑agnostic* representation of an edge.
    The smaller element (according to the default ordering) is placed first.
    """
    a, b = e
    return (a, b) if a <= b else (b, a)


def normalize_prediction(pred: Dict[str, Any]) -> Tuple[Set[Tuple[Any, Any]], Set[Any]]:
    """
    Convert a single prediction dictionary into two *sets*:

        edges_needed : Set[Tuple[node, node]]
        missing_nodes: Set[node]

    Both sets are order‑independent.
    """
    edges = { _norm_edge(e) for e in pred.get('Edges Needed', []) }
    nodes = set(pred.get('Missing Nodes', []))
    return edges, nodes


def compute_counts(
    true_edges: Set[Tuple[Any, Any]],
    pred_edges: Set[Tuple[Any, Any]],
    true_nodes: Set[Any],
    pred_nodes: Set[Any],
) -> Dict[str, Counter]:
    """
    Return a dictionary with two Counters (one per task) that contain
    TP, FP and FN.
    """
    edge_counter = Counter(
        TP = len(true_edges & pred_edges),
        FP = len(pred_edges - true_edges),
        FN = len(true_edges - pred_edges),
    )
    node_counter = Counter(
        TP = len(true_nodes & pred_nodes),
        FP = len(pred_nodes - true_nodes),
        FN = len(true_nodes - pred_nodes),
    )
    return {'edges': edge_counter, 'nodes': node_counter}


def precision_recall_f1(cnt: Counter) -> Tuple[float, float, float]:
    """Given a Counter with TP, FP, FN return (prec, rec, f1)."""
    tp, fp, fn = cnt['TP'], cnt['FP'], cnt['FN']
    prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    rec  = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1   = (2 * prec * rec) / (prec + rec) if (prec + rec) > 0 else 0.0
    return prec, rec, f1


def exact_match(true_edges, pred_edges, true_nodes, pred_nodes) -> bool:
    """Return True only when *both* edge‑sets and node‑sets are identical."""
    return (true_edges == pred_edges) and (true_nodes == pred_nodes)




# --------------------------------------------------------------
# 1 Load data & generate predictions (your original code)
# --------------------------------------------------------------
MGR = MGRavensDataset(data_dir="ravens/ravensML/data/raw")
MGR_CONN_TEST, Y = gen_conn_error(MGR,rename_prob=0.25,delete_prob=0.15,size=10000)          # Y = ground‑truth dict
MGR_CONN_TEST.process_for_ML()

GSC = GraphSearchConnectivity()
Y_pred = GSC(MGR_CONN_TEST.data())              # list of dicts

# --------------------------------------------------------------
# 2 Normalize everything into sets
# --------------------------------------------------------------
# Y (ground truth) is a dict of the form
#   {idx: {"Edges Needed": [...], "Missing Nodes": [...]}, ...}
# Convert it to a list that aligns with Y_pred order.
true_edges_list: List[Set[Tuple[Any, Any]]] = []
true_nodes_list: List[Set[Any]] = []


for i, y in enumerate(Y):
    e, n = normalize_prediction(y)
    true_edges_list.append(e)
    true_nodes_list.append(n)

# Normalize predictions
pred_edges_list: List[Set[Tuple[Any, Any]]] = []
pred_nodes_list: List[Set[Any]] = []

for pred in Y_pred:
    e, n = normalize_prediction(pred["y_pred"])
    pred_edges_list.append(e)
    pred_nodes_list.append(n)

# --------------------------------------------------------------
# 3 Compute per‑sample counters and aggregate them
# --------------------------------------------------------------
agg_edge_cnt = Counter()
agg_node_cnt = Counter()
exact_match_cnt = 0

for i, (t_e, t_n, p_e, p_n) in enumerate(
    zip(true_edges_list, true_nodes_list, pred_edges_list, pred_nodes_list)
):
    cnts = compute_counts(t_e, p_e, t_n, p_n)
    agg_edge_cnt += cnts['edges']
    agg_node_cnt += cnts['nodes']

    if exact_match(t_e, p_e, t_n, p_n):
        exact_match_cnt += 1

# --------------------------------------------------------------
# 4 Print a tidy report
# --------------------------------------------------------------
n_samples = len(Y_pred)

print("\n=== Accuracy report (order‑ and direction‑agnostic) ===\n")

# Edge metrics
e_prec, e_rec, e_f1 = precision_recall_f1(agg_edge_cnt)
print("Edges Needed")
print(f"  TP / FP / FN : {agg_edge_cnt['TP']} / {agg_edge_cnt['FP']} / {agg_edge_cnt['FN']}")
print(f"  Precision    : {e_prec:3.3%}")
print(f"  Recall       : {e_rec:3.3%}")
print(f"  F1‑score     : {e_f1:3.3%}\n")

# Missing‑node metrics
n_prec, n_rec, n_f1 = precision_recall_f1(agg_node_cnt)
print("Missing Nodes")
print(f"  TP / FP / FN : {agg_node_cnt['TP']} / {agg_node_cnt['FP']} / {agg_node_cnt['FN']}")
print(f"  Precision    : {n_prec:3.3%}")
print(f"  Recall       : {n_rec:3.3%}")
print(f"  F1‑score     : {n_f1:3.3%}\n")

# Exact‑match accuracy
exact_acc = exact_match_cnt / n_samples
print(f"Exact‑match (both edges & nodes correct) : {exact_match_cnt}/{n_samples} = {exact_acc:3.3%}")
