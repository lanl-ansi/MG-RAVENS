import pytest

from ravens.schema import RavensSchema
from jschon import JSONSchema


def test_build_schema():
    schema = RavensSchema()
    assert schema
    assert len(schema.schemas) == 1009

    assert JSONSchema(schema.schema)


def test_all_refs_are_local_file_references():
    """Test that all $ref values point to local file references, not #/$defs/"""
    schema = RavensSchema()

    def check_refs_recursive(obj, path="", schema_key=""):
        """Recursively check all $ref values in the schema"""
        refs_with_defs = []

        if isinstance(obj, dict):
            # Check if this dict has a $ref
            if "$ref" in obj:
                ref_value = obj["$ref"]
                if ref_value.startswith("#/$defs/"):
                    refs_with_defs.append({"schema": schema_key, "path": path, "ref": ref_value})

            # Recursively check all nested dicts
            for key, value in obj.items():
                if key == "$ref":
                    continue  # Already checked above
                new_path = f"{path}.{key}" if path else key
                refs_with_defs.extend(check_refs_recursive(value, new_path, schema_key))

        elif isinstance(obj, list):
            # Recursively check all items in lists
            for i, item in enumerate(obj):
                new_path = f"{path}[{i}]"
                refs_with_defs.extend(check_refs_recursive(item, new_path, schema_key))

        return refs_with_defs

    # Check all schemas
    all_bad_refs = []
    for schema_key, schema_obj in schema.schemas.items():
        bad_refs = check_refs_recursive(schema_obj, schema_key=schema_key)
        all_bad_refs.extend(bad_refs)

    # If there are any #/$defs/ references, fail the test with details
    if all_bad_refs:
        error_msg = "Found $ref values that still use #/$defs/ instead of local file references:\n"
        for ref_info in all_bad_refs[:10]:  # Show first 10 to avoid huge output
            error_msg += f"  - Schema: {ref_info['schema']}\n"
            error_msg += f"    Path: {ref_info['path']}\n"
            error_msg += f"    Ref: {ref_info['ref']}\n"

        if len(all_bad_refs) > 10:
            error_msg += f"\n  ... and {len(all_bad_refs) - 10} more"

        pytest.fail(error_msg)

    # Also verify that refs do point to valid schema files
    all_refs = []
    for schema_key, schema_obj in schema.schemas.items():
        refs = extract_all_refs(schema_obj)
        all_refs.extend(refs)

    # Check that all refs point to existing schemas
    invalid_refs = []
    for ref in all_refs:
        if ref not in schema.schemas:
            invalid_refs.append(ref)

    if invalid_refs:
        error_msg = f"Found {len(invalid_refs)} $ref values that don't point to existing schemas:\n"
        for ref in invalid_refs[:10]:
            error_msg += f"  - {ref}\n"
        if len(invalid_refs) > 10:
            error_msg += f"  ... and {len(invalid_refs) - 10} more"
        pytest.fail(error_msg)


def extract_all_refs(obj):
    """Extract all $ref values from a schema object"""
    refs = []

    if isinstance(obj, dict):
        if "$ref" in obj:
            refs.append(obj["$ref"])

        for value in obj.values():
            refs.extend(extract_all_refs(value))

    elif isinstance(obj, list):
        for item in obj:
            refs.extend(extract_all_refs(item))

    return refs


def test_no_defs_in_decomposed_schemas():
    """Test that individual decomposed schemas don't contain $defs"""
    schema = RavensSchema()

    schemas_with_defs = []
    for schema_key, schema_obj in schema.schemas.items():
        if "$defs" in schema_obj and schema_key != schema.schema_path("Root"):
            schemas_with_defs.append(schema_key)

    if schemas_with_defs:
        error_msg = f"Found {len(schemas_with_defs)} schemas with $defs (should only be in Root):\n"
        for key in schemas_with_defs[:10]:
            error_msg += f"  - {key}\n"
        if len(schemas_with_defs) > 10:
            error_msg += f"  ... and {len(schemas_with_defs) - 10} more"
        pytest.fail(error_msg)
