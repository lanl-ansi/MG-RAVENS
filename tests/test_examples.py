import pytest

from ravens.schema.validate import RavensValidator


def test_examples():
    validator = RavensValidator()

    for file in glob.glob("examples/schema/*.json"):
        pass
