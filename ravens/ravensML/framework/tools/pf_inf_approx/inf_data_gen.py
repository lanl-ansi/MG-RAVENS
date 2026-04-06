import sys
import copy
import random
from typing import List, Sequence, Tuple, Any, Dict
from warnings import warn
import numpy as np
from pathlib import Path
import sys, os
rML_ROOT = Path(__file__).resolve().parents[3]
if str(rML_ROOT) not in sys.path:
    sys.path.insert(0, str(rML_ROOT))
from framework.dataset import MGRavensDataset
from framework.tools.mgr_helpers import update_mgr, run_pf


def inf_data_gen(
    mgr: MGRavensDataset,
    *,
    mean: float = 1.0,
    std: float = 1.0, 
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
    X_mgr = copy.deepcopy(mgr)
    raw_data = copy.deepcopy(X_mgr.raw_data)
    X_mgr.raw_data = [] #X data for learning
    Y_inf = [] #infeasibility values for target


    # ------------------------------------------------------------------
    # 2  Create Errors in the data 
    # ------------------------------------------------------------------
    data_generated = 0
    rng = np.random.default_rng()
    while data_generated < size: 
        #generate clean data to modify to create errored input
        data_generated += 1
        ravens_data_prime = random.choice(raw_data)
        file_name,ravens_data=ravens_data_prime[0],copy.deepcopy(ravens_data_prime[1])

        #produce errored input X
        source_object = ravens_data_prime[1].get("PowerSystemResource").get("Equipment").get("ConductingEquipment").get("EnergyConnection").get("EnergyConsumer")
        target_object = ravens_data.get("PowerSystemResource").get("Equipment").get("ConductingEquipment").get("EnergyConnection").get("EnergyConsumer")
        for source_name, source_data in source_object.items():
            if "EnergyConsumer.p" in source_data.keys() and "EnergyConsumer.q" in source_data.keys():
                target_object[source_name]["EnergyConsumer.p"] = source_data.get("EnergyConsumer.p")*rng.normal(loc=mean, scale=std)
                target_object[source_name]["EnergyConsumer.q"] = source_data.get("EnergyConsumer.q")*rng.normal(loc=mean, scale=std)

        #store modified input X
        X_mgr.raw_data.append([file_name,ravens_data])    

        #store resulting output Y 
        Y_inf.append(inf_score(ravens_data))

    return (X_mgr, Y_inf)

def inf_score(target_grid):
    results = run_pf(target_grid)
    return system_demand_not_met(results)

def system_demand_not_met(pmd_output):
    total_generation = 0.0
    total_load = 0.0
    expected_losses = 0.0
    pm_solution = pmd_output['solution']
    
    # Process generation - directly using 'gen' which we know exists
    if "gen" in pm_solution:
        for gen in pm_solution["gen"].values():
            if "pg" in gen:
                pg_value = gen["pg"]
                if isinstance(pg_value, list):
                    # Sum all elements if pg is a list
                    total_generation += sum(float(val) for val in pg_value)
                else:
                    # Handle single value case
                    total_generation += float(pg_value)
    
    # Process load - directly using 'load' which we know exists
    if "load" in pm_solution:
        for load in pm_solution["load"].values():
            if "pd" in load:
                pd_value = load["pd"]
                if isinstance(pd_value, list):
                    # Sum all elements if pd is a list
                    total_load += sum(float(val) for val in pd_value)
                else:
                    # Handle single value case
                    total_load += float(pd_value)
    
    # Calculate branch losses - directly using 'branch' which we know exists
    if "branch" in pm_solution:
        for branch in pm_solution["branch"].values():
            if "pf" in branch and "pt" in branch:
                pf_value = branch["pf"]
                pt_value = branch["pt"]
                
                # Handle if these are lists
                if isinstance(pf_value, list) and isinstance(pt_value, list):
                    for i in range(min(len(pf_value), len(pt_value))):
                        expected_losses += abs(float(pf_value[i]) + float(pt_value[i]))
                else:
                    expected_losses += abs(float(pf_value) + float(pt_value))
    
    # Generation should equal load plus losses
    # Negative value means demand not met
    power_balance = total_generation - (total_load + expected_losses)
    return 100*max(0.0, -power_balance)  # In per unit, only return positive values
    
    



