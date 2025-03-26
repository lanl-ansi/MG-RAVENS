import pytest

from ravens.schema import RavensSchema
from jschon import JSONSchema


def test_build_schema():
    schema = RavensSchema()
    assert schema
    assert len(schema.schemas) == 944

    assert JSONSchema(schema.schema)
