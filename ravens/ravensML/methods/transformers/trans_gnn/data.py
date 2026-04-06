# data.py
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
# Helper: convert the dict you already produce (MGRavensDataset.ravens_to_ML)
# ----------------------------------------------------------------------
def dict_to_pyg(data_dict: Dict[str, Any]) -> Data:
    """
    Convert the dictionary produced by ``MGRavensDataset.ravens_to_ML`` into a
    ``torch_geometric.data.Data`` object.
    """
    # --------------------------------------------------------------
    # 1) Node features
    # --------------------------------------------------------------
    x = torch.tensor(data_dict["node_features"], dtype=torch.float)

    # --------------------------------------------------------------
    # 2) Edge index – the dict already stores integer pairs
    # --------------------------------------------------------------
    edge_idx: list[list[int]] = []
    for _branch_id, pairs in data_dict["edge_index"].items():
        edge_idx.extend(pairs)                     # each pair is [src, dst]

    edge_index = torch.tensor(edge_idx, dtype=torch.long).t().contiguous()

    # --------------------------------------------------------------
    # 3) Determine the maximum number of phases in *this* graph
    # --------------------------------------------------------------
    # Every edge‑feature dict contains a key ``"phases"`` (as int or str)
    max_phase = max(
        int(feat["phases"]) for feat in data_dict["edge_features"].values()
    )
    # Guard against a graph that (for some reason) has no edges
    if max_phase == 0:
        max_phase = 1

    # --------------------------------------------------------------
    # 4) Helper that turns any entry (scalar / 1‑D / 2‑D) into a
    #    padded square matrix of shape (max_phase, max_phase)
    # --------------------------------------------------------------
    def _pad_matrix(mat):
        """Return a (max_phase, max_phase) float32 matrix."""
        mat = np.array(mat, dtype=np.float32)

        # ---- scalar ------------------------------------------------
        if mat.ndim == 0:                     # e.g. 0.0
            # broadcast the scalar to the whole matrix
            return np.full((max_phase, max_phase), float(mat), dtype=np.float32)

        # ---- 1‑D vector -------------------------------------------
        if mat.ndim == 1:                     # e.g. [r11, r22, r33]
            # place the vector on the diagonal of a zero matrix
            diag_mat = np.zeros((max_phase, max_phase), dtype=np.float32)
            diag_len = min(mat.shape[0], max_phase)
            diag_mat[np.arange(diag_len), np.arange(diag_len)] = mat[:diag_len]
            return diag_mat

        # ---- 2‑D matrix (the normal case) ------------------------
        if mat.ndim == 2:
            # If the matrix is already the right size we can return it
            if mat.shape == (max_phase, max_phase):
                return mat
            # Otherwise pad with zeros on the bottom‑right
            padded = np.zeros((max_phase, max_phase), dtype=np.float32)
            rows = min(mat.shape[0], max_phase)
            cols = min(mat.shape[1], max_phase)
            padded[:rows, :cols] = mat[:rows, :cols]
            return padded

        # ---- any higher‑dimensional object – fallback to zeros ----
        return np.zeros((max_phase, max_phase), dtype=np.float32)

    # --------------------------------------------------------------
    # 5) Build a *uniform* edge‑feature matrix
    # --------------------------------------------------------------
    edge_attrs: list[list[float]] = []

    # The order of ``edge_attrs`` must match the order of ``edge_index``.
    # For each branch we have stored both directions in ``edge_index``,
    # therefore we append the flattened feature *twice*.
    for _branch_id, feat in data_dict["edge_features"].items():
        phases = int(feat["phases"])

        # Pad the four impedance/admittance matrices
        R = _pad_matrix(feat.get("R", np.zeros((phases, phases))))
        X = _pad_matrix(feat.get("X", np.zeros((phases, phases))))
        G = _pad_matrix(feat.get("G", np.zeros((phases, phases))))
        B = _pad_matrix(feat.get("B", np.zeros((phases, phases))))

        # Scalars that are always present (fill missing keys with defaults)
        edge_type = float(feat.get("Edge Type", 0.0))
        tap = float(feat.get("Tap", 1.0))
        shift = float(feat.get("Shift", 0.0))

        # print(feat.get("name"))

        # Flatten everything in a deterministic order
        flat_feat = [
            float(phases),                     # 1
            *R.ravel().tolist(),               # max_phase**2
            *X.ravel().tolist(),               # max_phase**2
            *G.ravel().tolist(),               # max_phase**2
            *B.ravel().tolist(),               # max_phase**2
            edge_type,                         # 1
            tap,                               # 1
            shift,                             # 1
        ]

        # Two directions -> two identical rows
        edge_attrs.extend([flat_feat,flat_feat])

    edge_attr = torch.tensor(edge_attrs, dtype=torch.float)

    # --------------------------------------------------------------
    # 6) Return the PyG Data object.
    #    (Optionally store max_phase for downstream use.)
    # --------------------------------------------------------------
    data = Data(x=x, edge_index=edge_index, edge_attr=edge_attr)
    data.max_phase = max_phase          # handy if you need it later
    return data



# ----------------------------------------------------------------------
# InMemoryDataset that returns (corrupted, clean) pairs
# ----------------------------------------------------------------------
class MGTransformerDataset(InMemoryDataset):
    """
    PyG ``InMemoryDataset`` that yields a tuple ``(corrupted, clean)`` where
    both entries are ``torch_geometric.data.Data`` objects.

    Parameters
    ----------
    root : str
        Must contain a sub‑folder ``raw/`` with the original JSON files.
    split : str, optional
        ``'train'``, ``'val'`` or ``'test'``.  Dataset is split
        deterministically by a fixed seed.
    size : int, optional
        Number of *corrupted* samples to generate (default = all raw graphs).
    error_kwargs : dict
        Keyword arguments forwarded to ``generate_trans_error``.
    """
    def __init__(
        self,
        root: str,
        split: str = "full",
        size: int | None = None,
        error_kwargs: dict | None = None,
        transform=None,
        pre_transform=None,
    ):

        self.root = Path(root).expanduser()
        self.split = split
        self.error_kwargs = error_kwargs or {}
        self.size = size
        super().__init__(self.root, transform, pre_transform)

        #load dataset
        self.process()

        # ------------------------------------------------------------------
        # Keep separate lists for easy indexing: (corrupt, clean)
        # ------------------------------------------------------------------
        self.pair_idxs = list(range(len(self)))  # each entry already a pair

    @property
    def raw_file_names(self):
        # all json files in raw/
        return [p.name for p in (self.root / "raw").glob("*.json")]

    @property
    def processed_file_names(self):
        # same file for all splits – we embed the split in the file name
        return [f"{self.split}_data.pt"]

    # ------------------------------------------------------------------
    # Main processing pipeline
    # ------------------------------------------------------------------
    def process(self):
        from pathlib import Path
        import sys, os
        rML_ROOT = Path(__file__).resolve().parents[3]
        if str(rML_ROOT) not in sys.path:
            sys.path.insert(0, str(rML_ROOT))
        from framework.dataset import MGRavensDataset
        from methods.transformers.gen_trans_error import generate_trans_error

        # ------------------------------------------------------------------
        # 1 Load the clean data
        # ------------------------------------------------------------------
        mgr = MGRavensDataset(data_dir=str(self.root / "data/seg_data"))
        mgr.process_for_ML()

        # ------------------------------------------------------------------
        # 2 Create corrupted version + keep clean reference
        # ------------------------------------------------------------------
        # If you want *exactly* `size` samples, ask the generator for that many,
        # otherwise generate for every raw graph.
        target_size = self.size
        corrupted_mgr, clean_copies = generate_trans_error(
            mgr,
            size = target_size,
            **self.error_kwargs,
        )
        corrupted_mgr.process_for_ML()
        clean_copies.process_for_ML()


        # print(corrupted_mgr)

        # ------------------------------------------------------------------
        # 3 Convert each (corrupt, clean) pair to PyG Data objects
        # ------------------------------------------------------------------
        data_list = []
        for i in range(target_size):
            # ---- corrupted ----
            corrupt_dict = corrupted_mgr[i][2]
            corrupt_data = dict_to_pyg(corrupt_dict)

            # ---- clean (ground truth) ----

            clean_dict = clean_copies[i][2]
            clean_data = dict_to_pyg(clean_dict)

            # Store as a tuple (corrupt, clean).  PyG expects a single object,
            # so we glue them together in the ``y`` field.
            # ``y`` will be a dict with ``x`` and ``edge_attr`` of the clean graph.
            name, grid = clean_dict["file_name"], clean_dict["original_data"]
            name = os.path.splitext(os.path.basename(name))[0]
            mgr_path = f"{rML_ROOT.as_posix()}/methods/transformers/trans_gnn/tmp/mgr_data_tmp/{name}.json"
            with open(mgr_path, "w", encoding="utf-8") as f:
                json.dump(grid, f, indent=2)

            corrupt_data.y = {
                "x": clean_data.x,
                "edge_attr": clean_data.edge_attr,
                "edge_index": clean_data.edge_index, 
                "max_phase": clean_data.max_phase,
                "file_name": clean_copies[i][0],
                "raw_mgr": mgr_path,
            }
            data_list.append(corrupt_data)

        # ------------------------------------------------------------------
        # 4 Split deterministically (70/15/15) using a fixed seed
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

        # Save processed data
        data, slices = self.collate(data_slice)
        torch.save((data, slices), self.processed_paths[0])
        self.data, self.slices = data, slices

    

    # ------------------------------------------------------------------
    # Convenience getters
    # ------------------------------------------------------------------
    def __len__(self):
        return super().__len__()

    def __getitem__(self, idx):
        # Returns a single Data object whose .y holds the clean target
        return super().__getitem__(idx)

if __name__ == '__main__':
    from pathlib import Path
    import sys, os
    rML_ROOT = Path(__file__).resolve().parents[3]
    if str(rML_ROOT) not in sys.path:
        sys.path.insert(0, str(rML_ROOT))
    dataset = MGTransformerDataset(
        root=rML_ROOT,
        size=20,
    )
    print(dataset[1])
