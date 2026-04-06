import torch
import torch.nn as nn
import torch.nn.functional as F
from torch_geometric.utils import degree
from warnings import warn
from random import random
from pathlib import Path
import sys, os
rML_ROOT = Path(__file__).resolve().parents[3]
if str(rML_ROOT) not in sys.path:
    sys.path.insert(0, str(rML_ROOT))
from methods.connectivity.conn_gnn.mgr_helpers import update_mgr
from methods.connectivity.conn_gnn.data import MGConnDataset
from framework.tools.pf_inf_approx.model import SimpleGNN
from framework.tools.pf_inf_approx.data import MG_Inf_Dataset

class AdjMSELoss(nn.Module):
    """
    Weighted mean‑squared‑error between a predicted adjacency matrix and the
    target matrix stored in ``target.y["missing_edges"]``.

    The loss can optionally:
      * ignore the diagonal (self‑loops),
      * amplify the contribution of *positive* edges via ``pos_weight`` (β),
      * be multiplied by a global scaling factor ``K`` (useful when the loss
        is combined with other objectives).

    Parameters
    ----------
    ignore_diagonal : bool, default=False
        If ``True`` the diagonal entries are masked out before the loss is
        computed.
    reduction : str, default='mean'
        Reduction mode passed to ``torch.nn.functional.mse_loss`` – can be
        ``'mean'``, ``'sum'`` or ``'none'``.
    K : float | torch.Tensor, default=1.0
        Positive scaling factor applied **after** the reduction.
    pos_weight : float | torch.Tensor, default=4.0
        Weight (β) applied **only** on entries where ``target == 1``.
        A larger β makes the model favour high predictions on true edges.
    """

    def __init__(
        self,
        ignore_diagonal: bool = False,
        reduction: str = "mean",
        K: float | torch.Tensor = 1.0,
        pos_weight: float | torch.Tensor = 4.0,
    ):
        super().__init__()
        self.ignore_diagonal = ignore_diagonal
        self.reduction = reduction

        # store K and β as buffers so they move with the module (e.g. to GPU)
        self.register_buffer("K", torch.tensor(float(K)))
        self.register_buffer("beta", torch.tensor(float(pos_weight)))


    def _mask_diagonal(self, tensor: torch.Tensor) -> torch.Tensor:
        N = tensor.shape[-1]
        diag_mask = ~torch.eye(N, dtype=torch.bool, device=tensor.device)
        return tensor * diag_mask

    def forward(self, prediction: torch.Tensor, target_grid) -> torch.Tensor:

        target = target_grid.y["missing_edges"].to(device=prediction.device, dtype=prediction.dtype)

        if self.ignore_diagonal:
            prediction = self._mask_diagonal(prediction)
            target = self._mask_diagonal(target)

        diff = prediction - target                     # (N, N)
        per_elem_loss = diff.pow(2) * (1.0 + self.beta * target)

        if self.reduction == "mean":
            loss = per_elem_loss.mean()
        elif self.reduction == "sum":
            loss = per_elem_loss.sum()
        elif self.reduction == "none":
            loss = per_elem_loss
        else:
            raise ValueError(f"Unsupported reduction mode '{self.reduction}'")

        loss = loss * self.K

        return loss
    

class PIAdjMSELoss(nn.Module):
    """
    Weighted mean‑squared‑error between a predicted adjacency matrix and the
    target matrix stored in ``target.y["missing_edges"]``.

    The loss can optionally:
      * ignore the diagonal (self‑loops),
      * amplify the contribution of *positive* edges via ``pos_weight`` (β),
      * be multiplied by a global scaling factor ``K`` (useful when the loss
        is combined with other objectives).

    Parameters
    ----------
    ignore_diagonal : bool, default=False
        If ``True`` the diagonal entries are masked out before the loss is
        computed.
    reduction : str, default='mean'
        Reduction mode passed to ``torch.nn.functional.mse_loss`` – can be
        ``'mean'``, ``'sum'`` or ``'none'``.
    K : float | torch.Tensor, default=1.0
        Positive scaling factor applied **after** the reduction.
    pos_weight : float | torch.Tensor, default=4.0
        Weight (β) applied **only** on entries where ``target == 1``.
        A larger β makes the model favour high predictions on true edges.
    """

    def __init__(
        self,
        ignore_diagonal: bool = False,
        reduction: str = "mean",
        K: float | torch.Tensor = 1.0,
        pos_weight: float | torch.Tensor = 4.0,
        inf_penalty: float | torch.Tensor = 0,
        test_percentage: float | torch.Tensor = 0.5, 
        branch_inf_mode:bool = False
    ):
        super().__init__()
        self.ignore_diagonal = ignore_diagonal
        self.reduction = reduction

        # store K and β as buffers so they move with the module (e.g. to GPU)
        self.register_buffer("K", torch.tensor(float(K)))
        self.register_buffer("beta", torch.tensor(float(pos_weight)))
        self.inf_penalty = inf_penalty
        self.test_percentage = test_percentage
        self.branch_inf_mode = branch_inf_mode
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

        #TODO: Remove        
        from warnings import warn
        warn("inf_score() is currently non-differentiable in Pytorch. Treat this as a placeholder for a soon to be released" \
        "differentiable approximation.")


    def _mask_diagonal(self, tensor: torch.Tensor) -> torch.Tensor:
        N = tensor.shape[-1]
        diag_mask = ~torch.eye(N, dtype=torch.bool, device=tensor.device)
        return tensor * diag_mask

    def forward(self, prediction: torch.Tensor, target_grid) -> torch.Tensor:

        target = target_grid.y["missing_edges"].to(device=prediction.device, dtype=prediction.dtype)

        if self.ignore_diagonal:
            prediction = self._mask_diagonal(prediction)
            target = self._mask_diagonal(target)

        diff = prediction - target                     # (N, N)
        per_elem_loss = diff.pow(2) * (1.0 + self.beta * target)

        if self.reduction == "mean":
            loss = per_elem_loss.mean()
        elif self.reduction == "sum":
            loss = per_elem_loss.sum()
        elif self.reduction == "none":
            loss = per_elem_loss
        else:
            raise ValueError(f"Unsupported reduction mode '{self.reduction}'")

        #process random infeasibility test
        if random() < self.test_percentage:
            infeasibility_score = self.inf_score(prediction,target_grid)* self.inf_penalty
        else:
            infeasibility_score = 0

        loss += infeasibility_score 

        loss = loss * self.K 

        return loss

    def inf_score(self, pred, target_grid):
        new_mgr = update_mgr(pred,target_grid)
        tensor_input = self.check_feas.convert_input(new_mgr,self.device)
        output = self.model(tensor_input).squeeze() 
        return output
    
    def init_model(self):
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        dataset = MGConnDataset(
            root=rML_ROOT,
            max_nodes=20,
            size=1,
            error_kwargs={"del_e_prob": 0.15},
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