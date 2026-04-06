from ravens.schema.schema import RavensSchema


def _make_empty_schema_builder() -> RavensSchema:
    schema = RavensSchema.__new__(RavensSchema)
    schema.schemas = {}
    schema.base_id_uri = "https://example.com/schema"
    schema.omit_file_extension = False
    return schema


def test_decompose_schema_decomposes_anyof_members_on_object_schemas():
    schema = _make_empty_schema_builder()
    root = {
        "title": "Parent",
        "type": "object",
        "properties": {
            "Parent.Meta": {
                "title": "Meta",
                "type": "object",
                "properties": {
                    "Meta.name": {"type": "string"},
                },
            }
        },
        "anyOf": [
            {
                "title": "ChildA",
                "type": "object",
                "properties": {
                    "ChildA.value": {"type": "string"},
                },
            },
            {
                "title": "ChildB",
                "type": "object",
                "properties": {
                    "ChildB.value": {"type": "number"},
                },
            },
        ],
    }

    root_ref = schema.decompose_schema(root, debug_key="Parent")
    parent_key = schema.schema_path("Parent_anyOfContainer")
    meta_key = schema.schema_path("Meta")
    child_a_key = schema.schema_path("ChildA")
    child_b_key = schema.schema_path("ChildB")

    assert root_ref == parent_key
    assert parent_key in schema.schemas
    assert meta_key in schema.schemas
    assert child_a_key in schema.schemas
    assert child_b_key in schema.schemas

    parent_schema = schema.schemas[parent_key]
    assert parent_schema["properties"]["Parent.Meta"] == {"$ref": meta_key}
    assert parent_schema["anyOf"] == [{"$ref": child_a_key}, {"$ref": child_b_key}]


def test_build_schema_from_map_collapses_redundant_pure_anyof_wrappers():
    schema = _make_empty_schema_builder()
    root = schema.build_schema_from_map(
        {
            "title": "Parent",
            "type": "object",
            "properties": {
                "Parent.Ref": {
                    "title": "ActivityRecord_anyOfPointer",
                    "anyOf": [
                        {
                            "type": "string",
                            "title": "ActivityRecord_Pointer",
                            "description": "Pointer to ActivityRecord object",
                            "pattern": "^ActivityRecord::'(.+)'$",
                        },
                        {
                            "type": "string",
                            "title": "EnvironmentalEvent_Pointer",
                            "description": "Pointer to EnvironmentalEvent object",
                            "pattern": "^ActivityRecord::'(.+)'$",
                        },
                    ],
                }
            },
        }
    )

    ref_schema = root["properties"]["Parent.Ref"]
    assert ref_schema == {
        "type": "string",
        "title": "ActivityRecord_Pointer",
        "description": "Pointer to ActivityRecord object",
        "pattern": "^ActivityRecord::'(.+)'$",
    }

    root_ref = schema.decompose_schema(root, debug_key="Parent")
    parent_schema = schema.schemas[root_ref]

    assert parent_schema["properties"]["Parent.Ref"] == ref_schema
    assert schema.schema_path("ActivityRecord_anyOfPointer_anyOfContainer") not in schema.schemas


def test_build_schema_from_map_preserves_object_anyof_wrappers_with_properties():
    schema = _make_empty_schema_builder()
    root = schema.build_schema_from_map(
        {
            "title": "Parent",
            "type": "object",
            "properties": {
                "Parent.Child": {
                    "title": "CommunityFacility",
                    "type": "object",
                    "properties": {
                        "CommunityFacility.name": {"type": "string"},
                    },
                    "anyOf": [
                        {
                            "title": "GridFacility",
                            "type": "object",
                            "properties": {"GridFacility.name": {"type": "string"}},
                        }
                    ],
                }
            },
        }
    )

    child_schema = root["properties"]["Parent.Child"]
    assert child_schema["type"] == "object"
    assert "properties" in child_schema
    assert "anyOf" in child_schema
