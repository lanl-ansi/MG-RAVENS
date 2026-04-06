from ravens.uml.autotemplate.compare import SchemaComparator


def test_base_template_name_strips_synthetic_suffixes():
    assert SchemaComparator._base_template_name("CommunityFacility_anyOfContainer") == "CommunityFacility"
    assert SchemaComparator._base_template_name("GeographicalRegion_anyOfPointer_anyOfContainer") == "GeographicalRegion"
    assert SchemaComparator._base_template_name("ConformLoad_PointerArray") == "ConformLoad"
    assert SchemaComparator._base_template_name("Message_Array") == "Message"


def test_template_scope_and_actionability_distinguish_root_only_from_kept_nonroot():
    root_only = {
        "diagram_exclusion_status": "not_on_excluded_diagrams",
        "diagram_names": ["Root"],
        "root_diagram_names": ["Root"],
        "excluded_diagram_names": [],
        "kept_nonroot_diagram_names": [],
    }
    kept_nonroot = {
        "diagram_exclusion_status": "not_on_excluded_diagrams",
        "diagram_names": ["EnergyConsumers"],
        "root_diagram_names": [],
        "excluded_diagram_names": [],
        "kept_nonroot_diagram_names": ["EnergyConsumers"],
    }
    root_and_excluded = {
        "diagram_exclusion_status": "present_on_kept_and_excluded_diagrams",
        "diagram_names": ["Root", "InfFacilities"],
        "root_diagram_names": ["Root"],
        "excluded_diagram_names": ["InfFacilities"],
        "kept_nonroot_diagram_names": [],
    }

    assert SchemaComparator._template_scope_status(root_only) == "root_only"
    assert SchemaComparator._template_actionability("root_only") == "likely_hand_beyond_simplified_scope"

    assert SchemaComparator._template_scope_status(kept_nonroot) == "kept_nonroot_present"
    assert SchemaComparator._template_actionability("kept_nonroot_present") == "candidate_builder_gap"

    assert SchemaComparator._template_scope_status(root_and_excluded) == "root_and_excluded_only"
    assert SchemaComparator._template_actionability("root_and_excluded_only") == "likely_hand_beyond_simplified_scope"
