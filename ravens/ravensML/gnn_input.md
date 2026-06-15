# GNN Input/Output

## Case: Connection Prediction

### Premise

Take a grid input of (N Nodes, E Edges) w/ feature descriptors for each and output an NxN adjacency matrix where each cell represents a confidence between 0 and 1 about whether there is a missing edge between those nodes.

The below example is trained on a dataset of graphs each with 20 buses and a varying number of edges. Edges can consist of Switches, ACLineSegments and Transformers. Nodes are always buses but we store generation/load parameters in the relevant node features.

### Input Datapoint

**Size of (X,y) Pair:**

``` Python
Data(
  x=[20, 10], #10 Node features for each node
  edge_index=[2, 38], #(to_bus,fr_bus) pairs for each edge (38 edges for this case)
  edge_attr=[38, 40], #(4 + 4*max_phase^2) typically 40 Edge features for each edge 
  max_phase=3, #Helper value
  y={
    missing_edges=[20, 20], #(NxN) missing_edges[i,j] = 1 if edge from bus_i to bus_j has been removed
    raw_mgr='<path to training directory>/<file_name>_<id>.json',
  }
)
```

#### x - Node Features

Stores 10 features for each node:

- bus_id (int) - id label for the bus
- vm (float) - Voltage magnitude
- va (float) - Voltage angle
- pd (float) - Active power demand
- qd (float) - Reactive power demand
- pg (float) - Active power generation
- qg (float) - Reactive power generation
- vmin (float) - Minimum voltage
- vmax (float) - Maximum voltage
- node_type (int) - [1: bus, 2: source, 3: load]

#### edge_attr - Edge Features

Stores (4 + 4*max_phase^2) features for each edge:

- phases - number of phases (1 int)
- R - R matrix (max_phase**2 floats)
- X - X matrix (max_phase**2 floats)
- G - G matrix (max_phase**2 floats)
- B - B matrix (max_phase**2 floats)
- edge_type - edge type (1 int)
- tap - tap ratio (1 float)
- shift - phase shift (1 float)

#### edge_index - Graph Structure

Straightforward ('to_bus','fr_bus') pairs which is inline with what Pytorch Geometric wants:

``` Python
edge_idx: list[list[int]] = []
for _branch_id, pairs in data_dict["edge_index"].items():
    edge_idx.extend(pairs)

edge_index = torch.tensor(edge_idx, dtype=torch.long).t().contiguous()
```

#### max_phase - Max Phase Helper (Not For Training)

I store this in order to track the max phases for any edge in the dataset. There is certainly a more elegant way to do this but I did not bother to implement that. This allows a loss function to know how many phases to expect when unpacking features that are flattened (Phase x Phase) matrices. This is not used in any training.

Note: if max_phase = m, we pad all features to m phases with zeroes.

#### y.missing_edges - Target Output

If we are training on an N node case our target will always be an NxN matrix of 0s and 1s. The way I create this is by randomly removing k edges from a graph and then marking those edges on the matrix in order to create (X,y) pairs for training.

#### y.raw_mgr - Reference Path (Not For Training)

I store a reference back to the original file for each datapoint to make write-back and other downstream analysis easier. This is purely for ease of implementation and is not used in any training.
