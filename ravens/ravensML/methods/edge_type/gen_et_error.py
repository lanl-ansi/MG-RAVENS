import sys
import copy
import random
import numpy as np
from typing import List, Sequence, Tuple, Any, Dict
from pathlib import Path
import sys, os
rML_ROOT = Path(__file__).resolve().parents[2]
if str(rML_ROOT) not in sys.path:
    sys.path.insert(0, str(rML_ROOT))
from framework.dataset import MGRavensDataset



def gen_et_error(
    mgr: MGRavensDataset,
    *,
    change_prob: float = 0.12,
    seed: int | None = None,
    size: int = 0,
    enforce_PE: bool = False
) -> MGRavensDataset:
    if seed is not None:
        random.seed(seed)

    #setup new dataset
    corrupted_mgr = copy.deepcopy(mgr)
    raw_data = copy.deepcopy(corrupted_mgr.raw_data)
    corrupted_mgr.raw_data = []
    corrections, errors = [], []

    #generate synthetic data
    data_generated = 0
    while data_generated < size:
        data_generated += 1
        ravens_data_prime = random.choice(raw_data)
        if enforce_PE:
            ravens_data_prime = (ravens_data_prime[0],perm_equivar(ravens_data_prime[1]))

        file_name,ravens_data=copy.deepcopy(ravens_data_prime[0]),copy.deepcopy(ravens_data_prime[1])

        node_list = list(ravens_data["ConnectivityNode"].keys())
        def find_index(name):
            name = name.split(":")[-1].strip("'")
            try:
                return node_list.index(name)
            except ValueError:
                print(node_list,name)
                raise ValueError(f"Node name '{name}' not found in MGR 'Connectivity Nodes'")

        #collect edge info with associated to and from labels
        correct = []
        for line in ravens_data['PowerSystemResource']['Equipment']['ConductingEquipment']['Conductor'].get('ACLineSegment', {}).values():
            label = 0
            to_node = find_index(line["ConductingEquipment.Terminals"][0]["Terminal.ConnectivityNode"])
            fr_node = find_index(line["ConductingEquipment.Terminals"][1]["Terminal.ConnectivityNode"])
            correct.append([label,to_node,fr_node])
        for switch in ravens_data['PowerSystemResource']['Equipment']['ConductingEquipment'].get('Switch', {}).values():
            label = 1
            to_node = find_index(switch["ConductingEquipment.Terminals"][0]["Terminal.ConnectivityNode"])
            fr_node = find_index(switch["ConductingEquipment.Terminals"][1]["Terminal.ConnectivityNode"])
            correct.append([label,to_node,fr_node])
        for trans in ravens_data['PowerSystemResource']['Equipment']['ConductingEquipment'].get('PowerTransformer', {}).values():
            label = 2
            to_node = find_index(trans["ConductingEquipment.Terminals"][0]["Terminal.ConnectivityNode"])
            fr_node = find_index(trans["ConductingEquipment.Terminals"][1]["Terminal.ConnectivityNode"])
            correct.append([label,to_node,fr_node])

        #generate correct edge label adjacency matrix
        correct_adj = np.zeros(
            (len(node_list), len(node_list)),
            dtype=np.float32
        )
        correct_adj -= 1 #shift labels to 0 indexed
        for label, src, dst in correct:
            correct_adj[src, dst] = label
            correct_adj[dst, src] = label
        
        #generate errored edge label adjacency matrix
        errored_adj = copy.deepcopy(correct_adj)
        for i in range(len(node_list)):
            for j in range(len(node_list)):
                t = errored_adj[i][j]
                if random.random() < change_prob and t != -1:
                    errored_adj[i][j] =  (t + random.randint(1,2))%3 

        #store data
        corrupted_mgr.raw_data.append([file_name,ravens_data,ravens_data_prime[1]])
        corrections.append(correct_adj)
        errors.append(errored_adj)
    
    return (corrupted_mgr,corrections,errors)



def perm_equivar(ravens):
    pe_ravens = copy.deepcopy(ravens)
    #Pop the Current List of Nodes and Edges
    node_list = list(pe_ravens["ConnectivityNode"].items())
    edge_list = list(pe_ravens["PowerSystemResource"]["Equipment"]["ConductingEquipment"]["Conductor"]["ACLineSegment"].items())
    pe_ravens["PowerSystemResource"]["Equipment"]["ConductingEquipment"]["Conductor"]["ACLineSegment"] = {}
    pe_ravens["ConnectivityNode"] = {}
    #Re-Insert under permutation
    for i in range(len(node_list)):
        candidate = node_list.pop(random.randrange(len(node_list)))
        pe_ravens["ConnectivityNode"][candidate[0]] = candidate[1]
    for i in range(len(edge_list)):
        candidate = edge_list.pop(random.randrange(len(edge_list)))
        pe_ravens["PowerSystemResource"]["Equipment"]["ConductingEquipment"]["Conductor"]["ACLineSegment"][candidate[0]] = candidate[1]
    return pe_ravens

