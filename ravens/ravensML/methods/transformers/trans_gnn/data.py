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

class MGTransformerDataset(t_MG_Dataset):
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

if __name__ == '__main__':
    from pathlib import Path
    import sys, os
    rML_ROOT = Path(__file__).resolve().parents[3]
    if str(rML_ROOT) not in sys.path:
        sys.path.insert(0, str(rML_ROOT))
    dataset = MGTransformerDataset(
        root=rML_ROOT,
        path = "data/seg_data",
        size=20,
    )
    print(dataset[1])
