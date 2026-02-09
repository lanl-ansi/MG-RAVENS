import warnings
from copy import deepcopy
import json
import random
from collections import deque
import os
import re

class grid_segmenter:
    """
    This class is designed to allow a user to convert a grid specified in the MGRavens format and yield a set of feasible sub-grids.
    This solves a common problem where a user intending to preform analysis on a range of topologies may not have access to a sufficiently diverse set of grid topologies. 

    Parameters:
        - base_graph: A dictionary of an MGRavens graph

    Public Member Functions:
    - set_base_graph(new_MGR) --> sets base graph to a new MGR dictionary 
    - yield_graph(optional: MGR, min_nodes, max_nodes) --> yields a new subgraph segmented from either the passed MGRavens file, or the base graph with optional constraints on number of nodes
    """

    def __init__(self, base_graph = None, PF_Val = False):
        self.base_graph = base_graph
        self.sub_template = None
        self.PF_Val = PF_Val
        
    def set_base_graph(self, new_MGR):
        self.base_graph = new_MGR

    def load_from_file(self, path):
        with open(path, 'r') as f:
            self.base_graph = json.load(f)

    def yield_graph(
        self,
        MGR: dict | None = None,
        min_nodes: int = 0,
        output_path: str | None = None,
    ) -> dict:
        """
        Produce a feasible sub‑grid (a “segment”) from ``MGR`` or from the
        instance’s ``base_graph``.

        Parameters
        ----------
        MGR : dict, optional
            A full MGRavens graph.  If omitted the object’s ``base_graph`` is used.
        min_nodes : int, optional
            Desired minimum number of nodes in the returned sub‑grid.
        output_path : str, optional
            Path to a JSON file where the resulting sub‑grid should be saved.
            If ``None`` (default) the graph is **not** written to disk.

        Returns
        -------
        dict
            The sub‑grid as a Python dictionary.
        """
        # --------------------------------------------------------------
        # Resolve the source graph and sanity‑check
        # --------------------------------------------------------------
        MGR = self.base_graph if MGR is None else MGR
        if MGR is None:
            raise RuntimeError(
                "No source graph supplied – set a base graph, pass one via "
                "`MGR`, or call `set_base_graph` first."
            )

        # --------------------------------------------------------------
        # Begin the “search until a feasible graph is found” loop
        # --------------------------------------------------------------
        complete = False
        while not complete:
            # 1️⃣  Start from a clean template
            Sub_MGR = self._clean_mgr()

            # 2️⃣  BFS state containers
            added_nodes: set[tuple] = set()
            added_edges: set[tuple] = set()
            seen: deque[tuple[list, list]] = deque()

            # 3️⃣  Choose a random start node
            node_path = ["ConnectivityNode"]
            all_nodes = list(self._get_item(node_path).keys())
            start_node = random.choice(all_nodes)
            node_path.append(start_node)
            seen.append((node_path, []))

            # ----------------------------------------------------------
            # Grow the sub‑grid until the node count constraint is met
            # ----------------------------------------------------------
            while len(added_nodes) < min_nodes and seen:
                target_node, target_edge = seen.popleft()

                # copy the node and the edge that got us here
                self._copy_path(target_node, Sub_MGR)
                self._copy_path(target_edge, Sub_MGR)

                added_nodes.add(tuple(target_node))
                added_edges.add(tuple(target_edge))

                # enqueue neighbours that are still unseen
                self._visit_neighbors(
                    target_node, added_nodes, added_edges, seen
                )

            # ----------------------------------------------------------
            # Post‑processing fixes (source bus, phase codes, etc.)
            # ----------------------------------------------------------
            if ("ConnectivityNode", "sourcebus") not in added_nodes:
                Sub_MGR = self._replace(Sub_MGR, start_node, "sourcebus")

            # Normalise a few phase‑code strings that PowerModelsDistribution
            # does not like.
            for old, new in (
                ("PhaseCode.s1N", "PhaseCode.ABCN"),
                ("PhaseCode.Ns2", "PhaseCode.ABCN"),
                ("SinglePhaseKind.s1", "SinglePhaseKind.A"),
                ("SinglePhaseKind.s2", "SinglePhaseKind.B"),
            ):
                Sub_MGR = self._replace(Sub_MGR, old, new)

            # ----------------------------------------------------------
            # Optional power‑flow validation
            # ----------------------------------------------------------
            if self.PF_Val:
                warnings.warn(
                    "PMD‑PF calculation currently has issues with multiple "
                    "phase codes that frequently appear in the file"
                )
                warnings.warn("PF validation logic not implemented")
                res = self._run_pf(Sub_MGR)

                print(res["primal_status"])
                print(res["termination_status"])

                # If the PF solved, we are done; otherwise relax the node
                # count a little and try again.
                complete = res["primal_status"] != "INFEASIBLE_POINT"
                min_nodes = int(min_nodes * 1.05)
            else:
                complete = True

        # --------------------------------------------------------------
        # Write the result to disk only when a path was supplied
        # --------------------------------------------------------------
        if output_path is not None:
            # Ensure the parent directory exists
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(Sub_MGR, f, indent=2)

        return Sub_MGR

        
    def _clean_mgr(self):
        if self.sub_template == None:
            MGR = self.base_graph
            Sub_MGR = {}
            #Keep Reference Info
            Sub_MGR["LoadResponseCharacteristic"] = deepcopy(MGR["LoadResponseCharacteristic"])
            Sub_MGR["BaseVoltage"] = deepcopy(MGR["BaseVoltage"])
            Sub_MGR["OperationalLimitType"] = deepcopy(MGR["OperationalLimitType"])
            Sub_MGR["Versions"] = deepcopy(MGR["Versions"])
            Sub_MGR["OperationalLimitSet"] = deepcopy(MGR["OperationalLimitSet"])
            Sub_MGR["PerLengthLineParameter"] = deepcopy(MGR["PerLengthLineParameter"])
            Sub_MGR["AssetInfo"] = deepcopy(MGR["AssetInfo"])
            #Clean Content Dicts
            Sub_MGR["ConnectivityNode"] = {} #leaf to be filled in
            Sub_MGR["PowerSystemResource"] = {
                "Equipment":{
                    "ConductingEquipment":{
                        "Conductor":{
                            "ACLineSegment":{}#leaf to be filled in 
                        },
                        "PowerTransformer":{},#leaf to be filled in
                        "EnergyConnection":{
                            "EnergyConsumer":{}, #leaf to be filled in
                            "RegulatingCondEq":{
                                "ShuntCompensator":{} #leaf to be filled in
                            }, 
                            "EnergySource": {
                                "source": {
                                "IdentifiedObject.name": "source",
                                "EnergySource.nominalVoltage": 115000.0,
                                "EnergySource.voltageMagnitude": 120750.0,
                                "EnergySource.voltageAngle": 0.0,
                                "EnergySource.r": 0.0,
                                "EnergySource.x": 0.001,
                                "EnergySource.r0": 0.0,
                                "EnergySource.x0": 0.001,
                                "Equipment.inService": True,
                                "ConductingEquipment.BaseVoltage": "BaseVoltage::'BaseV_115.00000000000001'",
                                "ConductingEquipment.Terminals": [
                                    {
                                    "Ravens.cimObjectType": "Terminal",
                                    "IdentifiedObject.name": "source_T1",
                                    "ACDCTerminal.sequenceNumber": 1,
                                    "Terminal.phases": "PhaseCode.ABC",
                                    "Terminal.ConnectivityNode": "ConnectivityNode::'sourcebus'"
                                    }
                                ]
                                }
                            }
                        }
                    }
                },
                "RegulatingControl":deepcopy(MGR["PowerSystemResource"]["RegulatingControl"]),#copyable info leaf
                "TapChanger":{
                    "RatioTapChanger":deepcopy(MGR["PowerSystemResource"]["TapChanger"]["RatioTapChanger"])
                },
            }
            self.sub_template = deepcopy(Sub_MGR)
        return deepcopy(self.sub_template)
    
    def _copy_path(self,path,new_mgr):
        if path == []:
            return
        #Given: path = list of string keys
        
        #get target from base graph
        val = self.base_graph
        for k in path:
            val = val[k]
        
        #build up path in new_mgr
        cur = new_mgr
        for k in path[:-1]:
            cur = cur.setdefault(k, {})

        #execute copy
        cur[path[-1]] = deepcopy(val)

    def _get_item(self,path,MGR=None):
        if MGR==None:
            MGR = self.base_graph
        
        #search for item and return
        val = MGR
        for k in path:
            val = val[k]
        return val
    
    def _visit_neighbors(self,target_node,added_nodes,added_edges,seen):
        #NOTE: we should always treat objects as a path which is a list of keys --> this makes it easy to copy and search 
        if len(target_node) >= 2 and target_node[-2] == "ConnectivityNode":
            #Find all associated edges and the object they lead to (add these to the queue)
            node = self._get_item(target_node) #unpack node to dict object
            node_name = node["IdentifiedObject.name"] #get name to search for in the dict
            search_target = f"ConnectivityNode::'{node_name}'"
            new_target_paths = self._find_obj_containing(search_target)
            for target_edge_path in new_target_paths:
                #NOTE: we only look at an edge if its not already added
                if tuple(target_edge_path) not in added_edges:
                    #PARSE EDGE TYPE
                    if target_edge_path[-2] == "ACLineSegment":
                        edge = self._get_item(target_edge_path)
                        connected_names = [edge["ConductingEquipment.Terminals"][i]["Terminal.ConnectivityNode"] for i in range(len(edge["ConductingEquipment.Terminals"]))]
                        connected_names = [name for name in connected_names if name != f"ConnectivityNode::'{target_node[-1]}'"]
                        target_name = connected_names[0].split("'")[1] 
                        adj_node_path = self._find_obj_containing(target_name)[0]
                    elif target_edge_path[-2] == "PowerTransformer":
                        edge = self._get_item(target_edge_path)
                        connected_names = [edge["ConductingEquipment.Terminals"][i]["Terminal.ConnectivityNode"] for i in range(len(edge["ConductingEquipment.Terminals"]))]
                        connected_names = [name for name in connected_names if name != f"ConnectivityNode::'{target_node[-1]}'"]
                        target_name = connected_names[0].split("'")[1] 
                        adj_node_path = self._find_obj_containing(target_name)[0]
                    elif target_edge_path[-2] == "EnergyConsumer":
                        edge = self._get_item(target_edge_path)
                        adj_node_path = [] #Energy Consumers are edges without a second node
                    elif target_edge_path[-2] == "EnergySource":
                        edge = self._get_item(target_edge_path)
                        adj_node_path = [] #Energy Sources are edges without a second node
                    elif target_edge_path[-2] == "ShuntCompensator":
                        edge = self._get_item(target_edge_path)
                        adj_node_path = [] #Shunt Compensators are edges without a second node
                    elif target_edge_path[-2] == "ANY OTHER OF THE LEAF OBJECTS": #TODO: validate all things that connect to nodes
                        pass
                    else: #Catch all problems
                        raise TypeError(f"We should not find a {target_edge_path} connected as an edge")
                    
                    #log new edge/node pair into the seen queue
                    path_pair = (adj_node_path,target_edge_path)
                    seen.append(path_pair)
        elif target_node == []:
            pass
        else:
            raise TypeError(f"Non-Node parsed with path:{target_node}")
            

    def _find_obj_containing(self,search_target):
        leaf_set = set([
            "ACLineSegment", "ConnectivityNode", "PowerTransformer",
            "EnergyConsumer", "ShuntCompensator", "EnergySource",
            "RatioTapChanger",
        ])

        found_paths = set()

        def _walk(node, path):
            """Recursive depth‑first walk through dicts / lists."""
            if isinstance(node, dict):
                for k, v in node.items():
                    _walk(v, path + [k])
            elif isinstance(node, list):
                for idx, item in enumerate(node):
                    _walk(item, path + [idx])
            else:
                # leaf value – compare with the target string
                if node == search_target:
                    # climb back until we hit a leaf‑type key
                    for i in range(len(path) - 1, -1, -1):
                        key = path[i]
                        if isinstance(key, str) and key in leaf_set:
                            # object id is the next element in the path
                            if i + 1 < len(path):
                                obj_path = tuple(path[: i + 2])   # leaf + id
                                found_paths.add(obj_path)
                            break

        _walk(self.base_graph, [])

        # convert back to list‑of‑lists for the public API
        return [list(p) for p in found_paths]
    
    def _run_pf(self,mgr_grid):
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
        os.makedirs("/Users/oreed/Desktop/LANL-ANSI/MG-RAVENS/ravens/ravensML/framework/tmp", exist_ok=True)
        
        tmp_file = "/Users/oreed/Desktop/LANL-ANSI/MG-RAVENS/ravens/ravensML/framework/tmp/tmp_pf.json"
        with open(tmp_file, "w") as file:
            json.dump(mgr_grid, file, indent=2)

        Main.eval("eng = parse_file(\""+tmp_file+"\")")

        Main.eval("""
        open("/Users/oreed/Desktop/LANL-ANSI/MG-RAVENS/ravens/ravensML/framework/tmp/debug_eng.json", "w") do f
            JSON.print(f, eng)
        end
        """)
        
        Main.eval("rav_model = instantiate_mc_model_ravens(eng, IVRUPowerModel, build_mc_pf)")
        Main.eval("result = optimize_model!(rav_model,relax_integrality=false,optimizer=optimizer_with_attributes(Ipopt.Optimizer, \"print_level\"=>0, \"tol\"=>1e-6),solution_processors=Function[])")
        Main.eval("""
        open("/Users/oreed/Desktop/LANL-ANSI/MG-RAVENS/ravens/ravensML/framework/tmp/pf_info.json", "w") do f
            JSON.print(f, result)
        end
        """)

        with open("/Users/oreed/Desktop/LANL-ANSI/MG-RAVENS/ravens/ravensML/framework/tmp/pf_info.json", 'r') as file:
            file_content = json.load(file)

        return file_content
    
    def _replace(self, d, old, new):
        pattern = re.compile(rf'\b{re.escape(old)}\b')

        def _walk(item):
            if isinstance(item, dict):
                new_dict = {}
                for k, v in item.items():
                    # key: only replace when it is a string; otherwise keep as‑is
                    new_key = pattern.sub(new, k) if isinstance(k, str) else k
                    # value: recurse
                    new_dict[new_key] = _walk(v)
                return new_dict

            if isinstance(item, list):
                return [_walk(elem) for elem in item]

            if isinstance(item, tuple):
                return tuple(_walk(elem) for elem in item)

            if isinstance(item, set):
                return { _walk(elem) for elem in item }

            if isinstance(item, str):
                return pattern.sub(new, item)

            return item

        # ------------------------------------------------------------------
        # Kick‑off the recursion
        # ------------------------------------------------------------------
        return _walk(d)



if __name__ == "__main__":
    import sys
    sys.path.append('/Users/oreed/Desktop/LANL-ANSI/MG-RAVENS/ravens/')
    # from ravens.xml.opendss2xml import DssExport
    # from ravens.xml.xml2ravens import CrowsImport
    from ravensML.framework.dataset import MGRavensDataset

    # d = DssExport("ravens/ravensML/data/IEEE8500/Master.dss")
    # d.save("ravens/ravensML/framework/tmp/segmenter.xml")

    # MGR = CrowsImport("ravens/ravensML/framework/tmp/segmenter.xml")
    # MGR.dump("ravens/ravensML/framework/segmenter_test_data/segmenter.json", indent=2)

    # DS = MGRavensDataset(data_dir="ravens/ravensML/framework/segmenter_test_data")
    # DS.process_for_ML()
    # DS.visualize_graph()

    GS = grid_segmenter(PF_Val=False)
    GS.load_from_file("ravens/ravensML/framework/segmenter_test_data/segmenter.json")
    sub_MGR = GS.yield_graph(min_nodes=67,
                         output_path="ravens/ravensML/framework/tmp/results/sub_mgr.json")

    DS = MGRavensDataset(data_dir="ravens/ravensML/framework/tmp/results")
    DS.process_for_ML()
    DS.visualize_graph()
