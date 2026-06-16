import torch
import torch.nn as nn
import torch.nn.functional as F
from torch_geometric.nn import PNAConv, BatchNorm


class SimpleGNN(nn.Module):
    """
    Graph-Neural-Network that predicts, for every possible edge (i, j),
    a categorical distribution over the five classes  [-1, 0, 1, 2, 3].

    Returns
    -------
    probs : Tensor of shape (max_nodes, max_nodes, 5)
            probs[i, j, c] = P(class == class_list[c] | graph)
            The three last dimensions sum to 1 for each (i, j).
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
        #basic parameters
        self.degree = degree
        self.max_nodes = int(max_nodes)
        self.num_classes = 5                     # [-1, 0, 1, 2, 3]
        aggregators = ["mean", "min", "max", "std"]
        scalers = ["identity", "amplification", "attenuation"]


        # PNA graph convolutions
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


        # Edge-wise MLP
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
            nn.Linear(64, self.max_nodes * self.max_nodes * self.num_classes),
        )

    def forward(self, data):
        """
        Parameters
        ----------
        data : torch_geometric.data.Data
               Must contain ``x`` (node features), ``edge_index`` and ``edge_attr``.

        Returns
        -------
        probs : Tensor (max_nodes, max_nodes, 5)
                Probability distribution per (i, j) pair.
        """
        x, edge_index, edge_attr = data.x, data.edge_index, data.edge_attr

        #  Graph convolutions 
        for conv, bn in zip(self.convs, self.norms):
            x = F.relu(bn(conv(x, edge_index, edge_attr)))

        #  Edge representation 
        src = x[edge_index[0]]
        dst = x[edge_index[1]]
        edge_rep = torch.cat([src, dst, edge_attr], dim=-1)      # (E, 2*F + edge_features)

        #  Deep MLP (E, max_nodes^2 * C) 
        edge_logits = self.edge_mlp(edge_rep)                    # (E, max_nodes*max_nodes*C)

        #  Aggregate over all edges 
        graph_logits = edge_logits.mean(dim=0)                    # (max_nodes*max_nodes*C,)

        #  Reshape to (max_nodes, max_nodes, C) ---
        logits = graph_logits.view(self.max_nodes,
                                   self.max_nodes,
                                   self.num_classes)       # (N, N, C)

        # enforce symmetry 
        logits = (logits + logits.transpose(0, 1)) / 2

        # Convert to probabilities 
        probs = F.softmax(logits, dim=-1) 

        return probs