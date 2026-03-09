import torch
import torch.nn as nn
import torch.optim as optim
from torch_geometric.loader import DataLoader
from torch_geometric.utils import degree
import matplotlib.pyplot as plt
import random
import pprint
from mgr_helpers import unpack_edge

from data import MGTransformerDataset
from model import SimpleGNN, AttnGNN
from training_tools import train_epoch, validate

device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
print(f"Using device: {device}")

# reproducibility
torch.manual_seed(42)

# -------------------------
#   Dataset
# -------------------------
dataset = MGTransformerDataset(
    root="/Users/oreed/Desktop/LANL-ANSI/MG-RAVENS/ravens/ravensML",
    size=80000,
    error_kwargs={"deletion_prob": 0.01, 
                  "occurrence_prob": 0.55,
                  "mult_mean": 1,
                  "mult_var": 2.25,
                  "add_mean": 0,
                  "add_var": 2.25,},
)


# split
train_len = int(0.8 * len(dataset))
val_len   = len(dataset) - train_len
train_set, val_set = torch.utils.data.random_split(dataset, [train_len, val_len])

# data loaders
batch_size = 1 #TODO: cannot properly handle larger batches 
train_loader = DataLoader(train_set, batch_size=batch_size, shuffle=True)
val_loader   = DataLoader(val_set,   batch_size=batch_size, shuffle=False)

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


# model
model = SimpleGNN(                 
    node_features=node_feat_dim,
    edge_features=edge_feat_dim,
    degree=deg,
    transport_distance=10
).to(device)

# model = AttnGNN(
#     node_features=node_feat_dim,
#     edge_features=edge_feat_dim,
#     degree=deg,
#     transport_distance=0).to(device)

print(f"Model initialized -> input dim {(node_feat_dim,edge_feat_dim)} output dim {(edge_feat_dim)}")

# Training Settings
# loss_fn = nn.MSELoss()
import custom_loss as cl
# loss_fn = cl.WeightedMSELoss(3,penalty_strength=5)
loss_fn = cl.PI_WMSE_Loss(3,neg_penalty=5,inf_penalty=5,test_percentage=0,branch_inf_mode=False)
optimizer = optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-5)
scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode='min', factor=0.5, patience=5)
epochs = 120

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
        torch.save(model.state_dict(), "ravens/ravensML/methods/transformers/trans_gnn/tmp/best_model.pth")
        print("  -> saved new best model")

# -------------------------
#   Plot losses
# -------------------------
plt.figure(figsize=(10, 5))
plt.plot(train_losses, label="train")
plt.plot(val_losses, label="val")
plt.xlabel("epoch")
plt.ylabel("MSE")
plt.legend()
plt.title("Training / Validation loss")
plt.tight_layout()
plt.savefig("ravens/ravensML/methods/transformers/trans_gnn/tmp/loss_plot.png")
plt.close()

# -------------------------
#   Quick sanity check on a single graph
# -------------------------
model.eval()
with torch.no_grad():
    sample = dataset[random.randint(0,len(dataset)-1)].to(device)     
    pred   = model(sample)

    print("Input:")
    pprint.pprint(unpack_edge(sample["edge_attr"][0],3))
    print("Predicted:")
    pprint.pprint(unpack_edge(pred[0],3))
    print("True:")
    pprint.pprint(unpack_edge(sample.y["edge_attr"][0],3))
    test_mse = loss_fn(pred, sample)
    print(f"\nTest MSE on this graph: {test_mse.item():.6f}")

print("\nTraining finished!")