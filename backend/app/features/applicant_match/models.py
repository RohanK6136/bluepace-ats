"""Applicant Match data models: the job rubric, the applicant card, and request options.

Field order is part of the contract: cards are serialised in this order so repeat runs are byte-identical.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ItemType = Literal["skill", "certification", "language", "other"]
Group = Literal["coding", "cloud_tools", "domain", "soft", "other"]
Importance = Literal["must", "nice"]
Status = Literal["met", "partial", "unclear", "not_evidenced"]
EducationLevel = Literal["none", "high_school", "diploma", "associate", "bachelor", "master", "phd"]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ------------------------------------------------------------------ rubric
class RubricItem(Model):
    id: str = Field(description="R01, R02, … in rubric order")
    label: str = Field(min_length=1, max_length=120)
    type: ItemType
    group: Group
    importance: Importance
    weight: int = Field(default=1, ge=1, le=3)
    min_years: float | None = Field(default=None, ge=0, le=40)
    aliases: list[str] = Field(default_factory=list, description="Empty → judged by the model with a cited line")
    source_line: str | None = Field(default=None, description="Job line id (J01…) the item came from")
    source_text: str | None = None

    @field_validator("aliases")
    @classmethod
    def _clean_aliases(cls, v: list[str]) -> list[str]:
        return list(dict.fromkeys(a.strip() for a in v if a and a.strip()))


class EducationRequirement(Model):
    min_level: EducationLevel = "none"
    equivalent_experience_ok: bool = False
    source_line: str | None = None


class Weights(Model):
    required_skills: float = Field(default=50, ge=0, le=100)
    experience: float = Field(default=25, ge=0, le=100)
    preferred_skills: float = Field(default=15, ge=0, le=100)
    education: float = Field(default=10, ge=0, le=100)


class JobLine(Model):
    id: str
    section: Literal["must", "nice"]
    text: str
    origin: str = "source"


class Rubric(Model):
    """A job rubric. Drafts have no id/hash; saving freezes it as an immutable version."""

    rubric_id: str | None = None
    rubric_hash: str | None = None
    job_ref: str | None = Field(default=None, description="JD Standardizer run id, or 'text:<sha>' for pasted text")
    title: str | None = None
    weights: Weights = Field(default_factory=Weights)
    required_years: float | None = Field(default=None, ge=0, le=40)
    education: EducationRequirement = Field(default_factory=EducationRequirement)
    items: list[RubricItem] = Field(default_factory=list)
    job_lines: list[JobLine] = Field(default_factory=list, description="Requirement lines the items came from")
    created_at: str | None = None


class CompileNote(Model):
    code: str
    message: str
    line: str | None = None


class RubricDraft(Model):
    run_id: str
    rubric: Rubric
    notes: list[CompileNote]
    model: str | None = None
    profile: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0


class RubricSummary(Model):
    rubric_id: str
    rubric_hash: str
    title: str | None
    job_ref: str | None
    items: int
    created_at: str


class MatchOptions(Model):
    profile: str | None = Field(default=None, description="Model profile id from /v1/models; default if omitted")
    use_cache: bool = True


# ------------------------------------------------------------------ card
class EvidenceLine(Model):
    id: str
    text: str


class Evidence(Model):
    item_id: str
    label: str
    importance: Importance
    group: Group
    status: Status
    strength: Literal["role", "listed", "judged"] | None = None
    years: float | None = None
    min_years: float | None = None
    lines: list[EvidenceLine] = Field(default_factory=list)
    source: str | None = Field(default=None, description="Employer of the role the evidence sits in")
    note: str | None = None


class Gap(Model):
    item_id: str
    label: str
    importance: Importance
    status: Status
    note: str | None = None


class Role(Model):
    title: str
    company: str | None
    start: str | None
    end: str | None
    years: float | None
    lines: list[str]
    approximate: bool = False


class Profile(Model):
    latest_title: str | None = None
    latest_company: str | None = None
    total_years: float | None = None
    relevant_years: float | None = None
    education_level: EducationLevel | None = None
    location: str | None = None
    roles: list[Role] = Field(default_factory=list)
    education: list[dict[str, Any]] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)


class CountScore(Model):
    pct: int | None
    met: int
    partial: int = 0
    total: int


class GroupScore(CountScore):
    name: str
    label: str


class ExperienceScore(Model):
    pct: int | None
    relevant_years: float | None
    total_years: float | None
    required_years: float | None


class EducationScore(Model):
    pct: int | None
    level: EducationLevel | None
    required: EducationLevel | None


class Scores(Model):
    match: int | None
    required_skills: CountScore
    groups: list[GroupScore]
    experience: ExperienceScore
    preferred_skills: CountScore
    education: EducationScore
    weights_used: dict[str, float] = Field(description="Category weights after excluding empty categories")


class Summary(Model):
    value: str
    status: Literal["generated", "fallback"]
    reason: str | None = None


class Card(Model):
    request_id: str
    applicant_id: str
    status: Literal["complete", "manual"]
    reason: str | None = Field(default=None, description="Why the card is manual (read the resume directly)")
    rubric: dict[str, str | None]
    file: dict[str, Any]
    profile: Profile
    scores: Scores | None
    evidence: list[Evidence]
    gaps: list[Gap]
    flags: list[str]
    summary: Summary | None
    as_of: str
    versions: dict[str, Any]
    usage: dict[str, Any]
