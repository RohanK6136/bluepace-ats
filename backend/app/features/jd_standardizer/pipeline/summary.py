"""Step 11 — Short description via LLM (checked), with a template fallback."""

from __future__ import annotations

from app.core.errors import LLMBudgetExceeded, LLMStepFailed
from app.features.jd_standardizer.llm_schemas import summary_schema
from app.features.jd_standardizer.pipeline.checks import CheckContext, check_summary
from app.features.jd_standardizer.pipeline.llmstep import StepLLM
from app.features.jd_standardizer.pipeline.models import Fact, ShortDescription, StepTrace
from app.features.jd_standardizer.pipeline.policy import Policy


def location_text(fields: dict[str, Fact]) -> str | None:
    parts = [fields[f].value for f in ("city", "state") if isinstance(fields[f].value, str) and fields[f].value]
    country = fields["country"].value
    if isinstance(country, dict):
        parts.append(country["name"])
    return ", ".join(parts) if parts else None


def template_summary(fields: dict[str, Fact]) -> ShortDescription | None:
    title = fields["title"].value
    if not title:
        return None
    parts = [title]
    if fields["role_type"].value:
        parts.append(fields["role_type"].value)
    city = fields["city"].value if isinstance(fields["city"].value, str) else None
    country = fields["country"].value["name"] if isinstance(fields["country"].value, dict) else None
    loc = ", ".join(p for p in (city, country) if p)
    if loc:
        parts.append(loc)
    return ShortDescription(text=" · ".join(parts), origin="template")


async def summarize(fields: dict[str, Fact], about: str | None, responsibilities: list[str],
                    step_llm: StepLLM | None, policy: Policy, ctx: CheckContext,
                    max_chars: int) -> tuple[ShortDescription | None, StepTrace]:
    trace = StepTrace(name="summary")
    title = fields["title"].value
    if not title:
        trace.notes.append("no title: short_description null")
        return None, trace
    if step_llm is None or not step_llm.available:
        trace.notes.append("degraded: template")
        return template_summary(fields), trace
    s = step_llm.settings
    variables = {
        "max_chars": max_chars,
        "title": title,
        "role_type": fields["role_type"].value,
        "location": location_text(fields),
        "about": (about or "")[: s.SUMMARY_ABOUT_CHARS] or None,
        "responsibilities": responsibilities[:3],
        "repair_hint": None,
    }
    n0 = len(step_llm.ctx.records)
    for attempt in (1, 2):
        try:
            res = await step_llm.call("summary", "summary", variables, summary_schema(max_chars),
                                      s.SUMMARY_MAX_TOKENS)
        except (LLMStepFailed, LLMBudgetExceeded) as e:
            trace.notes.append(f"attempt {attempt} failed: {e}")
            break
        text = " ".join(res.parsed["summary"].split())
        codes = check_summary(text, title, ctx, policy, max_chars)
        if not codes:
            trace.llm_call_ids = step_llm.call_ids_since(n0)
            return ShortDescription(text=text, origin="llm"), trace
        variables["repair_hint"] = ", ".join(codes)
        trace.notes.append(f"attempt {attempt} rejected: {codes}")
    trace.llm_call_ids = step_llm.call_ids_since(n0)
    trace.notes.append("fallback: template")
    return template_summary(fields), trace
