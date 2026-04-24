import os
import json
import random
import numpy as np
from typing import List, Dict, Any, Callable, Tuple, Optional
from dataclasses import dataclass, field
import networkx as nx
from pathlib import Path
import matplotlib.pyplot as plt
from collections import defaultdict


@dataclass
class MGRavensDataset:
    """
    Data container for MG-RAVENS JSON schema power grids.
    Supports loading, processing, and converting data for ML applications.
    """
    data_dir: str = None
    raw_data: List[Dict[Any, Any]] = None
    ML_data: List[Any] = field(default_factory=list)
    is_raw: bool = True
    
    def __post_init__(self):
        """Initialize the dataset by loading files if data_dir is provided."""
        if self.data_dir:
            self.load_data()
    
    def load_data(self,new_path = None, verbose=False) -> None:
        """Load all JSON files from the specified directory."""
        #optionally set a new root path
        if new_path != None:
            self.data_dir = new_path

        self.raw_data = []
        path = Path(self.data_dir)
        
        # Find all JSON files in the directory
        if path.is_file() and path.suffix == '.json':
            json_files = [path]
        else:
            # Find all JSON files in the directory
            json_files = list(path.glob("*.json"))
        
        id_num = 0
        for file_path in json_files:
            try:
                with open(file_path, 'r') as f:
                    data = json.load(f)
                    self.raw_data.append((str(file_path)+"_"+str(id_num),data))
                    id_num+=1
            except Exception as e:
                print(f"Error loading {file_path}: {e}")
        
        if verbose:
            print(f"Loaded {len(self.raw_data)} MG-RAVENS grid files")
    
    def process_for_ML(self, custom_processor: Optional[Callable] = None) -> None:
        """
        Process raw data for GNN models.
        
        Args:
            custom_processor: Optional function to override default GNN processing
        """
        if self.raw_data is None:
            raise ValueError("No data loaded. Call load_data() first.")
        
        processor = custom_processor if custom_processor else self.ravens_to_ML
        self.ML_data = [processor(item) for item in self.raw_data]
        self.is_raw = False
    
    def ravens_to_ML(self, ravens_data: Tuple[str,Dict]) -> Dict:
        """
        Convert MG-RAVENS JSON data to a format suitable for ML processing.
        
        Args:
            ravens_data: A single MG-RAVENS JSON object
            
        Returns:
            Dictionary containing graph structure, Node Features, and Edge Features 
        """
        # Create a multigraph representation
        G = nx.MultiGraph()
        file_name, ravens_data = ravens_data[0], ravens_data[1]
        
        # Extract buses (nodes)
        buses = ravens_data.get('ConnectivityNode', {})
        for bus_id, bus_data in buses.items():
            G.add_node(bus_id, 
                    name=bus_data.get('IdentifiedObject.name', ''),
                    vm=1.0,  # Default voltage magnitude
                    va=0.0,  # Default voltage angle
                    pd=0.0,  # Default active power demand
                    qd=0.0,  # Default reactive power demand
                    pg=0.0,  # Default active power generation
                    qg=0.0,  # Default reactive power generation
                    vmin=0.9,  # Default minimum voltage
                    vmax=1.1,  # Default maximum voltage
                    node_type='bus')  # Mark as a regular bus
        
        # Extract branches (edges)
        branches = ravens_data['PowerSystemResource']['Equipment']['ConductingEquipment']['Conductor'].get('ACLineSegment', {})
        for branch_id, branch_data in branches.items():
            # Add edge with features
            length = branch_data.get('Conductor.length')
            phases = len(branch_data.get('ACLineSegment.ACLineSegmentPhase'))
            PLPIID = branch_data.get("ACLineSegment.PerLengthImpedance").split("::")[-1].strip("'\"")
            PLPI = ravens_data['PerLengthLineParameter']['PerLengthImpedance']['PerLengthPhaseImpedance'].get(PLPIID)
            R = np.zeros((phases,phases))
            X = np.zeros((phases,phases))
            B = np.zeros((phases,phases))
            for entry in PLPI["PerLengthPhaseImpedance.PhaseImpedanceData"]:
                row = entry["PhaseImpedanceData.row"] - 1  # Convert to 0-indexed
                col = entry["PhaseImpedanceData.column"] - 1  # Convert to 0-indexed
                
                # For upper triangular matrices, we only use values where col >= row
                if col >= row:
                    R[row, col] = entry["PhaseImpedanceData.r"]
                    X[row, col] = entry["PhaseImpedanceData.x"]
                    B[row, col] = entry["PhaseImpedanceData.b"]
                else:
                    # For entries where col < row, we place them in the upper triangular position
                    R[col, row] = entry["PhaseImpedanceData.r"]
                    X[col, row] = entry["PhaseImpedanceData.x"]
                    B[col, row] = entry["PhaseImpedanceData.b"]
            
            from_bus = branch_data.get('ConductingEquipment.Terminals')[0].get('Terminal.ConnectivityNode').split('::')[-1].strip("'\"")
            to_bus = branch_data.get('ConductingEquipment.Terminals')[1].get('Terminal.ConnectivityNode').split('::')[-1].strip("'\"")

            from_bus = "NOT_FOUND_" + from_bus if from_bus not in buses else from_bus 
            to_bus = "NOT_FOUND_" + to_bus if to_bus not in buses else to_bus 

            G.add_edge(from_bus, 
                    to_bus,
                    key=branch_id,  # Use branch_id as the key for the edge
                    phases=phases,
                    R=R.tolist(),
                    X=X.tolist(),
                    B=B.tolist(),
                    branch_id=branch_id,
                    edge_type='line',
                    name=branch_data.get("IdentifiedObject.name",{}))  # Mark as a line

        # Extract switches as edges
        switches = ravens_data['PowerSystemResource']['Equipment']['ConductingEquipment'].get('Switch', {})
        for switch_id, switch_data in switches.items():
            # Add edge with features
            length = switch_data.get('Conductor.length', 0)
            phases = len(switch_data.get('Switch.SwitchPhase'))
            
            from_bus = switch_data.get('ConductingEquipment.Terminals')[0].get('Terminal.ConnectivityNode').split('::')[-1].strip("'\"")
            to_bus = switch_data.get('ConductingEquipment.Terminals')[1].get('Terminal.ConnectivityNode').split('::')[-1].strip("'\"")
            
            from_bus = "NOT_FOUND_" + from_bus if from_bus not in buses else from_bus 
            to_bus = "NOT_FOUND_" + to_bus if to_bus not in buses else to_bus 
            
            G.add_edge(from_bus, 
                    to_bus,
                    key=switch_id,  # Use switch_id as the key for the edge
                    phases=phases,
                    R=np.zeros((phases,phases)).tolist(),
                    X=np.zeros((phases,phases)).tolist(),
                    B=np.zeros((phases,phases)).tolist(),
                    branch_id=switch_id,
                    edge_type='switch',
                    name=switch_data.get("IdentifiedObject.name",{}))  # Mark as a switch
        
        # Extract loads and generators and add them as node attributes
        loads = ravens_data['PowerSystemResource']['Equipment']['ConductingEquipment']['EnergyConnection'].get('EnergyConsumer', {})
        gens = ravens_data['PowerSystemResource']['Equipment']['ConductingEquipment']['EnergyConnection'].get('EnergySource', {})
        
        for load_id, load_data in loads.items():
            bus_id = load_data.get('ConductingEquipment.Terminals')[0].get('Terminal.ConnectivityNode').split('::')[-1].strip("'\"")
            if bus_id in G.nodes:
                # Add load as node attribute
                G.nodes[bus_id]['pd'] = G.nodes[bus_id].get('pd', 0.0) + load_data.get('EnergyConsumer.p', 0.0)
                G.nodes[bus_id]['qd'] = G.nodes[bus_id].get('qd', 0.0) + load_data.get('EnergyConsumer.q', 0.0)
                G.nodes[bus_id]['node_type'] = 'load'  # Mark as a load bus
        
        # Process energy sources (generators)
        for gen_id, gen_data in gens.items():
            # Extract the bus ID from the terminal connectivity node
            terminals = gen_data.get('ConductingEquipment.Terminals', [])
            if terminals:
                bus_id = terminals[0].get('Terminal.ConnectivityNode').split('::')[-1].strip("'\"")
                if bus_id in G.nodes:
                    # Add generator as node attribute
                    G.nodes[bus_id]['source'] = True
                    G.nodes[bus_id]['vm'] = gen_data.get('EnergySource.voltageMagnitude', 0.0)
                    G.nodes[bus_id]['va'] = gen_data.get('EnergySource.voltageAngle', 0.0)
                    G.nodes[bus_id]['r'] = gen_data.get('EnergySource.r', 0.0)
                    G.nodes[bus_id]['x'] = gen_data.get('EnergySource.x', 0.0)
                    G.nodes[bus_id]['r0'] = gen_data.get('EnergySource.r0', 0.0)
                    G.nodes[bus_id]['x0'] = gen_data.get('EnergySource.x0', 0.0)
                    G.nodes[bus_id]['nominal_voltage'] = gen_data.get('EnergySource.nominalVoltage', 0.0)
                    
                    # Traditional generator parameters if available
                    G.nodes[bus_id]['pg'] = G.nodes[bus_id].get('pg', 0.0) + gen_data.get('pg', 0.0)
                    G.nodes[bus_id]['qg'] = G.nodes[bus_id].get('qg', 0.0) + gen_data.get('qg', 0.0)
                    G.nodes[bus_id]['pmax'] = gen_data.get('pmax', 0.0)
                    G.nodes[bus_id]['pmin'] = gen_data.get('pmin', 0.0)
                    G.nodes[bus_id]['node_type'] = 'generator'  # Mark as a generator bus
                    
                    # Check if we need to create a virtual bus and branch for the source
                    r = gen_data.get('EnergySource.r', 0.0)
                    x = gen_data.get('EnergySource.x', 0.0)
                    r0 = gen_data.get('EnergySource.r0', 0.0)
                    x0 = gen_data.get('EnergySource.x0', 0.0)
                    
                    # If there's impedance, create a virtual bus and branch
                    if r > 0 or x > 0 or r0 > 0 or x0 > 0:
                        # Create a virtual bus for the generator
                        virtual_bus_id = f"_virtual_bus.{gen_id}"
                        G.add_node(virtual_bus_id,
                                name=f"Virtual Bus for {gen_id}",
                                vm=gen_data.get('EnergySource.voltageMagnitude', 0.0),
                                va=gen_data.get('EnergySource.voltageAngle', 0.0),
                                pd=0.0,
                                qd=0.0,
                                pg=G.nodes[bus_id].get('pg', 0.0),
                                qg=G.nodes[bus_id].get('qg', 0.0),
                                pmax=G.nodes[bus_id].get('pmax', 0.0),
                                pmin=G.nodes[bus_id].get('pmin', 0.0),
                                vmin=G.nodes[bus_id].get('vm', 0.9),
                                vmax=G.nodes[bus_id].get('vm', 1.1),
                                source=True,
                                node_type='virtual_generator')  # Mark as a virtual generator bus
                        
                        # Create a branch to represent the source impedance
                        phases = len(terminals[0].get('Terminal.phases', "TEST.ABC").split(".")[-1])
                        
                        # Create impedance matrices
                        R_mat = np.zeros((phases, phases))
                        X_mat = np.zeros((phases, phases))
                        
                        # Fill diagonal with impedance values
                        for i in range(phases):
                            R_mat[i, i] = r
                            X_mat[i, i] = x
                        
                        # Add the impedance branch
                        virtual_branch_id = f"{gen_id}"
                        G.add_edge(virtual_bus_id,
                                bus_id,
                                key=virtual_branch_id,
                                phases=phases,
                                R=R_mat.tolist(),
                                X=X_mat.tolist(),
                                B=np.zeros((phases, phases)).tolist(),
                                branch_id=virtual_branch_id,
                                edge_type='virtual_branch',
                                name=gen_data.get("IdentifiedObject.name",{}))  # Mark as a virtual branch

        # Process transformers if available
        if 'PowerSystemResource' in ravens_data and 'Equipment' in ravens_data['PowerSystemResource']:
            equipment = ravens_data['PowerSystemResource']['Equipment']
            if 'ConductingEquipment' in equipment and 'PowerTransformer' in equipment['ConductingEquipment']:
                transformers = equipment['ConductingEquipment']['PowerTransformer']
                for xfmr_id, xfmr_data in transformers.items():
                    # Extract terminals to find connectivity
                    terminals = xfmr_data.get('ConductingEquipment.Terminals', [])
                    if len(terminals) >= 2:  # Need at least 2 terminals for a transformer
                        # Find the connected buses
                        from_bus = None
                        to_bus = None
                        for terminal in terminals:
                            if 'Terminal.ConnectivityNode' in terminal:
                                bus_ref = terminal['Terminal.ConnectivityNode']
                                # Extract the bus ID from the reference (format: "ConnectivityNode::'busname'")
                                bus_id = bus_ref.split("::")[1].strip("'")
                                if from_bus is None:
                                    from_bus = bus_id
                                else:
                                    to_bus = bus_id
                                    break
                        ends = xfmr_data.get("PowerTransformer.PowerTransformerEnd",{})
                        R_mat = [0 for _ in ends]
                        X_mat = [0 for _ in ends]
                        G_mat = [0 for _ in ends]
                        B_mat = [0 for _ in ends]
                        for i, end in enumerate(ends):
                            TSI = end.get("TransformerEnd.StarImpedance",{})
                            R_mat[i] = TSI.get("TransformerStarImpedance.r",0)
                            X_mat[i] = TSI.get("TransformerStarImpedance.x",0)
                            TCA = end.get("TransformerEnd.CoreAdmittance",{})
                            G_mat[i] = TSI.get("TransformerCoreAdmittance.g",0)
                            B_mat[i] = TSI.get("TransformerCoreAdmittance.b",0)

                        from_bus = "NOT_FOUND_" + from_bus if from_bus not in buses else from_bus 
                        to_bus = "NOT_FOUND_" + to_bus if to_bus not in buses else to_bus 
                        
                        # Add transformer as an edge with transformer-specific attributes
                        G.add_edge(from_bus, to_bus, 
                                    key=xfmr_id,
                                    type='transformer',
                                    id=xfmr_id,
                                    R=R_mat,
                                    X=X_mat,
                                    G=G_mat,
                                    B=B_mat,
                                    tap=1.0,
                                    shift=0.0,
                                    branch_id=xfmr_id,
                                    edge_type='transformer',
                                    name=xfmr_data.get("IdentifiedObject.name",{}))  # Mark as a transformer
        
        # Convert to feature matrices for GNN
        # Node features
        node_ids = list(G.nodes())
        node_features = []
        
        for node in node_ids:
            features = [
                G.nodes[node].get('vm', 1.0),
                G.nodes[node].get('va', 0.0),
                G.nodes[node].get('p', 0.0),
                G.nodes[node].get('q', 0.0),
                G.nodes[node].get('pg', 0.0),
                G.nodes[node].get('qg', 0.0),
                G.nodes[node].get('pmax', 0.0),
                G.nodes[node].get('pmin', 0.0),
                G.nodes[node].get('vmin', 0.9),
                G.nodes[node].get('vmax', 1.1)
            ]
            node_features.append(features)
        
        # Edge indices and features
        edge_indices = defaultdict(list)
        edge_features = {}
        
        for u, v, key, data in G.edges(data=True, keys=True):
            # Convert node IDs to indices
            u_idx = node_ids.index(u)
            v_idx = node_ids.index(v)
            
            branch_id = data.get('branch_id')
            
            # Add edges in both directions for GNN
            edge_indices[branch_id].append([u_idx, v_idx])
            edge_indices[branch_id].append([v_idx, u_idx])  # Bidirectional
            
            # Edge features
            edge_type = 1.0 if data.get('edge_type') == 'transformer' else 0.0  # Edge type feature (0=line, 1=transformer)
            
            features = {
                "name": data.get('name',"NO_NAME"),
                "phases": data.get('phases', 1),
                "R": data.get('R', [0.0]),
                "X": data.get('X', [0.0]),
                "G": data.get('G', [0.0]),
                "B": data.get('B', [0.0]),
                "Edge Type": edge_type, #1 = Transformer, 0 = Other Edge
                # "Rated_S": data.get('RS', [0.0]), #Transformer Rated S (if applicable)
                # "Rated_U": data.get('RU', [0.0]), #Transformer Rated U (if applicable)
                "Tap": data.get('tap', 1.0) if edge_type else 0.0,  # Transformer tap ratio (if applicable)
                "Shift": data.get('shift', 0.0) if edge_type else 0.0,  # Phase shift angle (if applicable)
                "edge_type": edge_type  # Store the edge type as a string
            }
            edge_features[branch_id] = features
        
        return {
            'file_name': file_name,
            'node_ids': node_ids,
            'node_features': np.array(node_features, dtype=np.float32).tolist(),
            'edge_index': edge_indices,  
            'edge_features': edge_features,
            'graph': G,  # Keep the original graph for reference
            'original_data': ravens_data  # Keep the original data
        }

    
    def visualize_graph(self, index: int = 0, figsize: Tuple[int, int] = (12, 10), 
                       save_path: Optional[str] = None) -> None:
        """
        Visualize the power grid graph.
        
        Args:
            index: Index of the grid to visualize from ML_data
            figsize: Size of the figure (width, height)
            save_path: Path to save the figure. If None, the figure is displayed
        """
        if self.ML_data is None or index >= len(self.ML_data):
            raise ValueError(f"No data available at index {index}. Process data first.")
        
        G = self.ML_data[index]['graph']
        
        # Create a new figure
        plt.figure(figsize=figsize)
        
        # Set up node positions using a spring layout
        pos = nx.spring_layout(G, seed=42)
        
        # Prepare node colors based on node type
        node_colors = []
        for node in G.nodes():
            # Check if node has generation
            if G.nodes[node].get('pg', 0) > 0 or G.nodes[node].get('nominal_voltage', 0) > 0:
                node_colors.append('green')  # Generator nodes
            elif G.nodes[node].get('pd', 0) > 0 or G.nodes[node].get('qd', 0) > 0:
                node_colors.append('red')    # Load nodes
            else:
                node_colors.append('blue')   # Other nodes
        
        # Prepare edge colors based on edge type
        edge_colors = []
        for u, v, data in G.edges(data=True):
            if data.get('type') == 'transformer':
                edge_colors.append('orange')  # Transformers
            else:
                edge_colors.append('black')   # Lines
        
        # Draw the graph
        nx.draw_networkx_nodes(G, pos, node_color=node_colors, node_size=500)
        nx.draw_networkx_edges(G, pos, edge_color=edge_colors, width=2)
        nx.draw_networkx_labels(G, pos, font_size=10, font_weight='bold')
        
        # Add a legend
        from matplotlib.lines import Line2D
        legend_elements = [
            Line2D([0], [0], marker='o', color='w', markerfacecolor='green', markersize=10, label='Generator'),
            Line2D([0], [0], marker='o', color='w', markerfacecolor='red', markersize=10, label='Load'),
            Line2D([0], [0], marker='o', color='w', markerfacecolor='blue', markersize=10, label='Bus'),
            Line2D([0], [0], color='black', lw=2, label='Line'),
            Line2D([0], [0], color='orange', lw=2, label='Transformer')
        ]
        plt.legend(handles=legend_elements, loc='upper right')
        
        plt.title(f"Power Grid Graph (Grid {index})")
        plt.axis('off')  # Hide axis
        
        # Save or show the figure
        if save_path:
            plt.savefig(save_path, bbox_inches='tight')
            print(f"Graph visualization saved to {save_path}")
        else:
            plt.show()
    
    def save_data(self,index=0,filename="temp.json"):
        OD = self.ML_data[index].copy()

        print(OD["graph"].nodes)
        OD["graph"] = {"nodes":list(OD["graph"].nodes),"edges":list(OD["graph"].edges)}

        with open(filename, "w") as f:
            json.dump(OD, f, indent=2)


    def read_data(self,file_path):
        # ------------------------------------------------------------------
        # 1 Load the raw JSON
        # ------------------------------------------------------------------
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"Unable to locate JSON file: {file_path}")

        with path.open("r") as f:
            raw = json.load(f)

        # ------------------------------------------------------------------
        # 2 Re‑create the NetworkX graph from the stored lists
        # ------------------------------------------------------------------
        graph_info = raw.get("graph")
        if graph_info is None:
            raise ValueError("JSON does not contain a 'graph' entry.")

        # Choose the graph type you need – here we assume an undirected Graph.
        G = nx.MultiGraph()
        G.add_nodes_from(graph_info.get("nodes", []))
        G.add_edges_from(graph_info.get("edges", []))

        raw["graph"] = G

        self.ML_data.append(raw)

        return len(self.ML_data)
    
    def data(self):
        return self.ML_data
    
    def __getitem__(self, index):
        if self.is_raw:
            self.process_for_ML()
        return self.raw_data[index][0],self.raw_data[index][1],self.ML_data[index] #NAME, MGR, ML
    
    def __len__(self):
        return len(self.raw_data)


if __name__ == "__main__":
    MGR = MGRavensDataset(data_dir="ravens/ravensML/data/raw")
    MGR.load_data()
    MGR.process_for_ML()
    print(MGR[0][2].keys())
    print(MGR[0][2]['node_features'])
    MGR.visualize_graph(2)
    # MGR.save_data(0,"tmp/test_SL.json")
    
