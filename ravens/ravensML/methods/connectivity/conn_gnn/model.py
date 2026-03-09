# --------------------------------------------------------------
#  SimpleGNN  –  edge‑wise MLP returns a 2‑D soft‑maxed matrix
# --------------------------------------------------------------
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.nn import Linear, ReLU, Sequential
from torch_geometric.nn import BatchNorm, PNAConv, global_add_pool


class SimpleGNN(nn.Module):
    def __init__(self, node_features, edge_features, degree, max_nodes, transport_distance=5):
        super().__init__()
        aggregators = ['mean', 'min', 'max', 'std']
        scalers = ['identity', 'amplification', 'attenuation']

        # ------------------------------------------------------------------
        # PNA graph convolutions (unchanged)
        # ------------------------------------------------------------------
        self.convs = nn.ModuleList([
            PNAConv(node_features,
                    node_features,
                    aggregators=aggregators,
                    scalers=scalers,
                    deg=degree,
                    edge_dim=edge_features,
                    towers=5, pre_layers=1, post_layers=1,
                    divide_input=False) for _ in range(transport_distance)
        ])
        self.norms = nn.ModuleList([BatchNorm(node_features)
                                   for _ in range(transport_distance)])

        # ------------------------------------------------------------------
        # Edge‑wise MLP – keep the deep stack unchanged, only the final head
        # outputs `max_nodes**2` raw scores (no activation).  Soft‑max and reshape
        # are applied later in `forward()`.
        # ------------------------------------------------------------------
        self.edge_mlp = nn.Sequential(
            nn.Linear(node_features * 2 + edge_features, 64),
            nn.ReLU(),
            nn.Linear(64, 128),          # 64 → 128
            nn.Dropout(0.21),
            nn.ReLU(),
            nn.Linear(128, 128),         # 128 → 128
            nn.Dropout(0.20),
            nn.ReLU(),
            nn.Linear(128, 512),         # 128 → 512
            nn.Dropout(0.19),
            nn.ReLU(),
            nn.Linear(512, 128),         # 512 → 128
            nn.Dropout(0.18),
            nn.ReLU(),
            nn.Linear(128, 128),         # 128 → 128
            nn.Dropout(0.17),
            nn.ReLU(),
            nn.Linear(128, 128),         # 128 → 128
            nn.Dropout(0.17),
            nn.ReLU(),
            nn.Linear(128, 128),         # 128 → 128
            nn.Dropout(0.17),
            nn.ReLU(),
            nn.Linear(128, 128),         # 128 → 128
            nn.Dropout(0.16),
            nn.ReLU(),
            nn.Linear(128, 64),          # 128 → 64
            nn.Dropout(0.15),
            nn.ReLU(),
            # final projection – raw scores for a square matrix
            nn.Linear(64, max_nodes * max_nodes)  
        )
        # row‑wise soft‑max (each row of the matrix will sum to 1)
        self.row_softmax = nn.Softmax(dim=-1)

    def forward(self, data):
        """
        Returns
        -------
        adj : Tensor of shape (B, degree, degree)
              Row‑softmaxed adjacency matrix for each graph in the batch.
        """
        x, edge_index, edge_attr = data.x, data.edge_index, data.edge_attr

        # ------------------------------------------------------------------
        # Graph convolutions
        # ------------------------------------------------------------------
        for conv, bn in zip(self.convs, self.norms):
            x = F.relu(bn(conv(x, edge_index, edge_attr)))

        # ------------------------------------------------------------------
        # Build edge representations: concat(src_node, dst_node, edge_attr)
        # ------------------------------------------------------------------
        src = x[edge_index[0]]
        dst = x[edge_index[1]]
        edge_rep = torch.cat([src, dst, edge_attr], dim=-1)      # (E, 2*F + edge_features)

        # ------------------------------------------------------------------
        # Pass through deep MLP → (E, degree**2) logits
        # ------------------------------------------------------------------
        logits = self.edge_mlp(edge_rep)

        # ------------------------------------------------------------------
        # Reshape to a square matrix per edge (or per graph if you batch them)
        # ------------------------------------------------------------------
        B = logits.size(0)                     # number of edge samples (or batch size)
        logits = logits.view(B, self.convs[0].deg, self.convs[0].deg)

        # ------------------------------------------------------------------
        # Row‑wise soft‑max
        # ------------------------------------------------------------------
        adj = self.row_softmax(logits)         # shape (B, degree, degree)

        # optional: make symmetric if you need an undirected adjacency matrix
        # adj = (adj + adj.transpose(1, 2)) / 2
        # adj = self.row_softmax(adj)

        return adj

class EdgeAttentionModule(nn.Module):
    def __init__(self, node_dim, edge_dim, hidden_dim, num_heads=4, dropout=0.1):
        super(EdgeAttentionModule, self).__init__()

        # Initial embedding of concatenated features for edge processing
        self.input_proj = nn.Linear(node_dim * 2 + edge_dim, hidden_dim)
        
        # Multi-head self-attention for edge representations
        self.self_attention = nn.MultiheadAttention(
            embed_dim=hidden_dim,
            num_heads=num_heads,
            dropout=dropout,
            batch_first=True
        )
        
        # Normalization layers
        self.norm1 = nn.LayerNorm(hidden_dim)
        self.norm2 = nn.LayerNorm(hidden_dim)
        
        # Feed-forward network for transformation
        self.ffn = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim * 2),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim * 2, hidden_dim)
        )
        
        # Output projection for edge features
        self.edge_output = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim),
            nn.Dropout(dropout),
            nn.ReLU(),
            nn.LayerNorm(hidden_dim),
            
            nn.Linear(hidden_dim, hidden_dim),
            nn.Dropout(dropout),
            nn.ReLU(),
            nn.LayerNorm(hidden_dim),
            
            nn.Linear(hidden_dim, edge_dim)  # Project back to original edge dimension
        )
        
        # Node feature update components
        self.node_update = nn.Linear(hidden_dim + node_dim, node_dim)
        
    def forward(self, x, edge_index, edge_attr):
        # Build initial edge representations by concatenating source, target, and edge features
        src_nodes = x[edge_index[0]]
        dst_nodes = x[edge_index[1]]
        edge_rep = torch.cat([src_nodes, dst_nodes, edge_attr], dim=-1)
        
        # Project to hidden dimension
        edge_rep = self.input_proj(edge_rep)
        edge_rep = F.relu(edge_rep)
        
        # Self-attention over edge representations
        batch_edge_rep = edge_rep.unsqueeze(0)  # [1, num_edges, hidden_dim]
        
        # Apply self-attention
        attn_out, _ = self.self_attention(batch_edge_rep, batch_edge_rep, batch_edge_rep)
        attn_out = attn_out.squeeze(0)  # [num_edges, hidden_dim]
        
        # Residual connection and normalization
        edge_rep = self.norm1(edge_rep + attn_out)
        
        # Feed-forward network
        ffn_out = self.ffn(edge_rep)
        edge_rep = self.norm2(edge_rep + ffn_out)
        
        # Process edge representations back to original dimension
        updated_edge_attr = self.edge_output(edge_rep)
        
        # Update node features using aggregated edge representations
        # Aggregate edge information for each node
        updated_x = x.clone()
        
        # For each node, aggregate information from its edges
        for i in range(edge_index.size(1)):
            source_idx = edge_index[0, i]
            edge_info = edge_rep[i]
            
            # Combine current node features with edge representation
            node_edge_combined = torch.cat([updated_x[source_idx], edge_info], dim=0)
            
            # Update node features
            node_update = self.node_update(node_edge_combined)
            updated_x[source_idx] = node_update
            
        return updated_x, edge_index, updated_edge_attr 

# --------------------------------------------------------------
#  AttnGNN 
# --------------------------------------------------------------
class AttnGNN(nn.Module):
    def __init__(self, node_features, edge_features, degree, max_nodes, transport_distance=5):
        super().__init__()
        aggregators = ['mean', 'min', 'max', 'std']
        scalers = ['identity', 'amplification', 'attenuation']

        # ------------------------------------------------------------------
        # Edge‑attention module (unchanged)
        # ------------------------------------------------------------------
        self.edge_attention = EdgeAttentionModule(
            node_dim=node_features,
            edge_dim=edge_features,
            hidden_dim=128 * 2,
            num_heads=8,
            dropout=0
        )

        # ------------------------------------------------------------------
        # PNA convolutions (unchanged)
        # ------------------------------------------------------------------
        self.convs = nn.ModuleList([
            PNAConv(node_features,
                    node_features,
                    aggregators=aggregators,
                    scalers=scalers,
                    deg=degree,
                    edge_dim=edge_features,
                    towers=5, pre_layers=1, post_layers=1,
                    divide_input=False) for _ in range(transport_distance)
        ])
        self.norms = nn.ModuleList([BatchNorm(node_features)
                                   for _ in range(transport_distance)])

        # ------------------------------------------------------------------
        # Edge‑wise MLP – deep stack unchanged, final head outputs max_nodes**2 logits
        # ------------------------------------------------------------------
        self.edge_mlp = nn.Sequential(
            nn.Linear(node_features * 2 + edge_features, 64),
            nn.ReLU(),
            nn.Linear(64, 128),
            nn.Dropout(0.20),
            nn.ReLU(),
            nn.Linear(128, 128),
            nn.Dropout(0.20),
            nn.ReLU(),
            nn.Linear(128, 128),
            nn.Dropout(0.20),
            nn.ReLU(),
            nn.Linear(128, 128),
            nn.Dropout(0.20),
            nn.ReLU(),
            nn.Linear(128, 64),
            nn.Dropout(0.20),
            nn.ReLU(),
            # final projection – raw scores for a square matrix
            nn.Linear(64, max_nodes * max_nodes)   # no activation here
        )
        self.row_softmax = nn.Softmax(dim=-1)   # row‑wise soft‑max

    def forward(self, data):
        """
        Returns a soft‑maxed adjacency matrix of shape (B, degree, degree).
        """
        x, edge_index, edge_attr = data.x, data.edge_index, data.edge_attr

        # ------------------------------------------------------------------
        # Edge‑attention preprocessing
        # ------------------------------------------------------------------
        x, edge_index, edge_attr = self.edge_attention(x, edge_index, edge_attr)

        # ------------------------------------------------------------------
        # Graph convolutions
        # ------------------------------------------------------------------
        for conv, bn in zip(self.convs, self.norms):
            x = F.relu(bn(conv(x, edge_index, edge_attr)))

        # ------------------------------------------------------------------
        # Build edge representations
        # ------------------------------------------------------------------
        src = x[edge_index[0]]
        dst = x[edge_index[1]]
        edge_rep = torch.cat([src, dst, edge_attr], dim=-1)

        # ------------------------------------------------------------------
        # Pass through deep MLP → (E, degree**2) logits
        # ------------------------------------------------------------------
        logits = self.edge_mlp(edge_rep)

        # ------------------------------------------------------------------
        # Reshape + row‑softmax
        # ------------------------------------------------------------------
        B = logits.size(0)                     # number of edge samples (or batch size)
        logits = logits.view(B, self.convs[0].deg, self.convs[0].deg)
        adj = self.row_softmax(logits)         # shape (B, degree, degree)

        # optional symmetry step (commented out)
        # adj = (adj + adj.transpose(1, 2)) / 2
        # adj = self.row_softmax(adj)

        return adj