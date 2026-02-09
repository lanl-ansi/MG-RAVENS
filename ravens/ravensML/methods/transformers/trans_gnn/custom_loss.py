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

    def forward(self, predictions, targets):        
        # Ensure predictions and targets have the same shape
        if predictions.shape != targets.shape:
            raise ValueError(f"Predictions shape {predictions.shape} does not match targets shape {targets.shape}")

        # Expand weights to match batch size
        weights = self.weights.to(predictions.device).expand(predictions.shape[0], -1)

        negative_mask = predictions < 0 
        negative_penalty = torch.sum(torch.abs(predictions[negative_mask])**2) * self.penalty_strength
        
        weighted_diff = (predictions - targets) * weights

        loss = torch.mean((weighted_diff) ** 2) + negative_penalty
        return loss
    

class PI_WMSE_Loss(nn.Module):
    def __init__(self,max_phases,neg_penalty=0,inf_penalty=0,test_percentage=0.5):
        super(PI_WMSE_Loss, self).__init__()
        self.weights = torch.tensor(
            [10] +
            [3 * (i == j) + 1 * (1-(i == j)) for _ in range(4) for i in range(max_phases) for j in range(max_phases)] +
            [1, 1, 1]
        )
        self.neg_penalty = neg_penalty
        self.inf_penalty = inf_penalty
        self.test_percentage = test_percentage

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
    
    def analyze_infeasibility(self,pf_res):
        with open("tmp.json", "w") as f:
            json.dump(pf_res, f, indent=2)
        #TODO: unimport json when we get rid of this
        #TODO:figure out if better method exists
        return pf_res['objective']
    
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

    def inf_score(self, pred, target_grid):
        # print("<DEBUG> doing a random inf test")
        new_mgr = update_mgr(pred,target_grid) 
        results = run_pf(new_mgr)
        branch_infeasibility = self.analyze_branch_infeasibility(results) #TODO: Implement Correctly --> propagate to iterative methods 
        return sum(branch["total_infeasibility"] for branch in branch_infeasibility.values())



    

if __name__ == "__main__":
    W = WeightedMSELoss(3)
    a = torch.tensor([1 for _ in range(40)])
    b = torch.tensor([2 for _ in range(40)])
    print(W(a,b))