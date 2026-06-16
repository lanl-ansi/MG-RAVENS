# Connectivity Correction

## Problem Premise

Often, when working with large-scale power-grid models we encounter errors in the
grid topology that arise from user mistakes during data entry, conversion, or
transfer, or from the way different groups choose to model real-world grids.
When such models are converted into **MG-RAVENS**, the errors appear as

* **Missing nodes** – a `ConnectivityNode` entry is deleted.  
* **Misspecified terminals** – the `Terminal.ConnectivityNode` string of an
  `ACLineSegment` is corrupted (character substitution, off-by-one typo, etc.).  
* **Deleted edges** – whole line segments are removed.

A downstream power-flow solver (PowerModelsDistribution) can process these
files, but the errors often lead to physically implausible results that differ
substantially from true operation.  For simplicity we focus only on edge
errors: either an edge is missing or it references an invalid terminal.

The task is to **recover the original topology**: given a corrupted grid file,
produce a list of *edges that must be added* and insert them back into the
MG-RAVENS file.

---

## Formulation

### Formal Problem Definition

Let  

* $G = (V, E)$ be the *true* undirected grid graph,  
* $G' = (V', E')$ the *observed* corrupted graph,  
* $E_{\text{missing}} = \{(u, v) \mid u, v \in V,\ (u, v) \in E,\ (u, v) \notin E'\}$.

The correction problem is to infer the set $E_{\text{missing}}$.

In a machine-learning setting we treat this as a **binary-matrix reconstruction**
problem.  Define the adjacency matrix of the true graph
$\mathbf{A}\in\{0,1\}^{N\times N}$ with $N = |V|$.
The corrupted adjacency $\mathbf{A}'$ is obtained from $\mathbf{A}$ by
zeroing entries that correspond to missing edges or by swapping node
identifiers through a string-level typo.

The learning objective is to predict a matrix $\hat{\mathbf{A}}$ such that  


$\hat{\mathbf{A}} \approx \mathbf{A}\quad\text{and}\quad$
$\hat{\mathbf{A}}_{ij} \in [0,1]$.


From $\hat{\mathbf{A}}$ we extract a set of predicted missing edges  


$\hat{E}_{\text{missing}} = \{(i,j) \mid \hat{\mathbf{A}}_{ij} > \tau\}$,


where $\tau$ is a threshold chosen during inference.

### Formal Data Description

| Symbol | Meaning |
|--------|---------|
| `raw_mgr` | List of tuples $[\,\text{file\_name},\ \text{ravens\_data},\ \text{original\_data}\,]$. |
| `ConnectivityNode` | Dictionary mapping node identifiers to their CIM attributes. |
| `ACLineSegment` | Edge objects; each contains two terminal entries with a `Terminal.ConnectivityNode` string. |
| `rename_prob` | Probability that a terminal name is corrupted (typo). |
| `delete_prob` | Probability that a `ConnectivityNode` entry is removed. |
| `del_e_prob` | Probability that an entire line segment is deleted. |
| `corrections` | List of dictionaries `{"Edges Needed": [...], "Missing Nodes": [...]}` that store the ground-truth error for each generated sample. |
| `y_pred` (output) | Dictionary `{'Edges Needed': [...], 'Missing Nodes': [...]}` used as the learning target. |

The helper function `gen_conn_error` creates a **synthetic dataset** by
injecting the three error types above while preserving a copy of the pristine
graph for supervision.

---

## Methods

### Graph Search Method

`GraphSearchConnectivity` implements a deterministic, rule-based pipeline:

1. **Connected-component analysis** – uses NetworkX’s `connected_components`.  
2. **Dead-node detection** – any node that appears only in an edges data without being specified in the 
    ravens file is labelled a *dead node*, indicating a missing node or a misspecified incident edge.  
3. **Errored-edge collection** – edges that touch at least one dead node are
   gathered; a per-node reference count is stored (`node_ref_counts`).  
4. **Candidate generation** – under the assumption that misspecification stems
   from a corrupted name, the algorithm computes the Levenshtein edit distance
   between each dead node and every *alive* node, selects the `k = 3` nearest
   candidates, and evaluates each candidate by:  
   * removing the dead node,  
   * rewiring its incident edges to the candidate,  
   * counting the resulting number of connected components (to see whether the
     change resolves a disconnected segment).  
5. **Selection** – the candidate that *strictly reduces* the component count is
   kept; otherwise the dead node is reported as truly missing.  
6. **Report generation** – a human-readable multi-line string summarises
   component statistics, dead-node reference counts, distinct errored edges,
   proposed rewiring, and a final list of missing nodes that could not be
   resolved.

The method outputs a `y_pred` dictionary compatible with the supervised loss
functions used by the GNN models, enabling a direct performance comparison.

**Key Implementation Highlights**

* Edit distance is computed by a dynamic-programming routine (`_levenshtein`),
  wrapped in `edit_distance` to produce the full
  $|V_{\text{dead}}| \times |V_{\text{alive}}|$ matrix.  
* Candidate evaluation uses a temporary copy of the graph (`_evaluate_candidate`);
  the original structure remains unchanged.  
* The final report is built by `_build_report`, which formats the information
  using plain hyphens only (no em-dashes).

---

### GNN Method

Two message-passing architectures are provided:

| Model | Description |
|-------|-------------|
| **SimpleGNN** | Stacks `transport_distance` PNA convolutions, followed by a deep edge-wise MLP that outputs a flat vector of size `max_nodes^2`. After reshaping and a sigmoid, the result is a probabilistic adjacency matrix. |
| **AttnGNN** | Same PNA backbone, but precedes it with an **EdgeAttentionModule** that performs multi-head self-attention over edge representations. The attention-enhanced edge attributes are then fed to the same MLP head as SimpleGNN. |

Both models share the following pipeline:

1. **Node / edge feature extraction** – supplied by the `MGRavensDataset` loader.  
2. **Optional edge-attention preprocessing** – only in `AttnGNN`.  
3. **`transport_distance` rounds of PNA message passing** with BatchNorm.  
4. **Edge representation** – concatenation of source node embedding, destination node embedding, and original edge attributes.  
5. **Deep MLP** – 10+ linear layers with ReLU, dropout, and progressive dimensionality reduction, ending in a $(\text{max\_nodes} \times \text{max\_nodes})$ logit vector.  
6. **Aggregation** – average over all edges to obtain a single graph-level vector,
   reshaped to `max_nodes × max_nodes` and squashed via `sigmoid`.  
   Symmetrisation $(A + A^{\top})/2$ enforces undirectedness.

#### Loss Functions

* **AdjMSELoss** – weighted mean-squared error between predicted adjacency
  $\hat{\mathbf{A}}$ and the ground-truth mask `missing_edges`.  
  Optional diagonal masking, a positive-edge weight $\beta$, and a global
  scaling factor $K$ are supported.  
* **PIAdjMSELoss** – extends `AdjMSELoss` with a *penalty term* that evaluates
  the physical feasibility of the corrected grid:  
  * With probability `test_percentage` the method uses a NN to predict the results amount of system demand
    not met when solving power flow via `run_pf` and `system_demand_not_met`.
  * A penalty multiplier (`inf_penalty`) will be applied to the predicted infeasibility
    and added to the loss to yield a differentiable physics informed loss component.  

Both losses are fully differentiable; the infeasibility term is a scalar that
does not back-propagate through the Julia solver, but its magnitude still
guides the optimizer toward physically plausible reconstructions.

#### Data Flow

1. **Corruption** – `gen_conn_error` produces `(corrupted_mgr, corrections)`.
   `corrections` are stored as the target `y["missing_edges"]` and
   `y["missing_nodes"]`.  
2. **Dataset** – `MGRavensDataset.process_for_ML()` converts each case into a
   PyTorch Geometric `Data` object containing `x` (node features), `edge_index`,
   `edge_attr`, and the supervision tensors.  
3. **Training** – the GNN receives batches of `Data`, produces $\hat{\mathbf{A}}$,
   and the loss (`AdjMSELoss` or `PIAdjMSELoss`) is back-propagated.  
4. **Inference** – after training, `define_edges` thresholds the predicted
   adjacency (default $\tau = 0.5$), creates CIM-compliant line objects from the
   `DEFAULT_LINE` template, and inserts them into the original JSON file via
   `update_mgr`.  The resulting grid can be handed to the power-flow routine for
   validation.

---

### Results

**Dataset:** 20,000 20-node subsets of IEEE8500  
**Training:** 100 epochs  
**Metric:** Validation MSE

| Model Architecture | Validation MSE |
|-------------------|----------------|
| Fully Connected MLP Head | 1.026791 |
| 7× PNA Convolutions w/ MLP Head | 1.001263 |
| 14× PNA Convolutions w/ MLP Head | 1.023394 |
| 18× PNA Convolutions w/ MLP Head | 1.018607 |
| 20× PNA Convolutions w/ MLP Head | 1.020473 |
| 1x Edge Attention w/ MLP Head |  1.017812 |
| 2x Edge Attention w/ MLP Head | 1.163918  |
| 3x Edge Attention w/ MLP Head | 0.987771 |
| 4x Edge Attention w/ MLP Head | 0.958742 |


---

| #  | Model     | TD | IP | TP  | Loss       |
|----|-----------|----|----|-----|------------|
| 1  | SimpleGNN | 14 | 5  | 0.0 | 73.476521  |
| 2  | SimpleGNN | 18 | 5  | 0.0 | 82.780338  |
| 3  | SimpleGNN | 20 | 5  | 0.0 | 90.976347  |
| 4  | AttnGNN   | 3  | 5  | 0.0 | 110.999518 |
| 5  | SimpleGNN | 7  | 5  | 0.0 | 111.451487 |
| 6  | AttnGNN   | 2  | 5  | 0.0 | 178.891453 |
| 7  | AttnGNN   | 3  | 5  | 1.0 | 215.723340 |
| 8  | AttnGNN   | 1  | 5  | 0.0 | 221.067478 |
| 9  | AttnGNN   | 4  | 5  | 0.0 | 237.509754 |
| 10 | SimpleGNN | 0  | 5  | 0.0 | 671.897062 |
