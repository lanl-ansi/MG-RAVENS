import pytest

from ravens.uml.autotemplate.builder import AutoTemplateBuilder


def _get_nested(mapping, *keys):
    cur = mapping
    for key in keys:
        assert isinstance(cur, dict), f"Expected dict before key {key!r}, got {type(cur)!r}"
        assert key in cur, f"Missing key {key!r}"
        cur = cur[key]
    return cur


@pytest.fixture(scope="module")
def raw_auto_template():
    return AutoTemplateBuilder().build()


def test_inherit_only_operational_limit_wrapper_keeps_family_object_id(raw_auto_template):
    items = _get_nested(
        raw_auto_template,
        "properties",
        "OperationalLimitSet",
        "properties",
        "OperationalLimitSet.OperationalLimitValue",
        "items",
    )

    assert items["$objectType"] == "object"
    assert items["$objectId"] == "OperationalLimit"
    assert isinstance(items.get("anyOf"), list)


def test_inherit_only_producer_cost_parameter_wrapper_keeps_family_object_id(raw_auto_template):
    items = _get_nested(
        raw_auto_template,
        "properties",
        "ProducerCostFunction",
        "properties",
        "ProducerCostFunction.CostParameters",
        "items",
    )

    assert items["$objectType"] == "object"
    assert items["$objectId"] == "ProducerCostParameter"
    assert isinstance(items.get("anyOf"), list)
