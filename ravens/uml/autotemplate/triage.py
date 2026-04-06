import json
import re
from pathlib import Path

import pandas as pd


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def normalize_path(path):
    return re.sub(r"\[\d+\]", "[]", path)


def walk_occurrences(node, target, path="$", parent_edge=None, ancestors=None):
    if ancestors is None:
        ancestors = []

    out = []

    if isinstance(node, dict):
        current = {
            "path": path,
            "oid": node.get("$objectId"),
            "otype": node.get("$objectType"),
            "has_anyof": isinstance(node.get("anyOf"), list),
            "parent_edge": parent_edge,
        }

        if node.get("$objectId") == target:
            nearest_parent = next(
                (a for a in reversed(ancestors) if a.get("oid") and a.get("oid") != target),
                None,
            )
            nearest_anyof_wrapper = next(
                (a for a in reversed(ancestors) if a.get("has_anyof")),
                None,
            )

            if parent_edge == "anyOf_item":
                kind = "anyof_variant"
            elif parent_edge == "items":
                kind = "array_item"
            elif parent_edge == "patternProperty":
                kind = "pattern_object"
            elif parent_edge == "property":
                kind = "property_object"
            else:
                kind = "object_node"

            out.append(
                {
                    "target_class": target,
                    "path": path,
                    "path_norm": normalize_path(path),
                    "kind": kind,
                    "parent_oid": None if nearest_parent is None else nearest_parent["oid"],
                    "parent_path": None if nearest_parent is None else nearest_parent["path"],
                    "anyof_wrapper_oid": None if nearest_anyof_wrapper is None else nearest_anyof_wrapper["oid"],
                    "anyof_wrapper_path": None if nearest_anyof_wrapper is None else nearest_anyof_wrapper["path"],
                }
            )

        for k, v in node.items():
            if k == "properties" and isinstance(v, dict):
                for pk, pv in v.items():
                    out.extend(
                        walk_occurrences(
                            pv,
                            target,
                            path=f"{path}.properties['{pk}']",
                            parent_edge="property",
                            ancestors=ancestors + [current],
                        )
                    )
            elif k == "patternProperties" and isinstance(v, dict):
                for pk, pv in v.items():
                    out.extend(
                        walk_occurrences(
                            pv,
                            target,
                            path=f"{path}.patternProperties['{pk}']",
                            parent_edge="patternProperty",
                            ancestors=ancestors + [current],
                        )
                    )
            elif k == "items":
                out.extend(
                    walk_occurrences(
                        v,
                        target,
                        path=f"{path}.items",
                        parent_edge="items",
                        ancestors=ancestors + [current],
                    )
                )
            elif k == "anyOf" and isinstance(v, list):
                for i, item in enumerate(v):
                    out.extend(
                        walk_occurrences(
                            item,
                            target,
                            path=f"{path}.anyOf[{i}]",
                            parent_edge="anyOf_item",
                            ancestors=ancestors + [current],
                        )
                    )
            else:
                if isinstance(v, (dict, list)):
                    out.extend(
                        walk_occurrences(
                            v,
                            target,
                            path=f"{path}.{k}",
                            parent_edge=k,
                            ancestors=ancestors + [current],
                        )
                    )

    elif isinstance(node, list):
        for i, item in enumerate(node):
            out.extend(
                walk_occurrences(
                    item,
                    target,
                    path=f"{path}[{i}]",
                    parent_edge="list_item",
                    ancestors=ancestors,
                )
            )

    return out


def build_signature(row):
    if row["kind"] == "anyof_variant":
        return (
            f"anyof_variant"
            f"|wrapper_oid={row['anyof_wrapper_oid']}"
            f"|wrapper_path={normalize_path(str(row['anyof_wrapper_path']))}"
        )
    if row["kind"] == "array_item":
        return (
            f"array_item"
            f"|parent_oid={row['parent_oid']}"
            f"|parent_path={normalize_path(str(row['parent_path']))}"
        )
    if row["kind"] == "pattern_object":
        return (
            f"pattern_object"
            f"|parent_oid={row['parent_oid']}"
            f"|parent_path={normalize_path(str(row['parent_path']))}"
        )
    if row["kind"] == "property_object":
        return (
            f"property_object"
            f"|parent_oid={row['parent_oid']}"
            f"|parent_path={normalize_path(str(row['parent_path']))}"
        )
    return (
        f"object_node"
        f"|parent_oid={row['parent_oid']}"
        f"|parent_path={normalize_path(str(row['parent_path']))}"
    )


def triage_present_missing_patterns(
    present_csv="present_missing.csv",
    hand_template_path="template.json",
    auto_template_path="template_auto.json",
):
    present = pd.read_csv(present_csv)
    hand = load_json(hand_template_path)
    auto = load_json(auto_template_path)

    classes = sorted(set(present["hand_name"]))

    auto_rows = []
    hand_rows = []

    for cls in classes:
        for row in walk_occurrences(auto, cls):
            row["template"] = "auto"
            row["signature"] = build_signature(row)
            auto_rows.append(row)

        for row in walk_occurrences(hand, cls):
            row["template"] = "hand"
            row["signature"] = build_signature(row)
            hand_rows.append(row)

    auto_occ = pd.DataFrame(auto_rows)
    hand_occ = pd.DataFrame(hand_rows)

    if auto_occ.empty:
        auto_occ = pd.DataFrame(columns=["target_class", "signature"])
    if hand_occ.empty:
        hand_occ = pd.DataFrame(columns=["target_class", "signature"])

    auto_sig_counts = (
        auto_occ.groupby(["signature", "kind", "anyof_wrapper_oid", "parent_oid"], dropna=False)
        .agg(
            n_classes=("target_class", "nunique"),
            classes=("target_class", lambda s: tuple(sorted(set(s))[:15])),
            n_occurrences=("target_class", "size"),
            sample_path=("path", "first"),
        )
        .reset_index()
        .sort_values(["n_classes", "n_occurrences", "signature"], ascending=[False, False, True])
    )

    class_summary = (
        auto_occ.groupby("target_class")
        .agg(
            n_auto_occurrences=("target_class", "size"),
            n_auto_signatures=("signature", "nunique"),
            auto_signatures=("signature", lambda s: tuple(sorted(set(s)))),
        )
        .reset_index()
    )

    hand_summary = (
        hand_occ.groupby("target_class")
        .agg(
            n_hand_occurrences=("target_class", "size"),
            n_hand_signatures=("signature", "nunique"),
            hand_signatures=("signature", lambda s: tuple(sorted(set(s)))),
        )
        .reset_index()
    )

    merged = present.merge(class_summary, left_on="hand_name", right_on="target_class", how="left")
    merged = merged.merge(hand_summary, left_on="hand_name", right_on="target_class", how="left", suffixes=("", "_hand"))

    merged = merged.drop(columns=[c for c in merged.columns if c == "target_class" or c == "target_class_hand"])

    return auto_occ, hand_occ, auto_sig_counts, merged


# ---- run ----
present_csv = r"X:\Research\Ravens\repo\MG-RAVENS\present_missing.csv"
hand_template_path = Path(r"X:\Research\Ravens\repo\MG-RAVENS\ravens\lib\template.json")
auto_template_path = Path(r"X:\Research\Ravens\repo\MG-RAVENS\ravens\lib\template_auto.json")

auto_occ, hand_occ, auto_sig_counts, merged = triage_present_missing_patterns(
    present_csv,
    hand_template_path,
    auto_template_path,
)

print("\nTOP AUTO SIGNATURES")
print(auto_sig_counts.head(25).to_string(index=False))

print("\nTOP SIGNATURE COUNTS ONLY")
print(auto_sig_counts[["signature", "n_classes", "n_occurrences"]].head(25).to_string(index=False))

print("\nCLASSES WITH ONLY ONE AUTO SIGNATURE")
print(
    merged.loc[merged["n_auto_signatures"] == 1, ["hand_name", "appearance_classification", "auto_signatures"]]
    .head(25)
    .to_string(index=False)
)

auto_occ.to_csv("present_missing_auto_occurrences.csv", index=False)
hand_occ.to_csv("present_missing_hand_occurrences.csv", index=False)
auto_sig_counts.to_csv("present_missing_auto_signature_counts.csv", index=False)
merged.to_csv("present_missing_pattern_summary.csv", index=False)
