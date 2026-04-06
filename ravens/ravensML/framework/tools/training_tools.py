# ----------------------------------------------------------------------
# framework/tools/training_tools.py
# ----------------------------------------------------------------------
import torch
from warnings import warn
from tqdm import tqdm                     # optional – nice progress bar

# ----------------------------------------------------------------------
# Keep the original deprecation warning so existing imports still see it.
# ----------------------------------------------------------------------
warn("Deprecated: please use framework.tools.training_tools rather than "
     "the this version", DeprecationWarning)

# ----------------------------------------------------------------------
# Helper – turn the Data/DataBatch object into a flat target tensor
# ----------------------------------------------------------------------
def _get_flat_target(batch, max_nodes):
    """
    Parameters
    ----------
    batch : torch_geometric.data.Batch
        A batch produced by DataLoader.
    max_nodes : int
        Upper bound on the number of nodes per graph (the same value you
        used when building `SimpleGNN`).

    Returns
    -------
    torch.Tensor
        1‑D tensor of shape (max_nodes**2,) on the same device as the batch.
    """
    # --------------------------------------------------------------
    # In your dataset you store the clean adjacency matrix inside
    #   batch.y["missing_edges"]   (see train.py)
    # --------------------------------------------------------------
    if isinstance(batch.y, dict):
        target = batch.y.get("missing_edges") or batch.y.get("adjacency")
    else:
        target = batch.y

    # Move to the same device, ensure float, flatten to (max_nodes**2,)
    target = target.to(batch.x.device).float().view(-1)   # (max_nodes**2,)
    return target


# ----------------------------------------------------------------------
# Train one epoch
# ----------------------------------------------------------------------
def train_epoch(model, loader, loss_fn, optimizer, device, max_nodes):
    """
    One training epoch.

    Returns
    -------
    float
        Mean loss over the whole dataset (not per batch).
    """
    model.train()
    total_loss = 0.0

    # Using tqdm is optional – you can delete the wrapper if you prefer.
    for batch in tqdm(loader, desc="train", leave=False):
        batch = batch.to(device)

        optimizer.zero_grad()
        pred = model(batch)                     # (max_nodes**2,)

        target = _get_flat_target(batch, max_nodes)   # (max_nodes**2,)
        loss = loss_fn(pred, target)

        loss.backward()
        optimizer.step()

        # `batch.num_graphs` is 1 for your current DataLoader (batch_size=1),
        # but we keep the multiplication for completeness.
        total_loss += loss.item() * batch.num_graphs

    # Length of the underlying dataset, not the number of batches.
    return total_loss / len(loader.dataset)


# ----------------------------------------------------------------------
# Validation (no grads)
# ----------------------------------------------------------------------
def validate(model, loader, loss_fn, device, max_nodes):
    """
    Validation loop – identical to `train_epoch` but without weight updates.
    """
    model.eval()
    total_loss = 0.0

    with torch.no_grad():
        for batch in tqdm(loader, desc="val", leave=False):
            batch = batch.to(device)

            pred = model(batch)
            target = _get_flat_target(batch, max_nodes)
            loss = loss_fn(pred, target)

            total_loss += loss.item() * batch.num_graphs

    return total_loss / len(loader.dataset)