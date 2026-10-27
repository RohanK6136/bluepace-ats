"""Step 6 — Extract facts with the LLM (always). Verification happens in validate.py."""

from __future__ import annotations

from typing import Any

from app.core.errors import LLMBudgetExceeded, LLMStepFailed
from app.features.jd_standardizer.llm_schemas import facts_schema
from app.features.jd_standardizer.pipeline.llmstep import StepLLM
from app.features.jd_standardizer.pipeline.models import Candidate, CleanResult, Segmentation, StepTrace


def describe_candidate(c: Candidate) -> str:
    v = c.value
    if c.field == "experience":
        rng = f"{v['min_years']}-{v['max_years']}" if v.get("max_years") is not None else f"{v['min_years']}+"
        text = f"{rng} years ({v['scope']})"
    elif c.field == "duration_months":
        text = f"{v['months']} months"
    elif c.field == "country":
        text = f"{v['name']} ({v['iso2']})"
    elif c.field == "work_mode":
        text = ", ".join(v["modes"])
    else:
        text = str(v.get("value") or v.get("name"))
    return f"{c.field}: {text} [{c.line_id}, {c.source}]"


def facts_lines(cleaned: CleanResult, seg: Segmentation, cands: list[Candidate],
                max_header: int, first_body: int) -> list[dict[str, str]]:
    by_id = {ln.id: ln for ln in cleaned.lines}
    chrome = set(cleaned.chrome_ids)
    ids: set[str] = set(cleaned.header_ids[:max_header])
    ids |= {b.line_ids[0] for b in seg.blocks if b.kind == "kv"}
    ids |= {c.line_id for c in cands}
    body = [lid for b in seg.blocks for lid in b.line_ids]
    ids |= set(body[:first_body])
    ids -= chrome
    return [{"id": lid, "text": by_id[lid].text} for lid in sorted(ids, key=lambda i: by_id[i].n)]


async def extract_facts(cleaned: CleanResult, seg: Segmentation, cands: list[Candidate],
                        step_llm: StepLLM | None) -> tuple[dict[str, Any] | None, StepTrace]:
    trace = StepTrace(name="facts")
    if step_llm is None:
        trace.notes.append("degraded: regex candidates only")
        return None, trace
    s = step_llm.settings
    lines = facts_lines(cleaned, seg, cands, s.FACTS_MAX_HEADER_LINES, s.FACTS_FIRST_BODY_LINES)
    variables = {"candidates": [describe_candidate(c) for c in cands], "lines": lines}
    trace.input_summary = {"lines": len(lines), "candidates": len(cands)}
    n0 = len(step_llm.ctx.records)
    try:
        res = await step_llm.call("facts", "facts", variables, facts_schema(), s.FACTS_MAX_TOKENS)
    except (LLMStepFailed, LLMBudgetExceeded) as e:
        trace.notes.append(f"degraded: {e}")
        trace.llm_call_ids = step_llm.call_ids_since(n0)
        return None, trace
    trace.llm_call_ids = step_llm.call_ids_since(n0)
    trace.output_summary = res.parsed
    return res.parsed, trace
