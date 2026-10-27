"""JSON schemas for constrained decoding. Built programmatically, no $ref, nullable via anyOf."""

from __future__ import annotations

from typing import Any

LINE_ID: dict[str, Any] = {"type": "string", "pattern": r"^L\d+$"}
LABELS = [
    "about_role", "responsibilities", "requirements", "nice_to_have", "offer", "additional_info",
    "company_about", "legal", "apply_cta", "unclassified", "keep",
]
BASIS = ["brief", "generic_for_title"]


def nullable(schema: dict[str, Any]) -> dict[str, Any]:
    return {"anyOf": [schema, {"type": "null"}]}


def _obj(props: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "required": list(props), "properties": props}


def _text_fact() -> dict[str, Any]:
    return _obj({
        "value": nullable({"type": "string", "maxLength": 120}),
        "line": nullable(LINE_ID),
        "quote": nullable({"type": "string", "maxLength": 200}),
    })


def facts_schema() -> dict[str, Any]:
    props: dict[str, Any] = {
        f: _text_fact()
        for f in ("title", "category_hint", "role_type", "country", "state", "city", "work_mode")
    }
    props["experience"] = _obj({
        "min_years": nullable({"type": "number"}),
        "max_years": nullable({"type": "number"}),
        "scope": nullable({"type": "string", "enum": ["total", "relevant", "unspecified"]}),
        "line": nullable(LINE_ID),
        "quote": nullable({"type": "string", "maxLength": 200}),
    })
    props["duration_months"] = _obj({
        "months": nullable({"type": "integer"}),
        "line": nullable(LINE_ID),
        "quote": nullable({"type": "string", "maxLength": 200}),
    })
    return _obj(props)


def labels_schema(n: int) -> dict[str, Any]:
    item = _obj({
        "block": {"type": "string", "pattern": r"^B\d+$"},
        "section": {"type": "string", "enum": LABELS},
    })
    return _obj({"labels": {"type": "array", "items": item, "maxItems": n}})


def gapfill_list_schema(count: int) -> dict[str, Any]:
    item = _obj({
        "text": {"type": "string", "maxLength": 200},
        "basis": {"type": "string", "enum": BASIS},
        "line": nullable(LINE_ID),
    })
    return _obj({"items": {"type": "array", "items": item, "minItems": 1, "maxItems": count}})


def gapfill_about_schema() -> dict[str, Any]:
    return _obj({
        "text": {"type": "string", "maxLength": 600},
        "basis": {"type": "string", "enum": BASIS},
        "line": nullable(LINE_ID),
    })


def summary_schema(max_chars: int) -> dict[str, Any]:
    return _obj({"summary": {"type": "string", "maxLength": max_chars}})


def generate_schema(want: dict[str, Any], short_max: int) -> dict[str, Any]:
    """Single-call generation schema; only the pieces in `want` are requested (keeps output short)."""
    str_or_null = nullable({"type": "string", "maxLength": 160})
    facts = ("department", "employment_type", "location", "experience", "work_mode", "shift")
    props: dict[str, Any] = {
        "title": {"type": "string", "maxLength": 120},
        "short_description": {"type": "string", "maxLength": short_max + 40},
        "facts": _obj({k: str_or_null for k in facts}),
    }

    def strings(n: int, max_len: int) -> dict[str, Any]:
        return {"type": "array", "items": {"type": "string", "maxLength": max_len}, "minItems": n, "maxItems": n}

    if want.get("about_role"):
        props["about_role"] = strings(want["about_role"]["paragraphs"], 1200)
    resp = want.get("responsibilities")
    if resp and resp["groups"]:
        group = _obj({"heading": {"type": "string", "maxLength": 60}, "items": strings(resp["per_group"], 260)})
        props["responsibilities"] = {"type": "array", "items": group, "minItems": resp["groups"],
                                     "maxItems": resp["groups"]}
    elif resp:
        props["responsibilities"] = strings(resp["count"], 260)
    for key in ("qualifications", "preferred_skills"):
        if want.get(key):
            props[key] = strings(want[key]["count"], 260)
    return _obj(props)


def rewrite_schema(n: int) -> dict[str, Any]:
    item = _obj({"i": {"type": "integer"}, "text": {"type": "string", "maxLength": 300}})
    return _obj({"items": {"type": "array", "items": item, "minItems": n, "maxItems": n}})
