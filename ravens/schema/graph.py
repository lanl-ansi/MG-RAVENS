if __name__ == "__main__":
    import json
    import networkx as nx
    from ravens.io import parse_uml_data
    from ravens.cim_tools.common import build_package_exclusions, build_object_exclusions
    from ravens.cim_tools.graph import build_generalization_graph, build_attribute_graph, build_association_graph
    from ravens.cim_tools.template import CIMTemplate
    from ravens.schema.build_map import add_attributes_to_template
    from ravens.schema.build_schema import build_schema_from_map
    from ravens.schema.build_definitions import build_definitions
    from ravens.schema.decompose_schema import Schemas

    uml_data = parse_uml_data("cim/iec61970cim17v40_iec61968cim13v13b_iec62325cim03v17b_CIM100.1.1.1_mgravens24v1.xmi")

    exclude_packages = build_package_exclusions(uml_data.packages, lambda x: any(str(x.Name).startswith(k) for k in ["Inf", "Mkt"]))
    exclude_objects = build_object_exclusions(
        uml_data.objects,
        lambda x: any(str(x.Name).startswith(k) for k in ["Inf", "Mkt"]),
        exclude_packages=exclude_packages,
    )

    schema = build_schema_from_map(
        add_attributes_to_template(
            CIMTemplate("ravens/cim_tools/cim_conversion_template.json").template,
            CIMTemplate("ravens/cim_tools/cim_conversion_template.json").template,
            uml_data,
            build_generalization_graph(uml_data, exclude_packages, exclude_objects),
            build_attribute_graph(uml_data, exclude_packages, exclude_objects),
        )
    )
    schema["$defs"] = build_definitions(uml_data)
    a = Schemas(schema)

    # exclude_packages = build_package_exclusions(uml_data.packages, lambda x: any(str(x.Name).startswith(k) for k in ["Inf", "Mkt"]))
    exclude_objects_more = build_object_exclusions(
        uml_data.objects,
        lambda x: str(x.Name) not in a.schemas.keys(),
        exclude_packages=exclude_packages,
    )

    GG = build_generalization_graph(uml_data, exclude_packages, exclude_objects_more)
    # nx.write_graphml(GG, "out/CIM_graphs/GG.graphml")
    AT = build_attribute_graph(uml_data, exclude_packages, exclude_objects_more)
    # nx.write_graphml(AT, "out/CIM_graphs/AT.graphml")
    AG = build_association_graph(uml_data, exclude_packages, exclude_objects_more)
    # nx.write_graphml(AG, "out/CIM_graphs/AG.graphml")

    GG_AT_AG = nx.compose_all([GG, AT, AG])
    nx.write_graphml(GG_AT_AG, "out/CIM_graphs/RAVENS_Schema.graphml", named_key_ids=True, edge_id_from_attribute="Connector_ID")
