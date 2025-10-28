# Temporary code holder for functions to correct EA model algorithmically

from pathlib import Path
import re
from typing import Iterable
import json

from ravens.data import _TEMPLATE_JSON_PATH


def _leaf(name: str) -> str:
    """Return the last segment from qualified names like 'Pkg::Class' or 'Pkg/Class'."""
    segs = re.split(r"(?:::|[:/\\])", name)
    return segs[-1] if segs else name

def _prep_objects_df(uml) -> "pd.DataFrame":
    """
    Make a flat objects DataFrame with Object_ID as a column (since uml.objects is indexed by it).
    Keeps only the columns we need and drops rows with missing names.
    """
    df = uml.objects.reset_index()[["Object_ID", "Name", "Object_Type", "Package_ID"]].copy()
    df = df[df["Name"].notna()]
    # Normalize a case-folded key for robust matching
    df["_norm_name"] = df["Name"].astype(str).str.casefold()
    return df

def map_template_names_to_ea_ids(
    names: Iterable[str],
    uml,
    *,
    only_types: tuple[str, ...] = ("Class",),          # tighten to just real classes by default
    case_insensitive: bool = True,
    allow_qualified: bool = True,
) -> dict[str, list[int]]:
    """
    Map class names from the hand template to EA Object_IDs using uml.objects.

    Returns {original_name -> [Object_ID, ...]} (multiple IDs possible if duplicates exist).
    """
    df = _prep_objects_df(uml)
    if only_types:
        df = df[df["Object_Type"].isin(only_types)]

    out: dict[str, list[int]] = {}
    for raw in names:
        target = _leaf(raw) if allow_qualified else raw
        key = target.casefold() if case_insensitive else target
        hits = df[df["_norm_name"].eq(key)]
        out[raw] = hits["Object_ID"].astype(int).unique().tolist()
    return out

def build_role_sets_for_containers_from_uml(
    container_names: Iterable[str],
    uml,
    *,
    only_types: tuple[str, ...] = ("Class",),
) -> dict:
    """
    Produce the role_sets dict that export_ea_jscript_all expects, using uml.objects.
    """
    name_to_ids = map_template_names_to_ea_ids(
        container_names, uml, only_types=only_types
    )
    container_ids = sorted({eid for ids in name_to_ids.values() for eid in ids})
    return {
        "inheritOnlyClass":   [],
        "containerClass":     container_ids,
        "substitutableClass": [],
    }


def containers_from_hand_template(template_path=_TEMPLATE_JSON_PATH):
    """
    Return a list of dicts for every schema object with "$objectType": "container".
    Each item has:
      - 'path': slash-delimited path within the schema (good for disambiguation)
      - 'name': the last segment of the path (class name)
      - 'title'/'description' (if present)
    """
    data = json.loads(Path(template_path).read_text(encoding="utf-8"))
    out = []

    def walk(node, parts):
        if not isinstance(node, dict):
            return
        if node.get("$objectType") == "container":
            out.append({
                "path": "/".join(parts),
                "name": parts[-1] if parts else "",
                "title": node.get("title"),
                "description": node.get("description"),
            })

        # Recurse common JSON Schema nesting points
        for key in ("properties","patternProperties","items","oneOf","anyOf","allOf","definitions","$defs","additionalProperties"):
            val = node.get(key)
            if isinstance(val, dict):
                for k, v in val.items():
                    walk(v, parts + [k])
            elif isinstance(val, list):
                for i, v in enumerate(val):
                    walk(v, parts + [f"{key}[{i}]"])

        # Fallback: walk any other nested dict/list members
        for k, v in node.items():
            if k in ("properties","patternProperties","items","oneOf","anyOf","allOf","definitions","$defs","additionalProperties"):
                continue
            if isinstance(v, dict):
                walk(v, parts + [k])
            elif isinstance(v, list):
                for i, vv in enumerate(v):
                    walk(vv, parts + [f"{k}[{i}]"])

    walk(data, [])
    # Deduplicate by path (just in case)
    dedup, seen = [], set()
    for item in out:
        if item["path"] not in seen:
            seen.add(item["path"])
            dedup.append(item)
    return dedup

def container_names_from_hand_template(template_path=_TEMPLATE_JSON_PATH):
    """Convenience: sorted unique terminal names for container objects."""
    items = containers_from_hand_template(template_path)
    return sorted({it["name"] for it in items})


def export_ea_jscript_all(
    role_sets: dict | None = None,
    out_path: str | None = None,
    print_to_console: bool = True,
) -> str:
    """
    Emit a single EA JScript that updates ravensRole for ONLY the IDs passed in.

    Parameters
    ----------
    role_sets : dict
        {
          "inheritOnlyClass":     [EA_Element_ID, ...],
          "containerClass":       [EA_Element_ID, ...],
          "substitutableClass":   [EA_Element_ID, ...],
        }
        (assumed disjoint)
    out_path : str | None
        Optional path to write the .js script.
    print_to_console : bool
        If True, print the generated script to stdout.

    Returns
    -------
    str
        The JScript text.
    """
    if role_sets is None:
        raise ValueError("export_ea_jscript_all: role_sets must be provided (disjoint).")

    inh_ids = sorted({int(x) for x in role_sets.get("inheritOnlyClass", []) if x is not None})
    con_ids = sorted({int(x) for x in role_sets.get("containerClass", []) if x is not None})
    sub_ids = sorted({int(x) for x in role_sets.get("substitutableClass", []) if x is not None})

    # Defensive overlap check (reported as warnings in the script console)
    overlap_inh_con = set(inh_ids) & set(con_ids)
    overlap_inh_sub = set(inh_ids) & set(sub_ids)
    overlap_con_sub = set(con_ids) & set(sub_ids)

    all_ids = sorted(set(inh_ids) | set(con_ids) | set(sub_ids))

    def fmt_array(name, items):
        if not items:
            return f"var {name} = [];"
        CHUNK = 25
        lines = []
        for i in range(0, len(items), CHUNK):
            lines.append(", ".join(str(v) for v in items[i:i+CHUNK]))
        inner = ",\n    ".join(lines)
        return f"var {name} = [\n    {inner}\n];"

    script = f"""//!INC Local Scripts.EAConstants-JScript

// Update ravensRole for selected elements only.
// NOTE: This script *only* clears/sets IDs we pass in. It will not touch any others.

{fmt_array("ALL_IDS", all_ids)}
{fmt_array("INHERITONLY_IDS", inh_ids)}
{fmt_array("CONTAINER_IDS",   con_ids)}
{fmt_array("SUBSTITUTABLE_IDS", sub_ids)}

// --- helpers ---
function setMsg(label, arr) {{
    Session.Output(label + " (" + arr.length + "): " + (arr && arr.length ? arr.slice(0, 10).join(", ") + (arr.length>10?" ...":"") : "[]"));
}}

function clearSelected(ids) {{
    for (var i=0; i<ids.length; i++) {{
        var el = Repository.GetElementByID(ids[i]);
        if (!el) continue;
        if (el.Name && el.Name === "Root") continue;

        var tv = null;
        for (var t=0; t<el.TaggedValues.Count; t++) {{
            var candidate = el.TaggedValues.GetAt(t);
            if (candidate && candidate.Name === "ravensRole") {{
                tv = candidate; break;
            }}
        }}
        if (!tv) {{
            // create missing tag
            tv = el.TaggedValues.AddNew("ravensRole", "");
            tv.Value = "";
            tv.Update();
            el.TaggedValues.Refresh();
        }}

        // don't clear concrete roles
        if (tv.Value === "rootClass" || tv.Value === "embeddedClass") continue;

        // clear only if it's a not-concrete role we are resetting
        if (tv.Value === "inheritOnlyClass" || tv.Value === "containerClass" || tv.Value === "substitutableClass") {{
            tv.Value = "";
            tv.Update();
            el.TaggedValues.Refresh();
            el.Update();
        }}
    }}
}}

function setRoleByList(ids, roleValue) {{
    for (var i=0; i<ids.length; i++) {{
        var el = Repository.GetElementByID(ids[i]);
        if (!el) continue;
        if (el.Name && el.Name === "Root") continue;

        var tv = null;
        for (var t=0; t<el.TaggedValues.Count; t++) {{
            var candidate = el.TaggedValues.GetAt(t);
            if (candidate && candidate.Name === "ravensRole") {{
                tv = candidate; break;
            }}
        }}
        if (!tv) {{
            tv = el.TaggedValues.AddNew("ravensRole", "");
            tv.Value = "";
            tv.Update();
            el.TaggedValues.Refresh();
        }}

        // don't overwrite concrete roles
        if (tv.Value === "rootClass" || tv.Value === "embeddedClass") continue;

        // skip if already the desired value to minimize churn
        if (tv.Value === roleValue) continue;

        tv.Value = roleValue;
        tv.Update();
        el.TaggedValues.Refresh();
        el.Update();
    }}
}}

function main() {{
    Session.Output("Re-tagging selected not-concrete roles: starting...");
    setMsg("inheritOnly IDs", INHERITONLY_IDS);
    setMsg("container IDs", CONTAINER_IDS);
    setMsg("substitutable IDs", SUBSTITUTABLE_IDS);

    // Clear only those we will (re)set:
    clearSelected(ALL_IDS);

    // Because sets are expected disjoint, order is irrelevant; keep it stable.
    setRoleByList(INHERITONLY_IDS, "inheritOnlyClass");
    setRoleByList(CONTAINER_IDS,   "containerClass");
    setRoleByList(SUBSTITUTABLE_IDS, "substitutableClass");

    // Warn if overlaps (should be none if upstream enforces precedence)
    var warn = [];
    if ({'true' if overlap_inh_con else 'false'}) warn.push("inheritOnly ∩ container overlap exists");
    if ({'true' if overlap_inh_sub else 'false'}) warn.push("inheritOnly ∩ substitutable overlap exists");
    if ({'true' if overlap_con_sub else 'false'}) warn.push("container ∩ substitutable overlap exists");
    if (warn.length) {{
        for (var i=0; i<warn.length; i++) Session.Output("WARNING: " + warn[i]);
    }}

    Session.Output("Done. Updated " + ALL_IDS.length + " element(s).");
}}

main();
"""

    if print_to_console:
        print(script)
    if out_path:
        import pathlib
        pathlib.Path(out_path).write_text(script, encoding="utf-8")
    return script
