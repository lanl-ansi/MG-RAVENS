from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Union

import json
import pandas as pd


@dataclass(frozen=True)
class Discrepancy:
    """A single validation finding."""
    test: str
    severity: str  # ERROR | WARN | INFO
    path: str      # dotted path in template
    message: str
    hand: Optional[Any] = None
    auto: Optional[Any] = None
    details: Optional[Dict[str, Any]] = None


class DevTemplateValidator:
    """
    Development-focused validator for comparing HAND vs AUTO templates.

    This is intentionally *not* a strict "deep equality" checker. Instead it provides
    targeted invariants / regression tests for areas we've been actively debugging.

    Usage (interactive):
        v = DevTemplateValidator(hand_path="ravens/lib/template.json",
                                 auto_path="ravens/lib/template_auto.json")
        df = v.test_all()  # optionally pass included_class_names to classify "missing in SimplifiedDiagrams"
        df[df["severity"] == "ERROR"]
    """

    # --- Severity ordering for nicer sorting
    _SEV_ORDER = {"ERROR": 0, "WARN": 1, "INFO": 2}

    def __init__(
        self,
        *,
        hand_path: Union[str, Path],
        auto_path: Union[str, Path],
        hand: Optional[Dict[str, Any]] = None,
        auto: Optional[Dict[str, Any]] = None,
        included_class_names: Optional[Iterable[str]] = None,
    ) -> None:
        self.hand_path = Path(hand_path)
        self.auto_path = Path(auto_path)

        self.hand = hand if hand is not None else self._load_json(self.hand_path)
        self.auto = auto if auto is not None else self._load_json(self.auto_path)

        # Names of classes present in the filtered UML graphs (e.g., names_in_H = {Name for _,d in ug.H.nodes(data=True)}).
        # If provided, we can classify some HAND-vs-AUTO differences as "missing in SimplifiedDiagrams" rather than generator regressions.
        self.included_class_names: Optional[set[str]] = (
            None if included_class_names is None else {str(x) for x in included_class_names}
        )

    # -----------------
    # Public API
    # -----------------
    def test_all(self) -> pd.DataFrame:
        """
        Run all test_* methods and return a DataFrame of discrepancies.
        Columns are stable and meant for iterative development workflows.
        """
        findings: List[Discrepancy] = []

        for name in dir(self):
            if not name.startswith("test_") or name == "test_all":
                continue
            fn = getattr(self, name)
            if not callable(fn):
                continue
            try:
                out = fn()
            except Exception as e:  # keep dev workflow moving
                findings.append(
                    Discrepancy(
                        test=name,
                        severity="ERROR",
                        path="",
                        message=f"Test crashed: {type(e).__name__}: {e}",
                    )
                )
                continue

            if out:
                findings.extend(out)

        df = pd.DataFrame([self._as_row(d) for d in findings])
        if df.empty:
            # keep schema stable
            df = pd.DataFrame(
                columns=[
                    "test",
                    "severity",
                    "path",
                    "message",
                    "hand",
                    "auto",
                    "details",
                ]
            )
            return df

        df["severity_rank"] = df["severity"].map(lambda s: self._SEV_ORDER.get(str(s), 99))
        df = df.sort_values(["severity_rank", "test", "path"]).drop(columns=["severity_rank"])
        df = df.reset_index(drop=True)
        return df

    # -----------------
    # Tests
    # -----------------
    def test_operationallimitset_operationallimitvalue(self) -> List[Discrepancy]:
        """
        Regression test for:
          OperationalLimitSet.properties["OperationalLimitSet.OperationalLimitValue"]

        Expectations (current dev intent):
          - The property exists in AUTO.
          - It is an array.
          - items.anyOf includes all 10 substitutable OperationalLimit subclasses.
          - The embeddedInheritOnly base ("OperationalLimit") must NOT appear as $objectId
            anywhere in the AUTO (neither as wrapper nor as a variant).
          - Each variant object should include ONLY the base-owned dotted property:
              OperationalLimit.OperationalLimitType -> referencePath OperationalLimitType
        """
        test = "test_operationallimitset_operationallimitvalue"
        findings: List[Discrepancy] = []

        hand_sub = self._get(self.hand, ["properties", "OperationalLimitSet", "properties", "OperationalLimitSet.OperationalLimitValue"])
        auto_sub = self._get(self.auto, ["properties", "OperationalLimitSet", "properties", "OperationalLimitSet.OperationalLimitValue"])

        if hand_sub is None:
            findings.append(self._d(test, "WARN", "properties.OperationalLimitSet.properties.OperationalLimitSet.OperationalLimitValue",
                                   "HAND subtree not found (template.json differs from expected).", hand=None, auto=None))
        if auto_sub is None:
            findings.append(self._d(test, "ERROR", "properties.OperationalLimitSet.properties.OperationalLimitSet.OperationalLimitValue",
                                   "AUTO subtree missing: association OperationalLimitSet.OperationalLimitValue not emitted.", hand=hand_sub, auto=None))
            return findings  # can't do further checks

        # Type: array
        if auto_sub.get("type") != "array":
            findings.append(self._d(test, "ERROR",
                                   "properties.OperationalLimitSet.properties.OperationalLimitSet.OperationalLimitValue.type",
                                   "AUTO property should be an array.", hand=(hand_sub or {}).get("type") if isinstance(hand_sub, dict) else None,
                                   auto=auto_sub.get("type")))

        items = auto_sub.get("items")
        if not isinstance(items, dict):
            findings.append(self._d(test, "ERROR",
                                   "properties.OperationalLimitSet.properties.OperationalLimitSet.OperationalLimitValue.items",
                                   "AUTO array must define object items.", hand=(hand_sub or {}).get("items") if isinstance(hand_sub, dict) else None,
                                   auto=items))
            return findings

        # Prefer $arrayPosition present + null (matches house style)
        if "$arrayPosition" not in items:
            findings.append(self._d(test, "WARN",
                                   "properties.OperationalLimitSet.properties.OperationalLimitSet.OperationalLimitValue.items.$arrayPosition",
                                   "AUTO items wrapper is missing $arrayPosition (expected null).",
                                   hand=self._get(hand_sub, ["items", "$arrayPosition"]) if isinstance(hand_sub, dict) else None,
                                   auto=None))
        else:
            if items.get("$arrayPosition", "___MISSING___") is not None:
                findings.append(self._d(test, "ERROR",
                                       "properties.OperationalLimitSet.properties.OperationalLimitSet.OperationalLimitValue.items.$arrayPosition",
                                       "AUTO items.$arrayPosition must be null.", hand=self._get(hand_sub, ["items", "$arrayPosition"]) if isinstance(hand_sub, dict) else None,
                                       auto=items.get("$arrayPosition")))

        anyof = items.get("anyOf")
        if not isinstance(anyof, list) or len(anyof) == 0:
            findings.append(self._d(test, "ERROR",
                                   "properties.OperationalLimitSet.properties.OperationalLimitSet.OperationalLimitValue.items.anyOf",
                                   "AUTO items must include anyOf variants (substitutable OperationalLimit subclasses).",
                                   hand=self._get(hand_sub, ["items", "anyOf"]) if isinstance(hand_sub, dict) else None,
                                   auto=anyof))
            return findings

        # Collect $objectId values for variants
        auto_ids = []
        for i, obj in enumerate(anyof):
            if not isinstance(obj, dict):
                findings.append(self._d(test, "ERROR",
                                       f"...anyOf[{i}]",
                                       "AUTO anyOf element is not an object dict.",
                                       hand=None, auto=obj))
                continue
            oid = obj.get("$objectId")
            if not oid:
                findings.append(self._d(test, "ERROR",
                                       f"...anyOf[{i}].$objectId",
                                       "AUTO anyOf variant missing $objectId.",
                                       hand=None, auto=obj))
                continue
            auto_ids.append(str(oid))

        expected_ids = {
            "ActivePowerImbalanceLimit",
            "ActivePowerLimit",
            "ApparentPowerImbalanceLimit",
            "ApparentPowerLimit",
            "CurrentLimit",
            "ReactivePowerImbalanceLimit",
            "ReactivePowerLimit",
            "SwitchingActionLimit",
            "VoltageImbalanceLimit",
            "VoltageLimit",
        }

        auto_id_set = set(auto_ids)

        missing = sorted(expected_ids - auto_id_set)
        extra = sorted(auto_id_set - expected_ids)

        if missing:
            findings.append(self._d(test, "ERROR",
                                   "properties.OperationalLimitSet.properties.OperationalLimitSet.OperationalLimitValue.items.anyOf",
                                   "AUTO anyOf is missing expected OperationalLimit subclasses.",
                                   hand=sorted(expected_ids), auto=sorted(auto_id_set),
                                   details={"missing": missing}))

        if extra:
            findings.append(self._d(test, "WARN",
                                   "properties.OperationalLimitSet.properties.OperationalLimitSet.OperationalLimitValue.items.anyOf",
                                   "AUTO anyOf contains unexpected extra variants (check diagram/clusions).",
                                   hand=sorted(expected_ids), auto=sorted(auto_id_set),
                                   details={"extra": extra}))

        # Compare to HAND: ensure we didn't regress below HAND coverage
        if isinstance(hand_sub, dict):
            hand_anyof = self._get(hand_sub, ["items", "anyOf"])
            if isinstance(hand_anyof, list):
                hand_ids = sorted({(o or {}).get("$objectId") for o in hand_anyof if isinstance(o, dict) and (o or {}).get("$objectId")})
                missing_from_hand = sorted(set(hand_ids) - auto_id_set)
                if missing_from_hand:
                    findings.append(self._d(test, "ERROR",
                                           "properties.OperationalLimitSet.properties.OperationalLimitSet.OperationalLimitValue.items.anyOf",
                                           "AUTO is missing variants that exist in HAND (likely regression).",
                                           hand=hand_ids, auto=sorted(auto_id_set),
                                           details={"missing_from_hand": missing_from_hand}))
                # If AUTO has more than HAND, that's expected for this subtree (INFO)
                if len(auto_id_set) > len(hand_ids):
                    findings.append(self._d(test, "INFO",
                                           "properties.OperationalLimitSet.properties.OperationalLimitSet.OperationalLimitValue.items.anyOf",
                                           "AUTO has more variants than HAND (expected if HAND is outdated).",
                                           hand=hand_ids, auto=sorted(auto_id_set),
                                           details={"hand_count": len(hand_ids), "auto_count": len(auto_id_set)}))

        # EmbeddedInheritOnly base must not appear in AUTO subtree (or anywhere in AUTO)
        if self._contains_object_id(self.auto, "OperationalLimit"):
            findings.append(self._d(test, "ERROR",
                                   "$objectId==OperationalLimit",
                                   "AUTO contains $objectId: OperationalLimit (embeddedInheritOnly should not appear anywhere).",
                                   hand="HAND contains it in wrapper (known/outdated)", auto="FOUND"))

        # Base-only dotted property injection: ensure each variant includes only OperationalLimit.OperationalLimitType
        for i, obj in enumerate(anyof):
            if not isinstance(obj, dict):
                continue
            props = obj.get("properties") or {}
            if not isinstance(props, dict):
                findings.append(self._d(test, "ERROR", f"...anyOf[{i}].properties",
                                       "AUTO anyOf variant properties must be a dict.", hand=None, auto=props))
                continue

            key = "OperationalLimit.OperationalLimitType"
            if key not in props:
                findings.append(self._d(test, "ERROR", f"...anyOf[{i}].properties.{key}",
                                       "AUTO anyOf variant missing base-only dotted property OperationalLimit.OperationalLimitType.",
                                       hand=self._hand_variant_prop(hand_sub, obj.get("$objectId"), key), auto=None,
                                       details={"variant": obj.get("$objectId")}))

            # Check that no other properties exist (base-only requirement)
            other_keys = sorted([k for k in props.keys() if k != key])
            if other_keys:
                findings.append(self._d(test, "WARN", f"...anyOf[{i}].properties",
                                       "AUTO anyOf variant has extra properties (expected base-only).",
                                       hand=None, auto=other_keys,
                                       details={"variant": obj.get("$objectId"), "extra_keys": other_keys}))

            # Validate OperationalLimitType ref
            ref = props.get(key, {})
            if isinstance(ref, dict):
                if ref.get("$referencePath") != "OperationalLimitType":
                    findings.append(self._d(test, "ERROR", f"...anyOf[{i}].properties.{key}.$referencePath",
                                           "AUTO OperationalLimit.OperationalLimitType must reference OperationalLimitType.",
                                           hand="OperationalLimitType", auto=ref.get("$referencePath"),
                                           details={"variant": obj.get("$objectId")}))
                if ref.get("$objectType") != "reference":
                    findings.append(self._d(test, "WARN", f"...anyOf[{i}].properties.{key}.$objectType",
                                           "AUTO OperationalLimit.OperationalLimitType should have $objectType == 'reference'.",
                                           hand="reference", auto=ref.get("$objectType"),
                                           details={"variant": obj.get("$objectId")}))
            else:
                findings.append(self._d(test, "ERROR", f"...anyOf[{i}].properties.{key}",
                                       "AUTO OperationalLimit.OperationalLimitType must be a dict schema object.",
                                       hand=None, auto=ref,
                                       details={"variant": obj.get("$objectId")}))

        return findings

    # -----------------
    # Internals
    # -----------------
    def _load_json(self, path: Path) -> Dict[str, Any]:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def _as_row(self, d: Discrepancy) -> Dict[str, Any]:
        return {
            "test": d.test,
            "severity": d.severity,
            "path": d.path,
            "message": d.message,
            "hand": self._short(d.hand),
            "auto": self._short(d.auto),
            "details": d.details,
        }

    def _short(self, x: Any, maxlen: int = 600) -> Any:
        """Readable cell contents in DataFrame (avoid dumping huge dicts)."""
        if x is None:
            return None
        if isinstance(x, (str, int, float, bool)):
            return x
        try:
            s = json.dumps(x, ensure_ascii=False, sort_keys=True)
        except Exception:
            s = str(x)
        if len(s) > maxlen:
            return s[: maxlen - 3] + "..."
        return s

    def _d(
        self,
        test: str,
        severity: str,
        path: str,
        message: str,
        *,
        hand: Optional[Any] = None,
        auto: Optional[Any] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> Discrepancy:
        return Discrepancy(test=test, severity=severity, path=path, message=message, hand=hand, auto=auto, details=details)

    def _get(self, obj: Any, keys: Sequence[str]) -> Any:
        cur = obj
        for k in keys:
            if not isinstance(cur, dict):
                return None
            if k not in cur:
                return None
            cur = cur[k]
        return cur

    

    def test_curve_anyof_variants_match_hand(self) -> List[Discrepancy]:
        """Regression for Curve anyOf variant enumeration.

        If `included_class_names` was provided at init time (names from filtered ug.H),
        missing variants can be classified as:
          - WARN: present in HAND but not in filtered model (likely missing in SimplifiedDiagrams / EA diagrams)
          - ERROR: present in HAND and present in filtered model, but missing in AUTO (generator regression)

        If `included_class_names` is not provided, missing variants are reported as WARN with a note.
        """
        test = "test_curve_anyof_variants_match_hand"
        findings: List[Discrepancy] = []

        hand_curve = self._get(self.hand, ["properties", "Curve"])
        auto_curve = self._get(self.auto, ["properties", "Curve"])

        if hand_curve is None:
            return [self._d(test, "WARN", "properties.Curve",
                            "HAND template is missing Curve (cannot validate variants).",
                            hand=None, auto=auto_curve)]
        if auto_curve is None:
            return [self._d(test, "ERROR", "properties.Curve",
                            "AUTO template is missing Curve.",
                            hand=hand_curve, auto=None)]

        hand_any = hand_curve.get("anyOf")
        auto_any = auto_curve.get("anyOf")

        if not isinstance(hand_any, list) or not hand_any:
            return [self._d(test, "WARN", "properties.Curve.anyOf",
                            "HAND Curve.anyOf is missing or empty (cannot validate variants).",
                            hand=hand_any, auto=auto_any)]
        if not isinstance(auto_any, list) or not auto_any:
            return [self._d(test, "ERROR", "properties.Curve.anyOf",
                            "AUTO Curve.anyOf is missing or empty.",
                            hand=hand_any, auto=auto_any)]

        def ids(anyof: Any) -> List[str]:
            out: List[str] = []
            if not isinstance(anyof, list):
                return out
            for x in anyof:
                if isinstance(x, dict):
                    oid = x.get("$objectId")
                    if isinstance(oid, str) and oid.strip():
                        out.append(oid.strip())
            return out

        hand_ids = ids(hand_any)
        auto_ids = ids(auto_any)

        def dupes(vals: Sequence[str]) -> List[str]:
            seen = set()
            d = set()
            for v in vals:
                if v in seen:
                    d.add(v)
                else:
                    seen.add(v)
            return sorted(d, key=str.casefold)

        hand_dupes = dupes(hand_ids)
        auto_dupes = dupes(auto_ids)

        if hand_dupes:
            findings.append(self._d(test, "WARN", "properties.Curve.anyOf",
                                    "HAND Curve.anyOf contains duplicate $objectId entries.",
                                    details={"duplicates": hand_dupes}))
        if auto_dupes:
            findings.append(self._d(test, "WARN", "properties.Curve.anyOf",
                                    "AUTO Curve.anyOf contains duplicate $objectId entries.",
                                    details={"duplicates": auto_dupes}))

        hand_set = set(hand_ids)
        auto_set = set(auto_ids)

        missing_all = sorted(hand_set - auto_set, key=str.casefold)
        extra = sorted(auto_set - hand_set, key=str.casefold)

        if missing_all:
            if self.included_class_names is None:
                findings.append(self._d(
                    test, "WARN", "properties.Curve.anyOf",
                    "AUTO Curve.anyOf is missing variants present in HAND. "
                    "Pass included_class_names (names from filtered ug.H) to classify whether they are missing in SimplifiedDiagrams.",
                    details={"missing": missing_all, "hand": sorted(hand_set, key=str.casefold), "auto": sorted(auto_set, key=str.casefold)},
                ))
            else:
                missing_in_model = [v for v in missing_all if v in self.included_class_names]
                missing_not_in_model = [v for v in missing_all if v not in self.included_class_names]

                if missing_not_in_model:
                    findings.append(self._d(
                        test, "WARN", "properties.Curve.anyOf",
                        "HAND includes Curve variants that are not present in the filtered UML model (likely missing in SimplifiedDiagrams/EA diagrams).",
                        details={"missing_in_simplifieddiagrams": missing_not_in_model},
                    ))
                if missing_in_model:
                    findings.append(self._d(
                        test, "ERROR", "properties.Curve.anyOf",
                        "AUTO Curve.anyOf is missing variants that ARE present in the filtered UML model (generator regression).",
                        details={"missing": missing_in_model},
                    ))

        if extra:
            findings.append(self._d(
                test, "WARN", "properties.Curve.anyOf",
                "AUTO Curve.anyOf has extra variants not present in HAND.",
                details={"extra": extra, "hand": sorted(hand_set, key=str.casefold), "auto": sorted(auto_set, key=str.casefold)},
            ))

        return findings

    def test_switchingaction_anyof_variants_match_hand(self) -> List[Discrepancy]:
        """Regression for SwitchingAction anyOf variant enumeration.

        Classification mirrors test_curve_anyof_variants_match_hand.
        """
        test = "test_switchingaction_anyof_variants_match_hand"
        findings: List[Discrepancy] = []

        hand_sa = self._get(self.hand, ["properties", "SwitchingAction"])
        auto_sa = self._get(self.auto, ["properties", "SwitchingAction"])

        if hand_sa is None:
            return [self._d(test, "WARN", "properties.SwitchingAction",
                            "HAND template is missing SwitchingAction (cannot validate variants).",
                            hand=None, auto=auto_sa)]
        if auto_sa is None:
            return [self._d(test, "ERROR", "properties.SwitchingAction",
                            "AUTO template is missing SwitchingAction.",
                            hand=hand_sa, auto=None)]

        hand_any = hand_sa.get("anyOf")
        auto_any = auto_sa.get("anyOf")

        if not isinstance(hand_any, list) or not hand_any:
            return [self._d(test, "WARN", "properties.SwitchingAction.anyOf",
                            "HAND SwitchingAction.anyOf is missing or empty (cannot validate variants).",
                            hand=hand_any, auto=auto_any)]
        if not isinstance(auto_any, list) or not auto_any:
            return [self._d(test, "ERROR", "properties.SwitchingAction.anyOf",
                            "AUTO SwitchingAction.anyOf is missing or empty.",
                            hand=hand_any, auto=auto_any)]

        def ids(anyof: Any) -> List[str]:
            out: List[str] = []
            if not isinstance(anyof, list):
                return out
            for x in anyof:
                if isinstance(x, dict):
                    oid = x.get("$objectId")
                    if isinstance(oid, str) and oid.strip():
                        out.append(oid.strip())
            return out

        hand_ids = ids(hand_any)
        auto_ids = ids(auto_any)

        def dupes(vals: Sequence[str]) -> List[str]:
            seen = set()
            d = set()
            for v in vals:
                if v in seen:
                    d.add(v)
                else:
                    seen.add(v)
            return sorted(d, key=str.casefold)

        hand_dupes = dupes(hand_ids)
        auto_dupes = dupes(auto_ids)

        if hand_dupes:
            findings.append(self._d(test, "WARN", "properties.SwitchingAction.anyOf",
                                    "HAND SwitchingAction.anyOf contains duplicate $objectId entries.",
                                    details={"duplicates": hand_dupes}))
        if auto_dupes:
            findings.append(self._d(test, "WARN", "properties.SwitchingAction.anyOf",
                                    "AUTO SwitchingAction.anyOf contains duplicate $objectId entries.",
                                    details={"duplicates": auto_dupes}))

        hand_set = set(hand_ids)
        auto_set = set(auto_ids)

        missing_all = sorted(hand_set - auto_set, key=str.casefold)
        extra = sorted(auto_set - hand_set, key=str.casefold)

        if missing_all:
            if self.included_class_names is None:
                findings.append(self._d(
                    test, "WARN", "properties.SwitchingAction.anyOf",
                    "AUTO SwitchingAction.anyOf is missing variants present in HAND. "
                    "Pass included_class_names (names from filtered ug.H) to classify whether they are missing in SimplifiedDiagrams.",
                    details={"missing": missing_all, "hand": sorted(hand_set, key=str.casefold), "auto": sorted(auto_set, key=str.casefold)},
                ))
            else:
                missing_in_model = [v for v in missing_all if v in self.included_class_names]
                missing_not_in_model = [v for v in missing_all if v not in self.included_class_names]

                if missing_not_in_model:
                    findings.append(self._d(
                        test, "WARN", "properties.SwitchingAction.anyOf",
                        "HAND includes SwitchingAction variants that are not present in the filtered UML model (likely missing in SimplifiedDiagrams/EA diagrams).",
                        details={"missing_in_simplifieddiagrams": missing_not_in_model},
                    ))
                if missing_in_model:
                    findings.append(self._d(
                        test, "ERROR", "properties.SwitchingAction.anyOf",
                        "AUTO SwitchingAction.anyOf is missing variants that ARE present in the filtered UML model (generator regression).",
                        details={"missing": missing_in_model},
                    ))

        if extra:
            findings.append(self._d(
                test, "WARN", "properties.SwitchingAction.anyOf",
                "AUTO SwitchingAction.anyOf has extra variants not present in HAND.",
                details={"extra": extra, "hand": sorted(hand_set, key=str.casefold), "auto": sorted(auto_set, key=str.casefold)},
            ))

        return findings

    def _contains_object_id(self, obj: Any, object_id: str) -> bool:
        """Deep search for a particular $objectId value."""
        if isinstance(obj, dict):
            if obj.get("$objectId") == object_id:
                return True
            return any(self._contains_object_id(v, object_id) for v in obj.values())
        if isinstance(obj, list):
            return any(self._contains_object_id(v, object_id) for v in obj)
        return False

    def _hand_variant_prop(self, hand_sub: Any, variant_id: Any, prop_key: str) -> Any:
        """Helper: look up a property in HAND anyOf member by $objectId."""
        if not isinstance(hand_sub, dict):
            return None
        anyof = self._get(hand_sub, ["items", "anyOf"])
        if not isinstance(anyof, list):
            return None
        for obj in anyof:
            if isinstance(obj, dict) and obj.get("$objectId") == variant_id:
                props = obj.get("properties") or {}
                if isinstance(props, dict):
                    return props.get(prop_key)
        return None
