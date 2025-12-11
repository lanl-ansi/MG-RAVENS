import sys
import os
import re
import networkx as nx
from collections import Counter
from typing import List, Sequence, Tuple, Any, Dict
import json
import numpy as np
import copy

# Initialize Julia once at the beginning
from julia.api import Julia
jl = Julia(runtime="/Users/oreed/.juliaup/bin/julia", compiled_modules=False)

# Import Julia modules through PyJulia
from julia import PowerModelsDistribution as PMD
from julia import Ipopt
from julia import Main

sys.path.append('/Users/oreed/Desktop/LANL-ANSI/MG-RAVENS/ravens/ravensML')
from framework.dataset import MGRavensDataset
DEBUG = "ravens/ravensML/methods/transformers/trivial_solution/tmp/log.txt"
class Trans_Iterative_Optimizer(object):
    def __init__(self,max_iter=10):
        self.input_dataset = None
        self.output_data = []
        self.R2P = {}
        self.P2R = {}
        self.max_iter = max_iter
        
        # Set up Julia environment once during initialization
        Main.eval("import InfrastructureModels")
        Main.eval("import JuMP")
        Main.eval("import JSON")
        Main.eval("using Ipopt")
        Main.eval("using PowerModelsDistribution")
        
        # Parameters for gradient optimization
        self.learning_rate = 0.50  # Step size for parameter adjustments
        

    def __call__(self, X):
        self.input_dataset = X
        self.raw_data = X.raw_data
        
        for i in range(len(self.raw_data)):
            mgr_NAME, mgr_grid, mgr_MLD = self.input_dataset[i]
            print(f"Processing grid: {mgr_NAME}")
            
            # Store original Y/Z values for comparison
            original_values = copy.deepcopy(mgr_MLD)
            
            # Initial PF run to check if already feasible
            result_dict = self._run_pf(mgr_grid)
            
            if result_dict["termination_status"] == "LOCALLY_SOLVED" or result_dict["termination_status"] == "OPTIMAL":
                print("Grid is already feasible. No modifications needed.")
                self.output_data.append((mgr_NAME, mgr_grid,original_values))
                continue
            
            # If not feasible, start iterative optimization
            print("Grid is not feasible. Starting iterative optimization...")
            
            # Track modifications
            modifications_made = False
            MAX_ITER = self.max_iter
            best_grid = None
            best_violation_score = float('inf')
            best_violation_state = None
            
            # Store the initial state
            current_mgr_MLD = self.MGR_get_yz(i)
            
            for iteration in range(MAX_ITER):
                print(f"Iteration {iteration + 1}")
                modifications_made = False
                
                # Get current violation score
                current_violation_score,_ = self._get_score(i, current_mgr_MLD)
                print(f"Current violation score: {current_violation_score}")
                
                # Identify problematic branches/transformers
                branch_infeasibility = self.analyze_branch_infeasibility(result_dict)
                
                # Create copies for testing individual parameter changes
                r_only_mld = copy.deepcopy(current_mgr_MLD)
                x_only_mld = copy.deepcopy(current_mgr_MLD)
                g_only_mld = copy.deepcopy(current_mgr_MLD)  
                b_only_mld = copy.deepcopy(current_mgr_MLD)
                rx_mld = copy.deepcopy(current_mgr_MLD)
                gb_mld = copy.deepcopy(current_mgr_MLD)
                all_mld = copy.deepcopy(current_mgr_MLD)
                
                # Apply changes to each parameter separately
                r_only_mld = self.apply_parameter_changes(i,r_only_mld, branch_infeasibility, ["R"])
                x_only_mld = self.apply_parameter_changes(i,x_only_mld, branch_infeasibility, ["X"])
                g_only_mld = self.apply_parameter_changes(i,g_only_mld, branch_infeasibility, ["G"])
                b_only_mld = self.apply_parameter_changes(i,b_only_mld, branch_infeasibility, ["B"])
                rx_mld = self.apply_parameter_changes(i,rx_mld, branch_infeasibility, ["X", "R"])
                gb_mld = self.apply_parameter_changes(i,gb_mld, branch_infeasibility, ["G", "B"])
                all_mld = self.apply_parameter_changes(i,all_mld, branch_infeasibility, ["X", "R", "G", "B"])
                
                # Test each change separately
                r_score, _ = self._get_score(i, r_only_mld)
                x_score, _ = self._get_score(i, x_only_mld)
                g_score, _ = self._get_score(i, g_only_mld)
                b_score, _ = self._get_score(i, b_only_mld)
                rx_score, _ = self._get_score(i, rx_mld)
                gb_score, _ = self._get_score(i, gb_mld)
                all_score, _ = self._get_score(i, all_mld)
                
                print(f"R-only: {r_score}, X-only: {x_score}, G-only: {g_score}, B-only: {b_score}")
                print(f"R/X: {rx_score}, G/B: {gb_score}, All: {all_score}")
                
                # Keep only the changes that improve the score
                improved_mld = copy.deepcopy(current_mgr_MLD)
                
                if r_score < current_violation_score or all_score < current_violation_score or rx_score < current_violation_score:
                    print("Applying R changes (improved score)")
                    for branch_id, features in r_only_mld["edge_features"].items():
                        if branch_id in improved_mld["edge_features"]:
                            improved_mld["edge_features"][branch_id]["R"] = features["R"]
                    modifications_made = True
                
                if x_score < current_violation_score or all_score < current_violation_score or rx_score < current_violation_score:
                    print("Applying X changes (improved score)")
                    for branch_id, features in x_only_mld["edge_features"].items():
                        if branch_id in improved_mld["edge_features"]:
                            improved_mld["edge_features"][branch_id]["X"] = features["X"]
                    modifications_made = True
                
                if g_score < current_violation_score or all_score < current_violation_score or gb_score < current_violation_score:
                    print("Applying G changes (improved score)")
                    for branch_id, features in g_only_mld["edge_features"].items():
                        if branch_id in improved_mld["edge_features"] and "G" in features:
                            improved_mld["edge_features"][branch_id]["G"] = features["G"]
                    modifications_made = True
                
                if b_score < current_violation_score or all_score < current_violation_score or gb_score < current_violation_score:
                    print("Applying B changes (improved score)")
                    for branch_id, features in b_only_mld["edge_features"].items():
                        if branch_id in improved_mld["edge_features"]:
                            improved_mld["edge_features"][branch_id]["B"] = features["B"]
                    modifications_made = True
                
                # Update current state with improved parameters
                if modifications_made:
                    current_mgr_MLD = improved_mld
                    # Run PF with the updated parameters
                    self.MGR_set_yz(i, current_mgr_MLD)
                    
                    # Check if we've made an improvement
                    violation_score, result_dict = self._get_score(i, current_mgr_MLD)
                    if violation_score < best_violation_score:
                        print(f"Found better solution with violation score: {violation_score}")
                        best_violation_score = violation_score
                        best_violation_state = copy.deepcopy(current_mgr_MLD)
                else:
                    print("No improvements found, reducing learning rate")
                    self.learning_rate *= 0.8
                
                print(f"Violation score at iteration #{iteration}: {best_violation_score}")
                
                # Check if the grid is now feasible
                if result_dict["termination_status"] == "LOCALLY_SOLVED" or result_dict["termination_status"] == "OPTIMAL":
                    print(f"Grid became feasible after {iteration + 1} iterations")
                    best_grid = copy.deepcopy(mgr_grid)
                    break
                    
                # If we've reached max iterations and still not feasible
                if iteration == MAX_ITER-1:
                    print("Could not make grid feasible within iteration limit. Using best configuration found.")
                    if best_violation_state is not None:
                        self.MGR_set_yz(i, best_violation_state)
                    _, best_grid, _ = self.input_dataset[i]
                    break
            
            # Add the (potentially modified) grid to output data
            final_state = best_violation_state if best_violation_state is not None else current_mgr_MLD
            self.output_data.append((mgr_NAME, mgr_grid, final_state))
        
        return self.output_data


    
    def apply_parameter_changes(self, i, mld, branch_infeasibility, param_types):
        """
        Apply changes to transformer parameters (R, X, G, B)
        """
        # Sort branches by their infeasibility to focus on the most problematic ones
        sorted_branches = sorted(
            branch_infeasibility.items(), 
            key=lambda x: x[1]["total_infeasibility"], 
            reverse=True
        )

        #restrict modifications to only transformers
        _, mgr_RAW, _ = self.input_dataset[i]
        transformers = mgr_RAW['PowerSystemResource']['Equipment']['ConductingEquipment'].get('PowerTransformer', {})
        def is_transformer(branch):
            branch_id = str(self.P2R[branch])
            return (branch_id in transformers.keys()) == True
        sorted_transformers = [branch for branch in sorted_branches if is_transformer(branch[0])]
        
        # Focus on the top 40% most infeasible transformers (or at least 1)
        top_transformer_count = max(1, int(0.8 * len(sorted_transformers)))
        top_transformers = sorted_transformers[:top_transformer_count]
        
        # Apply corrections to the most problematic transformers
        for pmd_branch_id, metrics in top_transformers:
            branch_id = self.P2R[pmd_branch_id]
            branch_id_str = str(branch_id)  # Ensure branch_id is a string for dictionary lookup
            
            if branch_id_str not in mld["edge_features"]:
                print(f"<DEBUG> edge key {branch_id_str} does not exist in {list(mld['edge_features'].keys())}")
                continue
                
            # Get current parameters
            # For transformers, we expect R, X, G, and B values
            R = mld["edge_features"][branch_id_str].get("R", [0])
            X = mld["edge_features"][branch_id_str].get("X", [0])
            G = mld["edge_features"][branch_id_str].get("G", [0])
            B = mld["edge_features"][branch_id_str].get("B", [0])
            
            # Convert to numpy arrays for easier manipulation
            R_np = np.array(R)
            X_np = np.array(X)
            G_np = np.array(G)
            B_np = np.array(B)
            
            # Apply changes to parameters based on infeasibility metrics
            if "R" in param_types and metrics["r_infeasibility"] > 0.03:
                scale_factor = 1.0 - min(0.9, self.learning_rate * np.log1p(metrics["r_infeasibility"]))
                R_np = R_np * scale_factor
                R_np = np.maximum(R_np, [0 for _ in R_np]) # Ensure non-negative
                mld["edge_features"][branch_id_str]["R"] = R_np.tolist()
                
            if "X" in param_types and metrics["x_infeasibility"] > 0.03:
                scale_factor = 1.0 - min(0.9, self.learning_rate * np.log1p(metrics["x_infeasibility"]))
                X_np = X_np * scale_factor
                X_np = np.maximum(X_np, [0 for _ in X_np]) # Ensure non-negative
                mld["edge_features"][branch_id_str]["X"] = X_np.tolist()
                
            if "G" in param_types and metrics.get("g_infeasibility", 0) > 0.03:
                scale_factor = 1.0 - min(0.9, self.learning_rate * np.log1p(metrics["g_infeasibility"]))
                G_np = G_np * scale_factor
                G_np = np.maximum(G_np, [0 for _ in G_np])  # Ensure non-negative
                mld["edge_features"][branch_id_str]["G"] = G_np.tolist()
                
            if "B" in param_types and metrics["b_infeasibility"] > 0.03:
                scale_factor = 1.0 + min(0.9, self.learning_rate * np.log1p(metrics["b_infeasibility"]))
                B_np = B_np * scale_factor
                B_np = np.maximum(B_np, [0 for _ in B_np]) # Ensure non-negative
                mld["edge_features"][branch_id_str]["B"] = B_np.tolist()
        
        return mld

    def _get_score(self,i,MLD):
        #given new MLD generate a new MGR grid with updated parameters
        self.MGR_set_yz(i,MLD) 
        #get those updated parameters
        _, mgr_RAW, _ = self.input_dataset[i]

        #compute quality of results
        results = self._run_pf(mgr_RAW)
        branch_infeasibility = self.analyze_branch_infeasibility(results)
        violation_score = sum(branch["total_infeasibility"] for branch in branch_infeasibility.values())

        return violation_score, results


    def _run_pf(self, mgr_grid):
        """
        Run power flow analysis using PowerModelsDistribution
        """
        os.makedirs("tmp", exist_ok=True)
        
        tmp_file = "ravens/ravensML/methods/transformers/trivial_solution/tmp/tmp_pf.json"
        with open(tmp_file, "w") as file:
            json.dump(mgr_grid, file, indent=2)
 
        Main.eval("eng = parse_file(\""+tmp_file+"\")")
        Main.eval("rav_model = instantiate_mc_model_ravens(eng, IVRUPowerModel, build_mc_pf)")
        Main.eval("""
        open("ravens/ravensML/methods/transformers/trivial_solution/tmp/mc_info.json", "w") do f
            JSON.print(f, rav_model, 2)
        end
        """)
        
        #process branch map between Ravens and Power Models Distribution
        with open("ravens/ravensML/methods/transformers/trivial_solution/tmp/mc_info.json", 'r') as file:
            rav_model = json.load(file)
        rav_model_branches = rav_model["data"]["branch"]

        def clean(name):
            last_part = name.split('.')[-1]
            cleaned = re.sub(r'_\d+$', '', last_part)
            return cleaned
            
        self.R2P = {clean(b["name"]):str(b["index"]) for b in rav_model_branches.values()}
        self.P2R = {str(b["index"]):clean(b["name"]) for b in rav_model_branches.values()}
        
        Main.eval("result = optimize_model!(rav_model,relax_integrality=false,optimizer=optimizer_with_attributes(Ipopt.Optimizer, \"print_level\"=>0, \"tol\"=>1e-6),solution_processors=Function[])")
        Main.eval("""
        open("ravens/ravensML/methods/transformers/trivial_solution/tmp/pf_info.json", "w") do f
            JSON.print(f, result)
        end
        """)
    
        with open("ravens/ravensML/methods/transformers/trivial_solution/tmp/pf_info.json", 'r') as file:
            file_content = json.load(file)

        return file_content
    

    def MGR_get_yz(self,i:int):
        """
        Inputs: a dataset index
        Side Effects: None
        Outputs: ML data for a given dataset index
        """
        _, _, mgr_MLD = self.input_dataset[i]
        return mgr_MLD
    
    def MGR_set_yz(self,dataset_index:int,new_ml):
        """
        Inputs: an ML data object and a dataset index
        Side Effects: Updates dataset to properly store new transformer values from ml
        Outputs: None
        """
        _, mgr_RAW, _ = self.input_dataset[dataset_index]
        
        # Update transformers instead of line segments
        transformers = mgr_RAW['PowerSystemResource']['Equipment']['ConductingEquipment'].get('PowerTransformer', {})
        
        for trans_name, trans_data in transformers.items():
            # Check if this transformer has entries in our ML data
            if trans_name in new_ml["edge_features"]:
                ends = trans_data.get("PowerTransformer.PowerTransformerEnd", [])
                for i, end in enumerate(ends):
                    # Update star impedance parameters
                    if "TransformerEnd.StarImpedance" in end:
                        TSI = end["TransformerEnd.StarImpedance"]

                        # Use the transformer parameters from ML data
                        if "R" in new_ml["edge_features"][trans_name]:
                            r_value = new_ml["edge_features"][trans_name]["R"][i]
                            TSI["TransformerStarImpedance.r"] = r_value
                        
                        if "X" in new_ml["edge_features"][trans_name]:
                            x_value = new_ml["edge_features"][trans_name]["X"][i]
                            TSI["TransformerStarImpedance.x"] = x_value
                    
                    # Update core admittance parameters
                    if "TransformerEnd.CoreAdmittance" in end:
                        TCA = end["TransformerEnd.CoreAdmittance"]
                        
                        if "G" in new_ml["edge_features"][trans_name]:
                            g_value = new_ml["edge_features"][trans_name]["G"][i]
                            TCA["TransformerCoreAdmittance.g"] = g_value
                        
                        if "B" in new_ml["edge_features"][trans_name]:
                            b_value = new_ml["edge_features"][trans_name]["B"][i]
                            TCA["TransformerCoreAdmittance.b"] = b_value
    

    def analyze_branch_infeasibility(self, pmd_output):
        """
        Analyzes the infeasibility of transformer parameters from PowerModelsDistribution output.
        
        Args:
            pmd_output (dict): The PowerModelsDistribution output dictionary
        
        Returns:
            dict: A dictionary mapping branch/transformer names to their infeasibility metrics
        """
        if 'solution' not in pmd_output or 'branch' not in pmd_output['solution']:
            return {"error": "No branch/transformer data found in the solution"}
        
        branch_data = pmd_output['solution']['branch']
        infeasibility_metrics = {}
        
        for branch_id, branch in branch_data.items():
            # For transformers, we need different metrics than for lines
            
            # Calculate star impedance r infeasibility
            r_infeasibility = 0
            if 'cr_fr' in branch and 'cr_to' in branch:
                # For transformers, these would be related to winding resistance
                for i in range(min(len(branch['cr_fr']), len(branch['cr_to']))):
                    r_infeasibility += abs(branch['cr_fr'][i] + branch['cr_to'][i])
            
            # Calculate star impedance x infeasibility
            x_infeasibility = 0
            if 'ci_fr' in branch and 'ci_to' in branch:
                # For transformers, these would be related to leakage reactance
                for i in range(min(len(branch['ci_fr']), len(branch['ci_to']))):
                    x_infeasibility += abs(branch['ci_fr'][i] + branch['ci_to'][i])
            
            # Calculate core admittance g and b infeasibility
            b_infeasibility = 0
            g_infeasibility = 0
            if 'csr_fr' in branch and 'csi_fr' in branch:
                # For transformers, these relate to magnetizing current
                for i in range(min(len(branch['csr_fr']), len(branch['csi_fr']))):
                    g_infeasibility += abs(branch['csr_fr'][i])
                    b_infeasibility += abs(branch['csi_fr'][i])
            
            # Store the metrics
            infeasibility_metrics[branch_id] = {
                "r_infeasibility": r_infeasibility,
                "x_infeasibility": x_infeasibility,
                "g_infeasibility": g_infeasibility,
                "b_infeasibility": b_infeasibility,
                "total_infeasibility": r_infeasibility + x_infeasibility + g_infeasibility + b_infeasibility
            }
        
        return infeasibility_metrics
    


if __name__ == "__main__":
    from methods.transformers.gen_trans_error import generate_trans_error
    MGR = MGRavensDataset(data_dir="ravens/ravensML/data/proposed_trans_test")
    MGR_Trans, Y = generate_trans_error(MGR, occurrence_prob=0,
                                    deletion_prob=0,
                                    mult_mean = 1,
                                    mult_var = 1,
                                    add_mean = 5,
                                    add_var = 5, 
                                    size=1)
    MGR_Trans.process_for_ML()
    
    TIO = Trans_Iterative_Optimizer(max_iter = 10)
    TIO(MGR_Trans)
