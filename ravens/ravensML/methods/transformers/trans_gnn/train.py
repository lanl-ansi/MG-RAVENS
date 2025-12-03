import torch
import torch.nn as nn
import torch.optim as optim
from torch_geometric.loader import DataLoader
import matplotlib.pyplot as plt

from data import MGTransformerDataset
from model import SimpleGNN
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
    split="train",
    size=10000,
    error_kwargs={"deletion_prob": 0.01, 
                  "occurrence_prob": 0.35,
                  "mult_mean": 1,
                  "mult_var": 1,
                  "add_mean": 0,
                  "add_var": 1,},
)


# split
train_len = int(0.8 * len(dataset))
val_len   = len(dataset) - train_len
train_set, val_set = torch.utils.data.random_split(dataset, [train_len, val_len])

# data loaders
batch_size = 16
train_loader = DataLoader(train_set, batch_size=batch_size, shuffle=True)
val_loader   = DataLoader(val_set,   batch_size=batch_size, shuffle=False)

# input / output dimensions
sample = dataset[0]
node_feat_dim = sample.x.shape[1]  

# model
model = SimpleGNN(in_channels=node_feat_dim,
                    out_channels=node_feat_dim).to(device)
print(f"Model initialized → input dim {node_feat_dim}")

# Training Settings
loss_fn = nn.MSELoss()
optimizer = optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-5)
scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode='min', factor=0.5, patience=5)
epochs = 30

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
        print("  → saved new best model")

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
    for j in range(5):
        sample = dataset[j].to(device)           # single graph
        pred   = model(sample)                    # [num_nodes, feat_dim]

        print("\n--- First 3 nodes (prediction vs ground‑truth) ---")
        for i in range(min(3, pred.shape[0])):
            print(f"\nNode {i}:")
            print("  pred :", pred[i, :5].cpu().numpy())
            print("  true :", sample.y["x"][i, :5].cpu().numpy())

        test_mse = loss_fn(pred, sample.y["x"])
        print(f"\nTest MSE on this graph: {test_mse.item():.6f}")

print("\nTraining finished!")