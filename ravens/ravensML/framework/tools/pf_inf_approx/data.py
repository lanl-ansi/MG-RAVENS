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
from torch_geometric.data import Batch

from pathlib import Path
import sys, os
rML_ROOT = Path(__file__).resolve().parents[3]
if str(rML_ROOT) not in sys.path:
    sys.path.insert(0, str(rML_ROOT))
from framework.dataset import MGRavensDataset
from framework.tools.pf_inf_approx.inf_data_gen import inf_data_gen

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
    node_feat = data_dict["node_features"]
    x = torch.tensor(node_feat, dtype=torch.float)


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
class MG_Inf_Dataset(InMemoryDataset):
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
        Keyword arguments forwarded to ``generate_inf_error``.
    """
    def __init__(
        self,
        root: str,
        split: str = "train",
        size: int | None = None,
        error_kwargs: dict | None = None,
        transform=None,
        pre_transform=None,
    ):

        self.root = Path(root).expanduser()
        self.split = split
        self.error_kwargs = error_kwargs or {}
        self.size = size
        self.signature = int(10000*random.random())
        super().__init__(self.root, transform, pre_transform)


        if self.size != 0:
            #load dataset
            self.process()
            # ------------------------------------------------------------------
            # Keep separate lists for easy indexing: (corrupt, clean)
            # ------------------------------------------------------------------
            self.pair_idxs = list(range(len(self)))  # each entry already a pair

    @property
    def raw_file_names(self):
        # all json files in raw/
        return [p.name for p in (self.root / "data/seg_data").glob("*.json")]

    @property
    def processed_file_names(self):
        # same file for all splits – we embed the split in the file name
        return [f"{self.split}_data.pt"]

    # ------------------------------------------------------------------
    # Main processing pipeline
    # ------------------------------------------------------------------
    def process(self):

        # ------------------------------------------------------------------
        # 1 Load the clean data
        # ------------------------------------------------------------------
        mgr = MGRavensDataset(data_dir=str(self.root/"data/seg_data"))
        mgr.process_for_ML()

        # ------------------------------------------------------------------
        # 2 Create corrupted version + keep clean reference
        # ------------------------------------------------------------------
        # If you want *exactly* `size` samples, ask the generator for that many,
        # otherwise generate for every raw graph.
        target_size = self.size
        X_mgr, Y_inf = inf_data_gen(
            mgr,
            size = target_size,
            seed=0,
            **self.error_kwargs,
        )
        X_mgr.process_for_ML()


        # print(corrupted_mgr)

        # ------------------------------------------------------------------
        # 3 Convert each (corrupt, clean) pair to PyG Data objects
        # ------------------------------------------------------------------
        data_list = []
        for i in range(target_size):
            # ---- corrupted ----
            X_dict = X_mgr[i][2]
            X_data = dict_to_pyg(X_dict)

            # ---- clean (ground truth) ----

            # Store as a tuple (corrupt, clean).  PyG expects a single object,
            # so we glue them together in the ``y`` field.
            # ``y`` will be a dict with ``x`` and ``edge_attr`` of the clean graph.
            name, grid = X_dict["file_name"], X_dict["original_data"]
            name = os.path.splitext(os.path.basename(name))[0]+str(i)
            mgr_path = rML_ROOT/f"framework/tools/pf_inf_approx/inf_model_data/{name}.json"
            with open(mgr_path, "w", encoding="utf-8") as f:
                json.dump(grid, f, indent=2)

            X_data.y = Y_inf[i]
            data_list.append(X_data)

        # ------------------------------------------------------------------
        # 4 Split deterministically (70/15/15) using a fixed seed
        # ------------------------------------------------------------------
        random.Random(42).shuffle(data_list)
        n = len(data_list)
        if self.split == "train":
            data_slice = data_list[: int(0.7 * n)]
        elif self.split == "val":
            data_slice = data_list[int(0.7 * n) : int(0.85 * n)]
        else:  # test
            data_slice = data_list[int(0.85 * n) :]

        # Save processed data
        data, slices = self.collate(data_slice)
        torch.save((data, slices), self.processed_paths[0])
        self.data, self.slices = data, slices

    def convert_input(self,MGR_grid,device):
        mgr_path = self.root/f"framework/tools/pf_inf_approx/tmp/tmp_test_input/{str(self.signature)}tmp.json"
        with open(mgr_path, "w", encoding="utf-8") as f:
            json.dump(MGR_grid, f, indent=2)
        MGD = MGRavensDataset(data_dir=str(self.root/f"framework/tools/pf_inf_approx/tmp/tmp_test_input/{str(self.signature)}tmp.json"))
        MGD.process_for_ML()
        rML_obj = MGD[0][2]
        output = dict_to_pyg(rML_obj).to(device)
        return output

    # ------------------------------------------------------------------
    # Convenience getters
    # ------------------------------------------------------------------
    def __len__(self):
        return super().__len__()

    def __getitem__(self, idx):
        # Returns a single Data object whose .y holds the clean target
        return super().__getitem__(idx)

if __name__ == '__main__':
    import time
    from pathlib import Path
    import sys, os
    rML_ROOT = Path(__file__).resolve().parents[3]
    if str(rML_ROOT) not in sys.path:
        sys.path.insert(0, str(rML_ROOT))
    dataset = MG_Inf_Dataset(
        root=rML_ROOT,
        size=20,
        error_kwargs={"mean": 0.0,"std": 0.5},
    )
    time.sleep(5)
    print(dataset[1])
