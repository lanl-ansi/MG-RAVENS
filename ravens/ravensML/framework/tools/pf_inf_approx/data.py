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

class MG_Inf_Dataset(t_MG_Dataset):
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

if __name__ == '__main__':
    import time
    from pathlib import Path
    import sys, os
    rML_ROOT = Path(__file__).resolve().parents[3]
    if str(rML_ROOT) not in sys.path:
        sys.path.insert(0, str(rML_ROOT))
    dataset = MG_Inf_Dataset(
        root=rML_ROOT,
        path = "data/seg_data",
        size=10,
        synth_kwargs={"mean": 0.0,"std": 0.5},
    )
    time.sleep(5)
    print(dataset[1])
