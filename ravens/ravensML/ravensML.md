# ravensML

## Leveraging Pytorch ML tools on MG-RAVENS grids

**Workflow:**

```txt
DSS --> XML --> MG-RAVENS --> ravensML --> Pytorch-PyGraph -> GNN Frameworks
                                |               └─> PI-GNN Frameworks supported by PMD
                                └─> Custom Methods
```

ravensML provides a suite of tools designed to facilitate the use of PyTorch machine learning capabilities on MG-RAVENS grid data. The framework offers a streamlined pipeline that converts MG-RAVENS files into accessible Python data objects (called ravensML), enabling a wide range of ad-hoc computational methods. Additionally, ravensML includes functionality to transform these intermediate representations into PyTorch-compatible datasets. This comprehensive toolset bridges the gap between power grid data and modern machine learning techniques, allowing researchers and engineers to apply sophisticated analytical approaches to grid problems. The framework particularly shines in graph-based applications, as demonstrated in our example workflow where a Graph Neural Network (GNN) is used to predict transformer parameters from MG-RAVENS grid data. By removing technical barriers between domain-specific grid representations and machine learning libraries, ravensML empowers users to develop and deploy advanced ML solutions for power systems analysis with minimal overhead.

ravensML further aims to help address training data insufficiency. It provides examples of synthetic training data generation frameworks as well as data segmentation methods. When combined with the MG-RAVENS data conversion pipeline, these capabilities allow users to generate sufficiently large and diverse, albeit biased, training datasets from publicly available grid models, such as the IEEE 8500 model. Building out this data infrastructure is an important step in enabling the advancement of ML-enabled power systems analysis.

## Functionality

### Data Framework

The core of the ravensML data framework for MG-RAVENS grid models is the `MGRavensDataset` object implemented in `ravens/ravensML/framework/dataset.py`. This object allows users to specify a directory of MG-RAVENS.json files that have been previously processed using the MG-CROWS simplification tool. This preprocessing is required to standardize the representations of transformers and power lines.

Once provided with the directory, the `MGRavensDataset` converts each of these files into a ravensML object with the following format:

- `file_name`: original filename for debugging and reference
- `node_ids`: IDs for each node in the grid (from RAVENS bus objects)
- `node_features`: node parameters specified in the RAVENS file
- `edge_index`: IDs for each edge relative to node ID (edges are from RAVENS line/switch/transformer objects)
- `edge_features`: edge parameters specified in the RAVENS file, including line admittance/impedance as well as transformer parameters
- `graph`: NetworkX graph object
- `original_data`: original dict structure from the MG-RAVENS file

#### Supported Node Features

- `vm`: Voltage magnitude
- `va`: Voltage angle
- `pd`: Active power demand
- `qd`: Reactive power demand
- `pg`: Active power generation
- `qg`: Reactive power generation
- `pmax`: Maximum active power
- `pmin`: Minimum active power
- `vmin`: Minimum voltage
- `vmax`: Maximum voltage

#### Supported Edge Features

- `name`: Name of the branch
- `phases`: Number of phases
- `R`: Resistance matrix
- `X`: Reactance matrix
- `G`: Conductance matrix
- `B`: Susceptance matrix
- `Edge` Type: 1 for transformers, 0 for other edges
- `edge_type`: Edge type as a string ('transformer' or 'line')
- `Tap`: Transformer tap ratio (if applicable)
- `Shift`: Transformer phase shift angle (if applicable)

#### ravensML Dataset Creation

Below we have attached a usage example for converting an MG-Ravens directory into ravensML objects.

```python
#instantiate a dataset object
MGR = MGRavensDataset(data_dir="ravens/ravensML/data/raw")

#optionally reload from a new data path
MGR.load_data("ravens/ravensML/data/raw")

#runs the conversation of MG-Ravens data to ravensML objects
MGR.process_for_ML()

#reference examples
#first index [i] --> ith file
#second index [0] --> name, [1] --> original mgr dict, [2]--> ml object
print(MGR[0][2].keys()) #print 0th file's ML object keys 
print(MGR[0][2]['node_features']) #print 0th file's node features

#visualize the 2nd file using networkx and and matplotlib
MGR.visualize_graph(2)

#save a json representation of the graph in a json object
MGR.save_data(0,"tmp/test_SL.json")
```

### Training Data Generation

#### Data Segmentation

The `grid_segmenter` class in `ravens/ravensML/framework/grid_segmenter.py` provides a way to convert a full MG-RAVENS grid model into a set of feasible sub-grids. This is useful when a user has access to a single, large grid model but needs a more diverse set of topologies for training machine learning models.

**Usage:**

```python
#Initialize the `grid_segmenter` class with an optional base graph
from ravens.ravensML.framework.grid_segmenter import grid_segmenter

gs = grid_segmenter(base_graph=None, PF_Val=False)
    #base_graph: An optional MG-RAVENS grid model dictionary to use as the base for segmentation. If not provided, the class will initialize with an empty template.
    #PF_Val: A boolean flag to enable/disable power flow validation of the generated sub-grids. This will continue attempting to generate graphs naively until one satisfies the AC-PF constraints.

#Load an MG-RAVENS grid model from a file
gs.load_from_file("path/to/mgravens_file.json") #NOTE: this is called when `base_graph` is not set to None during object init

#Generate a sub-grid with optional constraints
sub_mgr = gs.yield_graph(
    min_nodes=67, #number of nodes to generate in graph
    output_path="path/to/output/sub_mgr.json" #output file path and name
)
```

**Implementation Details:**
The grid_segmenter class works by performing a breadth-first search (BFS) starting from a randomly selected node in the base graph. The search continues until the minimum node count is reached, adding nodes and edges to the sub-grid as it goes.

After the sub-grid is constructed, the class performs some post-processing steps, such as:

- Ensuring the sub-grid has a "source bus" node
- Normalizing phase code strings to be compatible with PowerModelsDistribution
- Optionally running a power flow validation
- The class maintains an internal template of the sub-grid structure to avoid repeating the initialization process for each call to yield_graph.

#### Synthetic X-y Generation Template/Examples

The ravensML package provides a methodology for users to create context-dependent synthetic data. In the test cases, the focus was on creating synthetic errors in MG-RAVENS files that machine learning models could aim to correct.

**Error Generation Scripts:**

- `ravens/ravensML/methods/transformers/gen_trans_error.py`
- `ravens/ravensML/methods/YZ/gen_YZ_error.py`
- `ravens/ravensML/methods/connectivity/gen_conn_error.py`

These scripts allow the user to generate a dataset of size `N` by introducing random errors either in line/node parameters or in the graph topology. For example, the following code generates a dataset where 1% of the transformer specifications are randomly missing, and 0.55% of the time, a random normal affine transformation is applied to the transformer parameters:

```python
from ravens.ravensML.framework.dataset import MGRavensDataset
from ravens.ravensML.methods.transformers.gen_trans_error import generate_trans_error

MGR = MGRavensDataset(data_dir="ravens/ravensML/data/trans_test")
MGR_TEST, Y = generate_trans_error(
    MGR,
    deletion_prob=0.01,
    occurrence_prob=0.55,
    mult_mean=1,
    mult_var=1.25,
    add_mean=0,
    add_var=1.25
)
```

We have included a template class for this type of error generation script at `ravens/ravensML/framework/templates/t_synthetic_transform.py`

### RavensML to Pytorch

The last step in being able to seamlessly run Pytorch-based ML training workflows using MG-Ravens data is to convert the ravensML format to PyG objects from pytorch geometric. We implement exactly this in `ravens/ravensML/methods/transformers/trans_gnn/data.py`.

The crux of this process is converting node/edge features as well as edge topology to tensors.

The `dict_to_pyg` function in `data.py` converts the dictionary produced by `MGRavensDataset.ravens_to_ML` into a `torch_geometric.data.Data` object. It handles the following steps:

1. Extract node features into a tensor `x`.
2. Convert the edge index (a list of node ID pairs) into a tensor `edge_index`.
3. Determine the maximum number of phases in the graph.
4. Build a uniform edge feature matrix `edge_attr` by padding the impedance/admittance matrices to the maximum phase count.
5. Return the `torch_geometric.data.Data` object with the computed tensors.

We have also included a template class `MGTransformerDataset` in `ravens/ravensML/framework/templates/t_pyg_dataset.py` that provides a PyG `InMemoryDataset` wrapper around the MG-RAVENS data.

## Developer Guide

Within the context of the ravensML framework, the usage of MG-RAVENS files should be no more difficult than implementing a traditional PyTorch Geometric training workflow. We do implement a features that may be of use to developers in `ravens/ravensML/framework/tools`

### Write Back to MG-RAVENS

- `tools.mgr_helpers.update_mgr(prediction,sample)`
  - `prediction` - predicted edge parameters tensor
  - `sample` - correct y value pytorch object
  - outputs: MG-Ravens grid object with updated parameters
- `tools.mgr_helpers.run_pf(mgr_grid)`
  - `mgr_grid` - MG-Ravens grid object
  - outputs: result of running a power flow computation on the given grid using `PowerModelsDistribution.jl`

**Note:** In order to use the `PowerModelsDistribution.jl` enabled `run_pf` function or any other `PMD` reliant function you need to install the `juliaup` package.
This may require you to modify the following path line in the code in whatever files it appears.

```python
julia_path = rML_ROOT.parents[4]/'.juliaup/bin/julia'
```

The current implementation assumes the `.juliaup` directory exists in a directory that is the parent of the parent of MG-RAVENS. This is a work in progress.

### Physics Informed Components

The easiest way to implement physics informed constraints is to train a Pytorch GNN on the results of a `PowerModelsDistribution.jl` computation. One such method is provided in `framework.tools.pf_inf_approx` and is helpful for adding a differentiable loss term that should help the model learn to produce demand feasible outputs. This is used in both the transformer and connectivity example methods. 

### Training Tools

- `tools.training_tools.train_epoch(model, loader, loss_fn, optimizer, device)`
  - given the above inputs, this will run one full epoch of training.
- `tools.training_tools.validate(model, loader, loss_fn, device)`
  - given the above inputs, this will run one full epoch of validation without updating model parameters.
