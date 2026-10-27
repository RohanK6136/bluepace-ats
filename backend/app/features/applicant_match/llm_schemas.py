"""JSON schemas for the Applicant Match model calls. Outputs are labels and cited line ids only, never scores."""

from __future__ import annotations

from typing import Any

LINE_ID = {"type": "string", "pattern": "^[JL][0-9]{2,3}$"}


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    return {"anyOf": [schema, {"type": "null"}]}


def _obj(props: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "required": list(props), "properties": props}


def rubric_schema(max_items: int = 60) -> dict[str, Any]:
    item = _obj({
        "line": LINE_ID,
        "label": {"type": "string", "minLength": 1, "maxLength": 120},
        "type": {"type": "string", "enum": ["skill", "certification", "language", "other"]},
        "group": {"type": "string", "enum": ["coding", "cloud_tools", "domain", "soft", "other"]},
    })
    return _obj({"items": {"type": "array", "items": item, "maxItems": max_items}})


def profile_schema() -> dict[str, Any]:
    text = {"type": "string", "maxLength": 200}
    role = _obj({
        "title": text, "company": _nullable(text), "start": _nullable({"type": "string", "maxLength": 40}),
        "end": _nullable({"type": "string", "maxLength": 40}), "first_line": LINE_ID, "last_line": LINE_ID,
    })
    cited = _obj({"line": LINE_ID, "text": text})
    return _obj({
        "roles": {"type": "array", "items": role, "maxItems": 15},
        "education": {"type": "array", "items": cited, "maxItems": 8},
        "certifications": {"type": "array", "items": cited, "maxItems": 20},
        "languages": {"type": "array", "items": cited, "maxItems": 10},
        "location": _nullable(cited),
    })


def judge_schema(ids: list[str]) -> dict[str, Any]:
    j = _obj({
        "id": {"type": "string", "enum": ids},
        "verdict": {"type": "string", "enum": ["met", "partial", "no"]},
        "line": _nullable(LINE_ID),
        "quote": _nullable({"type": "string", "maxLength": 200}),
    })
    return _obj({"judgments": {"type": "array", "items": j, "maxItems": len(ids)}})


def summary_schema(max_chars: int = 600) -> dict[str, Any]:
    return _obj({"summary": {"type": "string", "minLength": 20, "maxLength": max_chars}})
