import torch 
import torch.nn as nn
from random import random
from math import ceil
from mgr_helpers import unpack_edge, update_mgr, run_pf
import json

class AdjMSELoss(nn.Module):
    def __init__(self):
        super(AdjMSELoss, self).__init__()

    def forward(self, prediction, target_grid):
        try:
            target = target_grid.y["missing_edges"]
        except:
            raise ValueError("Expects an input of a full data object rather than an edge attribute")     
        
        # Ensure predictions and targets have the same shape
        if prediction.shape != target.shape:
            raise ValueError(f"Predictions shape {prediction.shape} does not match targets shape {target.shape}")
        
        weighted_diff = (prediction - target)

        loss = torch.mean((weighted_diff) ** 2)
        return loss
    
