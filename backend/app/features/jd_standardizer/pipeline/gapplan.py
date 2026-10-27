"""Step 8 — Gap plan: per-section status, action, tier, needs_input, brief_source lines."""

from __future__ import annotations

from dataclasses import dataclass

from app.features.jd_standardizer.pipeline.models import (
    FACT_FIELDS,
    GAP_FILL_ORDER,
    RENDERED_SECTIONS,
    Block,
    CleanResult,
    Fact,
    Flag,
    GapPlan,
    NeedsInput,
    SectionPlan,
)
from app.features.jd_standardizer.pipeline.policy import Policy
from app.features.jd_standardizer.pipeline.textutil import word_count

ITEM_KINDS = ("bullet", "paragraph", "kv")
TITLE_ONLY_MAX_BODY_WORDS = 10
BRIEF_MIN_DRAFTED_SECTIONS = 3


@dataclass
class GapPlanResult:
    plan: GapPlan
    dispositions: dict[str, str]
    flags: list[Flag]


def section_status(section: str, blocks: list[Block], policy: Policy) -> tuple[str, int, int]:
    items = [b for b in blocks if b.section == section and b.kind in ITEM_KINDS]
    words = sum(word_count(b.text) for b in items)
    pol = policy.section_policy(section)
    if section == "about_role" and "min_words_provided" in pol:
        if words >= pol["min_words_provided"]:
            return "provided", len(items), words
        if words >= pol.get("min_words_partial", 1):
            return "partial", len(items), words
        return "missing", len(items), words
    if "min_items_provided" in pol:
        if len(items) >= pol["min_items_provided"]:
            return "provided", len(items), words
        return ("partial" if items else "missing"), len(items), words
    return ("provided" if items else "missing"), len(items), words


def plan_gaps(cleaned: CleanResult, blocks: list[Block], fields: dict[str, Fact], dispositions: dict[str, str],
              policy: Policy, draft_gaps: bool) -> GapPlanResult:
    flags: list[Flag] = []
    sections: dict[str, SectionPlan] = {}
    for sec in RENDERED_SECTIONS:
        status, n_items, words = section_status(sec, blocks, policy)
        pol = policy.section_policy(sec)
        action, count = "none", 0
        if status == "missing" and pol.get("draft_when_missing"):
            action = "draft"
            count = pol.get("draft", {}).get("target_items", 1)
        elif status == "partial" and pol.get("supplement_when_partial"):
            d = pol.get("draft", {})
            action = "supplement"
            count = max(1, min(d.get("target_items", 1) - n_items, d.get("max_items", 1) - n_items))
        sections[sec] = SectionPlan(id=sec, status=status, items=n_items, words=words, action=action,
                                    draft_count=count)

    # body words: rendered-section lines + lines with no disposition yet (header leftovers)
    lines = {ln.id: ln for ln in cleaned.lines}
    disp = dict(dispositions)
    undisposed = [ln.id for ln in cleaned.lines if ln.id not in disp]
    body_words = sum(word_count(lines[lid].text) for lid, d in disp.items()
                     if d.startswith("section:")) + sum(word_count(lines[lid].text) for lid in undisposed)

    drafted = [s for s in GAP_FILL_ORDER if sections[s].action != "none"]
    core_provided = any(sections[s].status == "provided" for s in GAP_FILL_ORDER)
    threshold = policy.gap["tier"]["brief_body_words_below"]
    if not drafted:
        tier = "complete"
    elif len(drafted) >= BRIEF_MIN_DRAFTED_SECTIONS or (body_words < threshold and not core_provided):
        tier = "brief"
    else:
        tier = "partial"

    for lid in undisposed:
        if tier == "brief":
            disp[lid] = "brief_source"
        else:
            disp[lid] = "unassigned"
    unassigned = [lid for lid in undisposed if disp[lid] == "unassigned"]
    if unassigned:
        flags.append(Flag(code="unassigned_lines", severity="warn",
                          message=f"{len(unassigned)} line(s) not assigned to any section or fact",
                          lines=unassigned))

    needs: list[NeedsInput] = []
    required = set(policy.gap.get("required_facts", []))
    for name in FACT_FIELDS:
        f = fields[name]
        if f.status == "conflict":
            needs.append(NeedsInput(field=name, reason="conflict", candidates=f.candidates))
        elif name in required and f.status == "missing":
            needs.append(NeedsInput(field=name, reason="missing"))

    if (tier == "brief" and all(fields[f].status in ("missing", "conflict")
                                for f in ("role_type", "country", "experience"))
            and body_words < TITLE_ONLY_MAX_BODY_WORDS):
        flags.append(Flag(code="title_only_input", severity="warn",
                          message="input has little more than a title; drafts are generic"))

    if not draft_gaps:
        for sec, sp in sections.items():
            if sp.action != "none":
                flags.append(Flag(code="thin_section", severity="warn",
                                  message=f"{sec} is {sp.status}; drafting disabled"))
                sections[sec] = sp.model_copy(update={"action": "none", "draft_count": 0})

    plan = GapPlan(tier=tier, body_words=body_words, sections=sections, needs_input=needs)
    return GapPlanResult(plan=plan, dispositions=disp, flags=flags)
