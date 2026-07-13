import inspect

from ravens.schema.schema import RavensSchema
from ravens.schema.template import SchemaTemplate


def test_schema_template_source_defaults_to_auto():
    sig = inspect.signature(SchemaTemplate)
    assert sig.parameters["source"].default == "auto"


def test_ravens_schema_template_source_defaults_to_auto():
    sig = inspect.signature(RavensSchema)
    assert sig.parameters["template_source"].default == "auto"