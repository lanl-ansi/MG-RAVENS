import torch 
import torch.nn as nn
from random import random
from math import ceil
from torch_geometric.utils import degree
from mgr_helpers import unpack_edge, update_mgr, run_pf
import json
from pathlib import Path
import sys, os
rML_ROOT = Path(__file__).resolve().parents[3]
if str(rML_ROOT) not in sys.path:
    sys.path.insert(0, str(rML_ROOT))
from methods.transformers.trans_gnn.mgr_helpers import update_mgr
from methods.transformers.trans_gnn.data import MGTransformerDataset
from framework.tools.pf_inf_approx.model import SimpleGNN
from framework.tools.pf_inf_approx.data import MG_Inf_Dataset

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
    def __init__(self,max_phases,neg_penalty=0,inf_penalty=0,test_percentage=0.5):
        super(PI_WMSE_Loss, self).__init__()
        self.weights = torch.tensor(
            [5] +
            [3 * (i == j) + 3 * (1-(i == j)) for _ in range(4) for i in range(max_phases) for j in range(max_phases)] +
            [1, 1, 1]
        )
        self.neg_penalty = neg_penalty
        self.inf_penalty = inf_penalty
        self.test_percentage = test_percentage
        self.device = None

        self.model = self.init_model()
        state_dict = torch.load(
            rML_ROOT/"framework/tools/pf_inf_approx/tmp/DEV_InfApprox_best_model.pth",
            map_location=self.device,
        )
        self.model.load_state_dict(state_dict) 
        self.check_feas = MG_Inf_Dataset(
            root=rML_ROOT,
            size=0,
            error_kwargs={"mean": 0.0,"std": 0.0},
        )

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

    def inf_score(self, pred, target_grid):
        new_mgr = update_mgr(pred,target_grid)
        tensor_input = self.check_feas.convert_input(new_mgr,self.device)
        output = self.model(tensor_input).squeeze() 
        return output
    
    def init_model(self):
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        dataset = MGTransformerDataset(
            root=rML_ROOT,
            size=1,
            error_kwargs={"deletion_prob": 0.01, 
                        "occurrence_prob": 0.55,
                        "mult_mean": 1,
                        "mult_var": 2.25,
                        "add_mean": 0,
                        "add_var": 2.25,},
        )

        # input / output dimensions 
        sample = dataset[0]
        node_feat_dim = sample.x.shape[1]
        edge_feat_dim = sample.edge_attr.shape[1]

        # Compute the maximum in-degree in the training data.
        max_degree = -1
        for data in dataset:
            d = degree(data.edge_index[1], num_nodes=data.num_nodes, dtype=torch.long)
            max_degree = max(max_degree, int(d.max()))

        # Compute the in-degree histogram tensor
        deg = torch.zeros(max_degree + 1, dtype=torch.long)
        for data in dataset:
            d = degree(data.edge_index[1], num_nodes=data.num_nodes, dtype=torch.long)
            deg += torch.bincount(d, minlength=deg.numel())

        model = SimpleGNN(
            node_features=node_feat_dim,
            edge_features=edge_feat_dim,
            degree=deg,
            max_nodes=20,
            transport_distance=17,
        ).to(self.device)
        return model



    

if __name__ == "__main__":
    W = WeightedMSELoss(3)
    a = torch.tensor([1 for _ in range(40)])
    b = torch.tensor([2 for _ in range(40)])
    print(W(a,b))