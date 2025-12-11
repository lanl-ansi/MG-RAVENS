import os
import sys
import numpy as np
from data import MGTransformerDataset
import json
import re
import torch
sys.path.append('/Users/oreed/Desktop/LANL-ANSI/MG-RAVENS/ravens/ravensML')
from framework.dataset import MGRavensDataset



def unpack_edge(edge_params,max_phases):
    mat_len = max_phases**2 
    edge_params = edge_params.tolist()
    edge = { 
        "Phases":edge_params[0],
        "R":np.array(edge_params[1:mat_len+1]).reshape(max_phases,max_phases),
        "X":np.array(edge_params[1+mat_len:1+mat_len*2]).reshape(max_phases,max_phases),
        "G":np.array(edge_params[1+mat_len*2:1+mat_len*3]).reshape(max_phases,max_phases),
        "B":np.array(edge_params[1+mat_len*3:1+mat_len*4]).reshape(max_phases,max_phases),
        "edge_type":edge_params[1+mat_len*4],
        "tap":edge_params[2+mat_len*4],
        "shift":edge_params[3+mat_len*4],
    }
    return edge

def update_mgr(prediction,sample):
    prediction = prediction.detach().clone().to("cpu")
    sample = sample.detach().clone().to("cpu")

    mgr = sample.y["raw_mgr"]
    input = sample["edge_attr"]    
    transformers = mgr["PowerSystemResource"]["Equipment"]["ConductingEquipment"]["PowerTransformer"]
    transformer_names = list(transformers.keys())
    j = 0
    for i in range(len(prediction)):
        input_e = unpack_edge(input[i],3)
        pred_e  = unpack_edge(prediction[i],3)
        if input_e["edge_type"] == 1:
            if int(j) ==j:
                trans = transformers[transformer_names[int(j)]]
                print(transformer_names[int(j)])
                R_mat = pred_e["R"]
                X_mat = pred_e["X"]
                G_mat = pred_e["G"]
                B_mat = pred_e["B"]
                ends = trans.get("PowerTransformer.PowerTransformerEnd",{})
                for i, end in enumerate(ends):
                    if "TransformerEnd.MeshImpedance" in end.keys():
                        del end["TransformerEnd.MeshImpedance"]
                    TSI = end["TransformerEnd.StarImpedance"] = {}
                    TSI["TransformerStarImpedance.r"] = R_mat[i,i].item()
                    TSI["TransformerStarImpedance.x"] = X_mat[i,i].item()
                    TCA = end["TransformerEnd.CoreAdmittance"] = {}
                    TCA["TransformerCoreAdmittance.g"] = G_mat[i,i].item()
                    TCA["TransformerCoreAdmittance.b"] = B_mat[i,i].item()
                    print(type(TCA["TransformerCoreAdmittance.b"]))
                    print(type(pred_e["B"]))
            j+=.5
    print(mgr)
    mgr = _to_python(mgr)
    print(mgr)
    return mgr
        
def _to_python(o):
    """
    Recursively turn torch.Tensors (and other non‑JSON types) into
    JSON‑serialisable Python objects.
    """
    if isinstance(o, torch.Tensor):
        # 0‑dim tensor -> Python scalar, otherwise -> list
        print(o)
        return o.item() if len(o) == 1 else o.tolist()
    if isinstance(o, dict):
        return {k: _to_python(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_to_python(v) for v in o]
    return o   # already a JSON friendly type


def run_pf(mgr_grid):
    """
    Run power flow analysis using PowerModelsDistribution
    """
    # Initialize Julia once at the beginning
    from julia.api import Julia
    jl = Julia(runtime="/Users/oreed/.juliaup/bin/julia", compiled_modules=False)

    # Import Julia modules through PyJulia
    from julia import PowerModelsDistribution as PMD
    from julia import Ipopt
    from julia import Main
    Main.eval("import InfrastructureModels")
    Main.eval("import JuMP")
    Main.eval("import JSON")
    Main.eval("using Ipopt")
    Main.eval("using PowerModelsDistribution")
    os.makedirs("/Users/oreed/Desktop/LANL-ANSI/MG-RAVENS/ravens/ravensML/methods/transformers/trans_gnn/tmp", exist_ok=True)
    
    tmp_file = "/Users/oreed/Desktop/LANL-ANSI/MG-RAVENS/ravens/ravensML/methods/transformers/trans_gnn/tmp/tmp_pf.json"
    with open(tmp_file, "w") as file:
        json.dump(mgr_grid, file, indent=2)

    Main.eval("eng = parse_file(\""+tmp_file+"\")")
    Main.eval("rav_model = instantiate_mc_model_ravens(eng, IVRUPowerModel, build_mc_pf)")
    Main.eval("result = optimize_model!(rav_model,relax_integrality=false,optimizer=optimizer_with_attributes(Ipopt.Optimizer, \"print_level\"=>5, \"tol\"=>1e-6),solution_processors=Function[])")
    Main.eval("""
    open("/Users/oreed/Desktop/LANL-ANSI/MG-RAVENS/ravens/ravensML/methods/transformers/trans_gnn/tmp/pf_info.json", "w") do f
        JSON.print(f, result)
    end
    """)

    with open("/Users/oreed/Desktop/LANL-ANSI/MG-RAVENS/ravens/ravensML/methods/transformers/trans_gnn/tmp/pf_info.json", 'r') as file:
        file_content = json.load(file)

    return file_content