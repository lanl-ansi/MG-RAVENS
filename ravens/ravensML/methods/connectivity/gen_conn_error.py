import sys
import copy
import random
from typing import List, Sequence, Tuple, Any, Dict
from pathlib import Path
import sys, os
rML_ROOT = Path(__file__).resolve().parents[2]
if str(rML_ROOT) not in sys.path:
    sys.path.insert(0, str(rML_ROOT))
from framework.dataset import MGRavensDataset


def typo(good_str,):
    char_list = list(good_str)
    char_list = [ord(c) for c in char_list]
    char_list[random.randint(0,len(char_list)-1)] += 1
    bad_str = "".join([chr(c) for c in char_list])
    return bad_str

def gen_conn_error(
    mgr: MGRavensDataset,
    *,
    rename_prob: float = 0.12,
    delete_prob: float = 0.05,
    del_e_prob: float = 0,
    seed: int | None = None,
    size: int = 0
) -> MGRavensDataset:
    
    # ------------------------------------------------------------------
    # 0  Initialise RNG (optional reproducibility)
    # ------------------------------------------------------------------
    if seed is not None:
        random.seed(seed)

    # ------------------------------------------------------------------
    # 1  setup new dataset so the original stays pristine.
    # ------------------------------------------------------------------
    corrupted_mgr = copy.deepcopy(mgr)
    raw_data = copy.deepcopy(corrupted_mgr.raw_data)
    corrupted_mgr.raw_data = []
    corrections = []

    # ------------------------------------------------------------------
    # 2  Create Errors in the data 
    # ------------------------------------------------------------------
    data_generated = 0
    while data_generated < size:
        data_generated += 1
        ravens_data_prime = random.choice(raw_data)
        file_name,ravens_data=copy.deepcopy(ravens_data_prime[0]),copy.deepcopy(ravens_data_prime[1])
        correction = {"Edges Needed":[],"Missing Nodes":[]}

        #rename line end
        branches = ravens_data['PowerSystemResource']['Equipment']['ConductingEquipment']['Conductor'].get('ACLineSegment', {})
        for branch_id, branch_data in list(branches.items()):
            if random.random() < rename_prob:
                #store correct edge
                correction['Edges Needed'].append((branch_data['ConductingEquipment.Terminals'][0]['Terminal.ConnectivityNode'].split("::")[-1].strip("\'"),
                                                    branch_data['ConductingEquipment.Terminals'][1]['Terminal.ConnectivityNode'].split("::")[-1].strip("\'")))

                #produce error
                terminal = branch_data['ConductingEquipment.Terminals'][random.randint(0,1)]
                name_list = terminal['Terminal.ConnectivityNode'].split("::")
                node_id = name_list[-1].strip("\'")
                node_id = typo(node_id)
                name_list[-1] = f"'{node_id}'"
                edit_name = "::".join(name_list)
                terminal['Terminal.ConnectivityNode'] = edit_name
            elif random.random() < del_e_prob:
                correction['Edges Needed'].append((branch_data['ConductingEquipment.Terminals'][0]['Terminal.ConnectivityNode'].split("::")[-1].strip("\'"),
                                                    branch_data['ConductingEquipment.Terminals'][1]['Terminal.ConnectivityNode'].split("::")[-1].strip("\'")))
                del branches[branch_id]
                assert(branch_id not in branches.keys())
                

        #delete nodes
        buses = ravens_data.get('ConnectivityNode', {})
        for bus_id, bus_data in list(buses.items()):
            if random.random() < delete_prob:
                correction["Missing Nodes"].append(bus_id)
                ravens_data['ConnectivityNode'].pop(bus_id)
        
        corrupted_mgr.raw_data.append([file_name,ravens_data,ravens_data_prime[1]])

        corrections.append(correction)
    
    return (corrupted_mgr,corrections)
