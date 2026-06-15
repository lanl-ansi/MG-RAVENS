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
rML_ROOT = Path(__file__).resolve().parents[3]
if str(rML_ROOT) not in sys.path:  
    sys.path.insert(0, str(rML_ROOT))
from ravens.ravensML.framework.templates.t_pyg_dataset import t_MG_Dataset


class MGConnDataset(t_MG_Dataset):
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
        
        
if __name__ == '__main__':
    from pathlib import Path
    import sys, os
    rML_ROOT = Path(__file__).resolve().parents[3]
    if str(rML_ROOT) not in sys.path:
        sys.path.insert(0, str(rML_ROOT))
    dataset = MGConnDataset(
        root=rML_ROOT,
        path = "data/seg_data",
        size=20,
        max_nodes=20,
        synth_kwargs={"del_e_prob": 0.20},
    )
    print(dataset[1])
