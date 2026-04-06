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


def test_manual_gap_annotation_applies_override_when_present():
    annotation = SchemaComparator._manual_gap_annotation(
        "ConformLoad_PointerArray",
        "candidate_builder_gap",
        {
            "source": "user_verified_2026-04-06",
            "review_status": "verified_hand_relationship_not_present_in_valid_diagrams",
            "override_actionability": "verified_hand_beyond_current_valid_diagrams",
            "note": "No visible labeled association in valid diagrams.",
            "future_followup": "Add the relation to a valid diagram or narrow the hand template.",
        },
    )

    assert annotation["manual_review_status"] == "verified_hand_relationship_not_present_in_valid_diagrams"
    assert annotation["manual_review_source"] == "user_verified_2026-04-06"
    assert annotation["manual_review_note"] == "No visible labeled association in valid diagrams."
    assert annotation["manual_future_followup"] == "Add the relation to a valid diagram or narrow the hand template."
    assert annotation["manual_override_actionability"] == "verified_hand_beyond_current_valid_diagrams"
    assert annotation["effective_actionability"] == "verified_hand_beyond_current_valid_diagrams"


def test_manual_gap_annotation_preserves_actionability_without_override():
    annotation = SchemaComparator._manual_gap_annotation(
        "GeographicalRegion_anyOfPointer_anyOfContainer",
        "candidate_builder_gap",
        {
            "source": "user_verified_2026-04-06",
            "review_status": "mixed_manual_review",
            "note": "Mixed supported and unsupported relationships.",
            "future_followup": "Split relationship-level tracking.",
        },
    )

    assert annotation["manual_review_status"] == "mixed_manual_review"
    assert annotation["manual_override_actionability"] is None
    assert annotation["effective_actionability"] == "candidate_builder_gap"
