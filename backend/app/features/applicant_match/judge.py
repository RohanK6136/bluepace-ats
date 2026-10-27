"""Fuzzy judge: requirements without usable aliases ("stakeholder management", "experience leading teams").

The model returns met / partial / no with one cited line and a short quote. Code accepts met or partial only
when the line exists, is not redacted, and contains the quote; anything else becomes not_evidenced.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings
from app.features.applicant_match.llm_schemas import judge_schema
from app.features.applicant_match.models import RubricItem
from app.features.applicant_match.policy import MatchPolicy, fold, load_prompt
from app.features.applicant_match.resume import ResumeText
from app.llm.client import CallContext, ChatLLM, call_with_retry


@dataclass(frozen=True)
class Judgment:
    status: str  # met | partial | not_evidenced
    line: str | None
    note: str | None = None


def _norm(s: str) -> str:
    return " ".join("".join(ch if ch.isalnum() else " " for ch in fold(s)).split())


async def judge_items(items: list[RubricItem], resume: ResumeText, resume_text: str, llm: ChatLLM, ctx: CallContext,
                      settings: Settings, mp: MatchPolicy) -> dict[str, Judgment]:
    if not items:
        return {}
    tpl = load_prompt("judge")
    system, user = tpl.render(items=[{"id": it.id, "label": it.label, "source_text": it.source_text}
                                     for it in items], resume=resume_text)
    res = await call_with_retry(llm, ctx, settings, "match_judge", tpl.version, system, user,
                                judge_schema([it.id for it in items]), mp.settings["llm"]["judge_max_tokens"])
    return verify_judgments(res.parsed.get("judgments", []), items, resume)


def verify_judgments(raw: list[dict], items: list[RubricItem], resume: ResumeText) -> dict[str, Judgment]:
    lines = resume.by_id()
    out: dict[str, Judgment] = {}
    for j in raw:
        iid = j.get("id")
        if iid in out or iid not in {it.id for it in items}:
            continue
        verdict = j.get("verdict")
        if verdict not in ("met", "partial"):
            out[iid] = Judgment("not_evidenced", None)
            continue
        ln = lines.get(j.get("line") or "")
        quote = (j.get("quote") or "").strip()
        if ln is None or ln.redacted:
            out[iid] = Judgment("not_evidenced", None, "the model cited a line that does not exist")
        elif len(_norm(quote)) < 3 or _norm(quote) not in _norm(ln.text):
            out[iid] = Judgment("not_evidenced", None, "the model's quote is not in the cited line")
        else:
            out[iid] = Judgment(verdict, ln.id)
    for it in items:
        out.setdefault(it.id, Judgment("not_evidenced", None))
    return out
