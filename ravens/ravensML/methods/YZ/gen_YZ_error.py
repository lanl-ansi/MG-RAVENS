import sys
import copy
import random
from typing import List, Sequence, Tuple, Any, Dict
import numpy as np
sys.path.append('/Users/oreed/Desktop/LANL-ANSI/MG-RAVENS/ravens/ravensML')
from framework.dataset import MGRavensDataset


def generate_yz_error(
    mgr: MGRavensDataset,
    *,
    deletion_prob: float = 0.02,
    occurrence_prob: float = 0.12,
    mult_mean: float = 1,
    mult_var: float = 1,
    add_mean: float = 0,
    add_var: float = 1,
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
        #generate clean data to modify to create errored input
        data_generated += 1
        ravens_data_prime = copy.deepcopy(random.choice(raw_data))
        file_name,ravens_data=ravens_data_prime[0],ravens_data_prime[1]

        #store correct output Y 
        corrections.append(copy.deepcopy(ravens_data)) 

        #produce errored input X
        PLPI = ravens_data.get("PerLengthLineParameter",{}).get("PerLengthImpedance",{}).get("PerLengthPhaseImpedance",{})
        for plpi_name, plpi_data in PLPI.items():
            pid = plpi_data["PerLengthPhaseImpedance.PhaseImpedanceData"]
            if random.random() < deletion_prob: #Deletion Error
                for entry in pid:
                    # Directly modify the values in the original dictionary
                    for param in ["r", "x", "b"]:
                        key = f"PhaseImpedanceData.{param}"
                        if key in entry and entry[key] is not None:  # Check if parameter exists
                            entry[key] = 0
            else: #Affine Error
                for param in ["r", "x", "b"]:
                    if random.random() < occurrence_prob:
                        for entry in pid:
                            # Directly modify the values in the original dictionary
                            m = np.random.normal(loc=mult_mean,scale=np.sqrt(mult_var))
                            a = np.random.normal(loc=add_mean,scale=np.sqrt(add_var))
                            key = f"PhaseImpedanceData.{param}"
                            if key in entry and entry[key] is not None:  # Check if parameter exists
                                #generate affine error
                                entry[key] = max(0.0,m*entry[key]+a)   

        #store errored input X
        corrupted_mgr.raw_data.append([file_name,ravens_data])            

    return (corrupted_mgr, corrections)


if __name__ == "__main__":
    MGR = MGRavensDataset(data_dir="ravens/ravensML/data/raw")
    MGR_CONN_TEST, Y = generate_yz_error(MGR,occurrence_prob=1,size=1)  



