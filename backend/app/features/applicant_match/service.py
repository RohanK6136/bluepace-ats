"""Applicant Match orchestration: compile a rubric draft, and analyse one resume into an applicant card.

Each call is one recorded run (feature "applicant_match"). Only redacted resume text is stored; the original
file and text are never written anywhere.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date
from typing import Any

from app.config import Settings
from app.core.errors import LLMError, LLMUnavailable
from app.core.hashing import sha256_hex
from app.core.ids import new_request_id
from app.core.ingest import RawLine, ingest_file, ingest_text
from app.features.applicant_match.dates import years_of
from app.features.applicant_match.judge import Judgment, judge_items
from app.features.applicant_match.models import (
    Card,
    MatchOptions,
    Profile,
    Role,
    Rubric,
    RubricDraft,
)
from app.features.applicant_match.policy import PIPELINE_VERSION, MatchPolicy, load_match_policy, prompt_versions
from app.features.applicant_match.profile import VProfile, extract_profile, resume_prompt_text
from app.features.applicant_match.resume import ResumeText, looks_like_resume, prepare_resume
from app.features.applicant_match.rubric import JobSource, compile_rubric
from app.features.applicant_match.scoring import evaluate, judged_items
from app.features.applicant_match.summary import summary_facts, write_summary
from app.features.jd_standardizer.pipeline.policy import Policy
from app.llm.client import CallContext, ChatLLM
from app.observability.runs import RunRecorder

FEATURE = "applicant_match"


class NotAResume(ValueError):
    """The uploaded document does not look like a resume (E_NOT_A_RESUME)."""


@dataclass
class MatchDeps:
    llm: ChatLLM
    store: Any
    settings: Settings
    jd_policy: Policy


@dataclass
class ResumeInput:
    filename: str | None = None
    data: bytes | None = None
    text: str | None = None


def _context(options: MatchOptions, deps: MatchDeps, operation: str) -> tuple[CallContext, RunRecorder]:
    ctx = CallContext(request_id=new_request_id(), use_cache=options.use_cache, profile_id=options.profile,
                      feature=FEATURE)
    rec = RunRecorder(deps.store, deps.settings, feature=FEATURE, operation=operation, ctx=ctx,
                      model=deps.llm.describe(options.profile), options=options, pipeline_version=PIPELINE_VERSION)
    return ctx, rec


def _usage(ctx: CallContext, rec: RunRecorder) -> dict[str, Any]:
    return {"llm_calls": len(ctx.records), "cache_hits": ctx.cache_hits, "repairs": ctx.repairs,
            "prompt_tokens": ctx.prompt_tokens, "completion_tokens": ctx.completion_tokens,
            "cost_usd": ctx.cost_usd, "usage_estimated": any(r.get("usage_estimated") for r in ctx.records),
            "latency_ms": rec.elapsed_ms()}


# ------------------------------------------------------------------ rubric draft
async def draft_rubric(job: JobSource, options: MatchOptions, deps: MatchDeps) -> RubricDraft:
    ctx, rec = _context(options, deps, "compile_rubric")
    rec.start(source_type="jd_run" if not job.job_ref.startswith("text:") else "text",
              input_text="\n".join(f"{ln.id} [{ln.section}] {ln.text}" for ln in job.lines))
    try:
        rubric, notes = await compile_rubric(job, deps.llm, ctx, deps.settings, load_match_policy())
    except LLMError as e:
        rec.finish(status="llm_unavailable" if isinstance(e, LLMUnavailable) else "llm_failed", outcome="error",
                   error=f"{type(e).__name__}: {e}", trace={"llm_calls": ctx.records})
        raise
    except BaseException as e:
        rec.fail(e)
        raise
    info = deps.llm.describe(options.profile)
    draft = RubricDraft(run_id=ctx.request_id, rubric=rubric, notes=notes, model=info.model, profile=info.profile,
                        prompt_tokens=ctx.prompt_tokens, completion_tokens=ctx.completion_tokens,
                        cost_usd=ctx.cost_usd, latency_ms=rec.elapsed_ms())
    rec.finish(status="draft", outcome="success", title=f"Rubric · {job.title or 'job'}", result=draft)
    return draft


# ------------------------------------------------------------------ applicant card
def _latest_role(prof: VProfile) -> Any:
    dated = [r for r in prof.roles if r.interval]
    if dated:
        return max(dated, key=lambda r: (r.interval[1], r.interval[0]))  # type: ignore[index]
    return prof.roles[0] if prof.roles else None


def _profile_model(prof: VProfile, resume: ResumeText, total: float | None, relevant: float | None) -> Profile:
    latest = _latest_role(prof)
    return Profile(
        latest_title=latest.title if latest else None, latest_company=latest.company if latest else None,
        total_years=total, relevant_years=relevant, education_level=prof.education_level,  # type: ignore[arg-type]
        location=prof.location,
        roles=[Role(title=r.title, company=r.company, start=r.start, end=r.end,
                    years=years_of([r.interval]) if r.interval else None,
                    lines=[resume.lines[r.first].id, resume.lines[r.last].id], approximate=r.approximate)
               for r in prof.roles],
        education=prof.education, certifications=prof.certifications, languages=prof.languages)


def _manual(rid: str, applicant_id: str, rubric: Rubric, file: dict[str, Any], flags: list[str], reason: str,
            as_of: date, versions: dict[str, Any], usage: dict[str, Any]) -> Card:
    return Card(request_id=rid, applicant_id=applicant_id, status="manual", reason=reason,
                rubric={"id": rubric.rubric_id, "hash": rubric.rubric_hash, "title": rubric.title}, file=file,
                profile=Profile(), scores=None, evidence=[], gaps=[], flags=flags, summary=None,
                as_of=as_of.isoformat(), versions=versions, usage=usage)


def _ingest(inp: ResumeInput, settings: Settings) -> tuple[list[RawLine], str]:
    if inp.data is not None:
        return ingest_file(inp.filename or "resume.txt", inp.data, settings)
    return ingest_text(inp.text or ""), "text"


async def analyze(rubric: Rubric, inp: ResumeInput, options: MatchOptions, as_of: date, deps: MatchDeps) -> Card:
    ctx, rec = _context(options, deps, "analyze")
    try:
        return await _analyze(rubric, inp, as_of, deps, ctx, rec)
    except NotAResume:
        raise
    except BaseException as e:
        rec.fail(e)
        raise


async def _analyze(rubric: Rubric, inp: ResumeInput, as_of: date, deps: MatchDeps, ctx: CallContext,
                   rec: RunRecorder) -> Card:
    mp: MatchPolicy = load_match_policy()
    s = deps.settings
    raw, source_type = _ingest(inp, s)  # IngestError propagates before the run row exists
    resume = prepare_resume(raw, mp)
    redacted = "\n".join(f"{ln.id} {ln.text}" for ln in resume.lines)
    rec.start(source_type=source_type, input_text=redacted)
    rid = ctx.request_id
    applicant_id = "A-" + sha256_hex("\n".join(ln.text for ln in resume.lines))[:8]
    info = deps.llm.describe(ctx.profile_id)
    versions = {"pipeline": PIPELINE_VERSION, "prompts": prompt_versions(), "config": mp.config_hash,
                "rubric_hash": rubric.rubric_hash, "profile": info.profile, "model": info.model,
                "model_fingerprint": info.fingerprint}
    resume_text, truncated = resume_prompt_text(resume, mp.settings["resume"]["max_prompt_chars"])
    file = {"name": inp.filename, "source_type": source_type, "chars": resume.chars, "lines": len(resume.lines),
            "redactions": resume.redactions, "truncated": truncated}
    flags = list(resume.quality) + (["resume_truncated"] if truncated else [])

    def done(card: Card, outcome: str) -> Card:
        card.usage.update(_usage(ctx, rec))
        title = card.profile.latest_title or (inp.filename or "pasted resume")
        rec.finish(status=card.status, outcome=outcome, title=f"{applicant_id} · {title}", result=card,  # type: ignore[arg-type]
                   trace={"llm_calls": ctx.records})
        return card

    if resume.chars < mp.settings["resume"]["min_chars"]:
        flags.append("parse_quality:no_text")
        return done(_manual(rid, applicant_id, rubric, file, flags, "too little readable text (scanned PDF or "
                            "image-only file?); read the resume directly", as_of, versions, {}), "degraded")
    if not looks_like_resume([(ln.id, ln.text) for ln in resume.lines]):
        rec.finish(status="not_a_resume", outcome="rejected", error="no dates or resume sections found")
        raise NotAResume("this document does not look like a resume (no dates and no experience, education or "
                         "skills section)")

    to_judge = judged_items(rubric)
    prof_res, judge_res = await asyncio.gather(
        extract_profile(resume, deps.llm, ctx, s, mp, as_of, resume_text),
        judge_items(to_judge, resume, resume_text, deps.llm, ctx, s, mp),
        return_exceptions=True)
    if isinstance(prof_res, BaseException):
        if not isinstance(prof_res, LLMError):
            raise prof_res
        reason = ("the model is unavailable" if isinstance(prof_res, LLMUnavailable)
                  else "the model's answer was still invalid after a retry")
        flags.append("profile_failed")
        return done(_manual(rid, applicant_id, rubric, file, flags, f"{reason}; read the resume directly",
                            as_of, versions, {}), "degraded")
    judgments: dict[str, Judgment] | None
    if isinstance(judge_res, BaseException):
        if not isinstance(judge_res, LLMError):
            raise judge_res
        judgments = None
        flags.append("judge_failed")
    else:
        judgments = judge_res

    prof: VProfile = prof_res
    ev = evaluate(rubric, resume, prof, mp, judgments)
    profile = _profile_model(prof, resume, ev.total_years, ev.relevant_years)
    facts = summary_facts(ev, (profile.latest_title, profile.latest_company), rubric.required_years,
                          prof.education_level)
    summary = await write_summary(facts, deps.llm, ctx, s, mp)
    flags += prof.flags + ev.flags + (["summary_fallback"] if summary.status == "fallback" else [])
    card = Card(request_id=rid, applicant_id=applicant_id, status="complete", reason=None,
                rubric={"id": rubric.rubric_id, "hash": rubric.rubric_hash, "title": rubric.title}, file=file,
                profile=profile, scores=ev.scores, evidence=ev.evidence, gaps=ev.gaps,
                flags=list(dict.fromkeys(flags)), summary=summary, as_of=as_of.isoformat(), versions=versions,
                usage={})
    return done(card, "success")
