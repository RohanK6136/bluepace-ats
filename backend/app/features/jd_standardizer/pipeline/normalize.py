"""Mode-dependent item normalization (§8 step 12.1). Every applied edit is recorded."""

from __future__ import annotations

import re

from app.features.jd_standardizer.pipeline.textutil import has_marker, sentences, strip_marker

_ABBREV_END_RE = re.compile(r"(?:\betc|\be\.g|\bi\.e|\bvs|\bInc|\bLtd|\bCo|\bJr|\bSr|\b[A-Z])\.$")
_TRAILING_RE = re.compile(r"[.;,]+$")


def base_clean(text: str) -> tuple[str, list[str]]:
    edits: list[str] = []
    if has_marker(text):
        text = strip_marker(text)
        edits.append("strip_marker")
    collapsed = " ".join(text.split())
    if collapsed != text:
        edits.append("collapse_whitespace")
    return collapsed, edits


def strip_trailing(text: str) -> tuple[str, bool]:
    if _ABBREV_END_RE.search(text):
        return text, False
    new = _TRAILING_RE.sub("", text).rstrip()
    return new, new != text


def capitalize_first(text: str) -> tuple[str, bool]:
    if text and text[0].islower():
        return text[0].upper() + text[1:], True
    return text, False


def split_list_paragraph(text: str) -> list[str]:
    parts = sentences(text)
    return parts if len(parts) > 1 else [text]


def normalize_text(text: str, mode: str, list_section: bool) -> tuple[str, list[str]]:
    """Normalize one (already split) item text."""
    text, edits = base_clean(text)
    if mode == "verbatim":
        return text, edits
    if list_section:
        text, changed = strip_trailing(text)
        if changed:
            edits.append("strip_trailing_punct")
    text, changed = capitalize_first(text)
    if changed:
        edits.append("capitalize")
    return text, edits
