from copy import deepcopy

import pytest
from jschon import JSON, JSONSchema, create_catalog

from ravens.schema.schema import RavensSchema
from ravens.schema.validate import RavensValidator


def _make_empty_schema_builder() -> RavensSchema:
    schema = RavensSchema.__new__(RavensSchema)
    schema.schemas = {}
    schema.base_id_uri = "https://example.com/schema"
    schema.omit_file_extension = False
    schema.omit_descr = False
    return schema


@pytest.fixture(params=[False, True], ids=["anyof-only", "properties-and-anyof"])
def hashed_anyof_schema(request):
    schema = _make_empty_schema_builder()
    properties = {
        "EnergyConsumer.p": {"type": "ActivePower"},
        "EnergyConsumer.phaseConnection": {"type": "PhaseShuntConnectionKind"},
        "Ravens.cimObjectType": {"type": "string"},
    }
    consumer = {
        "title": "EnergyConsumer",
        "type": "object",
        "$objectType": "object",
        "$primaryObjectHash": "IdentifiedObject.name",
        "anyOf": [
            {
                "title": name,
                "type": "object",
                "$objectId": name,
                "properties": {
                    **deepcopy(properties),
                    "Ravens.cimObjectType": {"type": "string", "enum": [name]},
                },
            }
            for name in ["EnergyConsumer", "ConformLoad"]
        ],
    }
    if request.param:
        consumer["properties"] = deepcopy(properties)
    root = schema.build_schema_from_map({"title": "Root", "type": "object", "properties": {"EnergyConsumer": consumer}})
    root["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    root["$id"] = schema.schema_path("Root")
    root["$defs"] = {
        "ActivePower": {"title": "ActivePower", "type": "number"},
        "PhaseShuntConnectionKind": {"title": "PhaseShuntConnectionKind", "type": "string", "enum": ["Y", "D"]},
    }
    return schema, root


def test_build_schema_from_map_converts_hashed_anyof_members(hashed_anyof_schema):
    _, root = hashed_anyof_schema
    members = root["properties"]["EnergyConsumer"]["patternProperties"]["^.+$"]["anyOf"]
    assert len(members) == 2
    for member in members:
        assert member["properties"]["EnergyConsumer.p"] == {"$ref": "#/$defs/ActivePower"}
        assert member["properties"]["EnergyConsumer.phaseConnection"] == {"$ref": "#/$defs/PhaseShuntConnectionKind"}
        assert "$objectId" not in member

    create_catalog("2020-12")
    validator = JSONSchema(root)
    for name in ["EnergyConsumer", "ConformLoad"]:
        for power, phase, valid in [(42, "Y", True), (42, "D", True), ("wrong", "Y", False), (42, "wrong", False)]:
            data = {"EnergyConsumer": {"load1": {"EnergyConsumer.p": power, "EnergyConsumer.phaseConnection": phase, "Ravens.cimObjectType": name}}}
            assert validator.evaluate(JSON(data)).valid is valid
    assert not validator.evaluate(JSON({"EnergyConsumer": {"load1": {"Ravens.cimObjectType": "Other"}}})).valid


def test_decomposed_hashed_anyof_members_resolve_type_references(hashed_anyof_schema, tmp_path):
    schema, root = hashed_anyof_schema
    schema.decompose_schema(deepcopy(root))
    schema.decompose_defs(root["$defs"])
    schema.schemas[schema.schema_path("Root")].pop("$defs")
    schema.insert_refs()

    for name in ["EnergyConsumer", "ConformLoad"]:
        member = schema.schemas[schema.schema_path(name)]
        assert member["properties"]["EnergyConsumer.p"] == {"$ref": schema.schema_path("ActivePower")}
        assert member["properties"]["EnergyConsumer.phaseConnection"] == {"$ref": schema.schema_path("PhaseShuntConnectionKind")}

    schema.export_schemas(tmp_path)
    validator = RavensValidator(schema_base_uri=schema.base_id_uri + "/", local_path_to_schema=tmp_path / "Root.json")
    for name in ["EnergyConsumer", "ConformLoad"]:
        for power, phase, valid in [(42, "Y", True), ("wrong", "Y", False), (42, "wrong", False)]:
            validator.validate_dict({"EnergyConsumer": {"load1": {"EnergyConsumer.p": power, "EnergyConsumer.phaseConnection": phase, "Ravens.cimObjectType": name}}}, print_result=False)
            assert validator.result.valid is valid


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


def test_decompose_schema_skips_anonymous_hash_wrapper_artifacts():
    schema = _make_empty_schema_builder()
    root = {
        "title": "Root",
        "type": "object",
        "properties": {
            "Location": {
                "type": "object",
                "title": "Container",
                "description": "Hash table of  objects",
                "patternProperties": {
                    "^.+$": {
                        "type": "object",
                        "properties": {
                            "Location.Name": {"type": "string"},
                        },
                    }
                },
            },
            "EnvironmentalPhenomenon": {
                "type": "object",
                "title": "Container",
                "description": "Hash table of  objects",
                "patternProperties": {
                    "^.+$": {
                        "type": "object",
                        "anyOf": [
                            {
                                "title": "EnvironmentalPhenomenon",
                                "type": "object",
                                "properties": {},
                            }
                        ],
                    }
                },
            },
        },
    }

    schema.decompose_schema(root, debug_key="Root")

    assert schema.schema_path("Root") in schema.schemas
    assert schema.schema_path("EnvironmentalPhenomenon") in schema.schemas
    assert schema.schema_path("+$") not in schema.schemas
    assert schema.schema_path("+$_anyOfContainer") not in schema.schemas
    assert schema.schema_path("Container_Container") not in schema.schemas
