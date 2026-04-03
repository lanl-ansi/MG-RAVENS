import torch 
import torch.nn as nn
from random import random
from math import ceil
from mgr_helpers import unpack_edge, update_mgr, run_pf
import json

class WeightedMSELoss(nn.Module):
    def __init__(self,max_phases,penalty_strength=0):
        super(WeightedMSELoss, self).__init__()
        self.weights = torch.tensor(
            [10] +
            [3 * (i == j) + 1 * (1-(i == j)) for _ in range(4) for i in range(max_phases) for j in range(max_phases)] +
            [1, 1, 1]
        )
        self.penalty_strength = penalty_strength

    def forward(self, prediction, target_grid):
        try:
            target = target_grid.y["edge_attr"]
        except:
            raise ValueError("Expects an input of a full data object rather than an edge attribute")     
        
        # Ensure predictions and targets have the same shape
        if prediction.shape != target.shape:
            raise ValueError(f"Predictions shape {prediction.shape} does not match targets shape {target.shape}")

        # Expand weights to match batch size
        weights = self.weights.to(prediction.device).expand(prediction.shape[0], -1)

        negative_mask = prediction < 0 
        negative_penalty = torch.sum(torch.abs(prediction[negative_mask])**2) * self.penalty_strength
        
        weighted_diff = (prediction - target) * weights

        loss = torch.mean((weighted_diff) ** 2) + negative_penalty
        return loss
    

class PI_WMSE_Loss(nn.Module):
    def __init__(self,max_phases,neg_penalty=0,inf_penalty=0,test_percentage=0.5, branch_inf_mode = False):
        super(PI_WMSE_Loss, self).__init__()
        self.weights = torch.tensor(
            [5] +
            [3 * (i == j) + 3 * (1-(i == j)) for _ in range(4) for i in range(max_phases) for j in range(max_phases)] +
            [1, 1, 1]
        )
        self.neg_penalty = neg_penalty
        self.inf_penalty = inf_penalty
        self.test_percentage = test_percentage
        self.branch_inf_mode = branch_inf_mode
        from warnings import warn
        warn("inf_score() is currently non-differentiable in Pytorch. Treat this as a placeholder for a soon to be released" \
        "differentiable approximation.")

    def forward(self, prediction, target_grid):
        target_output = target_grid.y["edge_attr"]       
        # Ensure predictions and targets have the same shape
        if prediction.shape != target_output.shape:
            raise ValueError(f"Predictions shape {prediction.shape} does not match targets shape {target_output.shape}")

        # Calculate Weighted Difference
        weights = self.weights.to(prediction.device).expand(prediction.shape[0], -1)
        weighted_diff = (prediction - target_output) * weights

        #Calculate Output Negativity
        negative_mask = prediction < 0 
        negative_score = torch.sum(torch.abs(prediction[negative_mask])**2) * self.neg_penalty

        #Calculate Output Infeasibility
        if random() < self.test_percentage:
            infeasibility_score = self.inf_score(prediction,target_grid)* self.inf_penalty
        else:
            infeasibility_score = 0

        # print(f"<DEBUG> Calculated inf score: {infeasibility_score}")
        #Calculate the combined loss output
        loss = torch.mean((weighted_diff) ** 2) + negative_score + infeasibility_score 
        return loss
    
    def system_demand_not_met(self,pmd_output):
        total_generation = 0.0
        total_load = 0.0
        expected_losses = 0.0
        pm_solution = pmd_output['solution']
        
        # Process generation - directly using 'gen' which we know exists
        if "gen" in pm_solution:
            for gen in pm_solution["gen"].values():
                if "pg" in gen:
                    pg_value = gen["pg"]
                    if isinstance(pg_value, list):
                        # Sum all elements if pg is a list
                        total_generation += sum(float(val) for val in pg_value)
                    else:
                        # Handle single value case
                        total_generation += float(pg_value)
        
        # Process load - directly using 'load' which we know exists
        if "load" in pm_solution:
            for load in pm_solution["load"].values():
                if "pd" in load:
                    pd_value = load["pd"]
                    if isinstance(pd_value, list):
                        # Sum all elements if pd is a list
                        total_load += sum(float(val) for val in pd_value)
                    else:
                        # Handle single value case
                        total_load += float(pd_value)
        
        # Calculate branch losses - directly using 'branch' which we know exists
        if "branch" in pm_solution:
            for branch in pm_solution["branch"].values():
                if "pf" in branch and "pt" in branch:
                    pf_value = branch["pf"]
                    pt_value = branch["pt"]
                    
                    # Handle if these are lists
                    if isinstance(pf_value, list) and isinstance(pt_value, list):
                        for i in range(min(len(pf_value), len(pt_value))):
                            expected_losses += abs(float(pf_value[i]) + float(pt_value[i]))
                    else:
                        expected_losses += abs(float(pf_value) + float(pt_value))
        
        # Generation should equal load plus losses
        # Negative value means demand not met
        power_balance = total_generation - (total_load + expected_losses)
        return 100*max(0.0, -power_balance)  # In per unit, only return positive values
    


    
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

    def inf_score(self, pred, target_grid, differentiable_approximation=False):
        # print("<DEBUG> doing a random inf test")
        new_mgr = update_mgr(pred,target_grid) 
        results = run_pf(new_mgr)
        if self.branch_inf_mode:
            branch_infeasibility = self.analyze_branch_infeasibility(results)
            return sum(branch["total_infeasibility"] for branch in branch_infeasibility.values())
        else:
            return self.system_demand_not_met(results)



    

if __name__ == "__main__":
    W = WeightedMSELoss(3)
    a = torch.tensor([1 for _ in range(40)])
    b = torch.tensor([2 for _ in range(40)])
    print(W(a,b))