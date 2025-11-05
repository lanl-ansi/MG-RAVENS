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

class YZ_Iterative_Optimizer(object):
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
        self.learning_rate = 0.80  # Step size for parameter adjustments
        self.momentum = 0.9  # Momentum coefficient for smoother convergence
        self.prev_gradients = {}  # Store previous gradients for momentum
        
        # Tolerance parameters
        self.voltage_tolerance = 0.05  # 5% voltage deviation tolerance
        self.current_tolerance = 0.1  # 10% current rating tolerance

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
                self.output_data.append((mgr_NAME, mgr_grid))
                continue
            
            # If not feasible, start iterative optimization
            print("Grid is not feasible. Starting iterative optimization...")
            
            # Reset momentum gradients for this grid
            self.prev_gradients = {}
            
            # Track modifications
            modifications_made = False
            MAX_ITER = self.max_iter
            best_grid = None
            best_violation_score = float('inf')
            best_violation_state = None
            best_result_dict = None
            
            # Store the initial state
            current_mgr_MLD = self.MGR_get_yz(i)
            
            for iteration in range(MAX_ITER):
                print(f"Iteration {iteration + 1}")
                
                # Identify problematic branches and compute violation metrics
                mgr_MLD_updated, violation_score = self.PMD_get_new_yz(current_mgr_MLD, result_dict)
                
                print(f"Violation score: {violation_score}")
                
                # Check if we've made an improvement
                if violation_score < best_violation_score:
                    print(f"Found better solution with violation score: {violation_score}")
                    best_violation_score = violation_score
                    best_violation_state = copy.deepcopy(mgr_MLD_updated)
                    modifications_made = True
                
                # If no updates were made, use the best solution found so far
                if mgr_MLD_updated == current_mgr_MLD:
                    print("No updates made. Using best solution found.")
                    if best_violation_state is not None:
                        self.MGR_set_yz(i, best_violation_state)
                        current_mgr_MLD = best_violation_state
                    break
                
                # Update with new settings
                self.MGR_set_yz(i, mgr_MLD_updated) 
                current_mgr_MLD = mgr_MLD_updated
                
                # Run power flow again with modified parameters
                result_dict = self._run_pf(mgr_grid)
                
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
            
            # Add the (potentially modified) grid to output data
            self.output_data.append((mgr_NAME, mgr_grid,best_violation_state))
        
        return self.output_data


    def _run_pf(self, mgr_grid):
        """
        Run power flow analysis using PowerModelsDistribution
        """
        os.makedirs("tmp", exist_ok=True)
        
        tmp_file = "ravens/ravensML/methods/YZ/trivial_solution/tmp/tmp_pf.json"
        with open(tmp_file, "w") as file:
            json.dump(mgr_grid, file, indent=2)
 
        Main.eval("eng = parse_file(\""+tmp_file+"\")")
        Main.eval("rav_model = instantiate_mc_model_ravens(eng, IVRUPowerModel, build_mc_pf)")
        Main.eval("""
        open("ravens/ravensML/methods/YZ/trivial_solution/tmp/mc_info.json", "w") do f
            JSON.print(f, rav_model, 2)
        end
        """)
        
        #process branch map between Ravens and Power Models Distribution
        with open("ravens/ravensML/methods/YZ/trivial_solution/tmp/mc_info.json", 'r') as file:
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
        open("ravens/ravensML/methods/YZ/trivial_solution/tmp/pf_info.json", "w") do f
            JSON.print(f, result)
        end
        """)
    
        with open("ravens/ravensML/methods/YZ/trivial_solution/tmp/pf_info.json", 'r') as file:
            file_content = json.load(file)

        return file_content
    

    def MGR_get_yz(self,i:int):
        _, _, mgr_MLD = self.input_dataset[i]
        return mgr_MLD
    
    def MGR_set_yz(self,i:int,new_ml):
        _, mgr_RAW, _ = self.input_dataset[i]
        branches = mgr_RAW['PowerSystemResource']['Equipment']['ConductingEquipment']['Conductor'].get('ACLineSegment', {})
        for branch_id, branch_data in branches.items():
            # Update edge with features
            PLPIID = branch_data.get("ACLineSegment.PerLengthImpedance").split("::")[-1].strip("'\"")
            PLPI = mgr_RAW['PerLengthLineParameter']['PerLengthImpedance']['PerLengthPhaseImpedance'].get(PLPIID)
            R = new_ml["edge_features"][branch_id]["R"]
            X = new_ml["edge_features"][branch_id]["X"]
            B = new_ml["edge_features"][branch_id]["B"]
            for entry in PLPI["PerLengthPhaseImpedance.PhaseImpedanceData"]:
                row = entry["PhaseImpedanceData.row"] - 1  # Convert to 0-indexed
                col = entry["PhaseImpedanceData.column"] - 1  # Convert to 0-indexed
                # For MGR lines defined with upper triangular matrices (Pulling from UT MGR_MLD matrix)
                if col >= row:
                    entry["PhaseImpedanceData.r"] = R[row][col]
                    entry["PhaseImpedanceData.x"] = X[row][col]
                    entry["PhaseImpedanceData.b"] = B[row][col]
                else:
                    #For MGR lines defined with lower triangular matrices
                    entry["PhaseImpedanceData.r"] = R[col][row]
                    entry["PhaseImpedanceData.x"] = X[col][row]
                    entry["PhaseImpedanceData.b"] = B[col][row]
        #TODO: implement something that searches up if we have a virtual branch specified in the ML from the dataset file included below
        sources = mgr_RAW['PowerSystemResource']['Equipment']['ConductingEquipment']['EnergyConnection']['EnergySource']      
        for source_id, source_data in sources.items():
            # Check if this source has a virtual branch in the ML data
            if source_id in new_ml["edge_features"]:
                # Get the R and X matrices from the virtual branch
                R = new_ml["edge_features"][source_id]["R"]
                X = new_ml["edge_features"][source_id]["X"]
                
                # Update the source impedance parameters
                # For simplicity, we use the diagonal elements of the matrices
                if len(R) > 0 and len(R[0]) > 0:
                    source_data["EnergySource.r"] = R[0][0]
                    source_data["EnergySource.x"] = X[0][0]
                
                # Update zero-sequence impedance if available
                if len(R) > 1 and len(R[1]) > 1:
                    source_data["EnergySource.r0"] = R[1][1]
                    source_data["EnergySource.x0"] = X[1][1]
        ML = None
        return ML
    
    def PMD_get_new_yz(self, current_ml, results):
        #-----------------------------
        # Parse Results
        #-----------------------------
        branch_infeasibility = self.analyze_branch_infeasibility(results)

        #debug prints
        with open("ravens/ravensML/methods/YZ/trivial_solution/tmp/log.txt", "w") as f:
            f.write("keys: " + str(results.keys()) + "\n")
            f.write("infeasibility results: ")
            json.dump(branch_infeasibility, f, indent=2)
            f.write("Opti results: ")
            json.dump(results, f, indent=2)

        #-----------------------------
        # Quantify Infeasibility
        #-----------------------------
        if isinstance(branch_infeasibility, dict) and not "error" in branch_infeasibility:
            violation_score = sum(branch["total_infeasibility"] for branch in branch_infeasibility.values())
        else:
            # If there's an error or no branch data, return original data with infinite violation
            return current_ml, float('inf')
        
        #-----------------------------
        # Generate Updated ML Data
        #-----------------------------
        MLD_updated = copy.deepcopy(current_ml)
        
        # Sort branches by their infeasibility to focus on the most problematic ones
        sorted_branches = sorted(
            branch_infeasibility.items(), 
            key=lambda x: x[1]["total_infeasibility"], 
            reverse=True
        )
        # Focus on the top 40% most infeasible branches (or at least 1)
        top_branch_count = max(1, int(0.4 * len(sorted_branches)))
        top_branches = sorted_branches[:top_branch_count]

        # Track if any changes were made
        changes_made = False

        # Apply corrections to the most problematic branches
        for pmd_branch_id, metrics in top_branches:
            branch_id = self.P2R[pmd_branch_id]
            branch_id_str = str(branch_id)  # Ensure branch_id is a string for dictionary lookup
            if branch_id_str not in MLD_updated["edge_features"]:
                print(f"<DEBUG> edge key {branch_id_str} does not exist in {list(MLD_updated['edge_features'].keys())}")
                continue
                
            # Get current R, X, B matrices
            R = MLD_updated["edge_features"][branch_id_str]["R"]
            X = MLD_updated["edge_features"][branch_id_str]["X"]
            B = MLD_updated["edge_features"][branch_id_str]["B"]
            
            # Convert to numpy arrays for easier manipulation
            R_np = np.array(R)
            X_np = np.array(X)
            B_np = np.array(B)
            
            # Apply corrections based on infeasibility metrics
            # The larger the infeasibility, the more aggressive the correction
            
            # R matrix correction - reduce resistance to address r_infeasibility
            if metrics["r_infeasibility"] > 0.0:
                scale_factor = 1.0 - min(0.9, self.learning_rate * np.log1p(metrics["r_infeasibility"]))
                # print("<DEBUG> r:",scale_factor)
                R_np_new = R_np * scale_factor
                if not np.array_equal(R_np, R_np_new):
                    R_np = R_np_new
                    changes_made = True
            
            # X matrix correction - adjust reactance to address x_infeasibility
            if metrics["x_infeasibility"] > 0.0:
                scale_factor = 1.0 - min(0.9, self.learning_rate * np.log1p(metrics["x_infeasibility"]))
                # print("<DEBUG> x:",scale_factor)
                X_np_new = X_np * scale_factor
                if not np.array_equal(X_np, X_np_new):
                    X_np = X_np_new
                    changes_made = True
            
            # B matrix correction - adjust susceptance to address b_infeasibility
            if metrics["b_infeasibility"] > 0.0:
                # For B matrix, we might need to increase values to reduce infeasibility
                scale_factor = 1.0 + min(0.9, self.learning_rate * np.log1p(metrics["b_infeasibility"]))
                # print("<DEBUG> b:",scale_factor)
                B_np_new = B_np * scale_factor
                if not np.array_equal(B_np, B_np_new):
                    B_np = B_np_new
                    changes_made = True
            
            # Ensure matrices remain physically valid
            # For example, resistance should be positive
            R_np = np.maximum(R_np, 1e-6)
            
            # Update the MLD data with corrected matrices
            MLD_updated["edge_features"][branch_id_str]["R"] = R_np.tolist()
            MLD_updated["edge_features"][branch_id_str]["X"] = X_np.tolist()
            MLD_updated["edge_features"][branch_id_str]["B"] = B_np.tolist()

        # If no changes were made, return the original with its violation score
        if not changes_made:
            print("No changes made to parameters.")
            return current_ml, violation_score

        return MLD_updated, violation_score

    

    def analyze_branch_infeasibility(self,pmd_output):
        """
        Analyzes the infeasibility of branch X, R, and B matrices from PowerModelsDistribution output.
        
        Args:
            pmd_output (dict): The PowerModelsDistribution output dictionary
        
        Returns:
            dict: A dictionary mapping branch names to their infeasibility metrics
        """
        if 'solution' not in pmd_output or 'branch' not in pmd_output['solution']:
            return {"error": "No branch data found in the solution"}
        
        branch_data = pmd_output['solution']['branch']
        infeasibility_metrics = {}
        
        for branch_id, branch in branch_data.items():
            # Extract the relevant parameters for X, R, and B matrices
            # For a three-phase system, we need to check the consistency of these parameters
            
            # Calculate R matrix infeasibility (using cr_fr and cr_to)
            r_infeasibility = 0
            if 'cr_fr' in branch and 'cr_to' in branch:
                # R matrix should be symmetric and cr_fr should equal -cr_to
                for i in range(min(len(branch['cr_fr']), len(branch['cr_to']))):
                    r_infeasibility += abs(branch['cr_fr'][i] + branch['cr_to'][i])
            
            # Calculate X matrix infeasibility (using ci_fr and ci_to)
            x_infeasibility = 0
            if 'ci_fr' in branch and 'ci_to' in branch:
                # X matrix should be symmetric and ci_fr should equal -ci_to
                for i in range(min(len(branch['ci_fr']), len(branch['ci_to']))):
                    x_infeasibility += abs(branch['ci_fr'][i] + branch['ci_to'][i])
            
            # Calculate B matrix infeasibility (using csr_fr, csi_fr)
            b_infeasibility = 0
            if 'csr_fr' in branch and 'csi_fr' in branch:
                # For the shunt admittance (B), we can check if the values are consistent
                # This is a simplified check - in reality, the B matrix has more complex constraints
                for i in range(min(len(branch['csr_fr']), len(branch['csi_fr']))):
                    # In a lossless line, the real part should be close to zero
                    b_infeasibility += abs(branch['csr_fr'][i])
            
            # Calculate power flow infeasibility (power should be conserved)
            power_infeasibility = 0
            if 'pf' in branch and 'pt' in branch:
                for i in range(min(len(branch['pf']), len(branch['pt']))):
                    # Power losses should be minimal in an ideal system
                    power_infeasibility += abs(branch['pf'][i] + branch['pt'][i])
            
            # Store the metrics
            infeasibility_metrics[branch_id] = {
                "r_infeasibility": r_infeasibility,
                "x_infeasibility": x_infeasibility,
                "b_infeasibility": b_infeasibility,
                "power_infeasibility": power_infeasibility,
                "total_infeasibility": r_infeasibility + x_infeasibility + b_infeasibility + power_infeasibility
            }
        
        return infeasibility_metrics
    


if __name__ == "__main__":
    from methods.YZ.gen_YZ_error import generate_yz_error
    MGR = MGRavensDataset(data_dir="ravens/ravensML/data/raw")
    MGR_YZ, Y = generate_yz_error(MGR, occurrence_prob=1,
                                    deletion_prob=0,
                                    mult_mean = 1,
                                    mult_var = 1,
                                    add_mean = 0,
                                    add_var = 5, 
                                    size=1)
    MGR_YZ.process_for_ML()
    
    YZIO = YZ_Iterative_Optimizer(max_iter = 10)
    YZIO(MGR_YZ)

