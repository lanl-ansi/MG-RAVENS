from __future__ import annotations

import argparse
import importlib

# Ensure importlib.resources is available as an attribute on importlib.
# Some repo modules use `importlib.resources.files(...)` after only `import importlib`.
try:
    import importlib.resources as _importlib_resources
except Exception:  # pragma: no cover
    _importlib_resources = None
if _importlib_resources is not None and not hasattr(importlib, "resources"):
    importlib.resources = _importlib_resources

import json
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent

# Avoid importing ravens/__init__.py, which pulls in optional OpenDSS dependencies
# unrelated to template/schema smoke testing.
def _ensure_namespace(name: str, path: Path) -> types.ModuleType:
    mod = sys.modules.get(name)
    if mod is None:
        mod = types.ModuleType(name)
        mod.__path__ = [str(path)]
        sys.modules[name] = mod
    return mod


_ensure_namespace("ravens", REPO_ROOT / "ravens")
_ensure_namespace("ravens.schema", REPO_ROOT / "ravens" / "schema")
_ensure_namespace("ravens.uml", REPO_ROOT / "ravens" / "uml")
_ensure_namespace("ravens.uml.autotemplate", REPO_ROOT / "ravens" / "uml" / "autotemplate")

# Stub optional doc-generation dependency used by ravens.schema.schema.
if "json_schema_for_humans" not in sys.modules:
    _jsfh_pkg = types.ModuleType("json_schema_for_humans")
    _jsfh_gen = types.ModuleType("json_schema_for_humans.generate")
    _jsfh_pkg.generate = _jsfh_gen
    sys.modules["json_schema_for_humans"] = _jsfh_pkg
    sys.modules["json_schema_for_humans.generate"] = _jsfh_gen

# Populate ravens.uml namespace attributes needed by downstream imports.
ravens_uml = sys.modules["ravens.uml"]
UMLData = importlib.import_module("ravens.uml.data").UMLData
setattr(ravens_uml, "UMLData", UMLData)
UMLExclusions = importlib.import_module("ravens.uml.exclusions").UMLExclusions
setattr(ravens_uml, "UMLExclusions", UMLExclusions)
UMLGraphs = importlib.import_module("ravens.uml.graph").UMLGraphs
setattr(ravens_uml, "UMLGraphs", UMLGraphs)

# Populate ravens.schema namespace for autotemplate.compare imports.
ravens_schema_pkg = sys.modules["ravens.schema"]
SchemaTemplate = importlib.import_module("ravens.schema.template").SchemaTemplate
setattr(ravens_schema_pkg, "SchemaTemplate", SchemaTemplate)
RavensSchema = importlib.import_module("ravens.schema.schema").RavensSchema
setattr(ravens_schema_pkg, "RavensSchema", RavensSchema)

_autotemplate_builder_mod = importlib.import_module("ravens.uml.autotemplate.builder")
_autotemplate_validate_mod = importlib.import_module("ravens.uml.autotemplate.validate")
_autotemplate_compare_mod = importlib.import_module("ravens.uml.autotemplate.compare")

AutoTemplateBuilder = _autotemplate_builder_mod.AutoTemplateBuilder
AutoTemplateValidator = _autotemplate_validate_mod.AutoTemplateValidator
SchemaComparator = _autotemplate_compare_mod.SchemaComparator

# Populate ravens.uml.autotemplate namespace so runtime imports like
# `from ravens.uml.autotemplate import AutoTemplateBuilder` work.
ravens_autotemplate_pkg = sys.modules["ravens.uml.autotemplate"]
setattr(ravens_autotemplate_pkg, "AutoTemplateBuilder", AutoTemplateBuilder)
setattr(ravens_autotemplate_pkg, "AutoTemplateValidator", AutoTemplateValidator)
setattr(ravens_autotemplate_pkg, "SchemaComparator", SchemaComparator)
if hasattr(_autotemplate_builder_mod, "build_raw_autotemplate"):
    setattr(ravens_autotemplate_pkg, "build_raw_autotemplate", _autotemplate_builder_mod.build_raw_autotemplate)


@dataclass
class CheckResult:
    name: str
    ok: bool
    message: str
    details: dict[str, Any] | None = None


class CheckRecorder:
    def __init__(self) -> None:
        self.results: list[CheckResult] = []

    def expect(self, condition: bool, name: str, message: str, **details: Any) -> None:
        self.results.append(CheckResult(name=name, ok=bool(condition), message=message, details=details or None))


def _save_df(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def _write_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _get(node: dict[str, Any], path: Iterable[str]) -> Any:
    cur: Any = node
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            raise KeyError(".".join(path))
        cur = cur[key]
    return cur


def _count_status(df: pd.DataFrame, column: str = "status") -> dict[str, int]:
    if df.empty or column not in df.columns:
        return {}
    counts = df[column].value_counts(dropna=False)
    return {str(k): int(v) for k, v in counts.items()}


def check_shunt_family(auto_template: dict[str, Any]) -> list[CheckResult]:
    rec = CheckRecorder()
    path = [
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
        "ShuntCompensator",
    ]
    node = _get(auto_template, path)
    anyof = node.get("anyOf", [])
    by_oid = {item.get("$objectId"): item for item in anyof if isinstance(item, dict)}

    expected = {
        "ShuntCompensator": "ShuntCompensatorPhase",
        "LinearShuntCompensator": "LinearShuntCompensatorPhase",
        "NonlinearShuntCompensator": "NonlinearShuntCompensatorPhase",
    }
    prop_name = "ShuntCompensator.ShuntCompensatorPhase"

    rec.expect(len(by_oid) >= 3, "shunt.anyof_present", "ShuntCompensator anyOf variants should be present.", seen=list(by_oid))
    for oid, expected_item_oid in expected.items():
        item = by_oid.get(oid)
        rec.expect(item is not None, f"shunt.variant.{oid}", f"Variant {oid} should exist under ShuntCompensator anyOf.")
        if not isinstance(item, dict):
            continue
        props = item.get("properties", {})
        prop = props.get(prop_name)
        rec.expect(prop is not None, f"shunt.phase_property.{oid}", f"{oid} should include {prop_name}.")
        if not isinstance(prop, dict):
            continue
        rec.expect(prop.get("type") == "array", f"shunt.phase_array.{oid}", f"{prop_name} should be an array for {oid}.", actual_type=prop.get("type"))
        items = prop.get("items", {}) if isinstance(prop.get("items"), dict) else {}
        rec.expect(
            items.get("$objectId") == expected_item_oid,
            f"shunt.phase_item_oid.{oid}",
            f"{oid} should point to {expected_item_oid} items.",
            actual_object_id=items.get("$objectId"),
            expected_object_id=expected_item_oid,
        )
    return rec.results


def check_power_transformer_family(auto_template: dict[str, Any]) -> list[CheckResult]:
    rec = CheckRecorder()
    path = [
        "properties",
        "PowerSystemResource",
        "properties",
        "Equipment",
        "properties",
        "ConductingEquipment",
        "properties",
        "PowerTransformer",
    ]
    node = _get(auto_template, path)
    props = node.get("properties", {})

    pt_end = props.get("PowerTransformer.PowerTransformerEnd")
    rec.expect(pt_end is not None, "pt.power_transformer_end.present", "PowerTransformer.PowerTransformerEnd should be emitted.")
    if isinstance(pt_end, dict):
        rec.expect(pt_end.get("type") == "array", "pt.power_transformer_end.array", "PowerTransformer.PowerTransformerEnd should be an array.", actual_type=pt_end.get("type"))
        pt_end_items = pt_end.get("items", {}) if isinstance(pt_end.get("items"), dict) else {}
        rec.expect(pt_end_items.get("$objectId") == "PowerTransformerEnd", "pt.power_transformer_end.item_oid", "PowerTransformer.PowerTransformerEnd items should be PowerTransformerEnd.", actual_object_id=pt_end_items.get("$objectId"))
        rec.expect(pt_end_items.get("$arrayPosition") == "TransformerEnd.endNumber", "pt.power_transformer_end.array_position", "PowerTransformerEnd items should preserve TransformerEnd.endNumber as $arrayPosition.", actual_array_position=pt_end_items.get("$arrayPosition"))
        pt_end_props = pt_end_items.get("properties", {}) if isinstance(pt_end_items.get("properties"), dict) else {}
        for inherited_prop in [
            "TransformerEnd.BaseVoltage",
            "TransformerEnd.Terminal",
            "TransformerEnd.CoreAdmittance",
        ]:
            rec.expect(inherited_prop in pt_end_props, f"pt.power_transformer_end.inherited.{inherited_prop}", f"PowerTransformerEnd should include inherited property {inherited_prop}.")

    tanks = props.get("PowerTransformer.TransformerTanks")
    rec.expect(tanks is not None, "pt.transformer_tanks.present", "PowerTransformer.TransformerTanks should be emitted.")
    if isinstance(tanks, dict):
        rec.expect(tanks.get("type") == "array", "pt.transformer_tanks.array", "PowerTransformer.TransformerTanks should be an array.", actual_type=tanks.get("type"))
        tank_items = tanks.get("items", {}) if isinstance(tanks.get("items"), dict) else {}
        rec.expect(tank_items.get("$objectId") == "TransformerTank", "pt.transformer_tanks.item_oid", "PowerTransformer.TransformerTanks items should be TransformerTank.", actual_object_id=tank_items.get("$objectId"))
        tank_props = tank_items.get("properties", {}) if isinstance(tank_items.get("properties"), dict) else {}
        tank_ends = tank_props.get("TransformerTank.TransformerTankEnds")
        rec.expect(tank_ends is not None, "pt.transformer_tank_ends.present", "TransformerTank.TransformerTankEnds should be emitted under TransformerTank.")
        if isinstance(tank_ends, dict):
            rec.expect(tank_ends.get("type") == "array", "pt.transformer_tank_ends.array", "TransformerTank.TransformerTankEnds should be an array.", actual_type=tank_ends.get("type"))
            tank_end_items = tank_ends.get("items", {}) if isinstance(tank_ends.get("items"), dict) else {}
            rec.expect(tank_end_items.get("$objectId") == "TransformerTankEnd", "pt.transformer_tank_ends.item_oid", "TransformerTank.TransformerTankEnds items should be TransformerTankEnd.", actual_object_id=tank_end_items.get("$objectId"))
            rec.expect(tank_end_items.get("$arrayPosition") == "TransformerEnd.endNumber", "pt.transformer_tank_ends.array_position", "TransformerTankEnd items should preserve TransformerEnd.endNumber as $arrayPosition.", actual_array_position=tank_end_items.get("$arrayPosition"))
            tank_end_props = tank_end_items.get("properties", {}) if isinstance(tank_end_items.get("properties"), dict) else {}
            for inherited_prop in [
                "TransformerEnd.BaseVoltage",
                "TransformerEnd.Terminal",
                "TransformerEnd.CoreAdmittance",
            ]:
                rec.expect(inherited_prop in tank_end_props, f"pt.transformer_tank_end.inherited.{inherited_prop}", f"TransformerTankEnd should include inherited property {inherited_prop}.")
    return rec.results




def check_ar_curve_data_family(auto_template: dict[str, Any]) -> list[CheckResult]:
    rec = CheckRecorder()
    node = _get(auto_template, ["properties", "AnalysisResult"])
    anyof = node.get("anyOf", [])
    by_oid = {item.get("$objectId"): item for item in anyof if isinstance(item, dict)}

    expected_variants = {"OperationsResult", "AnalysisResult", "FaultStudyResult"}
    rec.expect(
        expected_variants.issubset(set(by_oid)),
        "arcurve.analysis_result.anyof_variants",
        "AnalysisResult anyOf should contain OperationsResult, AnalysisResult, and FaultStudyResult.",
        seen=sorted(list(by_oid)),
    )

    branch_specs = {
        ("OperationsResult", "OperationsResult.Voltages"): "AvVoltage",
        ("OperationsResult", "OperationsResult.Injections"): "AvInjection",
        ("OperationsResult", "OperationsResult.CurrentFlows"): "AvCurrentFlow",
        ("OperationsResult", "OperationsResult.Statuses"): "AvStatus",
        ("OperationsResult", "OperationsResult.PowerFlows"): "AvPowerFlow",
        ("OperationsResult", "OperationsResult.Switches"): "AvSwitch",
        ("OperationsResult", "OperationsResult.TransformerTaps"): "AvTapStep",
        ("OperationsResult", "OperationsResult.ShuntSections"): "AvShuntCompensatorSections",
        ("AnalysisResult", "AnalysisResult.Generics"): "AvGeneric",
        ("FaultStudyResult", "OperationsResult.Voltages"): "AvVoltage",
        ("FaultStudyResult", "OperationsResult.Injections"): "AvInjection",
        ("FaultStudyResult", "OperationsResult.CurrentFlows"): "AvCurrentFlow",
        ("FaultStudyResult", "OperationsResult.PowerFlows"): "AvPowerFlow",
    }

    total_nested_data_values = 0

    for (variant_oid, branch_name), expected_value_oid in branch_specs.items():
        variant = by_oid.get(variant_oid)
        rec.expect(
            isinstance(variant, dict),
            f"arcurve.variant.{variant_oid}",
            f"{variant_oid} should exist under AnalysisResult anyOf.",
        )
        if not isinstance(variant, dict):
            continue

        variant_props = variant.get("properties", {})
        branch = variant_props.get(branch_name)
        rec.expect(
            isinstance(branch, dict),
            f"arcurve.branch.{variant_oid}.{branch_name}",
            f"{variant_oid} should include {branch_name}.",
        )
        if not isinstance(branch, dict):
            continue

        rec.expect(
            branch.get("type") == "array",
            f"arcurve.branch_array.{variant_oid}.{branch_name}",
            f"{branch_name} should be an array.",
            actual_type=branch.get("type"),
        )

        items = branch.get("items", {}) if isinstance(branch.get("items"), dict) else {}
        item_props = items.get("properties", {}) if isinstance(items.get("properties"), dict) else {}

        direct_data_values = item_props.get("AnalysisResultData.DataValues")
        rec.expect(
            isinstance(direct_data_values, dict),
            f"arcurve.direct_data_values.{variant_oid}.{branch_name}",
            f"{branch_name} items should include AnalysisResultData.DataValues.",
        )
        if isinstance(direct_data_values, dict):
            rec.expect(
                direct_data_values.get("$objectId") == expected_value_oid,
                f"arcurve.direct_data_values_oid.{variant_oid}.{branch_name}",
                f"AnalysisResultData.DataValues for {branch_name} should be {expected_value_oid}.",
                actual_object_id=direct_data_values.get("$objectId"),
                expected_object_id=expected_value_oid,
            )

        curve = item_props.get("AnalysisResultData.Curve")
        rec.expect(
            isinstance(curve, dict),
            f"arcurve.curve.{variant_oid}.{branch_name}",
            f"{branch_name} items should include AnalysisResultData.Curve.",
        )
        if not isinstance(curve, dict):
            continue

        rec.expect(
            curve.get("$objectId") == "AnalysisResultCurve",
            f"arcurve.curve_oid.{variant_oid}.{branch_name}",
            f"AnalysisResultData.Curve for {branch_name} should be AnalysisResultCurve.",
            actual_object_id=curve.get("$objectId"),
        )

        curve_props = curve.get("properties", {}) if isinstance(curve.get("properties"), dict) else {}
        curve_datas = curve_props.get("AnalysisResultCurve.CurveDatas")
        rec.expect(
            isinstance(curve_datas, dict),
            f"arcurve.curve_datas.{variant_oid}.{branch_name}",
            f"AnalysisResultCurve.CurveDatas should be present for {branch_name}.",
        )
        if not isinstance(curve_datas, dict):
            continue

        rec.expect(
            curve_datas.get("type") == "array",
            f"arcurve.curve_datas_array.{variant_oid}.{branch_name}",
            f"AnalysisResultCurve.CurveDatas should be an array for {branch_name}.",
            actual_type=curve_datas.get("type"),
        )

        curve_items = curve_datas.get("items", {}) if isinstance(curve_datas.get("items"), dict) else {}
        rec.expect(
            curve_items.get("$objectId") == "ArCurveData",
            f"arcurve.curve_datas_item_oid.{variant_oid}.{branch_name}",
            f"AnalysisResultCurve.CurveDatas items should be ArCurveData for {branch_name}.",
            actual_object_id=curve_items.get("$objectId"),
        )

        curve_item_props = curve_items.get("properties", {}) if isinstance(curve_items.get("properties"), dict) else {}
        nested_data_values = curve_item_props.get("ArCurveData.DataValues")
        rec.expect(
            isinstance(nested_data_values, dict),
            f"arcurve.nested_data_values.{variant_oid}.{branch_name}",
            f"ArCurveData should include ArCurveData.DataValues for {branch_name}.",
        )
        if isinstance(nested_data_values, dict):
            total_nested_data_values += 1
            rec.expect(
                nested_data_values.get("$objectId") == expected_value_oid,
                f"arcurve.nested_data_values_oid.{variant_oid}.{branch_name}",
                f"ArCurveData.DataValues for {branch_name} should be {expected_value_oid}.",
                actual_object_id=nested_data_values.get("$objectId"),
                expected_object_id=expected_value_oid,
            )

    rec.expect(
        total_nested_data_values == len(branch_specs),
        "arcurve.total_nested_data_values",
        "All expected ArCurveData.DataValues branches should be present.",
        actual_total=total_nested_data_values,
        expected_total=len(branch_specs),
    )
    return rec.results


def run_targeted_checks(auto_template: dict[str, Any]) -> pd.DataFrame:
    results: list[CheckResult] = []
    for fn in (check_shunt_family, check_power_transformer_family, check_ar_curve_data_family):
        results.extend(fn(auto_template))
    rows = []
    for r in results:
        rows.append(
            {
                "name": r.name,
                "ok": r.ok,
                "message": r.message,
                "details": json.dumps(r.details, sort_keys=True) if r.details else "",
            }
        )
    return pd.DataFrame(rows, columns=["name", "ok", "message", "details"])


def run_json_validation(auto_schema: RavensSchema, json_paths: list[Path]) -> tuple[pd.DataFrame, str | None]:
    try:
        RavensValidator = importlib.import_module("ravens.schema.validate").RavensValidator
    except ModuleNotFoundError as exc:
        rows = [{"file": str(p), "valid": False, "message": f"skipped: missing dependency for RavensValidator ({exc})"} for p in json_paths]
        return pd.DataFrame(rows, columns=["file", "valid", "message"]), str(exc)

    rows: list[dict[str, Any]] = []
    validator = RavensValidator(schema=auto_schema)
    for path in json_paths:
        try:
            validator.validate_file(path, print_result=False)
            valid = bool(getattr(validator.result, "valid", False))
            rows.append({"file": str(path), "valid": valid, "message": "ok" if valid else json.dumps(validator.result.output("basic"))})
        except Exception as exc:
            rows.append({"file": str(path), "valid": False, "message": f"{type(exc).__name__}: {exc}"})
    return pd.DataFrame(rows, columns=["file", "valid", "message"]), None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke-test the auto-template builder and schema composition workflow.")
    parser.add_argument("--outdir", type=Path, default=REPO_ROOT / "out" / "smoke_autotemplate", help="Directory for smoke-test CSV/JSON outputs.")
    parser.add_argument("--validate-json", type=Path, nargs="*", default=[], help="Optional JSON files to validate against the composed auto schema.")
    parser.add_argument("--fail-on-validator-error", action="store_true", help="Exit non-zero if AutoTemplateValidator reports any ERROR rows.")
    parser.add_argument("--fail-on-validator-warn", action="store_true", help="Exit non-zero if AutoTemplateValidator reports any WARN rows.")
    parser.add_argument("--strict-json", action="store_true", help="Exit non-zero if any --validate-json file fails validation.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    outdir: Path = args.outdir
    outdir.mkdir(parents=True, exist_ok=True)

    summary: dict[str, Any] = {
        "repo_root": str(REPO_ROOT),
        "outdir": str(outdir),
    }

    print("[1/6] Rebuilding template_auto.json ...")
    builder = AutoTemplateBuilder()
    template_auto_path = builder.build_and_save()
    auto_template = builder.raw_template if isinstance(builder.raw_template, dict) else json.loads(template_auto_path.read_text(encoding="utf-8"))
    summary["template_auto_path"] = str(template_auto_path)

    print("[2/6] Running raw auto-template validator ...")
    validator = AutoTemplateValidator.from_builder(builder, auto=auto_template, build_if_needed=False)
    validator_df = validator.test_all()
    _save_df(validator_df, outdir / "raw_template_validator.csv")
    summary["raw_template_validator_counts"] = _count_status(validator_df, column="severity")

    print("[3/6] Composing hand and auto schemas ...")
    hand_schema = RavensSchema(template_source="hand")
    auto_schema = RavensSchema(template_source="auto")
    summary["hand_schema_count"] = len(hand_schema.schemas)
    summary["auto_schema_count"] = len(auto_schema.schemas)

    print("[4/6] Comparing schema inventories ...")
    cmp = SchemaComparator(hand_schema=hand_schema, auto_schema=auto_schema)
    schema_keys_df = cmp.compare_schema_keys(missing_only=False)
    normalized_df = cmp.compare_schema_keys_normalized(missing_only=False)
    missing_class_df = cmp.classify_missing_schema_keys()
    present_missing_df = cmp.classify_present_missing_schema_keys()
    template_gap_df = cmp.classify_template_shape_gaps()
    _save_df(schema_keys_df, outdir / "schema_keys.csv")
    _save_df(normalized_df, outdir / "schema_keys_normalized.csv")
    _save_df(missing_class_df, outdir / "missing_classification.csv")
    _save_df(present_missing_df, outdir / "present_missing_classification.csv")
    _save_df(template_gap_df, outdir / "template_shape_gaps.csv")
    summary["schema_key_counts"] = _count_status(schema_keys_df)
    summary["normalized_schema_key_counts"] = _count_status(normalized_df)
    summary["missing_classification_counts"] = _count_status(missing_class_df, column="classification_detail")
    summary["present_missing_appearance_counts"] = _count_status(present_missing_df, column="appearance_classification")
    summary["template_gap_actionability_counts"] = _count_status(template_gap_df, column="actionability")
    summary["template_gap_effective_actionability_counts"] = _count_status(template_gap_df, column="effective_actionability")
    summary["template_gap_manual_status_counts"] = _count_status(template_gap_df, column="manual_review_status")
    summary["template_gap_scope_counts"] = _count_status(template_gap_df, column="scope_status")
    summary["template_gap_mismatch_counts"] = _count_status(template_gap_df, column="shape_mismatch_kind")

    print("[5/6] Running targeted regression checks ...")
    targeted_df = run_targeted_checks(auto_template)
    _save_df(targeted_df, outdir / "targeted_checks.csv")
    targeted_failures = int((~targeted_df["ok"]).sum()) if not targeted_df.empty else 0
    summary["targeted_check_total"] = int(len(targeted_df))
    summary["targeted_check_failures"] = targeted_failures

    json_df = pd.DataFrame(columns=["file", "valid", "message"])
    json_skip_reason = None
    if args.validate_json:
        print("[6/6] Validating supplied JSON files against auto schema ...")
        json_df, json_skip_reason = run_json_validation(auto_schema, [p.resolve() for p in args.validate_json])
        _save_df(json_df, outdir / "json_validation.csv")
        summary["json_validation_valid"] = int(json_df["valid"].sum()) if not json_df.empty else 0
        summary["json_validation_invalid"] = int((~json_df["valid"]).sum()) if not json_df.empty else 0
        summary["json_validation_skip_reason"] = json_skip_reason
    else:
        print("[6/6] No external JSON validation requested.")
        summary["json_validation_valid"] = 0
        summary["json_validation_invalid"] = 0
        summary["json_validation_skip_reason"] = None

    _write_json(summary, outdir / "summary.json")

    print("\nSmoke summary")
    print(f"- template_auto: {template_auto_path}")
    print(f"- hand schemas: {summary['hand_schema_count']}")
    print(f"- auto schemas: {summary['auto_schema_count']}")
    print(f"- raw validator counts: {summary['raw_template_validator_counts']}")
    print(f"- normalized schema key counts: {summary['normalized_schema_key_counts']}")
    print(f"- targeted failures: {summary['targeted_check_failures']} / {summary['targeted_check_total']}")
    print(f"- outputs: {outdir}")

    failed = False
    if targeted_failures:
        failed = True
    if args.fail_on_validator_error and summary["raw_template_validator_counts"].get("ERROR", 0) > 0:
        failed = True
    if args.fail_on_validator_warn and summary["raw_template_validator_counts"].get("WARN", 0) > 0:
        failed = True
    if args.strict_json and not json_df.empty and (~json_df["valid"]).any():
        failed = True

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
