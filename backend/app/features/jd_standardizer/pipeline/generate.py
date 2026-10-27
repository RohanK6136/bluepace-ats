"""Fast mode: rule-based parse (ms) + ONE streamed LLM call that writes only what is missing.

Output layout (OpenAI-style, Blupace Tech branding):

    <Title>
    <Department> - <Location>
    <Employment type> · <Work model> · <Experience> · <Shift> · <Duration>
    About the Team / About the Role / Key Responsibilities / Qualifications / Preferred Skills /
    What We Offer / Additional Information / About Blupace Tech

Facts are never invented: values the model reports are used only to fill missing facts and only if they
appear in the recruiter's text. Everything the model writes is tagged origin="ai_draft". A source posting's
own employer block ("About OpenAI"), legal tail and compensation are dropped and replaced by Blupace Tech's.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import Field

from app.core.errors import LLMConfigError, LLMError, LLMTimeout, LLMUnavailable
from app.core.ids import new_request_id
from app.core.ingest import ingest_file, ingest_text, text_chars
from app.core.logging import log_event
from app.features.jd_standardizer.llm_schemas import generate_schema
from app.features.jd_standardizer.pipeline.assemble import format_experience, headings, source_items
from app.features.jd_standardizer.pipeline.candidates import experience_matches, find_candidates
from app.features.jd_standardizer.pipeline.checks import (
    banned_pattern_hits,
    banned_word_hits,
    build_context,
    ungrounded_tokens,
)
from app.features.jd_standardizer.pipeline.clean import clean
from app.features.jd_standardizer.pipeline.gapplan import section_status
from app.features.jd_standardizer.pipeline.location import DEFAULT_RESOLVER, parse_location
from app.features.jd_standardizer.pipeline.models import (
    FACT_FIELDS,
    OUTCOME_BY_STATUS,
    CleanResult,
    Fact,
    Flag,
    Item,
    Model,
    NeedsInput,
    NotImported,
    Options,
    Overrides,
    SplitHint,
)
from app.features.jd_standardizer.pipeline.runner import PipelineDeps, PipelineInput
from app.features.jd_standardizer.pipeline.segment import segment
from app.features.jd_standardizer.pipeline.textutil import (
    canonical_role_types,
    canonical_work_modes,
    heading_key,
    jaccard,
    norm,
    tokens,
    word_count,
)
from app.features.jd_standardizer.pipeline.validate import TITLE_PREFIX_RE, ValidateResult, validate
from app.features.jd_standardizer.promptlib import load_prompt
from app.llm.client import CallContext
from app.llm.types import ModelInfo
from app.observability.runs import RunRecorder

HARD_BANNED = ("pay", "deal", "benefits", "work_mode")  # deal terms: generated prose containing these is dropped
SOFT_BANNED = ("promo", "pronouns")  # style: kept, flagged for review
HEADER_KV = {"fact_location", "info_schedule"}  # shown in the header, not in Additional Information
TEAM_HEADINGS = {"about the team"}  # about_role blocks under these headings render as "About the Team"
DUPLICATE_JACCARD = 0.8
TITLE_MAX_WORDS = 10
MODE_LABEL = {"remote": "Remote", "hybrid": "Hybrid", "onsite": "On-site"}


# ------------------------------------------------------------------ output models
class TextOrigin(Model):
    text: str
    origin: Literal["source", "ai_draft", "template", "override"]


class HeaderLine(Model):
    label: str
    value: str


class FormatSection(Model):
    id: str
    heading: str
    kind: Literal["prose", "list"]
    items: list[Item]


class GenerateMeta(Model):
    pipeline_version: str
    prompt_version: int
    profile: str | None
    provider: str | None
    model: str | None
    model_fingerprint: str | None
    latency_ms: int
    llm_ms: int
    llm_calls: int
    cache_hit: bool
    prompt_tokens: int = 0
    completion_tokens: int = 0
    usage_estimated: bool = False
    cost_usd: float = 0.0
    generated: list[str]


def _meta(s: Any, model: ModelInfo, ctx: CallContext, t_start: float, llm_ms: int,
          generated: list[str]) -> GenerateMeta:
    return GenerateMeta(
        pipeline_version=s.PIPELINE_VERSION, prompt_version=load_prompt("generate").version, profile=model.profile,
        provider=model.provider, model=model.model, model_fingerprint=model.fingerprint,
        latency_ms=int((time.perf_counter() - t_start) * 1000), llm_ms=llm_ms, llm_calls=len(ctx.records),
        cache_hit=ctx.cache_hits > 0, prompt_tokens=ctx.prompt_tokens, completion_tokens=ctx.completion_tokens,
        usage_estimated=any(r.get("usage_estimated") for r in ctx.records), cost_usd=ctx.cost_usd,
        generated=generated,
    )


class GenerateResult(Model):
    request_id: str
    status: Literal["needs_text", "needs_split", "llm_unavailable", "needs_input", "needs_review", "ok"]
    final: bool = True
    publishable: bool
    publish_blockers: list[str]
    title: TextOrigin | None
    subtitle: str | None = Field(description="'<Department> - <Location>' line under the title")
    meta_line: list[str] = Field(description="Employment type · work model · experience · shift · duration")
    short_description: TextOrigin | None
    header: list[HeaderLine] = Field(description="Structured facts (label/value) for the portal form")
    sections: list[FormatSection]
    about_company: dict[str, Any] | None
    legal: dict[str, Any] | None
    long_description: str | None = Field(description="Full JD as Markdown")
    long_description_annotated: str | None = Field(description="Same, with [AI] after AI-drafted items")
    long_description_text: str | None = Field(description="Full JD as plain text (• bullets)")
    fields: dict[str, Fact]
    needs_input: list[NeedsInput]
    flags: list[Flag]
    not_imported: list[NotImported]
    meta: GenerateMeta
    message: str | None = None
    split_hints: list[SplitHint] | None = None


# ------------------------------------------------------------------ preparation
@dataclass
class Prepared:
    cleaned: CleanResult
    v: ValidateResult
    fields: dict[str, Fact]
    flags: list[Flag]
    want: dict[str, Any]
    source_text: str
    title_guess: str | None
    shift: str | None
    existing: list[str] = field(default_factory=list)


@dataclass
class Extras:
    """Display-only values reported by the model (verified against the text)."""

    department: str | None = None
    location_as_written: str | None = None
    shift: str | None = None


def _prefer_kv(fields: dict[str, Fact], flags: list[Flag]) -> dict[str, Fact]:
    """A labelled field (e.g. 'Employment Type: Full-Time') beats a loose header word; still flagged."""
    out = dict(fields)
    f = out["role_type"]
    if f.status == "conflict":
        kv_values = {c["value"] for c in f.candidates if c["source"] == "kv"}
        if len(kv_values) == 1:
            chosen = next(c for c in f.candidates if c["source"] == "kv")
            others = sorted({c["value"] for c in f.candidates} - kv_values)
            out["role_type"] = Fact(value=chosen["value"], status="verified", source="regex", line=chosen["line"],
                                    quote=chosen["raw"], candidates=f.candidates)
            for fl in flags:
                if fl.code == "role_type_conflict":
                    fl.message = (f"using '{chosen['value']}' from the labelled field; the header also says "
                                  f"{', '.join(others)}. Confirm.")
    return out


def title_guess(cleaned: CleanResult, v: ValidateResult) -> str | None:
    """Heuristic title for the instant preview / no-LLM fallback."""
    lines = {ln.id: ln for ln in cleaned.lines}
    header = [lines[i] for i in cleaned.header_ids]
    jd_marker = next((ln.n for ln in cleaned.lines if ln.id in cleaned.chrome_ids
                      and norm(ln.text) == "job description"), 0)
    for ln in header:
        if ln.n < jd_marker and any(h.n > jd_marker for h in header):
            continue
        if v.dispositions.get(ln.id, "").startswith("fact:") or word_count(ln.text) > TITLE_MAX_WORDS:
            continue
        return TITLE_PREFIX_RE.sub("", ln.text).strip() or None
    return None


def _shift(v: ValidateResult) -> str | None:
    for b in v.blocks:
        if b.kind == "kv" and b.kv_kind == "info_schedule" and b.value:
            return b.value
    return None


def plan_generation(v: ValidateResult, options: Options, gen_pol: dict[str, Any], policy: Any) -> dict[str, Any]:
    """What the model must write, sized by the detail profile (detailed | concise)."""
    want: dict[str, Any] = {}
    if not options.draft_gaps:
        return want
    prof = gen_pol["profiles"][options.detail]
    about, _, _ = section_status("about_role", v.blocks, policy)
    if about != "provided":
        want["about_role"] = {"paragraphs": prof["about_paragraphs"], "words": prof["about_words"]}
    resp, n_resp, _ = section_status("responsibilities", v.blocks, policy)
    total = prof["responsibility_groups"] * prof["bullets_per_group"] or prof["bullets_per_group"]
    if resp == "missing":
        want["responsibilities"] = {"groups": prof["responsibility_groups"], "per_group": prof["bullets_per_group"],
                                    "count": total, "words": prof["responsibility_words"]}
    elif resp == "partial":
        want["responsibilities"] = {"groups": 0, "per_group": 0, "words": prof["responsibility_words"],
                                    "count": max(gen_pol["supplement_min"], total - n_resp)}
    req, n_req, _ = section_status("requirements", v.blocks, policy)
    if req != "provided":
        n = prof["qualifications"]
        if req == "partial":
            n = max(gen_pol["supplement_min"], n - n_req)
        want["qualifications"] = {"count": n, "words": prof["qualification_words"]}
    nice, _, _ = section_status("nice_to_have", v.blocks, policy)
    if nice == "missing" and prof["preferred_skills"]:
        want["preferred_skills"] = {"count": prof["preferred_skills"], "words": prof["qualification_words"]}
    return want


def _location_text(fields: dict[str, Fact]) -> str | None:
    parts = [fields[k].value for k in ("city", "state") if isinstance(fields[k].value, str) and fields[k].value]
    if isinstance(fields["country"].value, dict):
        parts.append(fields["country"].value["name"])
    return ", ".join(parts) or None


def _known_facts(fields: dict[str, Fact], shift: str | None) -> list[str]:
    out: list[str] = []
    if fields["role_type"].status in ("verified", "override"):
        out.append(f"employment type: {fields['role_type'].value}")
    loc = _location_text(fields)
    if loc:
        out.append(f"location: {loc}")
    if fields["experience"].status in ("verified", "override"):
        exp = format_experience(fields["experience"].value)
        if exp:
            out.append(f"experience: {exp}")
    if shift:
        out.append(f"shift: {shift}")
    return out


def header_experience(v: dict[str, Any] | None) -> str | None:
    """'3 to 5 Years', '5+ Years'."""
    if not v:
        return None
    lo, hi = v.get("min_years"), v.get("max_years")
    if lo is not None and hi is not None:
        return f"{lo:g} to {hi:g} Years"
    if lo is not None:
        return f"{lo:g}+ Years"
    return f"Up to {hi:g} Years" if hi is not None else None


# ------------------------------------------------------------------ merge LLM output
def _in_source(value: str, src_norm: str, src_tokens: set[str]) -> bool:
    nv = norm(value)
    if not nv:
        return False
    if nv in src_norm:
        return True
    vt = tokens(value)
    return bool(vt) and sum(t in src_tokens for t in vt) / len(vt) >= 0.8


def merge_facts(fields: dict[str, Fact], facts: dict[str, Any], source: str, policy: Any,
                flags: list[Flag]) -> tuple[dict[str, Fact], Extras]:
    """Fill MISSING facts from the model's 'as written' values, only if they appear in the source."""
    out = dict(fields)
    extras = Extras()
    src_norm, src_tokens = norm(source), set(tokens(source))

    def ok(v: Any) -> bool:
        return isinstance(v, str) and _in_source(v, src_norm, src_tokens)

    def put(name: str, value: Any, quote: str) -> None:
        out[name] = Fact(value=value, status="verified", source="llm", quote=quote)

    rejected: list[str] = []
    et = facts.get("employment_type")
    if et and out["role_type"].status == "missing":
        found = canonical_role_types(et, policy) if ok(et) else []
        if len(found) == 1:
            put("role_type", found[0], et)
        else:
            rejected.append(f"employment type '{et}'")
    loc = facts.get("location")
    if all(out[k].status != "missing" for k in ("country", "city")):
        loc = None  # already known from the text; nothing to fill
    if loc and ok(loc):
        extras.location_as_written = " ".join(loc.split())
        p = parse_location(loc, policy, DEFAULT_RESOLVER)
        if p.country and out["country"].status == "missing":
            put("country", {"iso2": p.country[0], "name": p.country[1]}, loc)
        if p.city and out["city"].status == "missing" and out["country"].status != "conflict":
            put("city", p.city, loc)
        if p.state and out["state"].status == "missing":
            put("state", p.state, loc)
        if p.modes and out["work_mode"].status == "missing":
            put("work_mode", p.modes, loc)
    elif loc:
        rejected.append(f"location '{loc}'")
    exp = facts.get("experience")
    if exp and out["experience"].status == "missing":
        matches = (experience_matches(exp) or experience_matches(f"{exp} years")) if ok(exp) else []
        main = [m for m in matches if m["scope"] != "relevant"] or matches
        if main:
            m = main[0]
            put("experience", {"min_years": m["min_years"], "max_years": m["max_years"], "scope": m["scope"]}, exp)
        else:
            rejected.append(f"experience '{exp}'")
    wm = facts.get("work_mode")
    if wm and out["work_mode"].status == "missing" and ok(wm):
        modes = canonical_work_modes(wm, policy)
        if modes:
            put("work_mode", modes, wm)
    for key in ("shift", "department"):
        val = facts.get(key)
        if val and ok(val):
            setattr(extras, key, " ".join(val.split()))
    if rejected:
        flags.append(Flag(code="fact_unverified", severity="info",
                          message="ignored model facts not found in the text: " + "; ".join(rejected)))
    return out, extras


def _check_bullets(items: list[str], section: str, ctx: Any, policy: Any, bounds: list[int],
                   existing: list[str], flags: list[Flag]) -> list[str]:
    kept: list[str] = []
    dropped: list[str] = []
    for raw in items:
        text = " ".join(raw.split()).rstrip(".;, ").strip()
        if not text:
            continue
        n = len(text.split())
        reasons = [*banned_word_hits(text, policy, ctx.has_work_mode), *banned_pattern_hits(text, policy, ctx.numbers),
                   *[f"unknown name:{t}" for t in ungrounded_tokens(text, ctx)]]
        if not bounds[0] <= n <= bounds[1]:
            reasons.append(f"{n} words")
        if any(jaccard(text, e) >= DUPLICATE_JACCARD for e in [*existing, *kept]):
            reasons.append("duplicate")
        if reasons:
            dropped.append(f"{text[:60]}… ({', '.join(reasons[:2])})")
        else:
            kept.append(text[0].upper() + text[1:])
    if dropped:
        flags.append(Flag(code=f"draft_filtered:{section}", severity="info",
                          message=f"{len(dropped)} generated item(s) dropped by checks: "
                                  + "; ".join(dropped[:3])))
    return kept


def _check_prose(text: str, name: str, ctx: Any, policy: Any, flags: list[Flag]) -> str | None:
    text = " ".join(text.split())
    if not text:
        return None
    hard = (banned_word_hits(text, policy, ctx.has_work_mode, HARD_BANNED)
            or banned_pattern_hits(text, policy, ctx.numbers))
    if hard:
        flags.append(Flag(code=f"draft_rejected:{name}", severity="warn",
                          message=f"generated {name.replace('_', ' ')} dropped ({', '.join(hard[:3])})"))
        return None
    soft = banned_word_hits(text, policy, True, SOFT_BANNED) + [f"name:{t}" for t in ungrounded_tokens(text, ctx)]
    if soft:
        flags.append(Flag(code=f"style:{name}", severity="warn",
                          message=f"review wording in {name.replace('_', ' ')}: {', '.join(soft[:4])}"))
    return text


# ------------------------------------------------------------------ standard blocks
def markdown_parts(md: str) -> list[dict[str, Any]]:
    """Tiny Markdown subset used by standard blocks → [{"type": "p"|"h"|"ul", "text"|"items"}]."""
    parts: list[dict[str, Any]] = []
    for chunk in (c.strip() for c in md.strip().split("\n\n")):
        if not chunk:
            continue
        lines = [ln.strip() for ln in chunk.splitlines() if ln.strip()]
        if all(ln.startswith(("- ", "• ")) for ln in lines):
            parts.append({"type": "ul", "items": [ln[2:].strip() for ln in lines]})
        elif len(lines) == 1 and lines[0].startswith("#"):
            parts.append({"type": "h", "text": lines[0].lstrip("#").strip()})
        else:
            parts.append({"type": "p", "text": " ".join(lines)})
    return parts


def markdown_to_plain(md: str) -> str:
    out: list[str] = []
    for part in markdown_parts(md):
        if part["type"] == "ul":
            out.append("\n".join(f"• {i}" for i in part["items"]))
        else:
            out.append(part["text"])
    return "\n\n".join(out)


# ------------------------------------------------------------------ assembly
def _generated_groups(value: Any) -> list[tuple[str | None, list[str]]]:
    """Model output for a list section: flat ["…"] or grouped [{"heading", "items"}] → [(group, bullets)]."""
    if not value:
        return []
    if isinstance(value[0], dict):
        return [((g.get("heading") or "").strip() or None, list(g.get("items") or [])) for g in value]
    return [(None, list(value))]


def _status(needs: list[NeedsInput], flags: list[Flag], any_ai: bool, offline: bool) -> str:
    if offline:
        return "llm_unavailable"
    if needs:
        return "needs_input"
    if any_ai or any(f.severity == "warn" for f in flags):
        return "needs_review"
    return "ok"


def build_result(rid: str, prep: Prepared, gen: dict[str, Any] | None, *, final: bool, llm_problem: str | None,
                 deps: PipelineDeps, options: Options, overrides: Overrides, ctx: CallContext, model: ModelInfo,
                 t_start: float, llm_ms: int) -> GenerateResult:
    s, policy = deps.settings, deps.policy
    heads = headings(s)
    mode = options.mode if options.mode in ("verbatim", "light") else "light"
    flags = [f.model_copy() for f in prep.flags]
    fields = dict(prep.fields)
    gen = gen or {}
    lines = {ln.id: ln for ln in prep.cleaned.lines}
    blocks = prep.v.blocks

    extras = Extras()
    if gen.get("facts"):
        fields, extras = merge_facts(fields, gen["facts"], prep.source_text, policy, flags)
    shift = prep.shift or extras.shift
    ctx_checks = build_context(prep.cleaned.lines, set(prep.cleaned.chrome_ids), fields, prep.existing, policy)

    # ---- title / subtitle / meta line
    title: TextOrigin | None = None
    if overrides.title:
        title = TextOrigin(text=overrides.title.strip(), origin="override")
    elif gen.get("title"):
        t = TITLE_PREFIX_RE.sub("", " ".join(gen["title"].split())).strip()
        if t:
            title = TextOrigin(text=t, origin="source" if norm(t) in norm(prep.source_text) else "ai_draft")
    if title is None and prep.title_guess:
        title = TextOrigin(text=prep.title_guess, origin="source")
    fields["title"] = (Fact(value=title.text, status="override" if title.origin == "override" else "verified",
                            source="override" if title.origin == "override" else "llm" if gen else "regex")
                       if title else Fact())

    location = _location_text(fields) or extras.location_as_written
    department = extras.department or (fields["category_hint"].value if fields["category_hint"].value else None)
    subtitle = " - ".join(p for p in (department, location) if p) or None
    modes = [MODE_LABEL[m] for m in (fields["work_mode"].value or [])]
    exp = header_experience(fields["experience"].value) if fields["experience"].status != "conflict" else None
    role_type = fields["role_type"].value if fields["role_type"].status != "conflict" else None
    duration = f"{fields['duration_months'].value} months" if fields["duration_months"].value else None
    meta_line = [x for x in (role_type, "/".join(modes) or None, exp, shift, duration) if x]

    header = [HeaderLine(label="Company", value=s.COMPANY_NAME)]
    for label, value in (("Department", department), ("Location", location), ("Work Model", "/".join(modes)),
                         ("Employment Type", role_type), ("Experience", exp), ("Shift", shift),
                         ("Duration", duration)):
        if value:
            header.append(HeaderLine(label=label, value=value))

    # ---- sections
    sections: list[FormatSection] = []
    generated: list[str] = []
    team_blocks = [b for b in blocks if b.section == "about_role" and b.source_heading
                   and heading_key(b.source_heading) in TEAM_HEADINGS]
    role_blocks = [b for b in blocks if b not in team_blocks]
    team = source_items("about_role", team_blocks, lines, mode)
    if team:
        sections.append(FormatSection(id="about_team", heading=heads["about_team"], kind="prose", items=team))
    about = source_items("about_role", role_blocks, lines, mode)
    for para in gen.get("about_role") or []:
        text = _check_prose(para, "about_role", ctx_checks, policy, flags)
        if text:
            about.append(Item(text=text, origin="ai_draft", basis="generic_for_title"))
            if "about_role" not in generated:
                generated.append("about_role")
    if about:
        sections.append(FormatSection(id="about_role", heading=heads["about_the_role"], kind="prose", items=about))

    gen_pol = policy.gap["generate"]
    for sid, key, heading in (("responsibilities", "responsibilities", heads["responsibilities"]),
                              ("requirements", "qualifications", heads["qualifications"]),
                              ("nice_to_have", "preferred_skills", heads["preferred_skills"])):
        items = source_items(sid, blocks, lines, mode)
        if sid == "nice_to_have":
            items = [i.model_copy(update={"group": None}) for i in items]
        existing = [i.text for i in items]
        for group, bullets in _generated_groups(gen.get(key)):
            if group and (banned_word_hits(group, policy, ctx_checks.has_work_mode)
                          or banned_pattern_hits(group, policy, ctx_checks.numbers)):
                group = None
            kept = _check_bullets(bullets, key, ctx_checks, policy, gen_pol["bullet_words"], existing, flags)
            existing += kept
            items += [Item(text=t, origin="ai_draft", basis="generic_for_title", group=group) for t in kept]
            if kept and key not in generated:
                generated.append(key)
        if items:
            sections.append(FormatSection(id=sid, heading=heading, kind="list", items=items))

    offer =source_items("offer", blocks, lines, mode)
    if offer:
        sections.append(FormatSection(id="offer", heading=heads["offer"], kind="list", items=offer))
    extra = source_items("additional_info", [b for b in blocks if not (b.kind == "kv" and b.kv_kind in HEADER_KV)],
                         lines, mode)
    if extra:
        sections.append(FormatSection(id="additional_info", heading=heads["additional_info"], kind="prose",
                                      items=extra))

    # ---- short description
    short: TextOrigin | None = None
    if gen.get("short_description"):
        text = _check_prose(gen["short_description"], "short_description", ctx_checks, policy, flags)
        if text and len(text) <= s.SUMMARY_MAX_CHARS:
            short = TextOrigin(text=text, origin="ai_draft")
            generated.append("short_description")
    if short is None and title:
        short = TextOrigin(text=" · ".join([title.text, *([role_type] if role_type else []),
                                            *([location] if location else [])]), origin="template")

    company_md = policy.standard_blocks["about_company"].replace("{company}", s.COMPANY_NAME)
    about_company = {"heading": heads["about_company"], "origin": "standard", "block": "about_company",
                     "text": company_md, "parts": markdown_parts(company_md)}
    iso2 = fields["country"].value["iso2"] if isinstance(fields["country"].value, dict) else ""
    legal_id = policy.legal_regions.get(iso2, policy.legal_default)
    legal_text = policy.standard_blocks.get(legal_id, "")
    legal = (None if legal_text.upper().startswith("PLACEHOLDER")
             else {"heading": heads["legal"], "origin": "standard", "block": legal_id, "text": legal_text})

    # ---- needs_input / status / publish gate
    needs: list[NeedsInput] = []
    if title is None:
        needs.append(NeedsInput(field="title", reason="missing"))
    for name in policy.gap.get("required_facts", []):
        if name != "title" and fields[name].status in ("missing", "conflict"):
            needs.append(NeedsInput(field=name, reason=fields[name].status,
                                    candidates=fields[name].candidates or None))
    for name in FACT_FIELDS:
        if fields[name].status == "conflict" and not any(n.field == name for n in needs):
            needs.append(NeedsInput(field=name, reason="conflict", candidates=fields[name].candidates))
    if llm_problem:
        flags.append(Flag(code="llm_unavailable", severity="block", message=llm_problem))
    elif final and not gen:
        flags.append(Flag(code="generation_failed", severity="warn",
                          message="the model's answer could not be used; showing what was found in the text"))
    flags.sort(key=lambda f: (f.code, f.message))

    any_ai = bool((title and title.origin == "ai_draft") or any(i.origin == "ai_draft" for sec in sections
                                                                for i in sec.items))
    blockers = [f"{n.field}: {n.reason}" for n in needs]
    if any_ai:
        blockers.append("AI-drafted content needs review")
    blockers += [f"flag: {f.code}" for f in flags if f.severity == "block"]

    md, md_ai, txt = render_formats(title, subtitle, meta_line, sections, about_company, legal)
    return GenerateResult(
        request_id=rid, status=_status(needs, flags, any_ai, bool(llm_problem)), final=final,  # type: ignore[arg-type]
        publishable=not blockers, publish_blockers=blockers, title=title, subtitle=subtitle, meta_line=meta_line,
        short_description=short, header=header, sections=sections, about_company=about_company, legal=legal,
        long_description=md, long_description_annotated=md_ai, long_description_text=txt, fields=fields,
        needs_input=needs, flags=flags, not_imported=prep.v.not_imported,
        meta=_meta(s, model, ctx, t_start, llm_ms, generated),
    )


def render_formats(title: TextOrigin | None, subtitle: str | None, meta_line: list[str],
                   sections: list[FormatSection], about: dict[str, Any],
                   legal: dict[str, Any] | None) -> tuple[str, str, str]:
    name = title.text if title else "Untitled role"
    tail = [about] + ([legal] if legal else [])

    def md(annotate: bool) -> str:
        def tag(it: Item) -> str:
            return " [AI]" if annotate and it.origin == "ai_draft" else ""

        out = [f"# {name}"]
        if subtitle:
            out += ["", f"**{subtitle}**"]
        if meta_line:
            out += ["", " · ".join(meta_line)]
        for sec in sections:
            out += ["", f"## {sec.heading}", ""]
            if sec.kind == "prose":
                out += [x for it in sec.items for x in (f"{it.text}{tag(it)}", "")][:-1]
                continue
            group: str | None = None
            for it in sec.items:
                if it.group and it.group != group:
                    group = it.group
                    if out[-1] != "":
                        out.append("")
                    out += [f"**{group}**", ""]
                out.append(f"- {it.text}{tag(it)}")
        for block in tail:
            out += ["", f"## {block['heading']}", "", block["text"].strip()]
        return "\n".join(out).strip() + "\n"

    txt = [name] + ([subtitle] if subtitle else []) + ([" · ".join(meta_line)] if meta_line else []) + [""]
    for sec in sections:
        txt += [sec.heading, ""]
        group = None
        for it in sec.items:
            if sec.kind == "list" and it.group and it.group != group:
                group = it.group
                txt += [group, ""]
            txt += [f"• {it.text}" if sec.kind == "list" else it.text, ""]
    for block in tail:
        txt += [block["heading"], "", markdown_to_plain(block["text"]), ""]
    return md(False), md(True), "\n".join(txt).strip() + "\n"


# ------------------------------------------------------------------ driver
def _bare(rid: str, status: str, deps: PipelineDeps, ctx: CallContext, model: ModelInfo, t_start: float, *,
          message: str | None = None, split_hints: list[SplitHint] | None = None) -> GenerateResult:
    return GenerateResult(
        request_id=rid, status=status, publishable=False, publish_blockers=[status],  # type: ignore[arg-type]
        title=None, subtitle=None, meta_line=[], short_description=None, header=[], sections=[],
        about_company=None, legal=None, long_description=None, long_description_annotated=None,
        long_description_text=None, fields={f: Fact() for f in FACT_FIELDS}, needs_input=[], flags=[],
        not_imported=[], message=message, split_hints=split_hints,
        meta=_meta(deps.settings, model, ctx, t_start, 0, []),
    )


def _max_tokens(want: dict[str, Any], tok: dict[str, int]) -> int:
    n = tok["base"] + (tok["about"] if want.get("about_role") else 0)
    bullets = sum(want.get(k, {}).get("count", 0) for k in ("responsibilities", "qualifications", "preferred_skills"))
    return n + tok["per_bullet"] * bullets


def _llm_problem(e: Exception, model: ModelInfo) -> str:
    who = model.label or model.profile or "the model"
    if isinstance(e, LLMConfigError):
        return f"{who} is not usable: {e}"
    if isinstance(e, LLMTimeout):
        return (f"{who} accepted the request but is not responding ({e}). If it is a local server "
                "(LM Studio/Ollama), it is probably stuck: restart it or reload the model, then try again.")
    return f"{who} is unreachable ({e}). Start the model server or choose another model."


async def generate_events(inp: PipelineInput, options: Options, overrides: Overrides, deps: PipelineDeps,
                          request_id: str | None = None) -> AsyncIterator[dict[str, Any]]:
    """Yields {"event": "start"|"delta"|"final", ...}. IngestError is raised before the first event.

    Every invocation is recorded as a run (input, output, model, tokens, cost, latency, outcome), including
    failures and client disconnects.
    """
    s = deps.settings
    rid = request_id or new_request_id()
    ctx = CallContext(request_id=rid, use_cache=options.use_cache, profile_id=options.profile,
                      feature="jd_standardizer")
    model = deps.llm.describe(options.profile)
    recorder = RunRecorder(deps.store, s, feature="jd_standardizer", operation="generate", ctx=ctx, model=model,
                           options=options, overrides=overrides, pipeline_version=s.PIPELINE_VERSION)
    try:
        async for event in _generate_steps(inp, options, overrides, deps, ctx, model, recorder):
            yield event
    except GeneratorExit:
        recorder.finish(status="cancelled", outcome="error", error="client disconnected before the result")
        raise
    except BaseException as e:
        recorder.fail(e)
        raise


async def _generate_steps(inp: PipelineInput, options: Options, overrides: Overrides, deps: PipelineDeps,
                          ctx: CallContext, model: ModelInfo, recorder: RunRecorder) -> AsyncIterator[dict[str, Any]]:
    s, policy = deps.settings, deps.policy
    rid = ctx.request_id
    t_start = time.perf_counter()

    if inp.data is not None:
        raw, source_type = ingest_file(inp.filename or "upload.txt", inp.data, s)
        min_chars = s.MIN_TEXT_CHARS_FILE if source_type in ("pdf", "docx") else s.MIN_TEXT_CHARS_PASTED
    else:
        raw, source_type = ingest_text(inp.text or ""), "text"
        min_chars = s.MIN_TEXT_CHARS_PASTED
    recorder.start(source_type=source_type, input_text="\n".join(r.text for r in raw))

    def finish(res: GenerateResult, trace: dict[str, Any] | None = None) -> GenerateResult:
        recorder.finish(status=res.status, outcome=OUTCOME_BY_STATUS.get(res.status, "error"),  # type: ignore[arg-type]
                        title=res.title.text if res.title else None, result=res, trace=trace,
                        llm_ms=res.meta.llm_ms)
        return res

    chars = text_chars(raw)
    if chars < min_chars:
        res = _bare(rid, "needs_text", deps, ctx, model, t_start, message=f"only {chars} characters of text found")
        yield {"event": "final", "result": finish(res)}
        return

    cleaned = clean(raw, policy, s)
    if cleaned.split_hints:
        res = _bare(rid, "needs_split", deps, ctx, model, t_start, split_hints=cleaned.split_hints,
                    message="more than one job description detected; submit them one at a time")
        yield {"event": "final", "result": finish(res)}
        return

    seg = segment(cleaned, policy, s)
    cands = find_candidates(cleaned, seg, policy)
    v = validate(cleaned, seg, cands, None, overrides, policy, s)
    flags = list(v.flags)
    fields = _prefer_kv(v.fields, flags)
    gen_pol = policy.gap["generate"]
    want = plan_generation(v, options, gen_pol, policy)
    existing_ids = [sid for sid in ("about_role", "responsibilities", "requirements", "nice_to_have")
                    if section_status(sid, v.blocks, policy)[0] != "missing"]
    # Only text that survives into the posting is sent to the model (no foreign "About <employer>",
    # legal tail or compensation), so it cannot copy those into generated text.
    kept_ids = {lid for lid, d in v.dispositions.items() if not d.startswith("dropped:")}
    model_text = "\n".join(ln.text for ln in cleaned.lines
                           if ln.id in kept_ids or ln.id in cleaned.header_ids)
    prep = Prepared(cleaned=cleaned, v=v, fields=fields, flags=flags, want=want,
                    source_text=model_text[: gen_pol["max_source_chars"]], title_guess=title_guess(cleaned, v),
                    shift=_shift(v), existing=[b.text for b in v.blocks if b.kind in ("bullet", "paragraph")])

    common = {"deps": deps, "options": options, "overrides": overrides, "ctx": ctx, "model": model,
              "t_start": t_start}
    yield {"event": "start", "want": want,
           "result": build_result(rid, prep, None, final=False, llm_problem=None, llm_ms=0, **common)}

    tpl = load_prompt("generate")
    system, user = tpl.render(company=s.COMPANY_NAME, short_max=s.SUMMARY_MAX_CHARS, want=want,
                              known=_known_facts(fields, prep.shift), existing=existing_ids, text=prep.source_text)
    schema = generate_schema(want, s.SUMMARY_MAX_CHARS)
    max_tokens = _max_tokens(want, gen_pol["profiles"][options.detail]["tokens"])
    gen: dict[str, Any] | None = None
    llm_problem: str | None = None
    t_llm = time.perf_counter()
    parts: list[str] = []
    # The model call runs in its own task feeding a queue. If the client disconnects and this generator is
    # abandoned mid-stream, the task still finishes on its own and releases the per-model concurrency slot.
    queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

    async def produce() -> None:
        try:
            async for d in deps.llm.stream_json("generate", tpl.version, system, user, schema, max_tokens, ctx=ctx):
                queue.put_nowait(("delta", d))
            queue.put_nowait(("done", None))
        except Exception as e:  # noqa: BLE001 - surfaced to the consumer below
            queue.put_nowait(("error", e))

    task = asyncio.create_task(produce())
    try:
        while True:
            kind, payload = await queue.get()
            if kind == "delta":
                parts.append(payload)
                yield {"event": "delta", "text": payload}
            elif kind == "error":
                raise payload
            else:
                break
        gen = json.loads("".join(parts))
    except (LLMUnavailable, LLMTimeout) as e:
        llm_problem = _llm_problem(e, model)
    except (LLMError, json.JSONDecodeError) as e:
        log_event("generate_failed", run_id=rid, error=f"{type(e).__name__}: {e}")
    finally:
        if not task.done():  # consumer went away: stop generating
            task.cancel()
    llm_ms = int((time.perf_counter() - t_llm) * 1000)

    res = build_result(rid, prep, gen, final=True, llm_problem=llm_problem, llm_ms=llm_ms, **common)
    yield {"event": "final", "result": finish(res, trace={"want": want, "max_tokens": max_tokens,
                                                         "dispositions": dict(sorted(v.dispositions.items()))})}


async def generate(inp: PipelineInput, options: Options, overrides: Overrides, deps: PipelineDeps) -> GenerateResult:
    final: GenerateResult | None = None
    async for ev in generate_events(inp, options, overrides, deps):
        if ev["event"] == "final":
            final = ev["result"]
    assert final is not None
    return final
