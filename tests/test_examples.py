import glob
import pytest

from ravens.schema import RavensValidator, RavensSchema

validator = RavensValidator(schema=RavensSchema())

@pytest.mark.parametrize("file", glob.glob("examples/schema/*.json"))
def test_example(file):
    validator.validate_file(file)
    # Test JSON data file is not empty
    assert validator.data

    # Test that there is a result
    assert validator.result is not None

    # Test that result is valid
    assert validator.result.valid
