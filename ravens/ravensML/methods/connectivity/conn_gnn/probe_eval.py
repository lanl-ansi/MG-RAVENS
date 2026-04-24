import torch
import random
import numpy as np
from pathlib import Path
import sys, os
import re
from torch_geometric.loader import DataLoader
from torch_geometric.utils import degree
import custom_loss as cl
from methods.connectivity.conn_gnn.model import SimpleGNN, AttnGNN
from methods.connectivity.conn_gnn.data import MGConnDataset

# ======================= CONFIGURATION =======================
# Set seeds for reproducibility (matches training)
SEED = 42
random.seed(SEED)
np.random.seed(SEED)
torch.manual_seed(SEED)
if torch.cuda.is_available():
    torch.cuda.manual_seed_all(SEED)

# Project root
rML_ROOT = Path(__file__).resolve().parents[3]
if str(rML_ROOT) not in sys.path:
    sys.path.insert(0, str(rML_ROOT))

# Constants from training code
MAX_NODES = 20
ERROR_KWARGS = {"del_e_prob": 0.20}
VALIDATION_SIZE = 1000  # Fresh validation set size

# Model directory (where training code saved models)
MODEL_DIR = rML_ROOT / "methods" / "connectivity" / "conn_gnn" / "tmp" / "probe_data"

# ======================= HELPER FUNCTIONS =======================
def compute_deg_from_dataset(dataset):
    """Compute in-degree histogram tensor from a dataset"""
    max_degree = -1
    for data in dataset:
        d = degree(data.edge_index[1], num_nodes=data.num_nodes, dtype=torch.long)
        max_degree = max(max_degree, int(d.max()))
    
    deg = torch.zeros(max_degree + 1, dtype=torch.long)
    for data in dataset:
        d = degree(data.edge_index[1], num_nodes=data.num_nodes, dtype=torch.long)
        deg += torch.bincount(d, minlength=deg.numel())
    return deg

def parse_pass_id(pass_id):
    """Extract hyperparameters from Pass_ID string"""
    match = re.match(r'exp_\d+_model_(SimpleGNN|AttnGNN)_td(\d+)_tp([\d.]+)_ip(\d+)', pass_id)
    if not match:
        return None
    model_type_str, td_str, tp_str, ip_str = match.groups()
    return {
        'model_type': SimpleGNN if model_type_str == "SimpleGNN" else AttnGNN,
        'transport_distance': int(td_str),
        'test_percentage': float(tp_str),
        'inf_penalty': int(ip_str)
    }

# ======================= MAIN EXECUTION =======================
if __name__ == "__main__":
    # Initialize device
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print(f"Using device: {device}")
    
    # ==== STEP 1: Compute fixed statistics (DEG) from training set ====
    # Generate temporary training set (size=20) to compute DEG
    temp_dataset = MGConnDataset(
        root=rML_ROOT,
        size=20,
        max_nodes=MAX_NODES,
        error_kwargs=ERROR_KWARGS,
    )
    train_len = int(0.8 * len(temp_dataset))
    train_set, _ = torch.utils.data.random_split(
        temp_dataset,
        [train_len, len(temp_dataset) - train_len],
        generator=torch.Generator().manual_seed(SEED)
    )
    DEG = compute_deg_from_dataset(train_set)
    
    # ==== STEP 2: Generate fresh validation dataset (named 'validate') ====
    validate = MGConnDataset(
        root=rML_ROOT,
        size=VALIDATION_SIZE,
        max_nodes=MAX_NODES,
        error_kwargs=ERROR_KWARGS,
        split="full"
    )
    
    # Get feature dimensions from validation set
    sample = validate[0]
    NODE_FEAT_DIM = sample.x.shape[1]
    EDGE_FEAT_DIM = sample.edge_attr.shape[1]
    
    # ==== STEP 3: Evaluate all trained models ====
    # Find all saved model files
    model_files = [f for f in MODEL_DIR.glob("*_best_model.pth") if f.is_file()]
    if not model_files:
        raise FileNotFoundError(f"No model files found in {MODEL_DIR}")
    
    results = []
    
    for model_path in model_files:
        pass_id = model_path.stem.replace("_best_model", "")
        hyperparams = parse_pass_id(pass_id)
        if not hyperparams:
            print(f"Warning: Could not parse Pass_ID '{pass_id}', skipping")
            continue
        
        # Initialize model with training statistics and transport_distance
        model = hyperparams['model_type'](
            node_features=NODE_FEAT_DIM,
            edge_features=EDGE_FEAT_DIM,
            degree=DEG,
            max_nodes=MAX_NODES,
            transport_distance=hyperparams['transport_distance']
        ).to(device)
        
        # Load trained weights
        model.load_state_dict(torch.load(model_path, map_location=device))
        model.eval()
        
        # Initialize loss function with stored hyperparameters
        # Note: ignore_diagonal, K, pos_weight are fixed as per training param_grid
        loss_fn = cl.PIAdjMSELoss(
            ignore_diagonal=False,
            reduction='mean',
            K=10,
            pos_weight=10,
            inf_penalty=hyperparams['inf_penalty'],
            test_percentage=hyperparams['test_percentage']
        )
        
        # Evaluate on fresh validation dataset
        total_loss = 0.0
        num_graphs = 0
        loader = DataLoader(validate, batch_size=1, shuffle=False)
        
        with torch.no_grad():
            for data in loader:
                data = data.to(device)
                pred = model(data)
                loss = loss_fn(pred, data)
                total_loss += loss.item()
                num_graphs += 1
        
        avg_loss = total_loss / num_graphs if num_graphs > 0 else float('inf')
        
        # Store results
        results.append({
            'pass_id': pass_id,
            'model_type': hyperparams['model_type'].__name__,
            'transport_distance': hyperparams['transport_distance'],
            'inf_penalty': hyperparams['inf_penalty'],
            'test_percentage': 0,#hyperparams['test_percentage'],
            'avg_loss': avg_loss
        })
    
    # ==== STEP 4: Output clean results ====
    # Sort by validation loss (ascending)
    results.sort(key=lambda x: x['avg_loss'])
    
    print("\n" + "="*70)
    print("VALIDATION RESULTS ON FRESH DATASET")
    print("="*70)
    print(f"{'#':<4} {'Pass ID':<30} {'Model':<12} {'TD':<4} {'IP':<4} {'TP':<8} {'Loss':<10}")
    print("-"*70)
    
    for i, res in enumerate(results, 1):
        print(f"{i:<4} {res['pass_id']:<30} {res['model_type']:<12} "
              f"{res['transport_distance']:<4} {res['inf_penalty']:<4} "
              f"{res['test_percentage']:<8} {res['avg_loss']:<10.6f}")
    
    print("="*70)
    print(f"Best performing model: {results[0]['pass_id']} (Loss: {results[0]['avg_loss']:.6f})")