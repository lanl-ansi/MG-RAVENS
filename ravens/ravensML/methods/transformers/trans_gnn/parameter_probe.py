import torch
import torch.nn as nn
import torch.optim as optim
from torch_geometric.loader import DataLoader
from torch_geometric.utils import degree
import matplotlib.pyplot as plt
import random
import pprint
import itertools
from mgr_helpers import unpack_edge

from pathlib import Path
import sys, os
rML_ROOT = Path(__file__).resolve().parents[3]

from data import MGTransformerDataset
from model import SimpleGNN, AttnGNN
from training_tools import train_epoch, validate




device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
print(f"Using device: {device}")

# reproducibility
torch.manual_seed(42)


def run_training_pass(Pass_ID, train_loader, val_loader,  # Base Parameters
                      MODEL_TYPE, NFD, EFD, DEG, TD,      # Model Spec
                      NP, IP, TP,                    # Loss Spec
                      LR, WD,                             # optimizer
                      M, F, P,                            # scheduler
                      E,                                  # epochs
                      ):
    # model
    model = MODEL_TYPE(                 
        node_features=NFD,
        edge_features=EFD,
        degree=DEG,
        transport_distance=TD
    ).to(device)

    print(f"Model initialized -> input dim {(NFD, EFD)} output dim {(EFD)}")

    # Training Settings
    import custom_loss as cl
    loss_fn = cl.PI_WMSE_Loss(3, neg_penalty=NP, inf_penalty=IP, test_percentage=TP)
    optimizer = optim.Adam(model.parameters(), lr=LR, weight_decay=WD)
    scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode=M, factor=F, patience=P)
    epochs = E

    # training parameters
    best_val = float('inf')
    train_losses, val_losses = [], []

    for epoch in range(1, epochs + 1):
        tr_loss = train_epoch(model, train_loader, loss_fn, optimizer, device)
        va_loss = validate(model, val_loader, loss_fn, device)

        train_losses.append(tr_loss)
        val_losses.append(va_loss)

        scheduler.step(va_loss)

        print(f"Epoch {epoch:02d}/{epochs} | "
                f"Train MSE: {tr_loss:.6f} | Val MSE: {va_loss:.6f}")

        # checkpoint
        if va_loss < best_val:
            best_val = va_loss
            torch.save(model.state_dict(), rML_ROOT/f"methods/transformers/trans_gnn/tmp/probe_data/{Pass_ID}_best_model.pth")
            print(f"  -> saved new best model for {Pass_ID}")

    # Plot losses
    plt.figure(figsize=(10, 5))
    plt.plot(train_losses, label="train")
    plt.plot(val_losses, label="val")
    plt.xlabel("epoch")
    plt.ylabel("MSE")
    plt.legend()
    plt.title(f"Training / Validation loss for {Pass_ID}")
    plt.tight_layout()
    plt.savefig(rML_ROOT/f"methods/transformers/trans_gnn/tmp/probe_data/{Pass_ID}_loss_plot.png")
    plt.close()

    # Quick sanity check on a single graph
    model.eval()
    with torch.no_grad():
        sample = dataset[random.randint(0, len(dataset)-1)].to(device)     
        pred = model(sample)

        print(f"Sample check for {Pass_ID}:")
        print("Input:")
        pprint.pprint(unpack_edge(sample["edge_attr"][0], 3))
        print("Predicted:")
        pprint.pprint(unpack_edge(pred[0], 3))
        print("True:")
        pprint.pprint(unpack_edge(sample.y["edge_attr"][0], 3))
        test_mse = loss_fn(pred, sample)
        print(f"\nTest MSE on this graph: {test_mse.item():.6f}")

    print(f"\nTraining finished for {Pass_ID}!")
    
    return {
        'pass_id': Pass_ID,
        'final_train_loss': train_losses[-1],
        'final_val_loss': val_losses[-1],
        'best_val_loss': best_val,
        'model_type': MODEL_TYPE.__name__,
        'hyperparams': {
            'neg_penalty': NP,
            'inf_penalty': IP,
            'test_percentage': TP,
            'lr': LR,
            'weight_decay': WD,
            'transport_distance':TD
        }
    }


if __name__ == "__main__":
    # Setup Dataset
    dataset = MGTransformerDataset(
        root=rML_ROOT,
        size=20000,
        error_kwargs={"deletion_prob": 0.01, 
                    "occurrence_prob": 0.55,
                    "mult_mean": 1,
                    "mult_var": 2.25,
                    "add_mean": 0,
                    "add_var": 2.25,},
    )

    # split
    train_len = int(0.8 * len(dataset))
    val_len = len(dataset) - train_len
    train_set, val_set = torch.utils.data.random_split(dataset, [train_len, val_len])

    # data loaders
    batch_size = 1  
    train_loader = DataLoader(train_set, batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(val_set, batch_size=batch_size, shuffle=False)

    # input / output dimensions 
    sample = dataset[0]
    node_feat_dim = sample.x.shape[1]
    edge_feat_dim = sample.edge_attr.shape[1]
    output_feat_dim = sample.y["edge_attr"].shape[1]

    # Compute the maximum in-degree in the training data.
    max_degree = -1
    for data in train_set:
        d = degree(data.edge_index[1], num_nodes=data.num_nodes, dtype=torch.long)
        max_degree = max(max_degree, int(d.max()))

    # Compute the in-degree histogram tensor
    deg = torch.zeros(max_degree + 1, dtype=torch.long)
    for data in train_set:
        d = degree(data.edge_index[1], num_nodes=data.num_nodes, dtype=torch.long)
        deg += torch.bincount(d, minlength=deg.numel())

    # Define hyperparameter grid
    # param_grid = {
    #     'model_type': [SimpleGNN, AttnGNN],
    #     'neg_penalty': [10],
    #     'inf_penalty': [1, 5],
    #     'test_percentage': [0, .001],
    #     'lr': [1e-3],
    #     'weight_decay': [1e-5],
    #     'transport_distance': [0,7,14]
    # }
    param_grid = {
        'model_type': [SimpleGNN],
        'neg_penalty': [10],
        'inf_penalty': [5],
        'test_percentage': [0, 1],
        'lr': [1e-3],
        'weight_decay': [1e-5],
        'transport_distance': [7,14]
    }
    EPOCHS = 100

    # Generate all combinations of parameters
    # For a smaller experiment, you may want to select fewer parameters or combinations
    param_combinations = list(itertools.product(
        param_grid['model_type'],
        param_grid['neg_penalty'],
        param_grid['inf_penalty'],
        param_grid['test_percentage'],
        param_grid['lr'],
        param_grid['weight_decay'],
        param_grid['transport_distance']
    ))
    
    results = []
    
    # Run experiments
    for i, params in enumerate(param_combinations):
        model_type, neg_penalty, inf_penalty, test_percentage, lr, weight_decay, transport_distance = params
        
        pass_id = f"exp_{i}_model_{model_type.__name__}_td{transport_distance}_tp{test_percentage}_ip{inf_penalty}"
        print(f"\n\n{'='*80}\nStarting experiment {pass_id}\n{'='*80}\n")
        
        result = run_training_pass(
            pass_id,
            train_loader, val_loader,
            model_type, node_feat_dim, edge_feat_dim, deg, transport_distance,
            neg_penalty, inf_penalty, test_percentage,
            lr, weight_decay,
            'min', 0.5, 5,
            EPOCHS
        )
        results.append(result)
    
    # Print summary of results
    print("\n\n" + "="*80)
    print("EXPERIMENT RESULTS SUMMARY")
    print("="*80)
    
    # Sort by validation loss
    results.sort(key=lambda x: x['best_val_loss'])
    
    for i, result in enumerate(results):
        print(f"\n{i+1}. Pass ID: {result['pass_id']}")
        print(f"   Model: {result['model_type']}")
        print(f"   Best Val Loss: {result['best_val_loss']:.6f}")
        print(f"   Final Train/Val: {result['final_train_loss']:.6f} / {result['final_val_loss']:.6f}")
        print(f"   Hyperparams: NP={result['hyperparams']['neg_penalty']}, IP={result['hyperparams']['inf_penalty']}, "
              f"TP={result['hyperparams']['test_percentage']}, "
              f"LR={result['hyperparams']['lr']}, WD={result['hyperparams']['weight_decay']},  TD={result['hyperparams']['transport_distance']}")
