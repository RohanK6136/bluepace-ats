"""Step 4 — Candidates: pure regex/rule fact candidates, each tied to a line id."""

from __future__ import annotations

import re
from typing import Any

from app.features.jd_standardizer.pipeline.location import (
    DEFAULT_RESOLVER,
    MODE_WORD_RE,
    LocationResolver,
    parse_location,
)
from app.features.jd_standardizer.pipeline.models import Candidate, CleanResult, Line, Segmentation
from app.features.jd_standardizer.pipeline.policy import Policy
from app.features.jd_standardizer.pipeline.textutil import (
    canonical_role_types,
    canonical_work_modes,
    strip_marker,
    word_count,
)

_YRS = r"(?:\s*(?:total|relevant|overall|professional|related|industry|work)\b)?\s*(?:years?|yrs?)\b"
EXP_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("range", re.compile(r"(?<!\d)(\d{1,2})\s*(?:-|–|—|to)\s*(\d{1,2})\s*\+?" + _YRS, re.I)),
    ("plus", re.compile(r"(?<!\d)(\d{1,2})\s*\+" + _YRS, re.I)),
    ("min", re.compile(r"(?:minimum|min\.?|at least)\s*(?:of\s*)?(\d{1,2})\s*\+?" + _YRS, re.I)),
    ("plain", re.compile(r"(?<!\d)(\d{1,2})" + _YRS, re.I)),
)
_NOT_EXPERIENCE_AFTER = re.compile(r"^\W*(?:contract|term|tenure|duration|of age|old|ago)\b", re.I)
_DUR_KEYWORDS = re.compile(r"\b(contract|duration|tenure|term|initial|extendable)\b", re.I)
_DUR_MONTHS = re.compile(r"(?<!\d)(\d{1,3})\s*[- ]?\s*(?:months?|mos?)\b", re.I)
_DUR_YEARS = re.compile(r"(?<!\d)(\d{1,2})\s*[- ]?\s*(?:years?|yrs?)\b", re.I)

ROLE_TYPE_HEADER_MAX_WORDS = 8
EXPERIENCE_SECTIONS = {"about_role", "requirements", "additional_info"}
DURATION_EXCLUDED_SECTIONS = {"responsibilities", "requirements", "nice_to_have", "offer", "company_about", "legal"}


def experience_matches(text: str) -> list[dict[str, Any]]:
    """All experience mentions in one line, longest pattern first, non-overlapping."""
    taken: list[tuple[int, int]] = []
    out: list[tuple[int, dict[str, Any]]] = []
    for kind, pat in EXP_PATTERNS:
        for m in pat.finditer(text):
            s, e = m.span()
            if any(s < te and ts < e for ts, te in taken):
                continue
            if _NOT_EXPERIENCE_AFTER.match(text[e:e + 20]):
                continue
            taken.append((s, e))
            if kind == "range":
                lo, hi = int(m.group(1)), int(m.group(2))
                value = {"min_years": min(lo, hi), "max_years": max(lo, hi)}
            else:
                value = {"min_years": int(m.group(1)), "max_years": None}
            value["scope"] = _scope(text, s, e)
            value["raw"] = m.group(0).strip()
            out.append((s, value))
    return [v for _, v in sorted(out, key=lambda x: x[0])]


def _scope(text: str, s: int, e: int) -> str:
    after = text[s:e + 30].casefold()
    hits = [(after.find(w), w) for w in ("total", "relevant") if w in after]
    if hits:
        return min(hits)[1]
    before = text[max(0, s - 15):s].casefold()
    for w in ("total", "relevant"):
        if w in before:
            return w
    return "unspecified"


def duration_months(text: str) -> tuple[int, str] | None:
    m = _DUR_MONTHS.search(text)
    if m:
        return int(m.group(1)), m.group(0).strip()
    m = _DUR_YEARS.search(text)
    if m:
        return int(m.group(1)) * 12, m.group(0).strip()
    return None


def _merge_experience(cands: list[Candidate]) -> list[Candidate]:
    merged: dict[tuple[Any, Any], Candidate] = {}
    for c in cands:
        key = (c.value["min_years"], c.value["max_years"])
        if key not in merged:
            merged[key] = c
        elif merged[key].value["scope"] == "unspecified" and c.value["scope"] != "unspecified":
            merged[key] = merged[key].model_copy(update={"value": {**merged[key].value, "scope": c.value["scope"]}})
    return list(merged.values())


def find_candidates(cleaned: CleanResult, seg: Segmentation, policy: Policy,
                    resolver: LocationResolver = DEFAULT_RESOLVER) -> list[Candidate]:
    lines: dict[str, Line] = {ln.id: ln for ln in cleaned.lines}
    header = [lines[i] for i in cleaned.header_ids]
    first_header_id = header[0].id if header else None
    out: list[Candidate] = []

    # ---- role_type: kv values; short header lines
    for b in seg.blocks:
        if b.kind == "kv" and b.kv_kind == "fact_role_type" and b.value:
            for rt in canonical_role_types(b.value, policy):
                out.append(Candidate(field="role_type", raw=b.value, value={"value": rt}, line_id=b.line_ids[0],
                                     source="kv"))
    for ln in header:
        if word_count(ln.text) <= ROLE_TYPE_HEADER_MAX_WORDS:
            for rt in canonical_role_types(strip_marker(ln.text), policy):
                out.append(Candidate(field="role_type", raw=strip_marker(ln.text), value={"value": rt},
                                     line_id=ln.id, source="header"))

    # ---- experience
    def exp_from(lns: list[tuple[str, str, str]]) -> list[Candidate]:
        res: list[Candidate] = []
        for lid, text, src in lns:
            for v in experience_matches(text):
                raw = v.pop("raw")
                res.append(Candidate(field="experience", raw=raw, value=v, line_id=lid, source=src))
        return res

    exp_lines: list[tuple[str, str, str]] = [(ln.id, ln.text, "header") for ln in header]
    nice_lines: list[tuple[str, str, str]] = []
    for b in seg.blocks:
        if b.kind == "kv":
            exp_lines.append((b.line_ids[0], b.text, "kv"))
        elif b.kind in ("bullet", "paragraph"):
            if b.section in EXPERIENCE_SECTIONS or b.section is None:
                exp_lines.append((b.line_ids[0], b.text, "regex"))
            elif b.section == "nice_to_have":
                nice_lines.append((b.line_ids[0], b.text, "regex"))
    exp = exp_from(exp_lines) or exp_from(nice_lines)
    out.extend(_merge_experience(exp))

    # ---- duration
    for b in seg.blocks:
        if b.kind == "kv" and b.kv_kind == "fact_duration" and b.value:
            d = duration_months(b.value)
            if d:
                out.append(Candidate(field="duration_months", raw=d[1], value={"months": d[0]},
                                     line_id=b.line_ids[0], source="kv"))
    dur_lines = [(ln.id, ln.text, "header") for ln in header] + [
        (b.line_ids[0], b.text, "regex") for b in seg.blocks
        if b.kind in ("bullet", "paragraph", "kv") and b.kv_kind != "fact_duration"
        and b.section not in DURATION_EXCLUDED_SECTIONS
    ]
    for lid, text, src in dur_lines:
        if _DUR_KEYWORDS.search(text):
            d = duration_months(text)
            if d:
                out.append(Candidate(field="duration_months", raw=d[1], value={"months": d[0]}, line_id=lid,
                                     source=src))

    # ---- location + work mode
    loc_sources: list[tuple[str, str, str, bool]] = []  # (line_id, text, source, allow_city)
    for b in seg.blocks:
        if b.kind == "kv" and b.kv_kind == "fact_location" and b.value:
            loc_sources.append((b.line_ids[0], b.value, "kv", True))
    for ln in header:
        loc_sources.append((ln.id, ln.text, "header", ln.id != first_header_id))
    for lid, text, src, allow_city in loc_sources:
        p = parse_location(text, policy, resolver)
        if p.country:
            out.append(Candidate(field="country", raw=text, value={"iso2": p.country[0], "name": p.country[1]},
                                 line_id=lid, source=src))
            if allow_city and p.state:
                out.append(Candidate(field="state", raw=text, value={"name": p.state}, line_id=lid,
                                     source=src))
            if allow_city and p.city:
                out.append(Candidate(field="city", raw=text, value={"name": p.city}, line_id=lid,
                                     source=src))
        modes = p.modes or (canonical_work_modes(text, policy) if MODE_WORD_RE.search(text) else [])
        if modes and (src == "kv" or p.country or word_count(text) <= ROLE_TYPE_HEADER_MAX_WORDS):
            out.append(Candidate(field="work_mode", raw=text, value={"modes": modes}, line_id=lid,
                                 source=src))
    for b in seg.blocks:
        if b.kind == "kv" and b.kv_kind == "fact_work_mode" and b.value:
            modes = canonical_work_modes(b.value, policy)
            if modes:
                out.append(Candidate(field="work_mode", raw=b.value, value={"modes": modes},
                                     line_id=b.line_ids[0], source="kv"))

    return out
