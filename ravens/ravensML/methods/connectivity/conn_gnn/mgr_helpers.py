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


DEFAULT_LINE = {
        "IdentifiedObject.name": "{LINE_NAME}",
        "Equipment.inService": True,
        "Conductor.length": 38.521620999999996,
        "ACLineSegment.PerLengthImpedance": "PerLengthPhaseImpedance::'DEFAULT_PLPI'",
        "ConductingEquipment.Terminals": [
            {
                "Ravens.cimObjectType": "Terminal",
                "IdentifiedObject.name": "{LINE_NAME}_T1",
                "ACDCTerminal.sequenceNumber": 1,
                "Terminal.phases": "PhaseCode.ABC",
                "Terminal.ConnectivityNode": "ConnectivityNode::'{FROM_NODE}'",
                "ACDCTerminal.OperationalLimitSet": "OperationalLimitSet::'DEFAULT_OLS'"
            },
            {
                "Ravens.cimObjectType": "Terminal",
                "IdentifiedObject.name": "{LINE_NAME}_T2",
                "ACDCTerminal.sequenceNumber": 2,
                "Terminal.phases": "PhaseCode.ABC",
                "Terminal.ConnectivityNode": "ConnectivityNode::'{TO_NODE}'",
                "ACDCTerminal.OperationalLimitSet": "OperationalLimitSet::'DEFAULT_OLS'"
            },
        ],
        "ACLineSegment.ACLineSegmentPhase": [
            {
                "Ravens.cimObjectType": "ACLineSegmentPhase",
                "IdentifiedObject.name": "{LINE_NAME}_A",
                "ACLineSegmentPhase.phase": "SinglePhaseKind.A",
                "ACLineSegmentPhase.sequenceNumber": 1,
            },
            {
                "Ravens.cimObjectType": "ACLineSegmentPhase",
                "IdentifiedObject.name": "{LINE_NAME}_B",
                "ACLineSegmentPhase.phase": "SinglePhaseKind.B",
                "ACLineSegmentPhase.sequenceNumber": 2,
            },
            {
                "Ravens.cimObjectType": "ACLineSegmentPhase",
                "IdentifiedObject.name": "{LINE_NAME}_C",
                "ACLineSegmentPhase.phase": "SinglePhaseKind.C",
                "ACLineSegmentPhase.sequenceNumber": 3,
            },
        ],
    }

DEFAULT_PLPI = {
        "Ravens.cimObjectType": "PerLengthPhaseImpedance",
        "IdentifiedObject.name": "DEFAULT_PLPI",
        "PerLengthPhaseImpedance.conductorCount": 3,
        "PerLengthPhaseImpedance.PhaseImpedanceData": [
            {
                "Ravens.cimObjectType": "PhaseImpedanceData",
                "PhaseImpedanceData.row": 3,
                "PhaseImpedanceData.column": 2,
                "PhaseImpedanceData.sequenceNumber": "11",
                "PhaseImpedanceData.r": 0.00013851800000000002,
                "PhaseImpedanceData.x": 0.000405953,
                "PhaseImpedanceData.b": -9.316581509779747e-10,
            },
            {
                "Ravens.cimObjectType": "PhaseImpedanceData",
                "PhaseImpedanceData.row": 1,
                "PhaseImpedanceData.column": 1,
                "PhaseImpedanceData.sequenceNumber": "4",
                "PhaseImpedanceData.r": 0.00113148,
                "PhaseImpedanceData.x": 0.000884886,
                "PhaseImpedanceData.b": 2.972009482149016e-09,
            },
            {
                "Ravens.cimObjectType": "PhaseImpedanceData",
                "PhaseImpedanceData.row": 3,
                "PhaseImpedanceData.column": 1,
                "PhaseImpedanceData.sequenceNumber": "10",
                "PhaseImpedanceData.r": 0.000142066,
                "PhaseImpedanceData.x": 0.00036611500000000003,
                "PhaseImpedanceData.b": -6.636174657736936e-10,
            },
            {
                "Ravens.cimObjectType": "PhaseImpedanceData",
                "PhaseImpedanceData.row": 2,
                "PhaseImpedanceData.column": 1,
                "PhaseImpedanceData.sequenceNumber": "7",
                "PhaseImpedanceData.r": 0.00013749900000000002,
                "PhaseImpedanceData.x": 0.000388579,
                "PhaseImpedanceData.b": -7.980562685172923e-10,
            },
            {
                "Ravens.cimObjectType": "PhaseImpedanceData",
                "PhaseImpedanceData.row": 2,
                "PhaseImpedanceData.column": 2,
                "PhaseImpedanceData.sequenceNumber": "8",
                "PhaseImpedanceData.r": 0.00112461,
                "PhaseImpedanceData.x": 0.000893467,
                "PhaseImpedanceData.b": 3.092307348040277e-09,
            },
            {
                "Ravens.cimObjectType": "PhaseImpedanceData",
                "PhaseImpedanceData.row": 3,
                "PhaseImpedanceData.column": 3,
                "PhaseImpedanceData.sequenceNumber": "12",
                "PhaseImpedanceData.r": 0.0011336200000000001,
                "PhaseImpedanceData.x": 0.000882239,
                "PhaseImpedanceData.b": 3.046744201466733e-09,
            },
        ],
    }
DEFAULT_OLS = {
        "Ravens.cimObjectType": "OperationalLimitSet",
        "IdentifiedObject.name": "OpLimI_220.0_220.0",
        "OperationalLimitSet.OperationalLimitValue": [
            {
                "Ravens.cimObjectType": "CurrentLimit",
                "IdentifiedObject.name": "OpLimI_220.0_220.0_Emerg",
                "CurrentLimit.value": 220.0,
                "CurrentLimit.normalValue": 220.0,
                "OperationalLimit.OperationalLimitType": "OperationalLimitType::'absoluteValueType_86400.0s'"
            },
            {
                "Ravens.cimObjectType": "CurrentLimit",
                "IdentifiedObject.name": "OpLimI_220.0_220.0_Norm",
                "CurrentLimit.value": 220.0,
                "CurrentLimit.normalValue": 220.0,
                "OperationalLimit.OperationalLimitType": "OperationalLimitType::'absoluteValueType_5000000000.0s'"
            }
        ]
    }

def define_edges(adj_score,n_nodes,raw_mgr,threshold):
    edges_needed = []
    for i in range(0, n_nodes):
        for j in range(i,n_nodes):
            if adj_score[i,j] > threshold:
                edges_needed.append((i,j))
    node_list = list(raw_mgr["ConnectivityNode"].keys())
    edges = []
    for k, (i,j) in enumerate(edges_needed):
        if i < len(node_list) and j < len(node_list):
            mapping = {
                "LINE_NAME": f"Predicted_Line_{k}",
                "FROM_NODE": node_list[i],
                "TO_NODE":   node_list[j],     
            }
            edges.append({f"Predicted_Line_{k}":_replace_placeholders(copy.deepcopy(DEFAULT_LINE), mapping)})
    return edges

#removes the edges specified in an adj matrix
def purge_edges(mgr,removed_edges_adj,n_nodes):
    node_list = list(mgr["ConnectivityNode"].keys())
    for i in range(0, n_nodes):
        for j in range(i,n_nodes):
            if removed_edges_adj[i][j] == 1:
                target_nodes = set([node_list[i],node_list[j]])
                lines = mgr["PowerSystemResource"]["Equipment"]["ConductingEquipment"]["Conductor"]["ACLineSegment"]
                for line_name, line_data in list(lines.items()):
                    terminals = line_data["ConductingEquipment.Terminals"]
                    seen_nodes = set([term["Terminal.ConnectivityNode"].split("'")[-2] for term in terminals])
                    if target_nodes==seen_nodes:
                        del lines[line_name]
                        assert(line_name not in lines.keys())
    return mgr


def update_mgr(prediction,sample):
    #init data
    prediction = prediction.detach().to("cpu")
    sample = sample.detach().to("cpu")
    #pull parameters
    file_name = sample.y["raw_mgr"]
    removed_edges_adj = sample.y["missing_edges"]
    num_nodes = removed_edges_adj.size()[0]
    if isinstance(file_name,list):
        file_name = sample.y["raw_mgr"][0]
    with open(file_name, "r") as f:
        mgr = json.load(f)

    mgr = purge_edges(mgr,removed_edges_adj,num_nodes)

    # print(f"PMD: last file processed: {file_name}")

    #NEED TO REMOVE EDITED EDGES

    edges = define_edges(prediction,num_nodes,mgr,.50)
    for edge in edges:
        key = list(edge.keys())[0]
        val = edge[key]
        mgr["PowerSystemResource"]["Equipment"]["ConductingEquipment"]["Conductor"]["ACLineSegment"][key] = val 

    mgr["PerLengthLineParameter"]["PerLengthImpedance"]["PerLengthPhaseImpedance"]["DEFAULT_PLPI"] = copy.deepcopy(DEFAULT_PLPI)
    mgr["OperationalLimitSet"]["DEFAULT_OLS"] = copy.deepcopy(DEFAULT_OLS)

    return mgr
        
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