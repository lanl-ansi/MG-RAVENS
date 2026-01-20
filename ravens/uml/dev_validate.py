from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import json
import pandas as pd
import re


@dataclass
class Discrepancy:
    test: str
    severity: str  # "ERROR" | "WARN" | "INFO"
    path: str
    message: str
    hand: Any = None
    auto: Any = None
    details: Any = None


class DevTemplateValidator:
    """
    Development-focused validator for comparing specific fragile subtrees between
    HAND and AUTO templates.

    Add new regression checks by creating new methods named `test_*` that return
    `List[Discrepancy]`. `test_all()` runs them all and returns a DataFrame.

    Path syntax for discrepancies:
      - Dot segments access dict keys without dots.
      - Bracket notation accesses arbitrary keys:
          properties.OperationalLimitSet.properties["OperationalLimitSet.OperationalLimitValue"]
    """

    def __init__(self, hand_path: Union[str, Path], auto_path: Union[str, Path]) -> None:
        self.hand_path = Path(hand_path)
        self.auto_path = Path(auto_path)

        self.hand = self._load_json(self.hand_path)
        self.auto = self._load_json(self.auto_path)

        # Cache raw strings for fast global searches (e.g., ensure something never appears)
        self._hand_text = json.dumps(self.hand, sort_keys=True)
        self._auto_text = json.dumps(self.auto, sort_keys=True)

    @staticmethod
    def _load_json(path: Path) -> Dict[str, Any]:
        if not path.exists():
            raise FileNotFoundError(f"Template file not found: {path}")
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)

    # ----------------------------
    # Path helpers (handles dotted keys)
    # ----------------------------
    @staticmethod
    def _tokenize_path(path: str) -> List[str]:
        """
        Tokenize a mixed dot/bracket path into dict keys.

        Examples:
          properties.OperationalLimitSet.properties["OperationalLimitSet.OperationalLimitValue"]
          properties.Root.properties["$schema"]
        """
        tokens: List[str] = []
        i = 0
        n = len(path)

        def skip_ws(j: int) -> int:
            while j < n and path[j].isspace():
                j += 1
            return j

        while i < n:
            i = skip_ws(i)
            if i >= n:
                break

            if path[i] == ".":
                i += 1
                continue

            if path[i] == "[":
                # Parse ["..."] or ['...']
                i += 1
                i = skip_ws(i)
                if i >= n or path[i] not in ("'", '"'):
                    raise ValueError(f"Invalid bracket token in path: {path}")
                quote = path[i]
                i += 1
                start = i
                while i < n:
                    if path[i] == quote and path[i - 1] != "\\":
                        break
                    i += 1
                if i >= n:
                    raise ValueError(f"Unterminated quote in path: {path}")
                key = path[start:i]
                # Unescape \" and \'
                key = key.replace(r"\\", "\\").replace(r"\"","\"").replace(r"\'","'")
                i += 1
                i = skip_ws(i)
                if i >= n or path[i] != "]":
                    raise ValueError(f"Missing closing ] in path: {path}")
                i += 1
                tokens.append(key)
                continue

            # Plain identifier: read until '.' or '['
            start = i
            while i < n and path[i] not in ".[":
                i += 1
            key = path[start:i].strip()
            if key:
                tokens.append(key)

        return tokens

    @classmethod
    def _get(cls, d: Any, path: str) -> Any:
        """Getter for dicts using mixed dot/bracket syntax. Returns None if missing."""
        cur: Any = d
        for key in cls._tokenize_path(path):
            if not isinstance(cur, dict) or key not in cur:
                return None
            cur = cur[key]
        return cur

    # ----------------------------
    # Running tests
    # ----------------------------
    def test_all(self) -> pd.DataFrame:
        rows: List[Dict[str, Any]] = []
        for name in sorted(dir(self)):
            if not name.startswith("test_") or name == "test_all":
                continue
            fn = getattr(self, name)
            if not callable(fn):
                continue

            out: List[Discrepancy] = fn()
            for d in out:
                rows.append(asdict(d))

        df = pd.DataFrame(rows, columns=[
            "test", "severity", "path", "message", "hand", "auto", "details"
        ])
        return df

    # ----------------------------
    # Tests
    # ----------------------------
    def test_root_top_level_objects_match(self) -> List[Discrepancy]:
        """
        Compare the set of top-level objects under the schema root (schema['properties'])
        between HAND and AUTO.

        Notes:
          - This does NOT expect a literal 'Root' property key (the schema root *is* Root).
          - Missing-in-AUTO keys that exist in HAND are ERRORs (regressions).
          - Extra keys present only in AUTO are WARNs (AUTO may legitimately be ahead of HAND).
        """
        test = "test_root_top_level_objects_match"
        out: List[Discrepancy] = []

        hand_props = self.hand.get("properties")
        auto_props = self.auto.get("properties")

        if not isinstance(hand_props, dict):
            out.append(Discrepancy(
                test=test,
                severity="ERROR",
                path="properties",
                message="HAND template is missing top-level 'properties' dict",
                hand=hand_props,
            ))
            return out

        if not isinstance(auto_props, dict):
            out.append(Discrepancy(
                test=test,
                severity="ERROR",
                path="properties",
                message="AUTO template is missing top-level 'properties' dict",
                auto=auto_props,
            ))
            return out

        hand_keys = set(hand_props.keys())
        auto_keys = set(auto_props.keys())

        missing_in_auto = sorted(hand_keys - auto_keys, key=str.casefold)
        extra_in_auto = sorted(auto_keys - hand_keys, key=str.casefold)

        for k in missing_in_auto:
            out.append(Discrepancy(
                test=test,
                severity="ERROR",
                path=f'properties["{k}"]' if "." in k else f"properties.{k}",
                message="AUTO is missing a top-level object present in HAND",
                details={"missing": k},
            ))

        for k in extra_in_auto:
            out.append(Discrepancy(
                test=test,
                severity="WARN",
                path=f'properties["{k}"]' if "." in k else f"properties.{k}",
                message="AUTO has an extra top-level object not present in HAND",
                details={"extra": k},
            ))

        return out

    def test_no_anyof_with_properties(self) -> List[Discrepancy]:
        """
        HAND convention guardrail:
          - No dict node should contain BOTH 'anyOf' and 'properties' at the same level.

        This catches accidental creation of properties on anyOf wrappers (e.g., Fault, FossilFuel).
        """
        test = "test_no_anyof_with_properties"
        out: List[Discrepancy] = []

        def walk(obj: Any, prefix: str, which: str):
            if isinstance(obj, dict):
                if obj.get("$objectType") == "object" and "anyOf" in obj and "properties" in obj:
                    out.append(Discrepancy(
                        test=test,
                        severity=("ERROR" if which == "AUTO" else "WARN"),
                        path=prefix or "<root>",
                        message=f"{which} node has both anyOf and properties (HAND convention forbids this)",
                        details={"keys": sorted(list(obj.keys()))},
                    ))
                for k, v in obj.items():
                    # prefer bracket paths for dotted keys
                    if prefix:
                        if "." in k or k.startswith("$"):
                            np = f'{prefix}["{k}"]'
                        else:
                            np = f"{prefix}.{k}"
                    else:
                        np = f'["{k}"]' if ("." in k or k.startswith("$")) else k
                    walk(v, np, which)
            elif isinstance(obj, list):
                for i, v in enumerate(obj):
                    walk(v, f"{prefix}[{i}]", which)

        walk(self.hand, "", "HAND")
        walk(self.auto, "", "AUTO")
        return out

    def test_fault_anyof_wrapper(self) -> List[Discrepancy]:
        """
        Regression for Fault:
          - HAND uses an anyOf-only wrapper: properties.Fault has anyOf and NO properties.
          - AUTO should match that structure.
          - AUTO anyOf variant set should contain at least the HAND variants.
          - Common association-backed props from HAND (intersection across HAND anyOf members)
            must appear in every AUTO anyOf member's properties.
        """
        test = "test_fault_anyof_wrapper"
        out: List[Discrepancy] = []

        hand_fault = self._get(self.hand, "properties.Fault")
        auto_fault = self._get(self.auto, "properties.Fault")

        if hand_fault is None:
            out.append(Discrepancy(
                test=test,
                severity="WARN",
                path="properties.Fault",
                message="HAND template is missing Fault (unexpected, but can't validate)",
            ))
            return out

        if auto_fault is None:
            out.append(Discrepancy(
                test=test,
                severity="ERROR",
                path="properties.Fault",
                message="AUTO template is missing Fault",
            ))
            return out

        # Structure checks
        if "anyOf" not in auto_fault or not isinstance(auto_fault.get("anyOf"), list) or not auto_fault["anyOf"]:
            out.append(Discrepancy(
                test=test,
                severity="ERROR",
                path="properties.Fault.anyOf",
                message="AUTO Fault should be an anyOf wrapper with non-empty anyOf list",
                auto=auto_fault.get("anyOf"),
            ))
            return out

        if "properties" in auto_fault:
            out.append(Discrepancy(
                test=test,
                severity="ERROR",
                path="properties.Fault.properties",
                message="AUTO Fault anyOf wrapper must not also define 'properties' (HAND convention)",
                details={"auto_keys": sorted(list(auto_fault.keys()))},
            ))

        # Variant set comparison (by $objectId)
        def ids(anyof: Any) -> List[str]:
            if not isinstance(anyof, list):
                return []
            out_ids: List[str] = []
            for x in anyof:
                if isinstance(x, dict):
                    oid = x.get("$objectId")
                    if isinstance(oid, str) and oid.strip():
                        out_ids.append(oid.strip())
            return out_ids

        hand_ids = ids(hand_fault.get("anyOf"))
        auto_ids = ids(auto_fault.get("anyOf"))

        missing = [x for x in hand_ids if x not in auto_ids]
        extra = [x for x in auto_ids if x not in hand_ids]

        if missing:
            out.append(Discrepancy(
                test=test,
                severity="ERROR",
                path="properties.Fault.anyOf",
                message="AUTO Fault.anyOf is missing variants present in HAND",
                details={"missing": missing, "hand": hand_ids, "auto": auto_ids},
            ))
        if extra:
            out.append(Discrepancy(
                test=test,
                severity="WARN",
                path="properties.Fault.anyOf",
                message="AUTO Fault.anyOf has extra variants not in HAND",
                details={"extra": extra, "hand": hand_ids, "auto": auto_ids},
            ))

        # Common props required: intersection of HAND anyOf member properties keys
        hand_anyof = hand_fault.get("anyOf", [])
        common_props: Optional[set[str]] = None
        for mem in hand_anyof:
            if not isinstance(mem, dict):
                continue
            props = mem.get("properties")
            if not isinstance(props, dict):
                continue
            ks = set(props.keys())
            common_props = ks if common_props is None else (common_props & ks)

        if not common_props:
            # If HAND doesn't define properties on members, nothing more we can check.
            return out

        auto_anyof = auto_fault.get("anyOf", [])
        for i, mem in enumerate(auto_anyof):
            if not isinstance(mem, dict):
                continue
            props = mem.get("properties")
            if not isinstance(props, dict):
                out.append(Discrepancy(
                    test=test,
                    severity="ERROR",
                    path=f"properties.Fault.anyOf[{i}].properties",
                    message="AUTO Fault anyOf member is missing properties dict",
                    details={"member": mem.get("$objectId")},
                ))
                continue
            missing_props = [k for k in sorted(common_props) if k not in props]
            if missing_props:
                out.append(Discrepancy(
                    test=test,
                    severity="ERROR",
                    path=f"properties.Fault.anyOf[{i}].properties",
                    message="AUTO Fault anyOf member is missing common HAND properties",
                    details={"member": mem.get("$objectId"), "missing": missing_props},
                ))

        return out

    def test_operationallimitset_operationallimitvalue(self) -> List[Discrepancy]:
        """
        Regression test for:
          OperationalLimitSet.properties["OperationalLimitSet.OperationalLimitValue"]

        Expectations (AUTO-focused):
          - Property exists and is an array with items.anyOf.
          - anyOf includes all 10 expected substitutable subclasses.
          - Variants have base-only injected property OperationalLimit.OperationalLimitType.
          - Variants do NOT have OperationalLimit.OperationalLimitValue.
          - The inherit-only base OperationalLimit must NOT appear as $objectId anywhere in AUTO.
        """
        test = "test_operationallimitset_operationallimitvalue"
        out: List[Discrepancy] = []

        prop_key = "OperationalLimitSet.OperationalLimitValue"
        auto_prop_path = f'properties.OperationalLimitSet.properties["{prop_key}"]'
        hand_prop_path = f'properties.OperationalLimitSet.properties["{prop_key}"]'

        auto_node = self._get(self.auto, auto_prop_path)
        hand_node = self._get(self.hand, hand_prop_path)

        if hand_node is None:
            out.append(Discrepancy(
                test=test,
                severity="WARN",
                path=hand_prop_path,
                message="HAND template is missing this property (may be expected if HAND is stale)",
            ))
        if auto_node is None:
            out.append(Discrepancy(
                test=test,
                severity="ERROR",
                path=auto_prop_path,
                message="AUTO template is missing this property",
                hand=hand_node,
                auto=auto_node,
            ))
            return out

        if auto_node.get("type") != "array":
            out.append(Discrepancy(
                test=test,
                severity="ERROR",
                path=auto_prop_path,
                message='AUTO property should be type="array"',
                auto=auto_node.get("type"),
                details={"expected": "array"},
            ))

        items = auto_node.get("items")
        if not isinstance(items, dict):
            out.append(Discrepancy(
                test=test,
                severity="ERROR",
                path=auto_prop_path + ".items",
                message="AUTO property missing dict `items`",
                auto=items,
            ))
            return out

        anyof = items.get("anyOf")
        if not isinstance(anyof, list) or len(anyof) == 0:
            out.append(Discrepancy(
                test=test,
                severity="ERROR",
                path=auto_prop_path + ".items.anyOf",
                message="AUTO items.anyOf is missing or empty",
                auto=anyof,
            ))
            return out

        expected = sorted([
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
        ])
        got = sorted([x.get("$objectId") for x in anyof if isinstance(x, dict)])

        missing = [x for x in expected if x not in got]
        extra = [x for x in got if x not in expected and x is not None]

        if missing:
            out.append(Discrepancy(
                test=test,
                severity="ERROR",
                path=auto_prop_path + ".items.anyOf",
                message="AUTO anyOf is missing expected variants",
                details={"missing": missing, "got": got},
            ))
        if extra:
            out.append(Discrepancy(
                test=test,
                severity="WARN",
                path=auto_prop_path + ".items.anyOf",
                message="AUTO anyOf has unexpected extra variants",
                details={"extra": extra, "expected": expected},
            ))

        if re.search(r'"\$objectId"\s*:\s*"OperationalLimit"', self._auto_text):
            out.append(Discrepancy(
                test=test,
                severity="ERROR",
                path='$..["$objectId"]',
                message='AUTO contains "$objectId": "OperationalLimit" but embeddedInheritOnly bases must never appear',
            ))

        expected_base_prop = "OperationalLimit.OperationalLimitType"
        forbidden_prop = "OperationalLimit.OperationalLimitValue"

        for idx, variant in enumerate(anyof):
            if not isinstance(variant, dict):
                continue
            v_id = variant.get("$objectId", f"idx{idx}")
            v_path = auto_prop_path + f".items.anyOf[{idx}]"

            props = variant.get("properties", {})
            if not isinstance(props, dict):
                out.append(Discrepancy(
                    test=test,
                    severity="ERROR",
                    path=v_path + ".properties",
                    message="Variant is missing dict `properties`",
                    auto=props,
                    details={"variant": v_id},
                ))
                continue

            if forbidden_prop in props:
                out.append(Discrepancy(
                    test=test,
                    severity="ERROR",
                    path=v_path + f'.properties["{forbidden_prop}"]',
                    message=f"Variant incorrectly contains forbidden injected property {forbidden_prop}",
                    details={"variant": v_id},
                ))

            if expected_base_prop not in props:
                out.append(Discrepancy(
                    test=test,
                    severity="ERROR",
                    path=v_path + f'.properties["{expected_base_prop}"]',
                    message=f"Variant is missing base-only injected property {expected_base_prop}",
                    details={"variant": v_id, "present_props": sorted(list(props.keys()))},
                ))
            else:
                p = props[expected_base_prop]
                refpath = (p or {}).get("$referencePath") if isinstance(p, dict) else None
                if refpath != "OperationalLimitType":
                    out.append(Discrepancy(
                        test=test,
                        severity="ERROR",
                        path=v_path + f'.properties["{expected_base_prop}"].$referencePath',
                        message="Base-only injected property should reference OperationalLimitType",
                        auto=refpath,
                        details={"expected": "OperationalLimitType", "variant": v_id},
                    ))

        return out

    def test_location_association_properties(self) -> List[Discrepancy]:
        """
        Regression test for Location association-backed dotted properties.

        Expected (per HAND + UML diagrams):
          - Location.properties["Location.PositionPoints"] exists
              - type == "array"
              - items.$objectType == "object"
              - items.$objectId == "PositionPoint"
              - items.$arrayPosition == "PositionPoint.sequenceNumber" (if present in AUTO)
          - Location.properties["Location.CoordinateSystem"] exists
              - $objectType == "reference"
              - $objectId == "CoordinateSystem"
              - $referencePath == "CoordinateSystem"
        """
        test = "test_location_association_properties"
        out: List[Discrepancy] = []

        pp_key = "Location.PositionPoints"
        pp_path = f'properties.Location.properties["{pp_key}"]'
        hand_pp = self._get(self.hand, pp_path)
        auto_pp = self._get(self.auto, pp_path)

        if hand_pp is None:
            out.append(Discrepancy(
                test=test,
                severity="WARN",
                path=pp_path,
                message="HAND template is missing Location.PositionPoints (HAND may be stale)",
            ))
        if auto_pp is None:
            out.append(Discrepancy(
                test=test,
                severity="ERROR",
                path=pp_path,
                message="AUTO template is missing Location.PositionPoints",
                hand=hand_pp,
                auto=auto_pp,
            ))
        else:
            if auto_pp.get("type") != "array":
                out.append(Discrepancy(
                    test=test,
                    severity="ERROR",
                    path=pp_path + ".type",
                    message='Location.PositionPoints should have type="array"',
                    auto=auto_pp.get("type"),
                ))
            items = auto_pp.get("items")
            if not isinstance(items, dict):
                out.append(Discrepancy(
                    test=test,
                    severity="ERROR",
                    path=pp_path + ".items",
                    message="Location.PositionPoints is missing dict items",
                    auto=items,
                ))
            else:
                if items.get("$objectType") != "object":
                    out.append(Discrepancy(
                        test=test,
                        severity="ERROR",
                        path=pp_path + '.items.$objectType',
                        message="Location.PositionPoints.items should be an embedded object (not a reference)",
                        auto=items.get("$objectType"),
                    ))
                if items.get("$objectId") != "PositionPoint":
                    out.append(Discrepancy(
                        test=test,
                        severity="ERROR",
                        path=pp_path + '.items.$objectId',
                        message="Location.PositionPoints.items should have $objectId = PositionPoint",
                        auto=items.get("$objectId"),
                    ))
                ap = items.get("$arrayPosition")
                if ap is not None and ap != "PositionPoint.sequenceNumber":
                    out.append(Discrepancy(
                        test=test,
                        severity="WARN",
                        path=pp_path + '.items.$arrayPosition',
                        message="Unexpected $arrayPosition for PositionPoint items",
                        auto=ap,
                        details={"expected": "PositionPoint.sequenceNumber"},
                    ))

        cs_key = "Location.CoordinateSystem"
        cs_path = f'properties.Location.properties["{cs_key}"]'
        hand_cs = self._get(self.hand, cs_path)
        auto_cs = self._get(self.auto, cs_path)

        if hand_cs is None:
            out.append(Discrepancy(
                test=test,
                severity="WARN",
                path=cs_path,
                message="HAND template is missing Location.CoordinateSystem (HAND may be stale)",
            ))
        if auto_cs is None:
            out.append(Discrepancy(
                test=test,
                severity="ERROR",
                path=cs_path,
                message="AUTO template is missing Location.CoordinateSystem",
                hand=hand_cs,
                auto=auto_cs,
            ))
        else:
            if auto_cs.get("$objectType") != "reference":
                out.append(Discrepancy(
                    test=test,
                    severity="ERROR",
                    path=cs_path + '.$objectType',
                    message="Location.CoordinateSystem should be a reference",
                    auto=auto_cs.get("$objectType"),
                ))
            if auto_cs.get("$objectId") != "CoordinateSystem":
                out.append(Discrepancy(
                    test=test,
                    severity="ERROR",
                    path=cs_path + '.$objectId',
                    message="Location.CoordinateSystem should have $objectId=CoordinateSystem",
                    auto=auto_cs.get("$objectId"),
                ))
            if auto_cs.get("$referencePath") != "CoordinateSystem":
                out.append(Discrepancy(
                    test=test,
                    severity="ERROR",
                    path=cs_path + '.$referencePath',
                    message="Location.CoordinateSystem should reference CoordinateSystem",
                    auto=auto_cs.get("$referencePath"),
                ))

        return out

    def test_curve_anyof_variants_match_hand(self) -> List[Discrepancy]:
        """Regression for Curve anyOf variant enumeration.

        HAND is the target structure: AUTO should include at least the same set of $objectId
        variants under properties.Curve.anyOf.

        - Missing-in-AUTO variants present in HAND: ERROR
        - Extra variants present only in AUTO: WARN
        """
        test = "test_curve_anyof_variants_match_hand"
        out: List[Discrepancy] = []

        hand_curve = self._get(self.hand, "properties.Curve")
        auto_curve = self._get(self.auto, "properties.Curve")

        if hand_curve is None:
            out.append(Discrepancy(
                test=test,
                severity="WARN",
                path="properties.Curve",
                message="HAND template is missing Curve (cannot validate variants)",
            ))
            return out

        if auto_curve is None:
            out.append(Discrepancy(
                test=test,
                severity="ERROR",
                path="properties.Curve",
                message="AUTO template is missing Curve",
            ))
            return out

        def ids(anyof: Any) -> List[str]:
            if not isinstance(anyof, list):
                return []
            out_ids: List[str] = []
            for x in anyof:
                if isinstance(x, dict):
                    oid = x.get("$objectId")
                    if isinstance(oid, str) and oid.strip():
                        out_ids.append(oid.strip())
            return out_ids

        hand_ids = ids(hand_curve.get("anyOf"))
        auto_ids = ids(auto_curve.get("anyOf"))

        # Duplicate detection (hand issues shouldn't fail AUTO, but are useful to surface)
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
            out.append(Discrepancy(
                test=test,
                severity="WARN",
                path="properties.Curve.anyOf",
                message="HAND Curve.anyOf contains duplicate $objectId entries",
                details={"duplicates": hand_dupes},
            ))

        if auto_dupes:
            out.append(Discrepancy(
                test=test,
                severity="WARN",
                path="properties.Curve.anyOf",
                message="AUTO Curve.anyOf contains duplicate $objectId entries",
                details={"duplicates": auto_dupes},
            ))

        hand_set = set(hand_ids)
        auto_set = set(auto_ids)

        missing = sorted(hand_set - auto_set, key=str.casefold)
        extra = sorted(auto_set - hand_set, key=str.casefold)

        if missing:
            out.append(Discrepancy(
                test=test,
                severity="ERROR",
                path="properties.Curve.anyOf",
                message="AUTO Curve.anyOf is missing variants present in HAND",
                details={"missing": missing, "hand": sorted(hand_set, key=str.casefold), "auto": sorted(auto_set, key=str.casefold)},
            ))

        if extra:
            out.append(Discrepancy(
                test=test,
                severity="WARN",
                path="properties.Curve.anyOf",
                message="AUTO Curve.anyOf has extra variants not present in HAND",
                details={"extra": extra, "hand": sorted(hand_set, key=str.casefold), "auto": sorted(auto_set, key=str.casefold)},
            ))

        return out

    def test_switchingaction_anyof_variants_match_hand(self) -> List[Discrepancy]:
        """Regression for SwitchingAction anyOf variant enumeration.

        HAND is the target structure: AUTO should include at least the same set of $objectId
        variants under properties.SwitchingAction.anyOf.

        - Missing-in-AUTO variants present in HAND: ERROR
        - Extra variants present only in AUTO: WARN
        """
        test = "test_switchingaction_anyof_variants_match_hand"
        out: List[Discrepancy] = []

        hand_sa = self._get(self.hand, "properties.SwitchingAction")
        auto_sa = self._get(self.auto, "properties.SwitchingAction")

        if hand_sa is None:
            out.append(Discrepancy(
                test=test,
                severity="WARN",
                path="properties.SwitchingAction",
                message="HAND template is missing SwitchingAction (cannot validate variants)",
            ))
            return out

        if auto_sa is None:
            out.append(Discrepancy(
                test=test,
                severity="ERROR",
                path="properties.SwitchingAction",
                message="AUTO template is missing SwitchingAction",
            ))
            return out

        def ids(anyof: Any) -> List[str]:
            if not isinstance(anyof, list):
                return []
            out_ids: List[str] = []
            for x in anyof:
                if isinstance(x, dict):
                    oid = x.get("$objectId")
                    if isinstance(oid, str) and oid.strip():
                        out_ids.append(oid.strip())
            return out_ids

        hand_ids = ids(hand_sa.get("anyOf"))
        auto_ids = ids(auto_sa.get("anyOf"))

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
            out.append(Discrepancy(
                test=test,
                severity="WARN",
                path="properties.SwitchingAction.anyOf",
                message="HAND SwitchingAction.anyOf contains duplicate $objectId entries",
                details={"duplicates": hand_dupes},
            ))

        if auto_dupes:
            out.append(Discrepancy(
                test=test,
                severity="WARN",
                path="properties.SwitchingAction.anyOf",
                message="AUTO SwitchingAction.anyOf contains duplicate $objectId entries",
                details={"duplicates": auto_dupes},
            ))

        hand_set = set(hand_ids)
        auto_set = set(auto_ids)

        missing = sorted(hand_set - auto_set, key=str.casefold)
        extra = sorted(auto_set - hand_set, key=str.casefold)

        if missing:
            out.append(Discrepancy(
                test=test,
                severity="ERROR",
                path="properties.SwitchingAction.anyOf",
                message="AUTO SwitchingAction.anyOf is missing variants present in HAND",
                details={"missing": missing, "hand": sorted(hand_set, key=str.casefold), "auto": sorted(auto_set, key=str.casefold)},
            ))

        if extra:
            out.append(Discrepancy(
                test=test,
                severity="WARN",
                path="properties.SwitchingAction.anyOf",
                message="AUTO SwitchingAction.anyOf has extra variants not present in HAND",
                details={"extra": extra, "hand": sorted(hand_set, key=str.casefold), "auto": sorted(auto_set, key=str.casefold)},
            ))

        return out
