"""Neutral two-to-three sentence summary, written after scoring. Code checks it and falls back to a template.

Checks (all must pass): at most N words; no verdict words; no protected terms; every number and every
capitalised word (except the first word of a sentence) appears in the facts the model was given.
"""

from __future__ import annotations

import re
from typing import Any

from app.config import Settings
from app.core.errors import LLMError
from app.features.applicant_match.llm_schemas import summary_schema
from app.features.applicant_match.models import Summary
from app.features.applicant_match.policy import MatchPolicy, fold, load_prompt
from app.features.applicant_match.scoring import Evaluation
from app.llm.client import CallContext, ChatLLM, call_with_retry

EDU_NAMES = {"phd": "PhD", "master": "Master's degree", "bachelor": "Bachelor's degree",
             "associate": "Associate degree", "diploma": "Diploma", "high_school": "High school", "none": None}
NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
SENTENCE_START_RE = re.compile(r"(?:^|[.!?]\s+)([A-Z][\w'’\-]*)")
CAP_WORD_RE = re.compile(r"\b[A-Z][\w'’+#.\-]*")


def summary_facts(ev: Evaluation, prof_latest: tuple[str | None, str | None], required_years: float | None,
                  education_level: str | None) -> dict[str, Any]:
    musts = [e for e in ev.evidence if e.importance == "must"]
    return {
        "latest_title": prof_latest[0], "latest_company": prof_latest[1],
        "total_years": ev.total_years, "relevant_years": ev.relevant_years, "required_years": required_years,
        "education": EDU_NAMES.get(education_level or "none"),
        "must_met": sum(e.status == "met" for e in musts), "must_total": len(musts),
        "met_labels": [e.label for e in musts if e.status == "met"][:12],
        "partial_labels": [e.label for e in ev.evidence if e.status == "partial"][:8],
        "missing_labels": [e.label for e in musts if e.status in ("not_evidenced", "unclear")][:10],
        "nice_met_labels": [e.label for e in ev.evidence if e.importance == "nice" and e.status == "met"][:8],
    }


def template(f: dict[str, Any]) -> str:
    who = f["latest_title"] or "Applicant"
    years = f"{f['total_years']:g} years of dated experience" if f["total_years"] is not None else \
        "experience dates that could not be read"
    at = f", most recently at {f['latest_company']}" if f["latest_company"] else ""
    return (f"{who} with {years}{at}. Evidence found for {f['must_met']} of {f['must_total']} must-have "
            f"requirements.")


def check(text: str, facts_text: str, mp: MatchPolicy) -> str | None:
    """Returns the reason the summary is rejected, or None."""
    max_words = mp.settings["summary"]["max_words"]
    if len(text.split()) > max_words:
        return f"longer than {max_words} words"
    low = fold(text)
    for w in mp.settings["summary"]["verdict_words"]:
        if re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", low):
            return f"contains a verdict word ('{w}')"
    for w in mp.protected_terms:
        if re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", low):
            return f"mentions a protected attribute ('{w}')"
    facts = fold(facts_text)
    for n in NUMBER_RE.findall(text):
        if n not in facts:
            return f"number {n} is not in the facts"
    starts = {m.group(1) for m in SENTENCE_START_RE.finditer(text)}
    for w in CAP_WORD_RE.findall(text):
        word = w.rstrip(".'’-")
        if word in starts or len(word) < 2:
            continue
        if fold(word) not in facts:
            return f"'{word}' is not in the facts"
    return None


async def write_summary(facts: dict[str, Any], llm: ChatLLM, ctx: CallContext, settings: Settings,
                        mp: MatchPolicy) -> Summary:
    tpl = load_prompt("summary")
    system, user = tpl.render(max_words=mp.settings["summary"]["max_words"], **facts)
    try:
        res = await call_with_retry(llm, ctx, settings, "match_summary", tpl.version, system, user,
                                    summary_schema(), mp.settings["llm"]["summary_max_tokens"])
    except LLMError as e:
        return Summary(value=template(facts), status="fallback", reason=f"model unavailable: {type(e).__name__}")
    text = " ".join(str(res.parsed.get("summary", "")).split())
    reason = check(text, user, mp)
    if reason:
        return Summary(value=template(facts), status="fallback", reason=reason)
    return Summary(value=text, status="generated")
