"""Step 12 — Assemble sections with provenance, standard blocks, markdown, publish gate, status."""

from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings
from app.features.jd_standardizer.pipeline.models import (
    LIST_SECTIONS,
    RENDERED_SECTIONS,
    STATUS_PRECEDENCE,
    Block,
    Fact,
    Flag,
    GapPlan,
    Item,
    Line,
    NeedsInput,
    SectionResult,
    ShortDescription,
)
from app.features.jd_standardizer.pipeline.normalize import normalize_text, split_list_paragraph
from app.features.jd_standardizer.pipeline.policy import Policy
from app.features.jd_standardizer.pipeline.textutil import norm, strip_marker

ITEM_KINDS = ("bullet", "paragraph", "kv")


@dataclass
class AssembleResult:
    sections: list[SectionResult]
    flags: list[Flag]


def headings(settings: Settings) -> dict[str, str]:
    return {k: v.replace("{company}", settings.COMPANY_NAME) for k, v in settings.SECTION_HEADINGS.items()}


def source_items(section: str, blocks: list[Block], lines: dict[str, Line], mode: str) -> list[Item]:
    items: list[Item] = []
    is_list = section in LIST_SECTIONS
    for b in blocks:
        if b.section != section or b.kind not in ITEM_KINDS:
            continue
        line_ids: list[str] = []
        for lid in b.line_ids:
            line_ids.append(lid)
            if lid in lines:
                line_ids.extend(lines[lid].merged_ids)
        parts = [b.text]
        split_edit: list[str] = []
        if mode != "verbatim" and is_list and b.kind == "paragraph":
            parts = split_list_paragraph(strip_marker(b.text))
            if len(parts) > 1:
                split_edit = ["sentence_split"]
        for part in parts:
            text, edits = normalize_text(part, mode, is_list)
            if text:
                items.append(Item(text=text, origin="source", lines=line_ids, group=b.group,
                                  edits=split_edit + edits))
    return items


def dedupe(items: list[Item], mode: str, section: str, flags: list[Flag]) -> list[Item]:
    seen: set[str] = set()
    out: list[Item] = []
    for it in items:
        key = norm(it.text)
        if key in seen:
            if mode == "verbatim":
                flags.append(Flag(code="duplicate_item", severity="info", message=f"{section}: '{it.text[:60]}'",
                                  lines=it.lines))
                out.append(it)
            else:
                flags.append(Flag(code="duplicate_removed", severity="info",
                                  message=f"{section}: '{it.text[:60]}'", lines=it.lines))
            continue
        seen.add(key)
        out.append(it)
    return out


def build_sections(blocks: list[Block], lines: dict[str, Line], plan: GapPlan, drafts: dict[str, list[Item]],
                   mode: str, settings: Settings) -> AssembleResult:
    flags: list[Flag] = []
    heads = headings(settings)
    sections: list[SectionResult] = []
    for sec in RENDERED_SECTIONS:
        items = source_items(sec, blocks, lines, mode)
        drafted = []
        for d in drafts.get(sec, []):
            text, edits = normalize_text(d.text, "light", sec in LIST_SECTIONS)
            drafted.append(d.model_copy(update={"text": text, "edits": edits}))
        items = dedupe(items + drafted, mode, sec, flags)
        status = plan.sections[sec].status
        if drafted:
            status = "drafted" if status == "missing" else "supplemented"
        if not items:
            status = "empty"
        sections.append(SectionResult(id=sec, heading=heads.get(sec, sec), status=status, items=items))

    for s in sections:
        if s.id in LIST_SECTIONS and len(s.items) > settings.LONG_SECTION_ITEMS:
            flags.append(Flag(code="long_section", severity="info",
                              message=f"{s.id} has {len(s.items)} items (> {settings.LONG_SECTION_ITEMS})"))
    where: dict[str, list[str]] = {}
    for s in sections:
        for it in s.items:
            if it.origin == "source":
                secs = where.setdefault(norm(it.text), [])
                if s.id not in secs:
                    secs.append(s.id)
    for key, secs in sorted(where.items()):
        if len(secs) >= 2:
            flags.append(Flag(code="cross_section_duplicate", severity="info",
                              message=f"'{key[:60]}' appears in {', '.join(secs)}"))
    return AssembleResult(sections=sections, flags=flags)


def standard_blocks(fields: dict[str, Fact], sections: list[SectionResult], policy: Policy,
                    settings: Settings) -> dict[str, dict]:
    heads = headings(settings)
    out: dict[str, dict] = {
        "about_company": {
            "origin": "standard", "block": "about_company", "heading": heads["about_company"],
            "text": policy.standard_blocks["about_company"].replace("{company}", settings.COMPANY_NAME),
        }
    }
    country = fields["country"].value
    iso2 = country["iso2"] if isinstance(country, dict) else None
    legal_id = policy.legal_regions.get(iso2 or "", policy.legal_default)
    if legal_id not in policy.standard_blocks:
        legal_id = policy.legal_default
    out["legal"] = {"origin": "standard", "block": legal_id, "heading": heads["legal"],
                    "text": policy.standard_blocks[legal_id]}
    offer = next((s for s in sections if s.id == "offer"), None)
    if settings.OFFER_BLOCK_ENABLED and offer is not None and not offer.items:
        out["offer"] = {"origin": "standard", "block": "offer_default", "heading": heads["offer"],
                        "text": policy.standard_blocks["offer_default"]}
    return out


# --------------------------------------------------------------- markdown
def _tag(it: Item, annotate: bool) -> str:
    return " [AI]" if annotate and it.origin == "ai_draft" else ""


def _num(v: float | int) -> str:
    return str(int(v)) if float(v).is_integer() else str(v)


def format_experience(v: dict | None) -> str | None:
    if not v:
        return None
    lo, hi = v.get("min_years"), v.get("max_years")
    if lo is not None and hi is not None:
        return f"{_num(lo)}–{_num(hi)} years"
    if lo is not None:
        return f"{_num(lo)}+ years"
    if hi is not None:
        return f"Up to {_num(hi)} years"
    return None


def meta_line(fields: dict[str, Fact]) -> str:
    parts: list[str] = []
    if fields["role_type"].value:
        parts.append(fields["role_type"].value)
    loc = [fields[f].value for f in ("city", "state") if isinstance(fields[f].value, str) and fields[f].value]
    if isinstance(fields["country"].value, dict):
        loc.append(fields["country"].value["name"])
    if loc:
        parts.append(", ".join(loc))
    exp = format_experience(fields["experience"].value)
    if exp:
        parts.append(exp)
    dur = fields["duration_months"].value
    if dur:
        parts.append(f"{dur} month{'s' if dur != 1 else ''}")
    return " · ".join(parts)


def render_markdown(fields: dict[str, Fact], sections: list[SectionResult], std: dict[str, dict],
                    annotate: bool) -> str:
    out = [f"# {fields['title'].value or 'Untitled role'}"]
    meta = meta_line(fields)
    if meta:
        out.append(meta)
    std_offer = std.get("offer")
    for s in sections:
        items = s.items
        if not items and not (s.id == "offer" and std_offer):
            continue
        out += ["", f"## {s.heading}"]
        if not items and std_offer:
            out += ["", std_offer["text"]]
            continue
        if s.id in LIST_SECTIONS:
            has_groups = any(it.group for it in items)
            out.append("")
            prev: object = object()
            for it in items:
                if has_groups and it.group != prev:
                    prev = it.group
                    if it.group:
                        if out[-1] != "":
                            out.append("")
                        out += [f"**{it.group}**", ""]
                out.append(f"- {it.text}{_tag(it, annotate)}")
        else:
            for it in items:
                out += ["", f"{it.text}{_tag(it, annotate)}"]
    for key in ("about_company", "legal"):
        out += ["", f"## {std[key]['heading']}", "", std[key]["text"]]
    return "\n".join(out).strip() + "\n"


# ------------------------------------------------------------ gate/status
def publish_gate(fields: dict[str, Fact], sections: list[SectionResult], flags: list[Flag],
                 short: ShortDescription | None, policy: Policy) -> list[str]:
    blockers: list[str] = []
    for name in policy.gap.get("required_facts", []):
        st = fields[name].status
        if st in ("missing", "conflict"):
            blockers.append(f"{name}: {st}")
    by_id = {s.id: s for s in sections}
    req = by_id.get("requirements")
    if req is None or not req.items:
        blockers.append("requirements: empty")
    for s in sections:
        if policy.section_policy(s.id).get("review_required") and any(
                it.origin == "ai_draft" and it.accepted is not True for it in s.items):
            blockers.append(f"{s.id}: ai_draft items need acceptance")
    for f in flags:
        if f.severity == "block":
            blockers.append(f"flag: {f.code}")
    if short is None:
        blockers.append("short_description: missing")
    return blockers


def compute_status(*, llm_unavailable: bool, needs_input: list[NeedsInput], sections: list[SectionResult],
                   flags: list[Flag]) -> str:
    candidates: list[str] = ["ok"]
    if llm_unavailable:
        candidates.append("llm_unavailable")
    if needs_input:
        candidates.append("needs_input")
    if any(it.origin == "ai_draft" for s in sections for it in s.items) or any(f.severity == "warn" for f in flags):
        candidates.append("needs_review")
    return min(candidates, key=STATUS_PRECEDENCE.index)
