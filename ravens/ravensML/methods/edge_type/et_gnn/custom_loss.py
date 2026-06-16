import torch
import torch.nn as nn
import torch.nn.functional as F


class EdgeClassificationLoss(nn.Module):
    """
    Classification-oriented loss for a node x node adjacency matrix.

    * pred  : (max_nodes, max_nodes, 5)    - raw logits from the model
    * target: (max_nodes, max_nodes)       - integer labels -1 … 3
    Returns (loss, accuracy)
    """
    def __init__(self,
                 weight: torch.Tensor | None = None,
                 reduction: str = "mean",
                 eps: float = 1e-12):
        """
        Parameters
        ----------
        weight : optional 1-D tensor of size 5 giving class-wise weighting.
                 Useful if the five edge-type classes are imbalanced.
        reduction : "mean" or "sum" (behavior of nn.CrossEntropyLoss)
        eps : small constant added to denominator when computing accuracy.
        """
        super().__init__()
        self.ce = nn.CrossEntropyLoss(weight=weight, reduction=reduction)
        self.eps = eps

    def forward(self, pred: torch.Tensor, batch):
        """
        Parameters
        ----------
        pred : Tensor (max_nodes, max_nodes, 5) - raw logits.

        batch : a torch_geometric.data.Data (or any object) that contains
                the ground-truth adjacency matrix in
                `batch.y['edge_labels']`.  Shape must be (max_nodes,
                max_nodes) with values -1 … 3.

        Returns
        -------
        loss : scalar Tensor (requires grad)
        acc  : float Tensor (no grad) - top-1 classification accuracy,
                expressed as a fraction in [0, 1].
        """

        # Extract and preprocess the target tensor
        target = batch.y['edge_labels']                     # (N, N)
        # shift to zero indexed
        target = (target + 1).long()

        # place on same device as the predictions
        target = target.to(pred.device)


        # Reshape both tensors to a shape that CrossEntropyLoss expects:
        #          (N*N, 5)  logits
        #          (N*N,)    target indices
        N = pred.shape[0]           # = max_nodes
        logits = pred.reshape(N * N, -1)      # (N^2, 5)
        target_flat = target.reshape(N * N)   # (N^2,)


        # Compute the scalar loss
        loss = self.ce(logits, target_flat)   # scalar, back-propagatable

        # Compute top-1 accuracy (no gradient needed)
        with torch.no_grad():
            pred_class = logits.argmax(dim=-1)          # (N^2,)
            correct = (pred_class == target_flat).float().sum()
            acc = correct / (target_flat.numel() + self.eps)

        return loss, acc