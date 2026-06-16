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


class MGEdgeTypeDataset(t_MG_Dataset):
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


if __name__ == '__main__':
    from pathlib import Path
    import sys, os
    rML_ROOT = Path(__file__).resolve().parents[3]
    if str(rML_ROOT) not in sys.path:
        sys.path.insert(0, str(rML_ROOT))
    dataset = MGEdgeTypeDataset(
        root=rML_ROOT,
        path = "data/BIG_seg_data",
        size=20,
        synth_kwargs={"change_prob": 0.20},
    )
    print(dataset[1])
