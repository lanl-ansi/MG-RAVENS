import os
import sys
import numpy as np
import json
import re
import torch
import copy
from pathlib import Path
import sys, os
rML_ROOT = Path(__file__).resolve().parents[2]
if str(rML_ROOT) not in sys.path:
    sys.path.insert(0, str(rML_ROOT))
from framework.dataset import MGRavensDataset




def unpack_edge(edge_params,max_phases):
    mat_len = max_phases**2 
    # edge_params = edge_params.tolist()
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
    prediction = prediction.detach().to("cpu")
    sample = sample.detach().to("cpu")
    with open(sample.y["raw_mgr"], "r") as f:
        mgr = json.load(f)
    input = _to_python(sample["edge_attr"])

    with open("ravens/ravensML/framework/tools/tmp.json","w") as f:
        json.dump(mgr,f,indent=2)

    transformers = mgr["PowerSystemResource"]["Equipment"]["ConductingEquipment"]["PowerTransformer"]
    transformer_names = list(transformers.keys())
    j = 0
    for i in range(len(prediction)):
        input_e = unpack_edge(input[i],3)
        pred_e  = unpack_edge(prediction[i],3)
        if input_e["edge_type"] == 1:
            if int(j) ==j:
                trans = transformers[transformer_names[int(j)]]
                # print(transformer_names[int(j)])
                R_mat = pred_e["R"]
                X_mat = pred_e["X"]
                G_mat = pred_e["G"]
                B_mat = pred_e["B"]
                ends = copy.deepcopy(trans.get("PowerTransformer.PowerTransformerEnd", {}))
                for i, end in enumerate(ends):
                    # print(end)#TODO: why is it duplicating into a list of lists --> tl;dr it was a batch issue
                    if "TransformerEnd.MeshImpedance" in end.keys():
                        del end["TransformerEnd.MeshImpedance"]
                    end["TransformerEnd.StarImpedance"] = {
                        "TransformerStarImpedance.r": R_mat[i,i].item(),
                        "TransformerStarImpedance.x": X_mat[i,i].item()
                    }
                    end["TransformerEnd.CoreAdmittance"] = {
                        "TransformerCoreAdmittance.g": G_mat[i,i].item(),
                        "TransformerCoreAdmittance.b": B_mat[i,i].item()
                    }
                    # print(type(TCA["TransformerCoreAdmittance.b"]))
                    # print(type(pred_e["B"]))
                    ends[i] = end
                trans["PowerTransformer.PowerTransformerEnd"] = ends
            j+=.5
    return mgr
        
def _to_python(o):
    """
    Recursively turn torch.Tensors (and other non‑JSON types) into
    JSON‑serialisable Python objects.
    Collapses tensors with duplicate values into single Python values.
    """
    if isinstance(o, torch.Tensor):
        # Move tensor to CPU and detach from computation graph if needed
        if o.requires_grad:
            o = o.detach()
        if o.device.type != 'cpu':
            o = o.cpu()
            
        # 0-dim tensor -> Python scalar
        if o.numel() == 1:
            return o.item()
        
        as_list = o.tolist()  
        return as_list
    
    if isinstance(o, dict):
        return {k: _to_python(v) for k, v in o.items()}
    
    if isinstance(o, (list, tuple)):
        converted = [_to_python(v) for v in o]
        
        # Check if all elements in the list are identical after conversion
        if len(converted) > 0:
            first_value = converted[0]
            if all(x == first_value for x in converted) and not isinstance(first_value,dict):
                return first_value
        
        return converted
    
    # Already a JSON-friendly type
    return o



def run_pf(mgr_grid):
    """
    Run power flow analysis using PowerModelsDistribution
    """
    # Initialize Julia once at the beginning
    from julia.api import Julia
    julia_path = rML_ROOT.parents[4]/'.juliaup/bin/julia' #NOTE: juliaup should be installed in the user directory
    jl = Julia(runtime=julia_path, compiled_modules=False)

    # Import Julia modules through PyJulia
    from julia import PowerModelsDistribution as PMD
    from julia import Ipopt
    from julia import Main
    Main.eval("import InfrastructureModels")
    Main.eval("import JuMP")
    Main.eval("import JSON")
    Main.eval("using Ipopt")
    Main.eval("using PowerModelsDistribution")
    os.makedirs(rML_ROOT/'framework/tools/tmp', exist_ok=True)
    
    tmp_file = rML_ROOT/'framework/tools/tmp/tmp_pf.json'
    with open(tmp_file, "w") as file:
        json.dump(mgr_grid, file, indent=2)

    Main.eval("eng = parse_file(\""+tmp_file+"\")")
    Main.eval("rav_model = instantiate_mc_model_ravens(eng, IVRUPowerModel, build_mc_pf)")
    Main.eval("result = optimize_model!(rav_model,relax_integrality=false,optimizer=optimizer_with_attributes(Ipopt.Optimizer, \"print_level\"=>0, \"tol\"=>1e-6),solution_processors=Function[])")
    info_path = (rML_ROOT/'framework/tools/tmp/pf_info.json').as_posix()
    Main.eval(f'''
        open("{info_path}", "w") do f
            JSON.print(f, result)
        end
        ''')

    with open(info_path, 'r') as file:
        file_content = json.load(file)

    return file_content