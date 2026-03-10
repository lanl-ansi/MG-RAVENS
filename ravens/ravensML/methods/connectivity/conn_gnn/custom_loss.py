import torch
import torch.nn as nn
import torch.nn.functional as F


class AdjMSELoss(nn.Module):
    """
    Mean‑squared‑error between a predicted adjacency matrix and the target
    matrix stored in ``target.y["missing_edges"]``.

    Parameters
    ----------
    ignore_diagonal : bool, default=False
        If True the diagonal (self‑loops) is masked out before the loss is
        computed.
    reduction : str, default='mean'
        Reduction mode passed to ``torch.nn.functional.mse_loss`` – can be
        'mean', 'sum' or 'none'.
    """

    def __init__(self, ignore_diagonal: bool = False, reduction: str = "mean"):
        super().__init__()
        self.ignore_diagonal = ignore_diagonal
        self.reduction = reduction

    def forward(self, prediction: torch.Tensor, target_grid) -> torch.Tensor:
        """
        Parameters
        ----------
        prediction : torch.Tensor
            Predicted adjacency matrix. Shape may be (N, N) for a single graph
            or (B, N, N) for a batch.
        target_grid : object
            Expected to contain the attribute ``y`` with a key ``"missing_edges"``.
            The value associated to this key must be a torch tensor.

        Returns
        -------
        torch.Tensor
            The (reduced) MSE loss.
        """

        # -----------------------------------------------------------------
        # 1) Retrieve the ground‑truth adjacency matrix
        # -----------------------------------------------------------------
        try:
            target = target_grid.y["missing_edges"]
        except Exception as exc:
            raise ValueError(
                "target_grid must have attribute y['missing_edges']"
            ) from exc

        # -----------------------------------------------------------------
        # 2) Ensure both tensors are on the same device / dtype
        # -----------------------------------------------------------------
        target = target.to(device=prediction.device, dtype=prediction.dtype)

        # -----------------------------------------------------------------
        # 3) Align batch dimensions (allow (N,N) ↔ (B,N,N))
        # -----------------------------------------------------------------
        if prediction.dim() == 3 and target.dim() == 2:
            target = target.unsqueeze(0).expand_as(prediction)
        elif prediction.dim() == 2 and target.dim() == 3:
            prediction = prediction.unsqueeze(0).expand_as(target)

        if prediction.shape != target.shape:
            raise ValueError(
                f"Shape mismatch: prediction {prediction.shape}, "
                f"target {target.shape}"
            )

        # -----------------------------------------------------------------
        # 4) (Optional) mask out the diagonal
        # -----------------------------------------------------------------
        if self.ignore_diagonal:
            N = prediction.shape[-1]
            diag_mask = ~torch.eye(N, dtype=torch.bool, device=prediction.device)
            if prediction.dim() == 3:          # (B, N, N)
                diag_mask = diag_mask.unsqueeze(0)   # (1, N, N)
            prediction = prediction * diag_mask
            target = target * diag_mask

        # -----------------------------------------------------------------
        # 5) Compute the MSE
        # -----------------------------------------------------------------
        loss = F.mse_loss(prediction, target, reduction=self.reduction)
        return loss