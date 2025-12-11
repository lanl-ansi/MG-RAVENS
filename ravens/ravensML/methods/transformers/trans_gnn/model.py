import torch
import torch.nn as nn
from torch_geometric.nn import GCNConv

class GCNBlock(nn.Module):
    """
    A Graph Convolutional Network block that combines node and edge attributes.

    Parameters
    ----------
    in_channels : int
        Number of input node features.
    edge_in_channels : int
        Number of input edge features.
    out_channels : int
        Number of output node features after the block.
    """

    def __init__(self, in_channels: int, edge_in_channels: int, out_channels: int):
        super().__init__()

        self.linear = nn.Linear(in_channels + edge_in_channels, out_channels)
        self.conv = GCNConv(out_channels, out_channels)
        self.bn = nn.BatchNorm1d(out_channels)
        self.relu = nn.ReLU(inplace=True)

    def forward(self, node_attr: torch.Tensor,
                edge_index: torch.Tensor,
                edge_attr: torch.Tensor) -> torch.Tensor:

        num_nodes = node_attr.size(0)

        agg_edge = torch.zeros(num_nodes, edge_attr.size(1), device=node_attr.device)
        agg_cnt = torch.zeros(num_nodes, 1, device=node_attr.device)

        target = edge_index[1]
        agg_edge.index_add_(0, target, edge_attr)
        agg_cnt.index_add_(0, target, torch.ones_like(target, dtype=torch.float).unsqueeze(1))
        agg_edge = agg_edge / (agg_cnt + 1e-12)
        fused = torch.cat([node_attr, agg_edge], dim=1)   

        x = self.linear(fused)                          

        x = self.conv(x, edge_index)                         

        x = self.bn(x)
        x = self.relu(x)

        return x

class SimpleGNN(torch.nn.Module):
    def __init__(self, node_in_channels, edge_in_channels, edge_out_channels):
        """
        A basic Graph Neural Network for edge attribute prediction.
        """
        super(SimpleGNN, self).__init__()
        
        # Graph convolution blocks for processing node features
        self.block1 = GCNBlock(node_in_channels,edge_in_channels, 64)
        self.block2 = GCNBlock(64,edge_in_channels, 128)
        self.block3 = GCNBlock(128,edge_in_channels, 512)
        self.block4 = GCNBlock(512,edge_in_channels, 512)
        self.block5 = GCNBlock(512,edge_in_channels, 1024)
        
        # Final edge attribute prediction head
        # Takes concatenated source/target node embeddings + original edge attributes
        self.generator = nn.Sequential(
            nn.Dropout(0.20),
            nn.Linear(2*1024 + edge_in_channels, 512),  # 2×node_dim + edge_attr_dim
            nn.ReLU(),
            nn.Dropout(0.20),
            nn.Linear(512, 128),
            nn.ReLU(),
            nn.Dropout(0.20),
            nn.Linear(128, edge_out_channels)
        )
    
    def forward(self, data):
        node_attr, edge_index, edge_attr = data.x, data.edge_index, data.edge_attr
        
        # Process node features through GCN blocks
        x1 = self.block1(node_attr, edge_index, edge_attr)
        x2 = self.block2(x1, edge_index, edge_attr) 
        x3 = self.block3(x2, edge_index, edge_attr) 
        x4 = self.block4(x3, edge_index, edge_attr)  
        x4 = self.block4(x4, edge_index, edge_attr)
        x4 = self.block4(x4, edge_index, edge_attr)  
        x5 = self.block5(x4, edge_index, edge_attr)  
        
        # For each edge, get source and target node features
        src, dst = edge_index
        src_features = x5[src]  # Source node embeddings
        dst_features = x5[dst]  # Target node embeddings
        
        # Concatenate source features, target features, and edge attributes
        edge_features = torch.cat([src_features, dst_features, edge_attr], dim=1)
        
        # Generate edge attribute predictions
        edge_predictions = self.generator(edge_features)
        
        return edge_predictions
