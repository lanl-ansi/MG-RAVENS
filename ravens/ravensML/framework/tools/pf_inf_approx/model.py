# --------------------------------------------------------------
#  SimpleGNN  –  edge‑wise MLP returns a 2‑D matrix with values in [0, 1]
# --------------------------------------------------------------
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch_geometric.nn import BatchNorm, PNAConv


class SimpleGNN(nn.Module):
    """
    Parameters
    ----------
    node_features : int
        Dimensionality of node feature vectors.
    edge_features : int
        Dimensionality of edge feature vectors.
    degree : int
        Maximum node degree in the training graphs (required by PNA).
    max_nodes : int
        Upper bound on the number of nodes a graph can have.
    transport_distance : int, default 5
        Number of successive PNA message‑passing steps.
    """

    def __init__(
        self,
        node_features: int,
        edge_features: int,
        degree,
        max_nodes,
        transport_distance: int = 5,
    ):
        super().__init__()

        # ------------------------------------------------------------------
        # Cast to plain Python ints – safeguards against tensors/np scalars.
        # ------------------------------------------------------------------
        self.degree = degree
        self.max_nodes = int(max_nodes)

        aggregators = ["mean", "min", "max", "std"]
        scalers = ["identity", "amplification", "attenuation"]

        # ------------------------------------------------------------------
        # PNA graph convolutions (unchanged)
        # ------------------------------------------------------------------
        self.convs = nn.ModuleList(
            [
                PNAConv(
                    node_features,
                    node_features,
                    aggregators=aggregators,
                    scalers=scalers,
                    deg=self.degree,
                    edge_dim=edge_features,
                    towers=5,
                    pre_layers=1,
                    post_layers=1,
                    divide_input=False,
                )
                for _ in range(transport_distance)
            ]
        )
        self.norms = nn.ModuleList(
            [BatchNorm(node_features) for _ in range(transport_distance)]
        )

        # ------------------------------------------------------------------
        # Edge‑wise MLP – final head outputs `max_nodes ** 2` logits.
        # ------------------------------------------------------------------
        self.edge_mlp = nn.Sequential(
            nn.Linear(node_features * 2 + edge_features, 64),
            nn.ReLU(),
            nn.Linear(64, 128),
            nn.Dropout(0.21),
            nn.ReLU(),
            nn.Linear(128, 128),
            nn.Dropout(0.20),
            nn.ReLU(),
            nn.Linear(128, 128),
            nn.Dropout(0.19),
            nn.ReLU(),
            nn.Linear(128, 512),
            nn.Dropout(0.18),
            nn.ReLU(),
            nn.Linear(512, 128),
            nn.Dropout(0.17),
            nn.ReLU(),
            nn.Linear(128, 128),
            nn.Dropout(0.17),
            nn.ReLU(),
            nn.Linear(128, 128),
            nn.Dropout(0.17),
            nn.ReLU(),
            nn.Linear(128, 128),
            nn.Dropout(0.16),
            nn.ReLU(),
            nn.Linear(128, 64),
            nn.Dropout(0.15),
            nn.ReLU(),
            nn.Linear(64, 1),
        )

    # ------------------------------------------------------------------
    # Forward pass
    # ------------------------------------------------------------------
    def forward(self, data):
        """
        Returns
        -------
        adj : Tensor of shape (max_nodes, max_nodes, params)
              Values are squeezed into [0, 1] (no soft‑max).
        """
        x, edge_index, edge_attr = data.x, data.edge_index, data.edge_attr

        # --------------------------------------------------------------
        # Graph convolutions
        # --------------------------------------------------------------
        for conv, bn in zip(self.convs, self.norms):
            x = F.relu(bn(conv(x, edge_index, edge_attr)))

        # --------------------------------------------------------------
        # Edge representation: concat(src_node, dst_node, edge_attr)
        # --------------------------------------------------------------
        src = x[edge_index[0]]
        dst = x[edge_index[1]]
        edge_rep = torch.cat([src, dst, edge_attr], dim=-1)   # (E, 2*F + edge_features)

        # --------------------------------------------------------------
        # Deep MLP → (E, max_nodes²) logits
        # --------------------------------------------------------------
        edge_logits = self.edge_mlp(edge_rep)                # (E, max_nodes²)

        # --------------------------------------------------------------
        # Aggregate over edges → a single value per graph.
        # --------------------------------------------------------------
        adj = edge_logits.mean(dim=0)

        return adj