import warnings

class grid_segmenter:
    """
    This class is designed to allow a user to convert a grid specified in the MGRavens format and yield a set of feasible sub-grids.
    This solves a common problem where a user intending to preform analysis on a range of topologies may not have access to a sufficiently diverse set of grid topologies. 

    Parameters:
        - base_graph: A dictionary of an MGRavens graph

    Public Member Functions:
    - set_base_graph(new_MGR) --> sets base graph to a new MGR dictionary 
    - yield_graph(optional: MGR, min_nodes, max_nodes) --> yields a new subgraph segmented from either the passed MGRavens file, or the base graph with optional constraints on number of nodes
    """

    def __init__(self, base_graph = None):
        self.base_graph = base_graph
        if self.base_graph == None:
            warnings.warn("This class needs a base graph to be specified before segmentation may occur. Either set a base graph with `set_base_graph(new_MGRavens)` or pass in a graph to the `yield_graph` call")
        
    def set_base_graph(self, new_MGR):
        self.base_graph = new_MGR
        #TODO: add type checking and associated errors/warnings

    def yield_graph(self, MGR = None, min_nodes = 0, max_nodes = None):
        MGR = self.MGR if MGR == None else MGR
        if MGR == None:
            raise Exception("No base graph specified through object init, set_base_graph, or this function call")
        #TODO: implement network partition algorithm



if __name__ == "__main__":
    import sys
    sys.path.append('/Users/oreed/Desktop/LANL-ANSI/MG-RAVENS/ravens/')
    from ravens.xml.opendss2xml import DssExport
    from ravens.xml.xml2ravens import CrowsImport

    d = DssExport("ravens/ravensML/data/IEEE8500/Master.dss")
    d.save("ravens/ravensML/framework/tmp/segmenter.xml")

    MGR = CrowsImport("ravens/ravensML/framework/tmp/segmenter.xml")
    MGR.dump("ravens/ravensML/framework/tmp/segmenter.json", indent=2)