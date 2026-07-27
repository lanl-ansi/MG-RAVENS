import networkx as nx
import pandas as pd

from ravens.uml import UMLExclusions
from ravens.uml.autotemplate.clusions import UMLExclusions as AutoTemplateExclusions
from ravens.uml.autotemplate.clusions import UMLInclusions
from ravens.uml.autotemplate.graph import UMLGraphs as AutoTemplateGraphs
from ravens.uml.data import UMLData
from ravens.uml.graph import UMLGraphs


def _uml_data():
    uml_data = object.__new__(UMLData)

    uml_data.packages = pd.DataFrame(
        [{'Package_ID': 10, 'Name': 'SimplifiedDiagrams', 'Path': 'Model/SimplifiedDiagrams'}]
    ).set_index('Package_ID')
    uml_data.diagrams = pd.DataFrame(
        [{'Diagram_ID': 20, 'Package_ID': 10, 'Name': 'Fixture'}]
    ).set_index('Diagram_ID')
    uml_data.objects = pd.DataFrame(
        [
            {'Object_ID': 1, 'Object_Type': 'Class', 'Name': 'Root', 'Package_ID': 10, 'Stereotype': None, 'Note': None},
            {'Object_ID': 2, 'Object_Type': 'Class', 'Name': 'Child', 'Package_ID': 10, 'Stereotype': None, 'Note': None},
            {'Object_ID': 3, 'Object_Type': 'Class', 'Name': 'Related', 'Package_ID': 10, 'Stereotype': None, 'Note': None},
            {'Object_ID': 4, 'Object_Type': 'Class', 'Name': 'HiddenChild', 'Package_ID': 10, 'Stereotype': None, 'Note': None},
        ]
    ).set_index('Object_ID')
    uml_data.attributes = pd.DataFrame(
        [{'ID': 200, 'Object_ID': 2, 'Name': 'rating', 'Notes': None, 'Type': 'Float'}]
    ).set_index('ID')
    uml_data.connectors = pd.DataFrame(
        [
            {
                'Connector_ID': 100,
                'Connector_Type': 'Generalization',
                'Start_Object_ID': 2,
                'End_Object_ID': 1,
                'SourceRole': '',
                'DestRole': '',
                'SourceCard': '',
                'DestCard': '',
                'Name': '',
                'Stereotype': '',
            },
            {
                'Connector_ID': 101,
                'Connector_Type': 'Association',
                'Start_Object_ID': 2,
                'End_Object_ID': 3,
                'SourceRole': '',
                'DestRole': 'RelatedObjects',
                'SourceCard': '0..*',
                'DestCard': '1',
                'Name': '',
                'Stereotype': '',
            },
            {
                'Connector_ID': 102,
                'Connector_Type': 'Generalization',
                'Start_Object_ID': 4,
                'End_Object_ID': 1,
                'SourceRole': '',
                'DestRole': '',
                'SourceCard': '',
                'DestCard': '',
                'Name': '',
                'Stereotype': '',
            },
            {
                'Connector_ID': 103,
                'Connector_Type': 'Association',
                'Start_Object_ID': 4,
                'End_Object_ID': 3,
                'SourceRole': '',
                'DestRole': 'HiddenObjects',
                'SourceCard': '0..*',
                'DestCard': '1',
                'Name': '',
                'Stereotype': '',
            },
        ]
    ).set_index('Connector_ID')
    uml_data.diagramobjects = pd.DataFrame(
        [
            {'Instance_ID': 300, 'Diagram_ID': 20, 'Object_ID': 1},
            {'Instance_ID': 301, 'Diagram_ID': 20, 'Object_ID': 2},
            {'Instance_ID': 302, 'Diagram_ID': 20, 'Object_ID': 3},
            {'Instance_ID': 303, 'Diagram_ID': 20, 'Object_ID': 4},
        ]
    ).set_index('Instance_ID')
    uml_data.diagramlinks = pd.DataFrame(
        [
            {'Instance_ID': 400, 'DiagramID': 20, 'ConnectorID': 100, 'Hidden': False, 'Geometry': '', 'Style': ''},
            {'Instance_ID': 401, 'DiagramID': 20, 'ConnectorID': 101, 'Hidden': False, 'Geometry': '', 'Style': ''},
            {'Instance_ID': 402, 'DiagramID': 20, 'ConnectorID': 102, 'Hidden': True, 'Geometry': '', 'Style': ''},
            {'Instance_ID': 403, 'DiagramID': 20, 'ConnectorID': 103, 'Hidden': True, 'Geometry': '', 'Style': ''},
        ]
    ).set_index('Instance_ID')
    uml_data.objectproperties = pd.DataFrame(
        [
            {'PropertyID': 500, 'Object_ID': 1, 'Property': 'ravensRole', 'Value': 'rootClass'},
            {'PropertyID': 501, 'Object_ID': 2, 'Property': 'ravensRole', 'Value': 'substitutableClass'},
            {'PropertyID': 502, 'Object_ID': 3, 'Property': 'ravensRole', 'Value': 'embeddedClass'},
            {'PropertyID': 503, 'Object_ID': 4, 'Property': 'ravensRole', 'Value': 'inheritOnlyClass'},
        ]
    ).set_index('PropertyID')
    uml_data.connectortags = pd.DataFrame()
    uml_data.xrefs = pd.DataFrame()

    return uml_data


def test_autotemplate_uses_shared_exclusions():
    assert AutoTemplateExclusions is UMLExclusions


def test_legacy_graph_interface():
    uml_data = _uml_data()
    graphs = UMLGraphs(
        uml_data=uml_data,
        exclusions=UMLExclusions(uml_data=uml_data),
    )

    assert set(graphs.gen_graph.edges()) == {(2, 1), (4, 1)}
    assert graphs.attr_graph.has_edge(200, 2)
    assert graphs.attr_graph.nodes[200]['Name'] == 'rating'
    assert graphs.assoc_graph.has_edge(2, 3)
    assert graphs.assoc_graph.has_edge(3, 2)
    assert graphs.assoc_graph.has_edge(4, 3)

    forward = next(iter(graphs.assoc_graph.get_edge_data(2, 3).values()))
    reverse = next(iter(graphs.assoc_graph.get_edge_data(3, 2).values()))
    assert forward['DestRole'] == 'RelatedObjects'
    assert forward['SourceCard'] == '0..*'
    assert forward['DestCard'] == '1'
    assert reverse['SourceRole'] == 'RelatedObjects'
    assert reverse['SourceCard'] == '1'
    assert reverse['DestCard'] == '0..*'
    assert 200 in graphs.graph


def test_autotemplate_graph_interface():
    uml_data = _uml_data()
    inclusions = UMLInclusions(
        uml_data=uml_data,
        packages=('SimplifiedDiagrams',),
        auto_apply=False,
        exclude_inf_mkt_initial=False,
        exclude_hidden_links=True,
        drop_objects_without_visible_generalization=False,
    )
    auto_graphs = AutoTemplateGraphs(uml_data=uml_data, inclusions=inclusions)
    graphs = UMLGraphs(
        uml_data=uml_data,
        exclusions=UMLExclusions(uml_data=uml_data),
        inclusions=inclusions,
    )

    assert nx.utils.graphs_equal(graphs.H, auto_graphs.H)
    assert nx.utils.graphs_equal(graphs.A, auto_graphs.A)

    assert set(graphs.H.edges()) == {(2, 1)}
    assert set(graphs.HR.edges()) == {(1, 2)}
    assert graphs.H.nodes[1]['ravensRole'] == 'rootClass'
    assert graphs.H.nodes[2]['ravensRole'] == 'substitutableClass'

    assert list(graphs.A.edges()) == [(2, 3)]
    edge = next(iter(graphs.A.get_edge_data(2, 3).values()))
    assert edge['label'] == 'RelatedObjects'
    assert edge['start_mult'] == '0..*'
    assert edge['end_mult'] == '1'
    assert edge['Diagram'] == 'Fixture'
