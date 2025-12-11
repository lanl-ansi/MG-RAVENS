import torch 
import torch.nn as nn

class WeightedMSELoss(nn.Module):
    def __init__(self,max_phases,penalty_strength=0):
        super(WeightedMSELoss, self).__init__()
        self.weights = torch.tensor(
            [10] +
            [3 * (i == j) + 1 * (1-(i == j)) for _ in range(4) for i in range(max_phases) for j in range(max_phases)] +
            [1, 1, 1]
        )
        # self.weights = self.weights/torch.sum(self.weights)
        self.penalty_strength = penalty_strength

    def forward(self, predictions, targets):
        #negative penalty
        negative_mask = predictions < 0 
        negative_penalty = torch.sum(torch.abs(predictions[negative_mask])**2) * self.penalty_strength
        
        #weighted diff
        weighted_diff = (predictions - targets)*self.weights

        #MSE + negativity
        loss = torch.mean((weighted_diff) ** 2) + negative_penalty
        return loss
    

if __name__ == "__main__":
    W = WeightedMSELoss(3)
    a = torch.tensor([1 for _ in range(40)])
    b = torch.tensor([2 for _ in range(40)])
    print(W(a,b))