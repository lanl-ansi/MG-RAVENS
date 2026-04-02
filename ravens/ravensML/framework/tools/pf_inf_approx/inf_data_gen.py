import sys
import copy
import random
from typing import List, Sequence, Tuple, Any, Dict
import numpy as np
from pathlib import Path
import sys, os
rML_ROOT = Path(__file__).resolve().parents[3]
if str(rML_ROOT) not in sys.path:
    sys.path.insert(0, str(rML_ROOT))
from framework.dataset import MGRavensDataset


def t_generate_synthetic_transform(
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
    #NOTE: generates a number of datapoints equal to `size`
    while data_generated < size: 
        #generate clean data to modify to create errored input
        data_generated += 1
        ravens_data_prime = copy.deepcopy(random.choice(raw_data))
        file_name,ravens_data=ravens_data_prime[0],ravens_data_prime[1]

        #store correct output Y 
        #TODO implement a get infeasibility pipeline stolen from a loss function

        #produce errored input X
        target_object = ravens_data.get(
            # TODO: DEFINE RAVENS ITEM
        )
        for target_name, target_data in target_object.items():
            parameter = target_data.get(
                #TODO: select the parameter to modify
            )
            #TODO: add math to modify parameter
            parameter = None #TODO: new value

        #store errored input X
        X_mgr.raw_data.append([file_name,ravens_data])            

    return (X_mgr, Y_inf)




if __name__ == "__main__":
    MGR = MGRavensDataset(data_dir=rML_ROOT/'data/trans_test')
    MGR_TEST, Y = t_generate_synthetic_transform(MGR,syth_data_param_0=1,size=1)  
    



