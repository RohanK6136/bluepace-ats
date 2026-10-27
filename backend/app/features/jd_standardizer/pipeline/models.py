"""Typed models shared by every pipeline stage (Pydantic v2)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.ingest import RawLine  # noqa: F401  (re-exported: pipeline stages import it from here)

RENDERED_SECTIONS: tuple[str, ...] = (
    "about_role", "responsibilities", "requirements", "nice_to_have", "offer", "additional_info",
)
DROPPED_SECTIONS: tuple[str, ...] = ("company_about", "legal", "apply_cta", "chrome", "unclassified")
LIST_SECTIONS = frozenset({"responsibilities", "requirements", "nice_to_have", "offer"})
PROSE_SECTIONS = frozenset({"about_role", "additional_info"})
GAP_FILL_ORDER: tuple[str, ...] = ("about_role", "responsibilities", "requirements")
FACT_FIELDS: tuple[str, ...] = (
    "title", "category_hint", "role_type", "country", "state", "city", "work_mode", "experience", "duration_months",
)
STATUS_PRECEDENCE: tuple[str, ...] = (
    "failed", "needs_text", "needs_split", "llm_unavailable", "needs_input", "needs_review", "ok",
)

Mode = Literal["verbatim", "light", "rewrite"]
Severity = Literal["info", "warn", "block"]
BlockKind = Literal["section_heading", "group_heading", "bullet", "paragraph", "kv"]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ------------------------------------------------------------------ ingest/clean
class Line(Model):
    id: str
    n: int
    text: str
    zone: Literal["header", "body"] = "body"
    style: str | None = None
    level: int = 0
    merged_ids: list[str] = Field(default_factory=list)


class SplitHint(Model):
    line: int
    title_guess: str


class CleanResult(Model):
    lines: list[Line]
    chrome_ids: list[str]
    header_ids: list[str]
    split_hints: list[SplitHint] = Field(default_factory=list)


# ---------------------------------------------------------------------- segment
class Block(Model):
    id: str
    kind: BlockKind
    line_ids: list[str]
    text: str
    key: str | None = None
    value: str | None = None
    kv_kind: str | None = None
    section: str | None = None
    section_source: Literal["alias", "inherit", "llm", "none"] = "none"
    group: str | None = None
    source_heading: str | None = None


class Segmentation(Model):
    blocks: list[Block]
    unresolved_ids: list[str]
    relabel_ids: list[str]
    header_lines: list[str]
    foreign_employer_candidates: list[str]


class Candidate(Model):
    field: str
    raw: str
    value: dict[str, Any]
    line_id: str
    source: Literal["kv", "header", "regex"]


# ---------------------------------------------------------------- facts/output
class Flag(Model):
    code: str
    severity: Severity
    message: str = ""
    lines: list[str] = Field(default_factory=list)


class Fact(Model):
    value: Any = None
    status: Literal["verified", "override", "conflict", "missing"] = "missing"
    source: Literal["regex", "llm", "override"] | None = None
    line: str | None = None
    quote: str | None = None
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    also: list[dict[str, Any]] = Field(default_factory=list)
    edits: list[str] = Field(default_factory=list)


class Item(Model):
    text: str
    origin: Literal["source", "ai_draft", "standard"]
    lines: list[str] = Field(default_factory=list)
    group: str | None = None
    basis: Literal["brief", "generic_for_title"] | None = None
    accepted: bool | None = None
    edits: list[str] = Field(default_factory=list)


class SectionResult(Model):
    id: str
    heading: str
    status: Literal["provided", "partial", "missing", "drafted", "supplemented", "empty"]
    items: list[Item]


class NeedsInput(Model):
    field: str
    reason: Literal["missing", "conflict", "draft_failed"]
    candidates: list[dict[str, Any]] | None = None


class SectionPlan(Model):
    id: str
    status: Literal["provided", "partial", "missing"]
    items: int
    words: int
    action: Literal["draft", "supplement", "none"]
    draft_count: int = 0


class GapPlan(Model):
    tier: Literal["complete", "partial", "brief"]
    body_words: int
    sections: dict[str, SectionPlan]
    needs_input: list[NeedsInput]


class StepTrace(Model):
    name: str
    duration_ms: int = 0
    input_summary: dict[str, Any] = Field(default_factory=dict)
    output_summary: dict[str, Any] = Field(default_factory=dict)
    llm_call_ids: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ShortDescription(Model):
    text: str
    origin: Literal["llm", "template"]


class NotImported(Model):
    lines: list[str]
    text: str
    reason: str


class Meta(Model):
    pipeline_version: str
    prompt_versions: dict[str, int]
    profile: str | None = None
    model: str | None
    model_fingerprint: str | None
    llm_calls: int
    llm_calls_by_step: dict[str, int]
    repairs: int
    cache_hits: int
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int


class Result(Model):
    request_id: str
    status: Literal["failed", "needs_text", "needs_split", "llm_unavailable", "needs_input", "needs_review", "ok"]
    tier: Literal["complete", "partial", "brief"] | None
    mode: Mode
    publishable: bool
    publish_blockers: list[str]
    fields: dict[str, Fact]
    sections: list[SectionResult]
    short_description: ShortDescription | None
    standard_blocks: dict[str, dict[str, Any]]
    not_imported: list[NotImported]
    needs_input: list[NeedsInput]
    flags: list[Flag]
    description_markdown: str | None
    description_markdown_annotated: str | None
    meta: Meta
    split_hints: list[SplitHint] | None = None
    message: str | None = None
    trace: list[StepTrace] | None = None


# ---------------------------------------------------------------- request side
# Feature status -> feature-neutral run outcome used by the observability dashboard.
OUTCOME_BY_STATUS: dict[str, str] = {
    "ok": "success", "needs_review": "success", "needs_input": "success",
    "llm_unavailable": "degraded", "needs_text": "rejected", "needs_split": "rejected", "failed": "error",
}


class Options(Model):
    profile: str | None = Field(default=None, description="Model profile id from /v1/models; default if omitted")
    mode: Mode | None = None
    detail: Literal["detailed", "concise"] = "detailed"  # fast mode only: how much the model writes
    use_cache: bool = True
    draft_gaps: bool = True
    debug: bool = False


class ExperienceOverride(Model):
    min_years: float | None = None
    max_years: float | None = None


class Overrides(Model):
    title: str | None = None
    role_type: str | None = None
    country_iso2: str | None = None
    state: str | None = None
    city: str | None = None
    work_mode: list[str] | None = None
    experience: ExperienceOverride | None = None
    duration_months: int | None = None

    @field_validator("country_iso2")
    @classmethod
    def _country(cls, v: str | None) -> str | None:
        if v is None:
            return v
        import pycountry

        if pycountry.countries.get(alpha_2=v.strip().upper()) is None:
            raise ValueError(f"unknown ISO2 country code: {v!r}")
        return v.strip().upper()

    @field_validator("role_type")
    @classmethod
    def _role_type(cls, v: str | None) -> str | None:
        if v is None:
            return v
        from app.features.jd_standardizer.pipeline.policy import load_policy
        from app.features.jd_standardizer.pipeline.textutil import canonical_role_types

        found = canonical_role_types(v, load_policy())
        if len(found) != 1:
            raise ValueError(f"unknown role_type: {v!r}")
        return found[0]

    @field_validator("work_mode")
    @classmethod
    def _work_mode(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        from app.features.jd_standardizer.pipeline.policy import load_policy
        from app.features.jd_standardizer.pipeline.textutil import canonical_work_modes

        out: list[str] = []
        for m in v:
            found = canonical_work_modes(m, load_policy())
            if not found:
                raise ValueError(f"unknown work_mode: {m!r}")
            out.extend(found)
        return sorted(set(out), key=["remote", "hybrid", "onsite"].index)
