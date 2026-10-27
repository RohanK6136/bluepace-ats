"""Step 7 — Validate: quote-check LLM facts, resolve conflicts, overrides, flags, CTA removal, coverage."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.config import Settings
from app.features.jd_standardizer.pipeline.location import DEFAULT_RESOLVER, LocationResolver
from app.features.jd_standardizer.pipeline.models import (
    FACT_FIELDS,
    RENDERED_SECTIONS,
    Block,
    Candidate,
    CleanResult,
    Fact,
    Flag,
    Line,
    NotImported,
    Overrides,
    Segmentation,
)
from app.features.jd_standardizer.pipeline.policy import Policy
from app.features.jd_standardizer.pipeline.textutil import (
    canonical_role_types,
    canonical_work_modes,
    norm,
    sentences,
    strip_marker,
    tokens,
)

TITLE_PREFIX_RE = re.compile(r"^(job description|jd|job title|position|role)\s*[:\-–]\s*", re.I)
TOKEN_COVERAGE = 0.8
CTA_SECTIONS = {"additional_info", "offer", "about_role", "unclassified", None}
KV_FACT_FIELD = {
    "fact_role_type": "role_type",
    "fact_experience": "experience",
    "fact_duration": "duration_months",
    "fact_work_mode": "work_mode",
}
DROPPED_NOTICE_SECTIONS = ("company_about", "legal", "apply_cta", "unclassified")


@dataclass
class ValidateResult:
    fields: dict[str, Fact]
    flags: list[Flag]
    blocks: list[Block]
    dispositions: dict[str, str]
    not_imported: list[NotImported] = field(default_factory=list)


# --------------------------------------------------------------- quote check
def _supported(value: str, quote: str) -> bool:
    nv, nq = norm(value), norm(quote)
    if nv and nv in nq:
        return True
    vt = tokens(value)
    qt = set(tokens(quote))
    return bool(vt) and sum(1 for t in vt if t in qt) / len(vt) >= TOKEN_COVERAGE


def _num_in(n: float | int | None, quote: str) -> bool:
    if n is None:
        return True
    s = str(int(n)) if float(n).is_integer() else str(n)
    return re.search(rf"(?<!\d){re.escape(s)}(?!\d)", quote) is not None


def quote_check(raw: dict[str, Any] | None, lines: dict[str, Line], value_text: str | None) -> str | None:
    """Return None if OK, else a failure reason."""
    if not raw:
        return "empty"
    lid, quote = raw.get("line"), raw.get("quote")
    if not lid or lid not in lines:
        return "line_missing"
    if not quote or norm(quote) not in norm(lines[lid].text):
        return "quote_not_in_line"
    if value_text is not None and not _supported(value_text, quote):
        return "value_not_in_quote"
    return None


# ------------------------------------------------------------- LLM fact parse
def _llm_facts(llm: dict[str, Any] | None, lines: dict[str, Line], header_ids: set[str], policy: Policy,
               resolver: LocationResolver, flags: list[Flag]) -> dict[str, Fact]:
    """Return only LLM facts that pass the code checks (value + line + quote)."""
    out: dict[str, Fact] = {}
    if not llm:
        return out

    def fail(name: str, reason: str, raw: dict[str, Any]) -> None:
        flags.append(Flag(code=f"fact_unverified:{name}", severity="warn",
                          message=f"LLM value failed check ({reason}); cleared",
                          lines=[raw["line"]] if raw.get("line") else []))

    def ok(name: str, value: Any, raw: dict[str, Any], edits: list[str] | None = None) -> None:
        out[name] = Fact(value=value, status="verified", source="llm", line=raw["line"], quote=raw["quote"],
                         edits=edits or [])

    for name in ("title", "category_hint", "role_type", "country", "state", "city", "work_mode"):
        raw = llm.get(name) or {}
        value = raw.get("value")
        if value in (None, ""):
            continue
        reason = quote_check(raw, lines, value)
        if reason:
            fail(name, reason, raw)
            continue
        if name == "title":
            cleaned = TITLE_PREFIX_RE.sub("", value).strip()
            ok(name, cleaned, raw, ["title_prefix_stripped"] if cleaned != value.strip() else [])
        elif name == "category_hint":
            if raw["line"] in header_ids:
                ok(name, value.strip(), raw)
            else:
                fail(name, "not_in_header_zone", raw)
        elif name == "role_type":
            found = canonical_role_types(value, policy)
            if len(found) == 1:
                ok(name, found[0], raw)
            else:
                fail(name, "unknown_role_type", raw)
        elif name == "country":
            c = resolver.country(value)
            if c:
                ok(name, {"iso2": c[0], "name": c[1]}, raw)
            else:
                fail(name, "unknown_country", raw)
        elif name == "work_mode":
            modes = canonical_work_modes(value, policy)
            if modes:
                ok(name, modes, raw)
            else:
                fail(name, "unknown_work_mode", raw)
        else:  # state, city: as written
            ok(name, " ".join(value.split()), raw)

    exp = llm.get("experience") or {}
    if exp.get("min_years") is not None or exp.get("max_years") is not None:
        reason = quote_check(exp, lines, None)
        if not reason and not (_num_in(exp.get("min_years"), exp["quote"]) and
                               _num_in(exp.get("max_years"), exp["quote"])):
            reason = "numbers_not_in_quote"
        if reason:
            fail("experience", reason, exp)
        else:
            ok("experience", {"min_years": _int(exp.get("min_years")), "max_years": _int(exp.get("max_years")),
                              "scope": exp.get("scope") or "unspecified"}, exp)

    dur = llm.get("duration_months") or {}
    if dur.get("months") is not None:
        reason = quote_check(dur, lines, None)
        m = dur["months"]
        if not reason and not (_num_in(m, dur["quote"]) or (m % 12 == 0 and _num_in(m // 12, dur["quote"]))):
            reason = "numbers_not_in_quote"
        if reason:
            fail("duration_months", reason, dur)
        else:
            ok("duration_months", int(m), dur)
    return out


def _int(v: Any) -> Any:
    return int(v) if isinstance(v, float) and v.is_integer() else v


# ------------------------------------------------------------- resolution
def _cand_key(c: Candidate) -> Any:
    v = c.value
    if c.field == "role_type":
        return v["value"]
    if c.field == "country":
        return v["iso2"]
    if c.field in ("city", "state"):
        return v["name"].casefold()
    if c.field == "duration_months":
        return v["months"]
    if c.field == "experience":
        return (v["min_years"], v["max_years"])
    return repr(sorted(v.items()))


def _cand_value(c: Candidate) -> Any:
    v = c.value
    if c.field == "role_type":
        return v["value"]
    if c.field == "country":
        return {"iso2": v["iso2"], "name": v["name"]}
    if c.field in ("city", "state"):
        return v["name"]
    if c.field == "duration_months":
        return v["months"]
    if c.field == "experience":
        return {"min_years": v["min_years"], "max_years": v["max_years"], "scope": v["scope"]}
    return v


def _cand_public(c: Candidate) -> dict[str, Any]:
    return {"value": _cand_value(c), "line": c.line_id, "raw": c.raw, "source": c.source}


def _distinct(cands: list[Candidate]) -> dict[Any, list[Candidate]]:
    groups: dict[Any, list[Candidate]] = {}
    for c in cands:
        groups.setdefault(_cand_key(c), []).append(c)
    return groups


def resolve_fact(name: str, cands: list[Candidate], llm_fact: Fact | None) -> Fact:
    also: list[dict[str, Any]] = []
    if name == "experience":
        main = [c for c in cands if c.value["scope"] in ("total", "unspecified")]
        rel = [c for c in cands if c.value["scope"] == "relevant"]
        if main:
            also = [_cand_public(c) for c in rel]
            cands = main
    if name == "work_mode":
        modes: list[str] = []
        for c in cands:
            modes += c.value["modes"]
        if llm_fact:
            modes += llm_fact.value
        uniq = sorted(set(modes), key=["remote", "hybrid", "onsite"].index)
        if not uniq:
            return Fact(value=[], status="missing")
        src = llm_fact or None
        first = cands[0] if cands else None
        return Fact(value=uniq, status="verified", source="llm" if src else "regex",
                    line=src.line if src else first.line_id if first else None,
                    quote=src.quote if src else first.raw if first else None,
                    candidates=[_cand_public(c) for c in cands])
    groups = _distinct(cands)
    public = [_cand_public(c) for c in cands]
    if len(groups) >= 2:
        return Fact(value=None, status="conflict", candidates=public, also=also)
    if llm_fact is not None:
        return llm_fact.model_copy(update={"candidates": public, "also": also})
    if len(groups) == 1:
        c = next(iter(groups.values()))[0]
        return Fact(value=_cand_value(c), status="verified", source="regex", line=c.line_id, quote=c.raw,
                    candidates=public, also=also)
    return Fact(value=None, status="missing", also=also)


def apply_overrides(fields: dict[str, Fact], ov: Overrides, resolver: LocationResolver) -> dict[str, Fact]:
    out = dict(fields)

    def put(name: str, value: Any) -> None:
        prev = out.get(name) or Fact()
        out[name] = Fact(value=value, status="override", source="override", candidates=prev.candidates)

    if ov.title is not None:
        put("title", ov.title.strip())
    if ov.role_type is not None:
        put("role_type", ov.role_type)
    if ov.country_iso2 is not None:
        c = resolver.country(ov.country_iso2)
        put("country", {"iso2": ov.country_iso2, "name": c[1] if c else ov.country_iso2})
    if ov.state is not None:
        put("state", ov.state)
    if ov.city is not None:
        put("city", ov.city)
    if ov.work_mode is not None:
        put("work_mode", ov.work_mode)
    if ov.experience is not None and (ov.experience.min_years is not None or ov.experience.max_years is not None):
        put("experience", {"min_years": _int(ov.experience.min_years), "max_years": _int(ov.experience.max_years),
                           "scope": "unspecified"})
    if ov.duration_months is not None:
        put("duration_months", ov.duration_months)
    return out


# ------------------------------------------------------------------ CTA
def remove_cta(blocks: list[Block], policy: Policy) -> tuple[list[Block], list[NotImported]]:
    out: list[Block] = []
    dropped: list[NotImported] = []
    for b in blocks:
        if b.kind not in ("bullet", "paragraph", "kv") or b.section not in CTA_SECTIONS:
            out.append(b)
            continue
        sents = sentences(strip_marker(b.text))
        is_cta = [any(p.search(s) for p in policy.cta_res) for s in sents]
        if not any(is_cta):
            out.append(b)
            continue
        for s, cta in zip(sents, is_cta, strict=True):
            if cta:
                dropped.append(NotImported(lines=list(b.line_ids), text=s, reason="apply_cta"))
        keep = [s for s, cta in zip(sents, is_cta, strict=True) if not cta]
        if not keep:
            out.append(b.model_copy(update={"section": "apply_cta"}))
            continue
        for k, s in enumerate(keep, start=1):
            out.append(b.model_copy(update={"id": f"{b.id}.{k}", "text": s, "kind": "paragraph"}))
    return out, dropped


# -------------------------------------------------------------- dispositions
def dispositions(cleaned: CleanResult, blocks: list[Block], fields: dict[str, Fact],
                 cands: list[Candidate]) -> dict[str, str]:
    disp: dict[str, str] = {lid: "dropped:chrome" for lid in cleaned.chrome_ids}
    fact_lines: dict[str, str] = {}
    for name in FACT_FIELDS:
        f = fields.get(name)
        if f and f.line and f.status in ("verified", "override"):
            fact_lines.setdefault(f.line, f"fact:{name}")
    for c in cands:
        fact_lines.setdefault(c.line_id, f"fact:{c.field}")
    for b in blocks:
        for lid in b.line_ids:
            if lid in disp:
                continue
            if b.kind == "kv":
                if b.kv_kind == "fact_company":
                    disp[lid] = "dropped:company_kv"
                elif b.kv_kind in KV_FACT_FIELD:
                    disp[lid] = f"fact:{KV_FACT_FIELD[b.kv_kind]}"
                elif b.section in RENDERED_SECTIONS:
                    disp[lid] = f"section:{b.section}"
                else:
                    disp[lid] = f"dropped:{b.section or 'unclassified'}"
            elif b.section in RENDERED_SECTIONS:
                disp[lid] = f"section:{b.section}"
            else:
                disp[lid] = f"dropped:{b.section or 'unclassified'}"
    for lid in cleaned.header_ids:
        if lid not in disp and lid in fact_lines:
            disp[lid] = fact_lines[lid]
    return disp


# ------------------------------------------------------------------ main
def validate(cleaned: CleanResult, seg: Segmentation, cands: list[Candidate], llm_facts: dict[str, Any] | None,
             overrides: Overrides, policy: Policy, settings: Settings,
             resolver: LocationResolver = DEFAULT_RESOLVER) -> ValidateResult:
    lines = {ln.id: ln for ln in cleaned.lines}
    flags: list[Flag] = []
    llm_ok = _llm_facts(llm_facts, lines, set(cleaned.header_ids), policy, resolver, flags)

    by_field: dict[str, list[Candidate]] = {}
    for c in cands:
        by_field.setdefault(c.field, []).append(c)
    fields: dict[str, Fact] = {}
    for name in FACT_FIELDS:
        fields[name] = resolve_fact(name, by_field.get(name, []), llm_ok.get(name))
    fields = apply_overrides(fields, overrides, resolver)

    for name, f in fields.items():
        if f.status == "conflict":
            flags.append(Flag(code=f"{name}_conflict", severity="warn",
                              message=f"{len(f.candidates)} conflicting values for {name}",
                              lines=sorted({c['line'] for c in f.candidates})))

    # title_contains_location
    title = fields["title"].value
    if isinstance(title, str) and "," in title:
        tail = title.rsplit(",", 1)[1].strip()
        city = fields["city"].value
        if resolver.country(tail) or (isinstance(city, str) and tail.casefold() == city.casefold()):
            flags.append(Flag(code="title_contains_location", severity="warn",
                              message=f"title ends with location '{tail}'",
                              lines=[fields["title"].line] if fields["title"].line else []))

    blocks, cta_dropped = remove_cta(seg.blocks, policy)
    if cta_dropped:
        flags.append(Flag(code="cta_removed", severity="info",
                          message=f"{len(cta_dropped)} apply/CTA sentence(s) removed",
                          lines=sorted({lid for n in cta_dropped for lid in n.lines})))

    # foreign employer names in kept text
    kept_text = " ".join(b.text for b in blocks if b.section in RENDERED_SECTIONS and b.kind != "section_heading")
    for name in seg.foreign_employer_candidates:
        count = len(re.findall(rf"(?<!\w){re.escape(name)}(?!\w)", kept_text, re.I))
        if count:
            flags.append(Flag(code="foreign_employer_name", severity="warn",
                              message=f"'{name}' appears {count} time(s) in kept text"))

    # dropped sections
    not_imported = list(cta_dropped)
    for sec in DROPPED_NOTICE_SECTIONS:
        dropped = [b for b in blocks if b.section == sec]
        if not dropped:
            continue
        flags.append(Flag(code=f"section_dropped:{sec}", severity="warn" if sec == "unclassified" else "info",
                          message=f"{len(dropped)} block(s) dropped as {sec}",
                          lines=[lid for b in dropped for lid in b.line_ids]))
        for b in dropped:
            if b.kind != "section_heading":
                not_imported.append(NotImported(lines=list(b.line_ids), text=b.text, reason=sec))
    for b in blocks:
        if b.kind == "kv" and b.kv_kind == "fact_company":
            not_imported.append(NotImported(lines=list(b.line_ids), text=b.text, reason="company_kv"))

    disp = dispositions(cleaned, blocks, fields, cands)
    return ValidateResult(fields=fields, flags=flags, blocks=blocks, dispositions=disp, not_imported=not_imported)
