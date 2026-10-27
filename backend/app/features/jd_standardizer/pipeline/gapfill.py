"""Steps 9–10 — Gap-fill missing/partial sections with the LLM, check drafts, one targeted retry."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.errors import LLMBudgetExceeded, LLMStepFailed, LLMUnavailable
from app.features.jd_standardizer.llm_schemas import gapfill_about_schema, gapfill_list_schema
from app.features.jd_standardizer.pipeline.checks import CheckContext, check_about, filter_bullets, repair_hint
from app.features.jd_standardizer.pipeline.llmstep import StepLLM
from app.features.jd_standardizer.pipeline.models import (
    GAP_FILL_ORDER,
    Fact,
    Flag,
    GapPlan,
    Item,
    Line,
    NeedsInput,
    StepTrace,
)
from app.features.jd_standardizer.pipeline.policy import Policy
from app.features.jd_standardizer.promptlib import load_exemplar, load_styles


@dataclass
class GapFillResult:
    drafts: dict[str, list[Item]] = field(default_factory=dict)
    needs_input: list[NeedsInput] = field(default_factory=list)
    flags: list[Flag] = field(default_factory=list)
    traces: list[StepTrace] = field(default_factory=list)


def fact_sheet(fields: dict[str, Fact]) -> list[str]:
    out: list[str] = []
    for name in ("title", "role_type", "country", "state", "city", "work_mode", "experience", "duration_months"):
        f = fields.get(name)
        if not f or f.status not in ("verified", "override") or f.value in (None, [], ""):
            continue
        v = f.value
        if name == "country":
            v = v["name"]
        elif name == "work_mode":
            v = ", ".join(v)
        elif name == "experience":
            v = (f"{v['min_years']}–{v['max_years']} years" if v.get("max_years") is not None
                 else f"{v['min_years']}+ years")
        elif name == "duration_months":
            v = f"{v} months"
        out.append(f"{name}: {v}")
    return out


def _existing_payload(existing: dict[str, list[str]], headings: dict[str, str]) -> list[dict[str, Any]]:
    return [{"heading": headings.get(s, s), "lines": items} for s, items in existing.items() if items]


async def _draft_section(section: str, count: int, plan_status: str, variables: dict[str, Any],
                         step_llm: StepLLM, policy: Policy, ctx: CheckContext,
                         result: GapFillResult) -> list[Item]:
    spec = policy.section_policy(section).get("draft", {})
    is_about = section == "about_role"
    trace = StepTrace(name=f"gapfill:{section}", input_summary={"count": count, "status": plan_status})
    n0 = len(step_llm.ctx.records)
    hint: str | None = None
    items: list[Item] = []
    for attempt in (1, 2):
        vars_ = {**variables, "repair_hint": hint}
        if is_about:
            vars_ |= {"min_sentences": spec["sentences"][0], "max_sentences": spec["sentences"][1],
                      "min_words": spec["words"][0], "max_words": spec["words"][1]}
            prompt, schema = "gapfill_about", gapfill_about_schema()
            max_tokens = step_llm.settings.GAPFILL_ABOUT_MAX_TOKENS
        else:
            vars_ |= {"section": section, "count": count, "style": load_styles()[section],
                      "min_words": spec["words"][0], "max_words": spec["words"][1]}
            prompt, schema, max_tokens = "gapfill_list", gapfill_list_schema(count), 60 * count + 80
        if not step_llm.fits(prompt, vars_, max_tokens):
            vars_["existing"] = []  # shrink: drop lowest-priority context first
            trace.notes.append("payload shrunk: existing sections dropped")
        try:
            res = await step_llm.call(f"gapfill_{section}", prompt, vars_, schema, max_tokens)
        except (LLMStepFailed, LLMBudgetExceeded) as e:
            trace.notes.append(f"attempt {attempt} failed: {e}")
            break
        if is_about:
            p = res.parsed
            text = " ".join(p["text"].split())
            codes = check_about(text, p.get("basis"), p.get("line"), ctx, policy, spec)
            if not codes:
                items = [Item(text=text, origin="ai_draft", basis=p.get("basis"),
                              lines=[p["line"]] if p.get("line") else [])]
                break
            hint = repair_hint([(text, codes)])
            trace.notes.append(f"attempt {attempt} rejected: {hint}")
            continue
        min_items = min(spec.get("min_items", 1), count)
        accepted, failures = filter_bullets(res.parsed["items"], section, tuple(spec["words"]), ctx, policy)
        if len(accepted) >= min_items:
            items = [Item(text=a["text"], origin="ai_draft", basis=a.get("basis"),
                          lines=[a["line"]] if a.get("line") else []) for a in accepted[:count]]
            if failures:
                result.flags.append(Flag(code="draft_partial", severity="info",
                                         message=f"{section}: {len(failures)} drafted bullet(s) dropped by checks"))
            break
        hint = repair_hint(failures)
        trace.notes.append(f"attempt {attempt}: {len(accepted)}/{min_items} bullets passed; {hint}")

    trace.llm_call_ids = step_llm.call_ids_since(n0)
    trace.output_summary = {"accepted": len(items)}
    result.traces.append(trace)
    if not items:
        result.needs_input.append(NeedsInput(field=section, reason="draft_failed"))
        result.flags.append(Flag(code=f"draft_failed:{section}", severity="warn",
                                 message=f"could not produce checked drafts for {section}"))
    return items


async def gap_fill(plan: GapPlan, fields: dict[str, Fact], existing: dict[str, list[str]],
                   brief_lines: list[Line], step_llm: StepLLM, policy: Policy, ctx: CheckContext,
                   headings: dict[str, str]) -> GapFillResult:
    result = GapFillResult()
    base = {
        "fact_sheet": fact_sheet(fields),
        "brief_lines": [{"id": ln.id, "text": ln.text} for ln in brief_lines],
    }
    existing = {k: list(v) for k, v in existing.items()}
    for section in GAP_FILL_ORDER:
        sp = plan.sections[section]
        if sp.action == "none" or not step_llm.available:
            continue
        variables = {**base, "existing": _existing_payload(existing, headings),
                     "example": load_exemplar(section)}
        try:
            items = await _draft_section(section, sp.draft_count, sp.status, variables, step_llm, policy, ctx,
                                         result)
        except LLMUnavailable:
            result.traces.append(StepTrace(name=f"gapfill:{section}", notes=["LLM unavailable: drafting stopped"]))
            break
        if items:
            result.drafts[section] = items
            existing.setdefault(section, []).extend(i.text for i in items)
            ctx.existing.extend(i.text for i in items)
    return result
