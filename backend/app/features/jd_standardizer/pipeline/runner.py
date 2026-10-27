"""Runs the 12 pipeline steps, handles degradation, persists audit rows, returns the Result."""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass
from typing import Any

from app.config import Settings
from app.core.errors import LLMUnavailable
from app.core.ids import new_request_id
from app.core.ingest import ingest_file, ingest_text, text_chars
from app.core.logging import log_event
from app.features.jd_standardizer.pipeline.assemble import (
    build_sections,
    compute_status,
    headings,
    publish_gate,
    render_markdown,
    source_items,
    standard_blocks,
)
from app.features.jd_standardizer.pipeline.candidates import find_candidates
from app.features.jd_standardizer.pipeline.checks import build_context
from app.features.jd_standardizer.pipeline.clean import clean
from app.features.jd_standardizer.pipeline.facts import extract_facts
from app.features.jd_standardizer.pipeline.gapfill import GapFillResult, gap_fill
from app.features.jd_standardizer.pipeline.gapplan import plan_gaps
from app.features.jd_standardizer.pipeline.labels import label_blocks
from app.features.jd_standardizer.pipeline.llmstep import StepLLM
from app.features.jd_standardizer.pipeline.models import (
    FACT_FIELDS,
    OUTCOME_BY_STATUS,
    RENDERED_SECTIONS,
    Fact,
    Flag,
    Meta,
    Options,
    Overrides,
    Result,
    SplitHint,
    StepTrace,
)
from app.features.jd_standardizer.pipeline.policy import Policy
from app.features.jd_standardizer.pipeline.segment import segment
from app.features.jd_standardizer.pipeline.summary import summarize
from app.features.jd_standardizer.pipeline.validate import validate
from app.features.jd_standardizer.promptlib import prompt_versions
from app.llm.client import CallContext, ChatLLM
from app.llm.types import ModelInfo
from app.observability.runs import RunRecorder


@dataclass
class PipelineDeps:
    llm: ChatLLM
    store: Any  # app.store.db.Store | None
    settings: Settings
    policy: Policy


@dataclass
class PipelineInput:
    text: str | None = None
    filename: str | None = None
    data: bytes | None = None


def _meta(settings: Settings, ctx: CallContext, model: ModelInfo, latency_ms: int) -> Meta:
    return Meta(
        pipeline_version=settings.PIPELINE_VERSION,
        prompt_versions=prompt_versions(),
        profile=model.profile,
        model=model.model,
        model_fingerprint=model.fingerprint,
        llm_calls=len(ctx.records),
        llm_calls_by_step=dict(sorted(Counter(r["step"] for r in ctx.records).items())),
        repairs=ctx.repairs,
        cache_hits=ctx.cache_hits,
        prompt_tokens=ctx.prompt_tokens,
        completion_tokens=ctx.completion_tokens,
        cost_usd=ctx.cost_usd,
        latency_ms=latency_ms,
    )


def _empty_fields() -> dict[str, Fact]:
    fields = {f: Fact() for f in FACT_FIELDS}
    fields["work_mode"] = Fact(value=[])
    return fields


class _Run:
    """Mutable per-request state; stages themselves stay pure."""

    def __init__(self, deps: PipelineDeps, options: Options, overrides: Overrides, request_id: str | None):
        self.deps = deps
        self.s = deps.settings
        self.policy = deps.policy
        self.options = options
        self.overrides = overrides
        self.rid = request_id or new_request_id()
        self.mode = options.mode or self.s.DEFAULT_MODE
        self.t_start = time.perf_counter()
        self.traces: list[StepTrace] = []
        self.ctx = CallContext(request_id=self.rid, use_cache=options.use_cache, profile_id=options.profile,
                               feature="jd_standardizer")
        self.model = deps.llm.describe(options.profile)
        self.recorder = RunRecorder(deps.store, self.s, feature="jd_standardizer", operation="standardize",
                                    ctx=self.ctx, model=self.model, options=options, overrides=overrides,
                                    pipeline_version=self.s.PIPELINE_VERSION)
        self.step_llm = StepLLM(deps.llm, self.ctx, self.s)
        self.trace_extra: dict[str, Any] = {}

    def latency(self) -> int:
        return int((time.perf_counter() - self.t_start) * 1000)

    def stamp(self, trace: StepTrace, t0: float) -> None:
        trace.duration_ms = int((time.perf_counter() - t0) * 1000)
        self.traces.append(trace)
        log_event("step", run_id=self.rid, step=trace.name, duration_ms=trace.duration_ms,
                  llm_calls=len(trace.llm_call_ids))

    def llm_or_none(self) -> StepLLM | None:
        return self.step_llm if self.step_llm.available else None

    def finish(self, result: Result) -> Result:
        trace = {"steps": [t.model_dump() for t in self.traces], **self.trace_extra}
        title = result.fields["title"].value if "title" in result.fields else None
        self.recorder.finish(status=result.status, outcome=OUTCOME_BY_STATUS.get(result.status, "error"),
                             title=title, result=result, trace=trace,
                             llm_ms=sum(r.get("latency_ms") or 0 for r in self.ctx.records))
        if self.options.debug:
            result = result.model_copy(update={"trace": self.traces})
        return result

    def bare(self, status: str, *, message: str | None = None, split_hints: list[SplitHint] | None = None,
             flags: list[Flag] | None = None) -> Result:
        return Result(
            request_id=self.rid, status=status, tier=None, mode=self.mode, publishable=False,  # type: ignore[arg-type]
            publish_blockers=[status], fields=_empty_fields(), sections=[], short_description=None,
            standard_blocks={}, not_imported=[], needs_input=[], flags=flags or [],
            description_markdown=None, description_markdown_annotated=None,
            meta=_meta(self.s, self.ctx, self.model, self.latency()), split_hints=split_hints,
            message=message,
        )


async def run_pipeline(inp: PipelineInput, options: Options, overrides: Overrides, deps: PipelineDeps,
                       request_id: str | None = None) -> Result:
    run = _Run(deps, options, overrides, request_id)
    try:
        return await _run_steps(run, inp)
    except BaseException as e:  # record the failure on the run row, then let the API layer handle it
        run.recorder.fail(e)
        raise


async def _run_steps(run: _Run, inp: PipelineInput) -> Result:
    s, policy, options = run.s, run.policy, run.options

    # 1 — ingest
    t0 = time.perf_counter()
    if inp.data is not None:
        raw, source_type = ingest_file(inp.filename or "upload.txt", inp.data, s)
        min_chars = s.MIN_TEXT_CHARS_FILE if source_type in ("pdf", "docx") else s.MIN_TEXT_CHARS_PASTED
    else:
        raw, source_type = ingest_text(inp.text or ""), "text"
        min_chars = s.MIN_TEXT_CHARS_PASTED
    chars = text_chars(raw)
    run.stamp(StepTrace(name="ingest", output_summary={"raw_lines": len(raw), "chars": chars,
                                                       "source_type": source_type}), t0)
    if chars < min_chars:
        run.recorder.start(source_type=source_type, input_text="\n".join(r.text for r in raw))
        return run.finish(run.bare("needs_text", message=f"only {chars} characters of text found (< {min_chars})"))

    # 2 — clean
    t0 = time.perf_counter()
    cleaned = clean(raw, policy, s)
    run.recorder.start(source_type=source_type, input_text="\n".join(r.text for r in raw))
    run.trace_extra["lines"] = [ln.model_dump() for ln in cleaned.lines]
    run.stamp(StepTrace(name="clean", output_summary={"lines": len(cleaned.lines), "chrome": len(cleaned.chrome_ids),
                                                      "header": len(cleaned.header_ids)}), t0)
    if cleaned.split_hints:
        return run.finish(run.bare("needs_split", split_hints=cleaned.split_hints,
                                   message="more than one job description detected"))

    # 3 — segment
    t0 = time.perf_counter()
    seg = segment(cleaned, policy, s)
    run.stamp(StepTrace(name="segment", output_summary={
        "blocks": len(seg.blocks), "unresolved": len(seg.unresolved_ids), "relabel": len(seg.relabel_ids)}), t0)

    # 4 — candidates
    t0 = time.perf_counter()
    cands = find_candidates(cleaned, seg, policy)
    run.stamp(StepTrace(name="candidates", output_summary={"candidates": len(cands)}), t0)

    # 5 — labels (LLM, conditional)
    t0 = time.perf_counter()
    try:
        seg, changed, tr = await label_blocks(seg, run.llm_or_none())
    except LLMUnavailable:
        seg, changed, tr = await label_blocks(seg, None)
    run.stamp(tr, t0)
    if changed:
        t0 = time.perf_counter()
        cands = find_candidates(cleaned, seg, policy)
        run.stamp(StepTrace(name="candidates_rerun", output_summary={"candidates": len(cands)}), t0)

    # 6 — facts (LLM)
    t0 = time.perf_counter()
    try:
        llm_facts, tr = await extract_facts(cleaned, seg, cands, run.llm_or_none())
    except LLMUnavailable:
        llm_facts, tr = None, StepTrace(name="facts", notes=["LLM unavailable: regex candidates only"])
    run.stamp(tr, t0)

    # 7 — validate
    t0 = time.perf_counter()
    v = validate(cleaned, seg, cands, llm_facts, run.overrides, policy, s)
    run.stamp(StepTrace(name="validate", output_summary={
        "fields": {k: f.status for k, f in v.fields.items()}, "flags": len(v.flags)}), t0)

    # 8 — gap plan
    t0 = time.perf_counter()
    gp = plan_gaps(cleaned, v.blocks, v.fields, v.dispositions, policy, options.draft_gaps)
    run.trace_extra["dispositions"] = dict(sorted(gp.dispositions.items()))
    run.stamp(StepTrace(name="gapplan", output_summary=gp.plan.model_dump()), t0)

    # 9/10 — gap-fill + checks (LLM, conditional)
    lines_map = {ln.id: ln for ln in cleaned.lines}
    existing = {sec: [it.text for it in source_items(sec, v.blocks, lines_map, "light")] for sec in RENDERED_SECTIONS}
    check_ctx = build_context(cleaned.lines, set(cleaned.chrome_ids), v.fields,
                              [t for items in existing.values() for t in items], policy)
    gf = GapFillResult()
    if any(sp.action != "none" for sp in gp.plan.sections.values()) and run.step_llm.available:
        t0 = time.perf_counter()
        brief_lines = sorted((lines_map[lid] for lid, d in gp.dispositions.items() if d == "brief_source"),
                             key=lambda ln: ln.n)
        gf = await gap_fill(gp.plan, v.fields, existing, brief_lines, run.step_llm, policy, check_ctx, headings(s))
        for tr in gf.traces:
            run.traces.append(tr)
        run.stamp(StepTrace(name="gapfill", output_summary={k: len(x) for k, x in gf.drafts.items()}), t0)

    # 12a — sections (needed for the summary payload)
    t0 = time.perf_counter()
    asm = build_sections(v.blocks, lines_map, gp.plan, gf.drafts, run.mode, s)
    by_id = {sec.id: sec for sec in asm.sections}

    # 11 — summary (LLM, template fallback)
    t1 = time.perf_counter()
    about = " ".join(it.text for it in by_id["about_role"].items) or None
    resp = [it.text for it in by_id["responsibilities"].items]
    try:
        short, tr = await summarize(v.fields, about, resp, run.llm_or_none(), policy, check_ctx, s.SUMMARY_MAX_CHARS)
    except LLMUnavailable:
        short, tr = await summarize(v.fields, about, resp, None, policy, check_ctx, s.SUMMARY_MAX_CHARS)
    run.stamp(tr, t1)

    # 12b — assemble
    extra: list[Flag] = []
    if run.mode == "rewrite":
        extra.append(Flag(code="rewrite_not_implemented", severity="info",
                          message="mode=rewrite (M7) not implemented; light normalization applied"))
    if not run.step_llm.available:
        extra.append(Flag(code="llm_unavailable", severity="block",
                          message="LM Studio unreachable: heuristics-only result"))
    flags = sorted([*v.flags, *gp.flags, *gf.flags, *asm.flags, *extra], key=lambda f: (f.code, f.message))
    std = standard_blocks(v.fields, asm.sections, policy, s)
    needs_input = [*gp.plan.needs_input, *gf.needs_input]
    blockers = publish_gate(v.fields, asm.sections, flags, short, policy)
    status = compute_status(llm_unavailable=not run.step_llm.available, needs_input=needs_input,
                            sections=asm.sections, flags=flags)
    run.stamp(StepTrace(name="assemble", output_summary={"status": status, "blockers": blockers}), t0)

    result = Result(
        request_id=run.rid,
        status=status,  # type: ignore[arg-type]
        tier=gp.plan.tier,
        mode=run.mode,
        publishable=not blockers,
        publish_blockers=blockers,
        fields=v.fields,
        sections=asm.sections,
        short_description=short,
        standard_blocks=std,
        not_imported=v.not_imported,
        needs_input=needs_input,
        flags=flags,
        description_markdown=render_markdown(v.fields, asm.sections, std, annotate=False),
        description_markdown_annotated=render_markdown(v.fields, asm.sections, std, annotate=True),
        meta=_meta(s, run.ctx, run.model, run.latency()),
    )
    return run.finish(result)
