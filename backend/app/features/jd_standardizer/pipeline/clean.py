"""Step 2 — Clean: normalize, unwrap, number lines, drop chrome, multi-JD guard, header zone."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from app.config import Settings
from app.features.jd_standardizer.pipeline.models import CleanResult, Line, RawLine, SplitHint
from app.features.jd_standardizer.pipeline.policy import Policy
from app.features.jd_standardizer.pipeline.textutil import (
    MARKER,
    has_marker,
    match_kv,
    match_section_heading,
    strip_marker,
    word_count,
)

_ZERO_WIDTH_RE = re.compile("[​‌‍⁠﻿­]")
_SPACES_RE = re.compile(r"[ \t -   　]+")
_BULLET_RE = re.compile(r"^(?:[•●▪◦‣∙·]\s*|[*\-–]\s+)")
_JD_PREFIX_RE = re.compile(r"^job description\s*:\s*\S", re.I)
_TERMINAL = (".", ":", ";", "!", "?")
BODY_START_MIN_WORDS = 12


def normalize_line(text: str) -> str:
    t = unicodedata.normalize("NFC", text).replace(" ", " ")
    t = _ZERO_WIDTH_RE.sub("", t)
    t = _SPACES_RE.sub(" ", t).strip()
    m = _BULLET_RE.match(t)
    if m:
        rest = t[m.end():].strip()
        t = MARKER + rest if rest else ""
    return t


def is_chrome(text: str, policy: Policy) -> bool:
    t = strip_marker(text).strip()
    return any(p.match(t) for p in policy.chrome_res)


def _can_unwrap(prev: dict[str, Any], cur: dict[str, Any], policy: Policy) -> bool:
    if cur["blank_before"]:
        return False
    a, b = prev["text"], cur["text"]
    if a.endswith(_TERMINAL) or has_marker(b) or not b[:1].islower():
        return False
    if prev["style"] == "heading" or match_section_heading(a, policy)[0] or match_kv(a, policy):
        return False
    return True


def _is_body_start(text: str, policy: Policy) -> bool:
    return bool(
        match_section_heading(text, policy)[0] and not match_section_heading(text, policy)[1]
        or match_kv(text, policy)
        or word_count(text) >= BODY_START_MIN_WORDS
        or has_marker(text)
    )


def _split_hints(lines: list[Line], policy: Policy) -> list[SplitHint]:
    jd_prefix = [ln for ln in lines if _JD_PREFIX_RE.match(ln.text)]
    if len(jd_prefix) >= 2:
        return [SplitHint(line=ln.n, title_guess=ln.text.split(":", 1)[1].strip()) for ln in jd_prefix]
    resp_idx = [i for i, ln in enumerate(lines) if match_section_heading(ln.text, policy)[0] == "responsibilities"]
    if len(resp_idx) < 2:
        return []
    hints: list[SplitHint] = []
    for i in resp_idx:
        guess = ""
        for ln in reversed(lines[:i]):
            if (not has_marker(ln.text) and not match_section_heading(ln.text, policy)[0]
                    and not match_kv(ln.text, policy) and word_count(ln.text) <= 8):
                guess = ln.text
                break
        hints.append(SplitHint(line=lines[i].n, title_guess=guess))
    return hints


def clean(raw: list[RawLine], policy: Policy, settings: Settings) -> CleanResult:
    # 1. normalize (blank lines are remembered only as paragraph breaks)
    entries: list[dict[str, Any]] = []
    blank = False
    for r in raw:
        t = normalize_line(r.text)
        if not t:
            blank = True
            continue
        entries.append({"text": t, "style": r.style, "level": r.level, "blank_before": blank})
        blank = False

    # 3. number lines before anything is merged or dropped, so ids/quotes are stable
    for i, e in enumerate(entries, start=1):
        e["id"], e["n"] = f"L{i:03d}", i

    # 2. unwrap hard-wrapped lines (merged line keeps the first id)
    merged: list[dict[str, Any]] = []
    for e in entries:
        if merged and _can_unwrap(merged[-1], e, policy):
            merged[-1]["text"] += " " + e["text"]
            merged[-1]["merged_ids"].append(e["id"])
            continue
        e["merged_ids"] = []
        merged.append(e)

    lines = [Line(id=e["id"], n=e["n"], text=e["text"], style=e["style"], level=e["level"],
                  merged_ids=e["merged_ids"]) for e in merged]

    # 4. chrome
    chrome_ids = [ln.id for ln in lines if is_chrome(ln.text, policy)]
    kept = [ln for ln in lines if ln.id not in set(chrome_ids)]

    # 5. multi-JD guard
    hints = _split_hints(kept, policy)
    if hints:
        return CleanResult(lines=lines, chrome_ids=chrome_ids, header_ids=[], split_hints=hints)

    # 6. header zone: first kept line → body start, capped
    body_start = next((i for i, ln in enumerate(kept) if _is_body_start(ln.text, policy)), len(kept))
    header_ids = [ln.id for ln in kept[: min(body_start, settings.HEADER_MAX_LINES)]]
    hdr = set(header_ids)
    lines = [ln.model_copy(update={"zone": "header"}) if ln.id in hdr else ln for ln in lines]
    return CleanResult(lines=lines, chrome_ids=chrome_ids, header_ids=header_ids)
