from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

import pandas as pd

from ravens.schema import RavensSchema


@dataclass(frozen=True)
class SchemaKeyDiff:
    key: str
    status: str
    hand: bool
    auto: bool


class SchemaComparator:
    def __init__(
        self,
        hand_schema: RavensSchema | None = None,
        auto_schema: RavensSchema | None = None,
        *,
        omit_license: bool = True,
        omit_descriptions: bool = False,
    ):
        self.hand_schema = hand_schema if hand_schema is not None else RavensSchema(
            template_source="hand",
            omit_license=omit_license,
            omit_descriptions=omit_descriptions,
        )
        self.auto_schema = auto_schema if auto_schema is not None else RavensSchema(
            template_source="auto",
            omit_license=omit_license,
            omit_descriptions=omit_descriptions,
        )

    @staticmethod
    def _schema_keys(schema: RavensSchema) -> set[str]:
        return set(schema.schemas.keys())

    @staticmethod
    def _strip_suffix(s: str, suffix: str) -> str:
        return s[:-len(suffix)] if s.endswith(suffix) else s

    def _normalize_schema_key(self, key: str, schema: RavensSchema) -> str:
        prefix = (schema.base_id_uri or "").rstrip("/") + "/"
        name = key[len(prefix):] if key.startswith(prefix) else key
        if not schema.omit_file_extension:
            name = self._strip_suffix(name, ".json")
        return name

    @staticmethod
    def _collect_template_hits(template: Any, *, key: str | None = None, object_id: str | None = None) -> dict[str, bool]:
        hits = {
            "as_key": False,
            "as_objectid": False,
        }

        def visit(node: Any):
            if isinstance(node, dict):
                if object_id is not None and node.get("$objectId") == object_id:
                    hits["as_objectid"] = True
                for k, v in node.items():
                    if key is not None and k == key:
                        hits["as_key"] = True
                    visit(v)
            elif isinstance(node, list):
                for item in node:
                    visit(item)

        visit(template)
        return hits

    def _uml_class_names(self) -> set[str]:
        objs = self.hand_schema.uml_data.objects
        mask = objs["Object_Type"] == "Class"
        return set(objs.loc[mask, "Name"].dropna().astype(str).tolist())

    def _simplified_package_ids(self) -> set[int]:
        pkgs = self.hand_schema.uml_data.packages
        roots = pkgs[pkgs["Name"] == "SimplifiedDiagrams"]
        if roots.empty:
            return set()

        ids = set(int(i) for i in roots.index.tolist())
        changed = True
        while changed:
            changed = False
            children = pkgs[pkgs["Parent_ID"].isin(ids)]
            child_ids = set(int(i) for i in children.index.tolist())
            new_ids = child_ids - ids
            if new_ids:
                ids |= new_ids
                changed = True
        return ids

    def _diagram_status(self, class_name: str) -> dict[str, Any]:
        objs = self.hand_schema.uml_data.objects
        rows = objs[(objs["Name"] == class_name) & (objs["Object_Type"] == "Class")]
        if rows.empty:
            return {
                "diagram_exclusion_status": "not_in_uml",
                "diagram_names": [],
                "excluded_diagram_names": [],
                "kept_diagram_names": [],
                "root_diagram_names": [],
                "kept_nonroot_diagram_names": [],
                "global_diagram_names": [],
                "global_excluded_diagram_names": [],
                "global_kept_diagram_names": [],
            }

        obj_id = int(rows.index[0])
        dobj = self.hand_schema.uml_data.diagramobjects
        drows = dobj[dobj["Object_ID"] == obj_id]
        if drows.empty:
            return {
                "diagram_exclusion_status": "not_on_any_diagram",
                "diagram_names": [],
                "excluded_diagram_names": [],
                "kept_diagram_names": [],
                "root_diagram_names": [],
                "kept_nonroot_diagram_names": [],
                "global_diagram_names": [],
                "global_excluded_diagram_names": [],
                "global_kept_diagram_names": [],
            }

        dgms = self.hand_schema.uml_data.diagrams
        global_names = sorted(
            set(
                dgms[dgms.index.isin(drows["Diagram_ID"].tolist())]["Name"]
                .dropna()
                .astype(str)
                .tolist()
            )
        )
        global_excluded = [n for n in global_names if n.startswith(("Inf", "Mkt"))]
        global_kept = [n for n in global_names if not n.startswith(("Inf", "Mkt"))]

        simp_pkg_ids = self._simplified_package_ids()
        sdgms = dgms[dgms["Package_ID"].isin(simp_pkg_ids)] if simp_pkg_ids else dgms.iloc[0:0]
        names = sorted(
            set(
                sdgms[sdgms.index.isin(drows["Diagram_ID"].tolist())]["Name"]
                .dropna()
                .astype(str)
                .tolist()
            )
        )

        if not names:
            status = "not_on_any_simplified_diagram"
            excluded = []
            kept = []
            root_names = []
            kept_nonroot = []
        else:
            excluded = [n for n in names if n.startswith(("Inf", "Mkt"))]
            kept = [n for n in names if not n.startswith(("Inf", "Mkt"))]
            root_names = [n for n in names if n == "Root"]
            kept_nonroot = [n for n in kept if n != "Root"]
            if excluded and not kept:
                status = "excluded_by_inf_mkt_diagram_only"
            elif excluded and kept:
                status = "present_on_kept_and_excluded_diagrams"
            else:
                status = "not_on_excluded_diagrams"

        return {
            "diagram_exclusion_status": status,
            "diagram_names": names,
            "excluded_diagram_names": excluded,
            "kept_diagram_names": kept,
            "root_diagram_names": root_names,
            "kept_nonroot_diagram_names": kept_nonroot,
            "global_diagram_names": global_names,
            "global_excluded_diagram_names": global_excluded,
            "global_kept_diagram_names": global_kept,
        }

    @staticmethod
    def _base_template_name(schema_name: str) -> str:
        base = schema_name
        for suffix in (
            "_anyOfPointer_anyOfContainer",
            "_Pointer_anyOfContainer",
            "_anyOfContainer",
            "_PointerArray",
            "_Pointer",
            "_Container",
            "_Array",
        ):
            if base.endswith(suffix):
                return base[: -len(suffix)]
        return base

    @staticmethod
    def _template_scope_status(diag: dict[str, Any]) -> str:
        if diag["kept_nonroot_diagram_names"]:
            return "kept_nonroot_present"
        if diag["root_diagram_names"] and diag["excluded_diagram_names"]:
            return "root_and_excluded_only"
        if diag["root_diagram_names"]:
            return "root_only"
        if diag["excluded_diagram_names"]:
            return "excluded_only"
        if diag["diagram_exclusion_status"] == "not_on_any_simplified_diagram":
            return "not_on_any_simplified_diagram"
        if diag["diagram_exclusion_status"] == "not_on_any_diagram":
            return "not_on_any_diagram"
        if diag["diagram_exclusion_status"] == "not_in_uml":
            return "not_in_uml"
        if diag["diagram_names"]:
            return "other_simplified_only"
        return "unknown"

    @staticmethod
    def _template_actionability(scope_status: str) -> str:
        if scope_status in {"kept_nonroot_present", "other_simplified_only"}:
            return "candidate_builder_gap"
        if scope_status in {"root_only", "excluded_only", "root_and_excluded_only"}:
            return "likely_hand_beyond_simplified_scope"
        if scope_status in {"not_on_any_simplified_diagram", "not_on_any_diagram", "not_in_uml"}:
            return "likely_out_of_scope_for_current_diagrams"
        return "needs_manual_triage"

    @staticmethod
    def _collect_template_object_hits(template: Any, *, object_id: str) -> list[dict[str, Any]]:
        hits: list[dict[str, Any]] = []

        def visit(node: Any, path: str = "$", context: str = "root") -> None:
            if isinstance(node, dict):
                if node.get("$objectId") == object_id:
                    hits.append(
                        {
                            "path": path,
                            "context": context,
                            "object_type": node.get("$objectType"),
                            "type": node.get("type"),
                            "has_anyOf": isinstance(node.get("anyOf"), list),
                            "has_properties": isinstance(node.get("properties"), dict),
                        }
                    )

                for key, value in node.items():
                    if key == "properties" and isinstance(value, dict):
                        for child_key, child_value in value.items():
                            visit(child_value, f"{path}.properties['{child_key}']", "properties")
                    elif key == "patternProperties" and isinstance(value, dict):
                        for child_key, child_value in value.items():
                            visit(child_value, f"{path}.patternProperties['{child_key}']", "patternProperties")
                    elif key == "items":
                        visit(value, f"{path}.items", "items")
                    elif key == "anyOf" and isinstance(value, list):
                        for idx, child_value in enumerate(value):
                            visit(child_value, f"{path}.anyOf[{idx}]", "anyOf")
                    elif key not in {"properties", "patternProperties", "items", "anyOf"}:
                        visit(value, f"{path}.{key}", context)
            elif isinstance(node, list):
                for idx, item in enumerate(node):
                    visit(item, f"{path}[{idx}]", context)

        visit(template)
        return hits

    @staticmethod
    def _shape_label_for_hit(hit: dict[str, Any]) -> str:
        context = hit["context"]
        context_label = {
            "root": "root",
            "properties": "property",
            "patternProperties": "pattern",
            "items": "array_item",
            "anyOf": "anyof_variant",
        }.get(context, context)

        object_type = hit["object_type"]
        if object_type == "object":
            if hit["has_anyOf"] and hit["has_properties"]:
                core = "object_anyof_with_properties"
            elif hit["has_anyOf"]:
                core = "object_anyof"
            elif hit["has_properties"]:
                core = "object_properties"
            else:
                core = "object_other"
        elif object_type == "reference":
            if hit["has_anyOf"]:
                core = "reference_anyof"
            elif hit["type"] == "string":
                core = "reference_string"
            else:
                core = "reference_other"
        else:
            core = f"{object_type or 'unknown'}_{hit['type'] or 'unknown'}"

        return f"{context_label}:{core}"

    @classmethod
    def _shape_counts_for_hits(cls, hits: list[dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for hit in hits:
            key = cls._shape_label_for_hit(hit)
            counts[key] = counts.get(key, 0) + 1
        return dict(sorted(counts.items()))

    @staticmethod
    def _template_shape_mismatch_kind(
        classification: str,
        hand_counts: dict[str, int],
        auto_counts: dict[str, int],
        *,
        auto_hit_count: int,
    ) -> str:
        if auto_hit_count == 0:
            return "missing_from_auto_raw_template"

        def has(counts: dict[str, int], needle: str) -> bool:
            return counts.get(needle, 0) > 0

        if classification == "synthetic_anyof_container":
            if has(hand_counts, "root:object_anyof") and has(auto_counts, "root:object_properties"):
                return "hand_anyof_object_collapsed_to_concrete_object"
            if has(hand_counts, "property:object_anyof") and has(auto_counts, "property:object_properties"):
                return "hand_anyof_property_collapsed_to_concrete_object"
        if classification == "synthetic_anyof_pointer":
            if has(hand_counts, "property:reference_anyof") and has(auto_counts, "property:reference_string"):
                return "hand_anyof_reference_narrowed_to_single_reference"
            if has(hand_counts, "property:reference_anyof") and has(auto_counts, "property:object_properties"):
                return "hand_anyof_reference_replaced_by_object"
        if classification == "synthetic_array":
            if has(hand_counts, "array_item:object_properties") and has(auto_counts, "property:object_properties"):
                return "hand_array_of_objects_collapsed_to_single_object"
            if has(hand_counts, "array_item:object_anyof") and has(auto_counts, "property:object_properties"):
                return "hand_array_of_polymorphic_objects_collapsed_to_single_object"
        if classification == "synthetic_pointer_array":
            if has(hand_counts, "array_item:reference_string") and not has(auto_counts, "array_item:reference_string"):
                return "hand_pointer_array_missing_array_context_in_auto"
        if classification == "synthetic_container":
            return "hand_container_schema_missing_from_auto"
        if classification.startswith("real_class_absent"):
            return "real_class_absent_from_auto_template"
        return "shape_mismatch_unclassified"

    def _schema_path_by_name(self, schema: RavensSchema, name: str) -> str:
        return schema.schema_path(name)

    def _find_class_occurrences_in_schema(self, schema: Any, class_name: str) -> dict[str, list[str]]:
        hits: dict[str, list[str]] = {
            "title_root": [],
            "title_property": [],
            "title_pattern": [],
            "title_array_item": [],
            "title_anyof": [],
            "property_key": [],
            "pattern_key": [],
            "ref": [],
        }

        def visit(node: Any, path: str = "$", parent_ctx: str = "root"):
            if isinstance(node, dict):
                title = node.get("title")
                if title == class_name:
                    if parent_ctx == "root":
                        hits["title_root"].append(path)
                    elif parent_ctx == "properties":
                        hits["title_property"].append(path)
                    elif parent_ctx == "patternProperties":
                        hits["title_pattern"].append(path)
                    elif parent_ctx == "items":
                        hits["title_array_item"].append(path)
                    elif parent_ctx == "anyOf":
                        hits["title_anyof"].append(path)
                    else:
                        hits["title_property"].append(path)

                ref = node.get("$ref")
                if isinstance(ref, str) and ref == self._schema_path_by_name(self.auto_schema, class_name):
                    hits["ref"].append(path)

                if "properties" in node and isinstance(node["properties"], dict):
                    for k, v in node["properties"].items():
                        if k == class_name:
                            hits["property_key"].append(f"{path}.properties['{k}']")
                        visit(v, f"{path}.properties['{k}']", "properties")

                if "patternProperties" in node and isinstance(node["patternProperties"], dict):
                    for k, v in node["patternProperties"].items():
                        if k == class_name:
                            hits["pattern_key"].append(f"{path}.patternProperties['{k}']")
                        visit(v, f"{path}.patternProperties['{k}']", "patternProperties")

                if "items" in node:
                    visit(node["items"], f"{path}.items", "items")

                if "anyOf" in node and isinstance(node["anyOf"], list):
                    for i, item in enumerate(node["anyOf"]):
                        visit(item, f"{path}.anyOf[{i}]", "anyOf")

            elif isinstance(node, list):
                for i, item in enumerate(node):
                    visit(item, f"{path}[{i}]", parent_ctx)

        visit(schema)
        return hits

    @staticmethod
    def _first_or_none(items: list[str]) -> str | None:
        return items[0] if items else None

    def compare_schema_keys(self, *, missing_only: bool = False) -> pd.DataFrame:
        hand_keys = self._schema_keys(self.hand_schema)
        auto_keys = self._schema_keys(self.auto_schema)
        rows = []
        for key in sorted(hand_keys | auto_keys):
            hand = key in hand_keys
            auto = key in auto_keys
            if hand and auto:
                status = "shared"
            elif hand:
                status = "missing_in_auto"
            else:
                status = "only_in_auto"
            if missing_only and status != "missing_in_auto":
                continue
            rows.append(
                {
                    "key": key,
                    "status": status,
                    "hand": hand,
                    "auto": auto,
                }
            )
        return pd.DataFrame(rows, columns=["key", "status", "hand", "auto"])

    def missing_schema_keys(self) -> pd.DataFrame:
        return self.compare_schema_keys(missing_only=True)

    def compare_schema_keys_normalized(self, *, missing_only: bool = False) -> pd.DataFrame:
        hand_keys = self._schema_keys(self.hand_schema)
        auto_keys = self._schema_keys(self.auto_schema)

        auto_by_norm: dict[str, list[str]] = {}
        for key in sorted(auto_keys):
            norm = self._normalize_schema_key(key, self.auto_schema)
            auto_by_norm.setdefault(norm, []).append(key)

        rows = []
        seen_auto: set[str] = set()
        for hand_key in sorted(hand_keys):
            hand_name = self._normalize_schema_key(hand_key, self.hand_schema)
            auto_matches = auto_by_norm.get(hand_name, [])
            if hand_key in auto_keys:
                status = "shared_exact"
                matched_auto_key = hand_key
                matched_auto_name = self._normalize_schema_key(hand_key, self.auto_schema)
                seen_auto.add(hand_key)
            elif auto_matches:
                status = "shared_normalized"
                matched_auto_key = auto_matches[0]
                matched_auto_name = hand_name
                seen_auto.add(matched_auto_key)
            else:
                status = "missing_in_auto"
                matched_auto_key = None
                matched_auto_name = None

            if missing_only and status != "missing_in_auto":
                continue

            rows.append(
                {
                    "hand_key": hand_key,
                    "hand_name": hand_name,
                    "matched_auto_key": matched_auto_key,
                    "matched_auto_name": matched_auto_name,
                    "status": status,
                }
            )

        if not missing_only:
            for auto_key in sorted(auto_keys - seen_auto):
                rows.append(
                    {
                        "hand_key": None,
                        "hand_name": None,
                        "matched_auto_key": auto_key,
                        "matched_auto_name": self._normalize_schema_key(auto_key, self.auto_schema),
                        "status": "only_in_auto",
                    }
                )

        return pd.DataFrame(
            rows,
            columns=["hand_key", "hand_name", "matched_auto_key", "matched_auto_name", "status"],
        )

    def missing_schema_keys_normalized(self) -> pd.DataFrame:
        return self.compare_schema_keys_normalized(missing_only=True)

    def classify_missing_schema_keys(self) -> pd.DataFrame:
        missing = self.missing_schema_keys_normalized().copy()
        if missing.empty:
            return missing

        class_names = self._uml_class_names()
        hand_raw = self.hand_schema.schema_template.raw_template
        auto_raw = self.auto_schema.schema_template.raw_template
        auto_root_props = set(self.auto_schema.schema.get("properties", {}).keys())

        rows = []
        for row in missing.itertuples(index=False):
            hand_name = str(row.hand_name)
            tail_name = hand_name.split(".")[-1]

            is_real_class = hand_name in class_names
            tail_is_real_class = tail_name in class_names

            hand_hits = self._collect_template_hits(hand_raw, key=hand_name, object_id=hand_name)
            auto_hits = self._collect_template_hits(auto_raw, key=hand_name, object_id=hand_name)
            auto_tail_hits = self._collect_template_hits(auto_raw, key=tail_name, object_id=tail_name)

            if hand_name.startswith("+$"):
                classification = "synthetic_special"
            elif "_anyOfPointer" in hand_name:
                classification = "synthetic_anyof_pointer"
            elif hand_name.endswith("_anyOfContainer"):
                classification = "synthetic_anyof_container"
            elif hand_name.endswith("_PointerArray"):
                classification = "synthetic_pointer_array"
            elif hand_name.endswith("_Pointer"):
                classification = "synthetic_pointer"
            elif hand_name.endswith("_Container"):
                classification = "synthetic_container"
            elif hand_name.endswith("_Array"):
                classification = "synthetic_array"
            elif is_real_class or tail_is_real_class:
                present_in_auto_template = any([
                    auto_hits["as_key"],
                    auto_hits["as_objectid"],
                    auto_tail_hits["as_key"],
                    auto_tail_hits["as_objectid"],
                    hand_name in auto_root_props,
                ])
                classification = "real_class_present_in_auto_template" if present_in_auto_template else "real_class_absent_from_auto_template"
            else:
                classification = "unknown_nonclass"

            diag_name = hand_name if is_real_class else tail_name if tail_is_real_class else hand_name
            diag = self._diagram_status(diag_name)

            detail = classification
            if classification == "real_class_absent_from_auto_template":
                status = diag["diagram_exclusion_status"]
                if status == "excluded_by_inf_mkt_diagram_only":
                    detail = "real_class_absent_expected_inf_mkt_exclusion"
                elif status == "present_on_kept_and_excluded_diagrams":
                    detail = "real_class_absent_mixed_diagram_membership"
                elif status == "not_on_excluded_diagrams":
                    detail = "real_class_absent_unexpected"
                elif status == "not_on_any_diagram":
                    detail = "real_class_absent_not_on_any_diagram"
                elif status == "not_in_uml":
                    detail = "real_class_absent_not_in_uml"
            elif classification == "real_class_present_in_auto_template":
                status = diag["diagram_exclusion_status"]
                if status == "excluded_by_inf_mkt_diagram_only":
                    detail = "real_class_present_despite_inf_mkt_exclusion"
                elif status == "present_on_kept_and_excluded_diagrams":
                    detail = "real_class_present_mixed_diagram_membership"
                elif status == "not_on_excluded_diagrams":
                    detail = "real_class_present_not_on_excluded_diagrams"
                elif status == "not_on_any_diagram":
                    detail = "real_class_present_not_on_any_diagram"
                elif status == "not_in_uml":
                    detail = "real_class_present_not_in_uml"

            rows.append(
                {
                    "hand_key": row.hand_key,
                    "hand_name": hand_name,
                    "tail_name": tail_name,
                    "classification": classification,
                    "classification_detail": detail,
                    "is_real_class": is_real_class,
                    "tail_is_real_class": tail_is_real_class,
                    "in_hand_raw_as_key": hand_hits["as_key"],
                    "in_hand_raw_as_objectid": hand_hits["as_objectid"],
                    "in_auto_raw_as_key": auto_hits["as_key"],
                    "in_auto_raw_as_objectid": auto_hits["as_objectid"],
                    "tail_in_auto_raw_as_key": auto_tail_hits["as_key"],
                    "tail_in_auto_raw_as_objectid": auto_tail_hits["as_objectid"],
                    "in_auto_root_properties": hand_name in auto_root_props,
                    "diagram_exclusion_status": diag["diagram_exclusion_status"],
                    "diagram_names": diag["diagram_names"],
                    "excluded_diagram_names": diag["excluded_diagram_names"],
                    "kept_diagram_names": diag["kept_diagram_names"],
                    "root_diagram_names": diag["root_diagram_names"],
                    "kept_nonroot_diagram_names": diag["kept_nonroot_diagram_names"],
                    "status": row.status,
                }
            )

        cols = [
            "hand_key",
            "hand_name",
            "tail_name",
            "classification",
            "classification_detail",
            "is_real_class",
            "tail_is_real_class",
            "in_hand_raw_as_key",
            "in_hand_raw_as_objectid",
            "in_auto_raw_as_key",
            "in_auto_raw_as_objectid",
            "tail_in_auto_raw_as_key",
            "tail_in_auto_raw_as_objectid",
            "in_auto_root_properties",
            "diagram_exclusion_status",
            "diagram_names",
            "excluded_diagram_names",
            "kept_diagram_names",
            "root_diagram_names",
            "kept_nonroot_diagram_names",
            "status",
        ]
        return pd.DataFrame(rows, columns=cols)

    def classify_template_shape_gaps(self) -> pd.DataFrame:
        missing = self.classify_missing_schema_keys().copy()
        if missing.empty:
            return missing

        hand_raw = self.hand_schema.schema_template.raw_template
        auto_raw = self.auto_schema.schema_template.raw_template

        rows = []
        for row in missing.itertuples(index=False):
            hand_name = str(row.hand_name)
            base_name = self._base_template_name(hand_name)
            diag_name = hand_name if row.is_real_class else row.tail_name if row.tail_is_real_class else base_name
            diag = self._diagram_status(diag_name)
            scope_status = self._template_scope_status(diag)
            actionability = self._template_actionability(scope_status)

            hand_hits = self._collect_template_object_hits(hand_raw, object_id=base_name)
            auto_hits = self._collect_template_object_hits(auto_raw, object_id=base_name)
            hand_counts = self._shape_counts_for_hits(hand_hits)
            auto_counts = self._shape_counts_for_hits(auto_hits)
            mismatch_kind = self._template_shape_mismatch_kind(
                row.classification,
                hand_counts,
                auto_counts,
                auto_hit_count=len(auto_hits),
            )

            rows.append(
                {
                    "hand_name": hand_name,
                    "base_name": base_name,
                    "classification": row.classification,
                    "classification_detail": row.classification_detail,
                    "shape_mismatch_kind": mismatch_kind,
                    "scope_status": scope_status,
                    "actionability": actionability,
                    "diagram_exclusion_status": diag["diagram_exclusion_status"],
                    "diagram_names": diag["diagram_names"],
                    "root_diagram_names": diag["root_diagram_names"],
                    "excluded_diagram_names": diag["excluded_diagram_names"],
                    "kept_nonroot_diagram_names": diag["kept_nonroot_diagram_names"],
                    "hand_raw_hit_count": len(hand_hits),
                    "auto_raw_hit_count": len(auto_hits),
                    "hand_shape_counts": json.dumps(hand_counts, sort_keys=True),
                    "auto_shape_counts": json.dumps(auto_counts, sort_keys=True),
                    "hand_example_paths": json.dumps([hit["path"] for hit in hand_hits[:5]]),
                    "auto_example_paths": json.dumps([hit["path"] for hit in auto_hits[:5]]),
                }
            )

        cols = [
            "hand_name",
            "base_name",
            "classification",
            "classification_detail",
            "shape_mismatch_kind",
            "scope_status",
            "actionability",
            "diagram_exclusion_status",
            "diagram_names",
            "root_diagram_names",
            "excluded_diagram_names",
            "kept_nonroot_diagram_names",
            "hand_raw_hit_count",
            "auto_raw_hit_count",
            "hand_shape_counts",
            "auto_shape_counts",
            "hand_example_paths",
            "auto_example_paths",
        ]
        return pd.DataFrame(rows, columns=cols)

    def classify_present_missing_schema_keys(self) -> pd.DataFrame:
        cls = self.classify_missing_schema_keys().copy()
        if cls.empty:
            return cls

        cls = cls[cls["classification_detail"].isin([
            "real_class_present_not_on_excluded_diagrams",
            "real_class_present_mixed_diagram_membership",
            "real_class_present_despite_inf_mkt_exclusion",
            "real_class_present_not_on_any_diagram",
            "real_class_present_not_in_uml",
        ])].copy()
        if cls.empty:
            return cls

        rows = []
        for row in cls.itertuples(index=False):
            class_name = row.hand_name if row.is_real_class else row.tail_name
            schema_hits = self._find_class_occurrences_in_schema(self.auto_schema.schema, class_name)

            shape_flags = {
                "root_object": bool(schema_hits["title_root"]),
                "nested_object": bool(schema_hits["title_property"]),
                "pattern_object": bool(schema_hits["title_pattern"]),
                "array_item": bool(schema_hits["title_array_item"]),
                "anyof_variant": bool(schema_hits["title_anyof"]),
                "property_key_only": bool(schema_hits["property_key"]),
                "pattern_key_only": bool(schema_hits["pattern_key"]),
                "ref_only": bool(schema_hits["ref"]),
            }

            active_shapes = [k for k, v in shape_flags.items() if v]
            if len(active_shapes) == 0:
                appearance = "present_in_raw_template_but_not_found_in_built_schema"
            elif len(active_shapes) == 1:
                mapping = {
                    "root_object": "present_as_root_object_left_inline",
                    "nested_object": "present_as_nested_object_left_inline",
                    "pattern_object": "present_as_pattern_object_left_inline",
                    "array_item": "present_as_array_item_left_inline",
                    "anyof_variant": "present_as_anyof_variant_left_inline",
                    "property_key_only": "present_as_property_key_only",
                    "pattern_key_only": "present_as_pattern_key_only",
                    "ref_only": "present_as_ref_only",
                }
                appearance = mapping[active_shapes[0]]
            else:
                if any(shape_flags[k] for k in ["nested_object", "array_item", "anyof_variant", "pattern_object", "root_object"]):
                    appearance = "present_in_multiple_inline_shapes"
                else:
                    appearance = "present_in_multiple_noninline_shapes"

            rows.append(
                {
                    "hand_key": row.hand_key,
                    "hand_name": row.hand_name,
                    "tail_name": row.tail_name,
                    "classification": row.classification,
                    "classification_detail": row.classification_detail,
                    "appearance_classification": appearance,
                    "title_root_count": len(schema_hits["title_root"]),
                    "title_property_count": len(schema_hits["title_property"]),
                    "title_pattern_count": len(schema_hits["title_pattern"]),
                    "title_array_item_count": len(schema_hits["title_array_item"]),
                    "title_anyof_count": len(schema_hits["title_anyof"]),
                    "property_key_count": len(schema_hits["property_key"]),
                    "pattern_key_count": len(schema_hits["pattern_key"]),
                    "ref_count": len(schema_hits["ref"]),
                    "example_title_root_path": self._first_or_none(schema_hits["title_root"]),
                    "example_title_property_path": self._first_or_none(schema_hits["title_property"]),
                    "example_title_pattern_path": self._first_or_none(schema_hits["title_pattern"]),
                    "example_title_array_item_path": self._first_or_none(schema_hits["title_array_item"]),
                    "example_title_anyof_path": self._first_or_none(schema_hits["title_anyof"]),
                    "example_property_key_path": self._first_or_none(schema_hits["property_key"]),
                    "example_pattern_key_path": self._first_or_none(schema_hits["pattern_key"]),
                    "example_ref_path": self._first_or_none(schema_hits["ref"]),
                    "diagram_names": row.diagram_names,
                    "excluded_diagram_names": row.excluded_diagram_names,
                    "kept_diagram_names": row.kept_diagram_names,
                    "status": row.status,
                }
            )

        cols = [
            "hand_key",
            "hand_name",
            "tail_name",
            "classification",
            "classification_detail",
            "appearance_classification",
            "title_root_count",
            "title_property_count",
            "title_pattern_count",
            "title_array_item_count",
            "title_anyof_count",
            "property_key_count",
            "pattern_key_count",
            "ref_count",
            "example_title_root_path",
            "example_title_property_path",
            "example_title_pattern_path",
            "example_title_array_item_path",
            "example_title_anyof_path",
            "example_property_key_path",
            "example_pattern_key_path",
            "example_ref_path",
            "diagram_names",
            "excluded_diagram_names",
            "kept_diagram_names",
            "status",
        ]
        return pd.DataFrame(rows, columns=cols)

    def compare_root_properties(self, *, missing_only: bool = False) -> pd.DataFrame:
        hand_props = set(self.hand_schema.schema.get("properties", {}).keys())
        auto_props = set(self.auto_schema.schema.get("properties", {}).keys())
        rows = []
        for key in sorted(hand_props | auto_props):
            hand = key in hand_props
            auto = key in auto_props
            if hand and auto:
                status = "shared"
            elif hand:
                status = "missing_in_auto"
            else:
                status = "only_in_auto"
            if missing_only and status != "missing_in_auto":
                continue
            rows.append(
                {
                    "property": key,
                    "status": status,
                    "hand": hand,
                    "auto": auto,
                }
            )
        return pd.DataFrame(rows, columns=["property", "status", "hand", "auto"])

    def expected_template_schema_keys(self, source: str = "auto") -> set[str]:
        schema = self.auto_schema if source == "auto" else self.hand_schema
        keys: set[str] = set()
        self._collect_expected_schema_keys(deepcopy(schema.schema), keys)
        return keys

    def compare_template_to_schemas(self, source: str = "auto", *, missing_only: bool = True) -> pd.DataFrame:
        schema = self.auto_schema if source == "auto" else self.hand_schema
        expected = self.expected_template_schema_keys(source)
        actual = set(schema.schemas.keys())
        rows = []
        for key in sorted(expected | actual):
            exp = key in expected
            act = key in actual
            if exp and act:
                status = "present"
            elif exp:
                status = "missing_in_schemas"
            else:
                status = "schema_only"
            if missing_only and status != "missing_in_schemas":
                continue
            rows.append(
                {
                    "source": source,
                    "key": key,
                    "status": status,
                    "expected": exp,
                    "actual": act,
                }
            )
        return pd.DataFrame(rows, columns=["source", "key", "status", "expected", "actual"])

    def _collect_expected_schema_keys(self, schema: Any, keys: set[str], debug_key: str | None = None) -> None:
        if not isinstance(schema, dict):
            return

        title = schema.get("title", None)
        if title is None and debug_key is not None:
            title = debug_key.split(".")[-1]

        schema_id = None
        if schema.get("type", None) == "object" or schema.get("type", None) == "array" or "anyOf" in schema:
            if title is not None:
                if "patternProperties" in schema:
                    title = f"{title}_Container"
                if "anyOf" in schema:
                    title = f"{title}_anyOfContainer"
                schema_id = self.hand_schema.schema_path(title)
                keys.add(schema_id)

        if schema.get("type", None) == "object":
            for n in ["properties", "patternProperties"]:
                if n in schema:
                    for k, v in schema[n].items():
                        self._collect_expected_schema_keys(v, keys, debug_key=k)
        elif schema.get("type", None) == "array":
            self._collect_expected_schema_keys(schema.get("items"), keys, debug_key=debug_key)
        elif "anyOf" in schema:
            for item in schema["anyOf"]:
                self._collect_expected_schema_keys(item, keys, debug_key=debug_key)


def compare_schema_keys(*, missing_only: bool = True, **kwargs) -> pd.DataFrame:
    return SchemaComparator(**kwargs).compare_schema_keys(missing_only=missing_only)


def compare_schema_keys_normalized(*, missing_only: bool = True, **kwargs) -> pd.DataFrame:
    return SchemaComparator(**kwargs).compare_schema_keys_normalized(missing_only=missing_only)


def classify_missing_schema_keys(**kwargs) -> pd.DataFrame:
    return SchemaComparator(**kwargs).classify_missing_schema_keys()


def classify_present_missing_schema_keys(**kwargs) -> pd.DataFrame:
    return SchemaComparator(**kwargs).classify_present_missing_schema_keys()
