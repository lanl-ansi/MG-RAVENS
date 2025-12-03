import sys
import copy
import random
from typing import List, Sequence, Tuple, Any, Dict
import numpy as np
sys.path.append('/Users/oreed/Desktop/LANL-ANSI/MG-RAVENS/ravens/ravensML')
from framework.dataset import MGRavensDataset


def generate_trans_error(
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
    corrected_mgr = copy.deepcopy(mgr)
    raw_data = copy.deepcopy(corrupted_mgr.raw_data)
    corrupted_mgr.raw_data = []
    corrected_mgr.raw_data = []


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
        corrected_mgr.raw_data.append([file_name,copy.deepcopy(ravens_data)]) 

        #produce errored input X
        transformers = ravens_data.get("PowerSystemResource",{}).get("Equipment",{}).get("ConductingEquipment",{}).get("PowerTransformer",{})
        for trans_name, trans_data in transformers.items():
            ends = trans_data.get("PowerTransformer.PowerTransformerEnd",{})
            for end in ends:
                clean_end(end)
                if random.random() < deletion_prob: #Deletion Error
                    # Directly modify the values in the original dictionary
                    TSI = end.get("TransformerEnd.StarImpedance")
                    TSI["TransformerStarImpedance.r"] = 0
                    TSI["TransformerStarImpedance.x"] = 0
                    TCA = end.get("TransformerEnd.CoreAdmittance")
                    TCA["TransformerCoreAdmittance.g"] = 0
                    TCA["TransformerCoreAdmittance.b"] = 0
            else:
                def m_generator(mult_mean, mult_var):
                    while True:
                        yield np.random.normal(loc=mult_mean, scale=np.sqrt(mult_var))

                def a_generator(add_mean, add_var):
                    while True:
                        yield np.random.normal(loc=add_mean, scale=np.sqrt(add_var))

                # Create generator instances
                m = m_generator(mult_mean, mult_var)  # This creates the actual generator object
                a = a_generator(add_mean, add_var)    # This creates the actual generator object
                for end in ends:
                    clean_end(end)
                    TSI = end.get("TransformerEnd.StarImpedance")                   
                    TSI["TransformerStarImpedance.r"] = abs(next(m)*TSI["TransformerStarImpedance.r"] + next(a)) if (random.random() < occurrence_prob) else TSI["TransformerStarImpedance.r"]
                    TSI["TransformerStarImpedance.x"] = abs(next(m)*TSI["TransformerStarImpedance.x"] + next(a)) if (random.random() < occurrence_prob) else TSI["TransformerStarImpedance.x"]
                    TCA = end.get("TransformerEnd.CoreAdmittance")
                    TCA["TransformerCoreAdmittance.g"] = abs(next(m)*TCA["TransformerCoreAdmittance.g"] + next(a)) if (random.random() < occurrence_prob) else TCA["TransformerCoreAdmittance.g"]
                    TCA["TransformerCoreAdmittance.b"] = abs(next(m)*TCA["TransformerCoreAdmittance.b"] + next(a)) if (random.random() < occurrence_prob) else TCA["TransformerCoreAdmittance.b"] 

        #store errored input X
        corrupted_mgr.raw_data.append([file_name,ravens_data])            

    return (corrupted_mgr, corrected_mgr)

def clean_end(end):
    if "TransformerEnd.StarImpedance" not in end.keys():
        end["TransformerEnd.StarImpedance"] = {}
    if "TransformerEnd.CoreAdmittance" not in end.keys():
        end["TransformerEnd.CoreAdmittance"] = {}
    TSI = end.get("TransformerEnd.StarImpedance")                   
    TSI["TransformerStarImpedance.r"] = 0 if "TransformerStarImpedance.r" not in TSI.keys() else TSI["TransformerStarImpedance.r"]
    TSI["TransformerStarImpedance.x"] = 0 if "TransformerStarImpedance.x" not in TSI.keys() else TSI["TransformerStarImpedance.x"]
    TCA = end.get("TransformerEnd.CoreAdmittance")
    TCA["TransformerCoreAdmittance.g"] = 0 if "TransformerCoreAdmittance.g" not in TSI.keys() else TSI["TransformerCoreAdmittance.g"]
    TCA["TransformerCoreAdmittance.b"] = 0 if "TransformerCoreAdmittance.b" not in TSI.keys() else TSI["TransformerCoreAdmittance.b"]


if __name__ == "__main__":
    MGR = MGRavensDataset(data_dir="ravens/ravensML/data/trans_test")
    MGR_TEST, Y = generate_trans_error(MGR,occurrence_prob=1,size=1)  
    print(MGR_TEST.raw_data[0][1].get("PowerSystemResource",{}).get("Equipment",{}).get("ConductingEquipment",{}).get("PowerTransformer",{}))

    



