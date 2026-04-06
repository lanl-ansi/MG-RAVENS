# data.py
# ----------------------------------------------------------------------
# Imports
# ----------------------------------------------------------------------
import os
import json
import copy
import torch
import random
import numpy as np
from pathlib import Path
from typing import List, Tuple, Dict, Any

import networkx as nx
from torch_geometric.data import InMemoryDataset, Data, download_url
from torch_geometric.utils import from_networkx, to_networkx


# ----------------------------------------------------------------------
# Helper: convert the dict produced by MGRavensDataset.ravens_to_ML
# ----------------------------------------------------------------------
def dict_to_pyg(data_dict: Dict[str, Any]) -> Data:
    """
    Convert the dictionary returned by ``MGRavensDataset.ravens_to_ML`` into a
    ``torch_geometric.data.Data`` object that can be used by PyG models.
    """
    # ------------------------------------------------------------------
    # 1) Node features – stored under the key ``node_features``
    # ------------------------------------------------------------------
    x = torch.tensor(data_dict["node_features"], dtype=torch.float)

    # ------------------------------------------------------------------
    # 2) Edge index – build a (2, E) tensor from the per‑branch list of
    #    source‑target pairs stored in ``edge_index``.
    # ------------------------------------------------------------------
    edge_idx: list[list[int]] = []
    for _branch_id, pairs in data_dict["edge_index"].items():
        edge_idx.extend(pairs)                     # each pair is [src, dst]

    edge_index = torch.tensor(edge_idx, dtype=torch.long).t().contiguous()

    # ------------------------------------------------------------------
    # 3) Determine the maximum number of phases present in **any** edge of
    #    the current graph.  This value is used to pad all edge‑feature
    #    matrices to a common shape.
    # ------------------------------------------------------------------
    max_phase = max(
        int(feat["phases"]) for feat in data_dict["edge_features"].values()
    )
    # If the graph happens to have no edges, fall back to a single phase.
    if max_phase == 0:
        max_phase = 1

    # ------------------------------------------------------------------
    # 4) Local helper that takes a scalar, 1‑D vector or 2‑D matrix and
    #    returns a ``(max_phase, max_phase)`` float32 matrix, padding with
    #    zeros where necessary.
    # ------------------------------------------------------------------
    def _pad_matrix(mat):
        """Return a (max_phase, max_phase) float32 matrix."""
        mat = np.array(mat, dtype=np.float32)

        # ---- scalar ------------------------------------------------
        if mat.ndim == 0:                     # e.g. 0.0
            # Broadcast the scalar to the whole matrix.
            return np.full((max_phase, max_phase), float(mat), dtype=np.float32)

        # ---- 1‑D vector -------------------------------------------
        if mat.ndim == 1:                     # e.g. [r11, r22, r33]
            # Place the vector on the diagonal of a zero matrix.
            diag_mat = np.zeros((max_phase, max_phase), dtype=np.float32)
            diag_len = min(mat.shape[0], max_phase)
            diag_mat[np.arange(diag_len), np.arange(diag_len)] = mat[:diag_len]
            return diag_mat

        # ---- 2‑D matrix (the normal case) ------------------------
        if mat.ndim == 2:
            # Return unchanged if already the correct size.
            if mat.shape == (max_phase, max_phase):
                return mat
            # Otherwise pad/truncate to ``max_phase``.
            padded = np.zeros((max_phase, max_phase), dtype=np.float32)
            rows = min(mat.shape[0], max_phase)
            cols = min(mat.shape[1], max_phase)
            padded[:rows, :cols] = mat[:rows, :cols]
            return padded

        # ---- any higher‑dimensional object – fallback to zeros ----
        return np.zeros((max_phase, max_phase), dtype=np.float32)

    # ------------------------------------------------------------------
    # 5) Build a *uniform* edge‑feature matrix.
    #
    #    For each original edge we create a feature vector that contains:
    #      • number of phases (scalar)
    #      • flattened R, X, G, B matrices (each padded to max_phase²)
    #      • edge type, tap ratio and phase shift (scalars)
    #
    #    Because the dataset stores both directions of every branch, the
    #    same feature vector is duplicated so that the length of
    #    ``edge_attrs`` matches the length of ``edge_index``.
    # ------------------------------------------------------------------
    edge_attrs: list[list[float]] = []

    for _branch_id, feat in data_dict["edge_features"].items():
        phases = int(feat["phases"])

        # Pad the four impedance/admittance matrices to a common size.
        R = _pad_matrix(feat.get("R", np.zeros((phases, phases))))
        X = _pad_matrix(feat.get("X", np.zeros((phases, phases))))
        G = _pad_matrix(feat.get("G", np.zeros((phases, phases))))
        B = _pad_matrix(feat.get("B", np.zeros((phases, phases))))

        # Scalars that are always present – use sensible defaults if missing.
        edge_type = float(feat.get("Edge Type", 0.0))
        tap = float(feat.get("Tap", 1.0))
        shift = float(feat.get("Shift", 0.0))

        # Flatten everything in a deterministic order.
        flat_feat = [
            float(phases),                     # number of phases (1 value)
            *R.ravel().tolist(),               # R matrix (max_phase**2 values)
            *X.ravel().tolist(),               # X matrix (max_phase**2 values)
            *G.ravel().tolist(),               # G matrix (max_phase**2 values)
            *B.ravel().tolist(),               # B matrix (max_phase**2 values)
            edge_type,                         # edge type (1 value)
            tap,                               # tap ratio (1 value)
            shift,                             # phase shift (1 value)
        ]

        # Duplicate for the two directed edges.
        edge_attrs.extend([flat_feat, flat_feat])

    edge_attr = torch.tensor(edge_attrs, dtype=torch.float)

    # ------------------------------------------------------------------
    # 6) Assemble and return the PyG ``Data`` object.
    #
    #    ``max_phase`` is attached as an extra attribute for convenience
    #    in downstream processing (e.g. when reconstructing the original
    #    matrices).
    # ------------------------------------------------------------------
    data = Data(x=x, edge_index=edge_index, edge_attr=edge_attr)
    data.max_phase = max_phase
    return data



# ----------------------------------------------------------------------
# InMemoryDataset that returns (corrupted, clean) pairs
# ----------------------------------------------------------------------
class MGConnDataset(InMemoryDataset):
    """
    PyG ``InMemoryDataset`` that yields a tuple ``(corrupted, clean)`` where
    both entries are ``torch_geometric.data.Data`` objects.

    Parameters
    ----------
    root : str
        Path that contains a ``raw/`` sub‑folder with the original JSON files.
    split : str, optional
        ``'train'``, ``'val'`` or ``'test'``.  The split is performed
        deterministically using a fixed random seed.
    size : int | None, optional
        Desired number of *corrupted* samples.  ``None`` uses all available
        graphs.
    error_kwargs : dict | None
        Arguments forwarded to the connectivity‑error generator.
    transform, pre_transform : callable, optional
        Standard PyG transforms.
    max_nodes : int, optional
        Currently unused (kept for API compatibility).
    """
    def __init__(
        self,
        root: str,
        split: str = "full",
        size: int | None = None,
        error_kwargs: dict | None = None,
        transform=None,
        max_nodes: int = 1,
        pre_transform=None,
    ):

        self.root = Path(root).expanduser()
        self.split = split
        self.error_kwargs = error_kwargs or {}
        self.size = size
        self.max_nodes = max_nodes
        super().__init__(self.root, transform, pre_transform)

        # ------------------------------------------------------------------
        # Load and process the raw data immediately so that the dataset is
        # ready for indexing.
        # ------------------------------------------------------------------
        self.process()

        # ------------------------------------------------------------------
        # ``pair_idxs`` simply stores indices 0 … N‑1 so that ``__len__``
        # and ``__getitem__`` work as expected.  Each stored element is already
        # a (corrupt, clean) pair.
        # ------------------------------------------------------------------
        self.pair_idxs = list(range(len(self)))  # each entry already a pair

    @property
    def raw_file_names(self):
        # All JSON files that reside in ``raw/``.
        return [p.name for p in (self.root / "raw").glob("*.json")]

    @property
    def processed_file_names(self):
        # One processed file per split; the split identifier is baked into
        # the filename.
        return [f"{self.split}_data.pt"]

    # ------------------------------------------------------------------
    # Main processing pipeline
    # ------------------------------------------------------------------
    def process(self):
        import sys
        # Append the location of the original RAVENS code so that the imports
        # below succeed in a stand‑alone environment.
        from pathlib import Path
        import sys, os
        rML_ROOT = Path(__file__).resolve().parents[3]
        if str(rML_ROOT) not in sys.path:
            sys.path.insert(0, str(rML_ROOT))
        from framework.dataset import MGRavensDataset
        from methods.connectivity.gen_conn_error import gen_conn_error

        # ------------------------------------------------------------------
        # 1) Load the *clean* MG–RAVENS dataset and convert it to the ML
        #    representation expected by ``dict_to_pyg``.
        # ------------------------------------------------------------------
        mgr = MGRavensDataset(data_dir=str(self.root / "data/seg_data"))
        mgr.process_for_ML()

        # ------------------------------------------------------------------
        # 2) Generate corrupted versions of the graphs.
        #
        #    ``gen_conn_error`` returns two objects:
        #      • ``corrupted_mgr`` – a list of (index, raw_mgr, dict) tuples
        #      • ``corrections``    – the list of edge additions required
        #        to recover the original connectivity.
        # ------------------------------------------------------------------
        target_size = self.size
        corrupted_mgr, corrections = gen_conn_error(
            mgr,
            size=target_size,
            delete_prob=0,
            rename_prob=0,
            **self.error_kwargs,
        )
        corrupted_mgr.process_for_ML()

        # ------------------------------------------------------------------
        # 3) Convert each (corrupt, clean) pair into a PyG ``Data`` object.
        #    The clean target is stored in the ``y`` attribute as a dict
        #    containing:
        #        * ``missing_edges`` – a binary adjacency matrix of the edges
        #          that need to be added.
        #        * ``raw_mgr``       – path to a temporary JSON file that
        #          holds the original (uncorrupted) RAVENS representation.
        # ------------------------------------------------------------------
        data_list = []
        for i in range(target_size):
            # ----- corrupted graph ------------------------------------------------
            corrupted_raw_mgr = corrupted_mgr[i][1]      # raw dict of the corrupted graph
            clean_raw_mgr = corrupted_mgr.raw_data[i][2]  
            corrupt_dict = corrupted_mgr[i][2]           # dict already in ML format
            corrupt_data = dict_to_pyg(corrupt_dict)

            # ----- build the clean target -----------------------------------------
            # Map connectivity‑node names to integer indices.
            node_list = list(corrupted_raw_mgr["ConnectivityNode"].keys())
            def find_index(name):
                try:
                    return node_list.index(name)
                except ValueError:
                    raise ValueError(f"Node name '{name}' not found in MGR 'Connectivity Nodes'")

            correction = corrections[i]
            indexed_correction = [(find_index(a), find_index(b))
                                  for a, b in correction['Edges Needed']]

            # Binary adjacency matrix of the missing edges.
            missing_edges = torch.zeros(
                (self.max_nodes, self.max_nodes),   # shape
                dtype=torch.float32                 # use float 
            )
            for src, dst in indexed_correction:
                missing_edges[src, dst] = 1
                missing_edges[dst, src] = 1

            # ----- store the original uncorrupted RAVENS JSON on disk -------------
            # The model is expected to read this file later for feature
            # extraction, so we write it to a temporary location.
            name, grid = corrupt_dict["file_name"], corrupt_dict["original_data"]
            name = os.path.splitext(os.path.basename(name))[0]
            mgr_path = (f"{rML_ROOT.as_posix()}/methods/connectivity/conn_gnn/tmp/mgr_data_tmp/{name}.json")
            with open(mgr_path, "w", encoding="utf-8") as f:
                json.dump(clean_raw_mgr, f, indent=2)#STORE THE CLEAN ORIGINAL

            # Attach the clean target to the corrupt graph.
            corrupt_data.y = {
                "missing_edges": missing_edges,
                "raw_mgr": mgr_path,
            }
            data_list.append(corrupt_data)

        # ------------------------------------------------------------------
        # 4) Deterministic train/val/test split (70 % / 15 % / 15 %).
        #    The same seed (42) is used each time so that experiments are
        #    reproducible.
        # ------------------------------------------------------------------
        random.Random(42).shuffle(data_list)
        n = len(data_list)
        if self.split == "train":
            data_slice = data_list[: int(0.7 * n)]
        elif self.split == "val":
            data_slice = data_list[int(0.7 * n) : int(0.85 * n)]
        elif self.split == "full":
            data_slice = data_list
        else:  # test
            data_slice = data_list[int(0.85 * n) :]

        # ------------------------------------------------------------------
        # 5) Collate the slice into the PyG ``Data``/``slices`` pair and
        #    serialize it to ``processed/``.
        # ------------------------------------------------------------------
        data, slices = self.collate(data_slice)
        torch.save((data, slices), self.processed_paths[0])
        self.data, self.slices = data, slices

    # ------------------------------------------------------------------
    # Convenience getters
    # ------------------------------------------------------------------
    def __len__(self):
        # ``InMemoryDataset.__len__`` returns the number of stored graphs.
        return super().__len__()

    def __getitem__(self, idx):
        # Return a single ``Data`` object; its ``.y`` field holds the clean
        # target (missing‑edge matrix and path to the original RAVENS file).
        return super().__getitem__(idx)


# ----------------------------------------------------------------------
# Simple sanity‑check when the module is executed directly
# ----------------------------------------------------------------------
if __name__ == '__main__':
    from pathlib import Path
    import sys, os
    rML_ROOT = Path(__file__).resolve().parents[3]
    if str(rML_ROOT) not in sys.path:
        sys.path.insert(0, str(rML_ROOT))
    dataset = MGConnDataset(
        root=rML_ROOT,
        size=20,
        max_nodes=20,
        error_kwargs={"del_e_prob": 0.20},
    )
    print(dataset[1])
