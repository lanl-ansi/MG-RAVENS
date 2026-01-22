import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.nn import Embedding, Linear, ModuleList, ReLU, Sequential
from torch_geometric.nn import BatchNorm, PNAConv, global_add_pool


class SimpleGNN(nn.Module):
    def __init__(self, node_features, edge_features, degree, transport_distance=5):
        super().__init__()
        aggregators = ['mean', 'min', 'max', 'std']
        scalers = ['identity', 'amplification', 'attenuation']

        self.convs = nn.ModuleList([
            PNAConv(node_features, node_features,
                    aggregators=aggregators,
                    scalers=scalers,
                    deg=degree,
                    edge_dim=edge_features,
                    towers=5, pre_layers=1, post_layers=1,
                    divide_input=False) for _ in range(transport_distance)
        ])
        self.norms = nn.ModuleList([BatchNorm(node_features) for _ in range(transport_distance)])

        # Edge‑wise MLP (takes node embeddings + edge_attr as input)
        self.edge_mlp = nn.Sequential(
            nn.Linear(node_features * 2 + edge_features, 64),
            nn.ReLU(),
            nn.Linear(64, 128), # 64 --> 128
            nn.Dropout(0.1),
            nn.ReLU(),
            nn.Linear(128, 128), # 128 --> 128
            nn.Dropout(0.1),
            nn.ReLU(),
            nn.Linear(128, 128), # 128 --> 128
            nn.Dropout(0.1),
            nn.ReLU(),
            nn.Linear(128, 128), # 128 --> 128
            nn.Dropout(0.1),
            nn.ReLU(),
            nn.Linear(128, 64), # 128 --> 64
            nn.Dropout(0.1),
            nn.ReLU(),
            nn.Linear(64, 40)          # output dim = 40
        )

    def forward(self, data):
        x, edge_index, edge_attr = data.x, data.edge_index, data.edge_attr

        for conv, bn in zip(self.convs, self.norms):
            x = F.relu(bn(conv(x, edge_index, edge_attr)))

        # Build edge representations: concatenate source/target node embeddings + edge_attr
        src = x[edge_index[0]]
        dst = x[edge_index[1]]
        edge_rep = torch.cat([src, dst, edge_attr], dim=-1)   # (num_edges, 2*F + edge_features)

        edge_pred = self.edge_mlp(edge_rep)                  # (num_edges, 40)
        return edge_pred
