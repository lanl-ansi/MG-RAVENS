import json

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


def test_rotating_machine_generating_unit_preserves_polymorphic_wrapper(raw_auto_template):
    rotating_machine = _get_nested(
        raw_auto_template,
        "properties",
        "PowerSystemResource",
        "properties",
        "Equipment",
        "properties",
        "ConductingEquipment",
        "properties",
        "EnergyConnection",
        "properties",
        "RegulatingCondEq",
        "properties",
        "RotatingMachine",
    )

    base_variant = next(
        variant
        for variant in rotating_machine["anyOf"]
        if isinstance(variant, dict) and variant.get("$objectId") == "RotatingMachine"
    )
    generating_unit = base_variant["properties"]["RotatingMachine.GeneratingUnit"]

    assert generating_unit["$objectType"] == "object"
    assert generating_unit["$objectId"] == "GeneratingUnit"
    assert isinstance(generating_unit.get("anyOf"), list)
    assert {item.get("$objectId") for item in generating_unit["anyOf"] if isinstance(item, dict)} >= {
        "GeneratingUnit",
        "HydroGeneratingUnit",
        "ThermalGeneratingUnit",
    }


def test_load_area_subloadareas_emits_family_pointer_array(raw_auto_template):
    energy_area = _get_nested(
        raw_auto_template,
        "properties",
        "Group",
        "properties",
        "EnergyArea",
    )

    load_area_variant = next(
        variant
        for variant in energy_area["anyOf"]
        if isinstance(variant, dict) and variant.get("$objectId") == "LoadArea"
    )
    subload_areas = load_area_variant["properties"]["LoadArea.SubLoadAreas"]

    assert subload_areas["type"] == "array"
    assert subload_areas["items"]["$objectType"] == "reference"
    assert subload_areas["items"]["$objectId"] == "LoadArea"
    assert subload_areas["items"]["$referencePath"] == "Group/EnergyArea"


def test_builder_save_writes_explicit_template(raw_auto_template, tmp_path):
    out_path = tmp_path / "template_auto.json"
    saved_path = AutoTemplateBuilder().save(out_path, data=raw_auto_template)

    assert saved_path == out_path
    saved = json.loads(out_path.read_text())
    assert saved["title"] == "Root"
    assert saved["properties"]
