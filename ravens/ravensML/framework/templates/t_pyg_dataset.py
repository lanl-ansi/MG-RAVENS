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

from pathlib import Path
import sys, os
rML_ROOT = Path(__file__).resolve().parents[2]
if str(rML_ROOT) not in sys.path:
    sys.path.insert(0, str(rML_ROOT))
from framework.dataset import MGRavensDataset




class t_MG_Dataset(InMemoryDataset):
    def __init__(
        self,
        root: str,
        path: str,
        split: str = "train",
        size: int | None = None,
        synth_kwargs: dict | None = None,
        transform=None,
        pre_transform=None,
    ):

        self.root = Path(root).expanduser()
        self.split = split
        self.synth_kwargs = synth_kwargs or {}
        self.size = size
        self.path = Path(path)
        super().__init__(self.root, transform, pre_transform)

        #load dataset
        self.process()

        # Keep separate lists for easy indexing: (corrupt, clean)
        self.pair_idxs = list(range(len(self)))  # each entry already a pair

    @property
    def raw_file_names(self):
        # all json files in raw/
        return [p.name for p in (self.root / "raw").glob("*.json")]

    @property
    def processed_file_names(self):
        # same file for all splits – we embed the split in the file name
        return [f"{self.split}_data.pt"]

    def process(self):
        mgr = MGRavensDataset(data_dir=str(self.root / self.path))
        mgr.process_for_ML()


        # 2 Create corrupted version + keep clean reference
        target_size = self.size

        corrupted_mgr, aux = self._apply_synth_transform(mgr,target_size)


        # 3 Convert each (corrupt, clean) pair to PyG Data objects
        data_list = []
        for i in range(target_size):
            #create data
            corrupted_raw_mgr = corrupted_mgr[i][1]    
            clean_raw_mgr = corrupted_mgr.raw_data[i][2]  
            corrupt_dict = corrupted_mgr[i][2]
            corrupt_data = self._pyg_modify(self.dict_to_pyg(corrupt_dict),aux,corrupt_dict,corrupted_raw_mgr,i)

            name, grid = corrupt_dict["file_name"], corrupt_dict["original_data"]
            name = os.path.splitext(os.path.basename(name))[0]
            mgr_path = (f"{rML_ROOT.as_posix()}/methods/connectivity/conn_gnn/tmp/mgr_data_tmp/{name}.json")
            with open(mgr_path, "w", encoding="utf-8") as f:
                json.dump(clean_raw_mgr, f, indent=2)#STORE THE CLEAN ORIGINAL

            corrupt_data.y = self._get_target(i, mgr_path, corrupt_dict,corrupt_data, aux)
            data_list.append(corrupt_data)

        # 4 Split deterministically (70/15/15) using a fixed seed
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


    # Convert the dict form MGR object to py-geo
    def dict_to_pyg(self, data_dict: Dict[str, Any]):
        """
        Convert the dictionary produced by ``MGRavensDataset.ravens_to_ML`` into a
        ``torch_geometric.data.Data`` object.
        """
        # 1) Create Node features
        node_feat = data_dict["node_features"]
        x = torch.tensor(node_feat, dtype=torch.float)


        
        # 2) Create Edge index 
        edge_idx: list[list[int]] = []
        for _branch_id, pairs in data_dict["edge_index"].items():
            edge_idx.extend(pairs)                     # each pair is [src, dst]

        edge_index = torch.tensor(edge_idx, dtype=torch.long).t().contiguous()

        
        # 3) Phase correction
        max_phase = max(
            int(feat["phases"]) for feat in data_dict["edge_features"].values()
        ) or 1

        # Helper: pads matrices to max_phase size
        def _pad_matrix(mat):
            """Return a (max_phase, max_phase) float32 matrix."""
            mat = np.array(mat, dtype=np.float32)

            # scalar
            if mat.ndim == 0:
                # broadcast the scalar to the whole matrix
                return np.full((max_phase, max_phase), float(mat), dtype=np.float32)

            # 1-D vector 
            if mat.ndim == 1: # place the vector on the diagonal of a zero matrix
                diag_mat = np.zeros((max_phase, max_phase), dtype=np.float32)
                diag_len = min(mat.shape[0], max_phase)
                diag_mat[np.arange(diag_len), np.arange(diag_len)] = mat[:diag_len]
                return diag_mat

            # 2-D matrix 
            if mat.ndim == 2:
                # If the matrix is already the right size we can return it
                if mat.shape == (max_phase, max_phase):
                    return mat
                # Otherwise pad with zeros on the bottom-right
                padded = np.zeros((max_phase, max_phase), dtype=np.float32)
                rows = min(mat.shape[0], max_phase)
                cols = min(mat.shape[1], max_phase)
                padded[:rows, :cols] = mat[:rows, :cols]
                return padded

            return None

        
        # 4) Create edge-feature vector
        edge_attrs: list[list[float]] = []
        for _branch_id, feat in data_dict["edge_features"].items():
            phases = int(feat["phases"])

            # Pad the four impedance/admittance matrices to a common size.
            R = _pad_matrix(feat.get("R", np.zeros((phases, phases))))
            X = _pad_matrix(feat.get("X", np.zeros((phases, phases))))
            G = _pad_matrix(feat.get("G", np.zeros((phases, phases))))
            B = _pad_matrix(feat.get("B", np.zeros((phases, phases))))

            # Scalars that are always present – use sensible defaults if missing.
            edge_type = int(feat.get("edge_type", 3))
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

        data = Data(x=x, edge_index=edge_index, edge_attr=edge_attr)
        data.max_phase = max_phase          # handy if you need it later
        return data


    def __len__(self):
        return super().__len__()

    def __getitem__(self, idx):
        return super().__getitem__(idx)
    

    
    # Templates
    def _get_target(self, i, mgr_path, corrupt_dict, corrupt_data, aux):
        raise NotImplementedError("This instance of a MG-Ravens pytorch dataset is a template. Please implement it by defining the `_get_target` method.")
    
    def _apply_synth_transform(self, mgr,target_size):
        from framework.templates.t_synthetic_transform import t_generate_synthetic_transform
        #TODO: make optional
        raise NotImplementedError("This instance of a MG-Ravens pytorch dataset is a template. Please implement it by defining the `__apply_synth_transform` method.")
        corrupted_mgr, clean_copies = t_generate_synthetic_transform(
            mgr,
            size = target_size,
            **self.synth_kwargs,
        )
        corrupted_mgr.process_for_ML()
        clean_copies.process_for_ML()
        return corrupted_mgr, clean_copies, None
    
    def _pyg_modify(self, pyg, aux, data_dict, mg,i):
        return pyg

if __name__ == '__main__':
    #Test implementations of custom dataset objects
    class et_dataset(t_MG_Dataset):
        def _get_target(self, i, mgr_path, corrupt_dict, corrupt_data, aux):
            corrections = aux["corrections"]
            edge_type = torch.tensor(
                corrections[i], 
                dtype=torch.int8 
            )
            return {
                "edge_labels": edge_type,
                "raw_mgr": mgr_path,
            }

        def _apply_synth_transform(self,mgr,target_size):
            from methods.edge_type.gen_et_error import gen_et_error
            corrupted_mgr, corrections, errors = gen_et_error(
                mgr,
                size=target_size,
                **self.synth_kwargs,
            )
            corrupted_mgr.process_for_ML()
            node_list = []
            for i in range(len(corrupted_mgr)):
                node_list.append(list(corrupted_mgr[i][1]["ConnectivityNode"].keys()))
            aux = {"corrections":corrections,"node_list":node_list}
            return corrupted_mgr, aux
        
        def _pyg_modify(self, pyg, aux, data_dict, mgr, i):
            node_list = aux["node_list"][i]
            errors = aux["corrections"][i]
            def find_index(name):
                name = name.split(":")[-1].strip("'")
                try:
                    return node_list.index(name)
                except ValueError:
                    print(node_list,name)
                    raise ValueError(f"Node name '{name}' not found in MGR 'Connectivity Nodes'")
            for i, (_branch_id, feat) in enumerate(data_dict["edge_features"].items()):
                edge = pyg.edge_attr[i]
                if edge[-3] != 3:
                    to_node, fr_node = self._get_nodes(_branch_id,mgr) #TODO: think about this
                    if to_node != None:
                        a,b = find_index(to_node),find_index(fr_node)
                        pyg.edge_attr[i] = torch.tensor(errors[a][b]) 
            return pyg
        

        def _get_nodes(self,branch,mgr):
            lines = mgr['PowerSystemResource']['Equipment']['ConductingEquipment']['Conductor'].get('ACLineSegment', {})
            switches = mgr['PowerSystemResource']['Equipment']['ConductingEquipment'].get('Switch', {})
            trans = mgr['PowerSystemResource']['Equipment']['ConductingEquipment'].get('PowerTransformer', {})
            if branch in lines.keys():
                target = lines
            elif branch in switches.keys():
                target = switches
            elif branch in trans.keys():
                target = trans
            else:
                return None, None
            to_node = target[branch]["ConductingEquipment.Terminals"][0]["Terminal.ConnectivityNode"]
            fr_node = target[branch]["ConductingEquipment.Terminals"][1]["Terminal.ConnectivityNode"]
            return to_node, fr_node

            

    MGET = et_dataset(        
            root=rML_ROOT,
            path = "data/BIG_seg_data",
            size=10,
            synth_kwargs={"change_prob": 1, "enforce_PE":True},
        )
    
    print(MGET[0])

    class conn_dataset(t_MG_Dataset):
        def __init__(self, root, path, max_nodes, split = "train", size = None, synth_kwargs = None, transform=None, pre_transform=None):
            self.max_nodes = max_nodes
            super().__init__(root, path, split, size, synth_kwargs, transform, pre_transform)
            

        def _get_target(self, i, mgr_path, corrupt_dict, corrupt_data, aux):
            correction = aux["corrections"][i]
            node_list = aux["node_list"][i]

            def find_index(name):
                try:
                    return node_list.index(name)
                except ValueError:
                    raise ValueError(f"Node name '{name}' not found in MGR 'Connectivity Nodes'")
                
            indexed_correction = [(find_index(a), find_index(b))
                                  for a, b in correction['Edges Needed']]

            # Binary adjacency matrix of the missing edges.
            missing_edges = torch.zeros(
                (self.max_nodes, self.max_nodes),  
                dtype=torch.float32               
            )
            for src, dst in indexed_correction:
                missing_edges[src, dst] = 1
                missing_edges[dst, src] = 1
            return {
                "missing_edges": missing_edges,
                "raw_mgr": mgr_path,
            }

        def _apply_synth_transform(self,mgr,target_size):
            from methods.connectivity.gen_conn_error import gen_conn_error
            corrupted_mgr, corrections = gen_conn_error(
                mgr,
                size=target_size,
                delete_prob=0,
                rename_prob=0,
                **self.synth_kwargs,
            )
            corrupted_mgr.process_for_ML()
            node_list = []
            for i in range(len(corrupted_mgr)):
                node_list.append(list(corrupted_mgr[i][1]["ConnectivityNode"].keys()))
            aux = {"node_list":node_list,"corrections":corrections}
            return corrupted_mgr, aux
        
    MGC = conn_dataset(
        root=rML_ROOT,
        path = "data/seg_data",
        size=100,
        max_nodes=20,
        synth_kwargs={"del_e_prob": 1, "enforce_PE":True},
    )

    print(MGC[0])

    class trans_dataset(t_MG_Dataset):
        def _get_target(self, i, mgr_path, corrupt_dict, corrupt_data, aux):
            clean_copy = aux["clean_copies"][i][0]
            clean_data = aux["clean_data"][i]
            return {
                "x": clean_data.x,
                "edge_attr": clean_data.edge_attr,
                "edge_index": clean_data.edge_index, 
                "max_phase": clean_data.max_phase,
                "file_name": clean_copy,
                "raw_mgr": mgr_path,
            }
        
        def _apply_synth_transform(self,mgr,target_size):
            from methods.transformers.gen_trans_error import generate_trans_error
            corrupted_mgr, clean_copies = generate_trans_error(
                mgr,
                size = target_size,
                **self.synth_kwargs,
            )
            corrupted_mgr.process_for_ML()
            clean_copies.process_for_ML()
            clean_data_list = []
            for i in range(len(clean_copies)):
                clean_dict = clean_copies[i][2]
                clean_data_list.append(self.dict_to_pyg(clean_dict))
            aux = {"clean_copies":clean_copies, "clean_data": clean_data_list}
            return corrupted_mgr, aux
        
    MGTr = trans_dataset(
        root=rML_ROOT,
        path = "data/seg_data",
        size=10,
        synth_kwargs={"deletion_prob": 0.01, 
                    "occurrence_prob": 0.55,
                    "mult_mean": 1,
                    "mult_var": 2.25,
                    "add_mean": 0,
                    "add_var": 2.25,},
    )

    print(MGTr[0])



    class pinf_dataset(t_MG_Dataset):
        def _get_target(self, i, mgr_path, corrupt_dict, corrupt_data, aux):
            Y_inf = aux["infeasibility"]
            return Y_inf[i]
        
        def _apply_synth_transform(self,mgr,target_size):
            from framework.tools.pf_inf_approx.inf_data_gen import inf_data_gen
            (X_mgr, Y_inf) = inf_data_gen(
                mgr,
                size = target_size,
                seed=0,
                **self.synth_kwargs,
            )
            X_mgr.process_for_ML()
            aux = {"infeasibility": Y_inf}
            return X_mgr, aux


    
    MGPF = pinf_dataset(
        root=rML_ROOT,
        path = "data/seg_data",
        size=10,
        synth_kwargs={"mean": 0.0,"std": 0.5},
    )

    print(MGTr[0])

