from __future__ import annotations

import re
from typing import Any, Dict, Optional

import pandas as pd

from ravens.uml.data import UMLData


def get_names_of_enumeration_classes(uml_data: UMLData) -> list[str]:
    return [str(o.Name) for o in uml_data.objects.itertuples() if o.Object_Type == "Class" and o.Stereotype == "enumeration"]


def parse_connector_label_info(dl_row, con_row, stereotype_text: Optional[str] = None) -> Dict[str, Any]:
    def _kv_semicolon(s: Optional[str]) -> Dict[str, str]:
        if not isinstance(s, str):
            return {}
        out = {}
        for part in s.split(";"):
            if "=" in part:
                k, v = part.split("=", 1)
                out[k] = v
        return out

    def parse_style(style: Optional[str]) -> Dict[str, Any]:
        kv = _kv_semicolon(style)

        def _to_int(x):
            try:
                return int(x)
            except Exception:
                return None

        return {
            "hide_all": kv.get("HideLabels", "0") == "1",
            "color": _to_int(kv.get("Color")),
        }

    def parse_geom_hidden_flags(geometry: Optional[str]) -> Dict[str, int]:
        if not isinstance(geometry, str):
            return {}
        h = {}
        for code, block in re.findall(r'(L[A-Z]{2})=([^;]*);', geometry):
            parts = dict(p.split('=', 1) for p in block.split(':') if '=' in p)
            if 'HDN' in parts:
                try:
                    h[code] = int(parts['HDN'])
                except Exception:
                    h[code] = 0
        return h

    style = parse_style(dl_row.get("Style"))
    hdn = parse_geom_hidden_flags(dl_row.get("Geometry"))

    def is_hidden(slot: str) -> bool:
        return style["hide_all"] or bool(hdn.get(slot, 0))

    def _s(key: str) -> str:
        val = con_row.get(key, "") if hasattr(con_row, "get") else con_row[key]
        return "" if val is None else str(val)

    if stereotype_text is None:
        stereotype_text = _s("Stereotype")

    return pd.Series({
        "name_text": _s("Name"),
        "name_hidden": is_hidden("LMT"),
        "stereotype_text": stereotype_text,
        "stereotype_hidden": is_hidden("LMB"),
        "start_role_text": _s("SourceRole"),
        "start_role_hidden": is_hidden("LLT"),
        "start_mult_text": _s("SourceCard"),
        "start_mult_hidden": is_hidden("LLB"),
        "end_role_text": _s("DestRole"),
        "end_role_hidden": is_hidden("LRT"),
        "end_mult_text": _s("DestCard"),
        "end_mult_hidden": is_hidden("LRB"),
        "hide_all_labels": style["hide_all"],
        "source": con_row['Start_Object_ID'],
        "target": con_row['End_Object_ID'],
    })


def connector_directionality_from_labels(label_info: pd.Series, *, connector_type: str, s_id: Any, e_id: Any):
    def _label_visible(text, hidden) -> bool:
        if bool(hidden):
            return False
        if text is None or (isinstance(text, float) and pd.isna(text)):
            return False
        s = str(text).strip()
        return s != "" and s.lower() != "nan"

    one_way_types = {"Generalization"}
    if connector_type in one_way_types:
        end_text = label_info.get("end_role_text")
        end_vis = _label_visible(end_text, label_info.get("end_role_hidden", False))
        start_text = label_info.get("start_role_text")
        start_vis = _label_visible(start_text, label_info.get("start_role_hidden", False))
        lbl = str(end_text).strip() if end_vis else (str(start_text).strip() if start_vis else None)
        return [(s_id, e_id, lbl)]

    if bool(label_info.get("hide_all_labels", False)):
        return [(s_id, e_id, None), (e_id, s_id, None)]

    start_text = label_info.get("start_role_text")
    end_text = label_info.get("end_role_text")
    start_vis = _label_visible(start_text, label_info.get("start_role_hidden", False))
    end_vis = _label_visible(end_text, label_info.get("end_role_hidden", False))

    if not start_vis and not end_vis:
        return [(s_id, e_id, None), (e_id, s_id, None)]
    if start_vis and not end_vis:
        return [(e_id, s_id, str(start_text).strip())]
    if end_vis and not start_vis:
        return [(s_id, e_id, str(end_text).strip())]
    return [(s_id, e_id, str(end_text).strip()), (e_id, s_id, str(start_text).strip())]


def parse_multiplicity(label_info):
    hide_all = bool(label_info.get("hide_all_labels", False))

    def _clean(val):
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return ""
        s = str(val).strip()
        return "" if s.lower() in {"", "nan", "none", "null"} else s

    def _pick(txt_key: str, hid_key: str):
        if hide_all or bool(label_info.get(hid_key, False)):
            return ""
        return _clean(label_info.get(txt_key))

    return {
        "start_mult": _pick("start_mult_text", "start_mult_hidden"),
        "end_mult": _pick("end_mult_text", "end_mult_hidden"),
    }


def orient_edge_attrs_for_direction(base_attrs, *, u, v, s_id, e_id, start_mult, end_mult, objects_df):
    out = base_attrs.copy()
    out["Start_Object"] = objects_df.loc[u]["Name"]
    out["End_Object"] = objects_df.loc[v]["Name"]

    if u == s_id and v == e_id:
        out["start_mult"] = start_mult
        out["end_mult"] = end_mult
    elif u == e_id and v == s_id:
        out["start_mult"] = end_mult
        out["end_mult"] = start_mult
    else:
        out["start_mult"] = start_mult if u == s_id else end_mult
        out["end_mult"] = end_mult if v == e_id else start_mult
    return out
