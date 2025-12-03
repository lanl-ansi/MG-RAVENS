import torch
import torch.nn as nn
import torch.nn.functional as F
from torch_geometric.nn import GCNConv

class GCNBlock(nn.Module):
    def __init__(self, in_channels, out_channels):
        super(GCNBlock, self).__init__()
        self.conv = GCNConv(in_channels, out_channels)
        self.bn = nn.BatchNorm1d(out_channels)
        self.relu = nn.ReLU()
        
    def forward(self, x, edge_index):
        x = self.conv(x, edge_index)
        x = self.bn(x)
        x = self.relu(x)
        return x

class SimpleGNN(torch.nn.Module):
    def __init__(self, in_channels, out_channels):
        """
        A basic Graph Neural Network for graph classification.
        """
        super(SimpleGNN, self).__init__()
        
        # Graph convolution blocks
        self.block1 = GCNBlock(in_channels, 64)
        self.block2 = GCNBlock(64, 128)
        self.block3 = GCNBlock(128, 512)
        self.block4 = GCNBlock(512, 1024)
        
        # Final classification head
        self.generator = nn.Sequential(
            nn.Dropout(0.25),
            nn.Linear(1024, 512),
            nn.ReLU(),
            nn.Linear(512, 128),
            nn.ReLU(),
            nn.Dropout(0.25),
            nn.Linear(128, out_channels)
        )
    
    def forward(self, data):
        x, edge_index = data.x, data.edge_index
    
        
        # Process the graph structure
        x = self.block1(x, edge_index)
        x = self.block2(x, edge_index)
        x = self.block3(x, edge_index)
        x = self.block4(x, edge_index)
        
        # Generate output
        x = self.generator(x)
        
        return x
