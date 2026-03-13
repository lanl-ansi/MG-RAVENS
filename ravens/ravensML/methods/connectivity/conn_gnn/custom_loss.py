import torch
import torch.nn as nn
import torch.nn.functional as F
from warnings import warn
from random import random
from methods.connectivity.conn_gnn.mgr_helpers import update_mgr, run_pf

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

    def inf_score(self, pred, target_grid):
        new_mgr = update_mgr(pred,target_grid)
        try:  
            results = run_pf(new_mgr)
            if self.branch_inf_mode:
                branch_infeasibility = self.analyze_branch_infeasibility(results)
                return sum(branch["total_infeasibility"] for branch in branch_infeasibility.values())
            else:
                return self.system_demand_not_met(results)
        except Exception as e1:
            try:
                run_pf(target_grid)
            except Exception as e2:
                warn(f"PMD PF errors on the base and updated grids with the following error: \n'{e2}'.\nContinuing without penalty.")
                return 0
            warn(f"PMD PF fails only on the updated grid with the following error: \n'{e1}'.\nContinuing with penalty of 1000.")
            return 100 #TODO:refine error