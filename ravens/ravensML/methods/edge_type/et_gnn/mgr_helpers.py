import os
import sys
import numpy as np
import json
import re
import torch
import copy
from pathlib import Path
import sys, os
rML_ROOT = Path(__file__).resolve().parents[3]
if str(rML_ROOT) not in sys.path:
    sys.path.insert(0, str(rML_ROOT))
from framework.dataset import MGRavensDataset

 
def _to_python(o):
    """
    Recursively turn torch.Tensors (and other non-JSON types) into
    JSON-serialisable Python objects.
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


def _replace_placeholders(obj, mapping):
    """
    Recursively walk a dict / list structure and replace any string that
    contains a {placeholder} with the value supplied in *mapping*.
    """
    if isinstance(obj, dict):
        return {k: _replace_placeholders(v, mapping) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_replace_placeholders(item, mapping) for item in obj]
    if isinstance(obj, str):
        return obj.format(**mapping)
    return obj     

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
    os.makedirs(rML_ROOT/'methods/connectivity/conn_gnn/tmp', exist_ok=True)
    
    tmp_file = rML_ROOT/'methods/connectivity/conn_gnn/tmp/tmp_pf.json'
    with open(tmp_file, "w") as file:
        json.dump(mgr_grid, file, indent=2)

    Main.eval("eng = parse_file(\""+tmp_file.as_posix()+"\")")   
    Main.eval("rav_model = instantiate_mc_model_ravens(eng, IVRUPowerModel, build_mc_pf)")
    Main.eval("result = optimize_model!(rav_model,relax_integrality=false,optimizer=optimizer_with_attributes(Ipopt.Optimizer, \"print_level\"=>0, \"tol\"=>1e-6),solution_processors=Function[])")
    info_path = (rML_ROOT/'methods/connectivity/conn_gnn/tmp/pf_info.json').as_posix()
    Main.eval(f'''
        open("{info_path}", "w") do f
            JSON.print(f, result)
        end
        ''')

    with open(info_path, 'r') as file:
        file_content = json.load(file)

    return file_content