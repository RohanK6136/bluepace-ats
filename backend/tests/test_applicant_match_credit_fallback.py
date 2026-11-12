import asyncio
from datetime import date
from types import SimpleNamespace

import httpx
import pytest

from app.config import Settings
from app.core.errors import LLMUnavailable
from app.features.applicant_match.models import (
    EducationRequirement,
    JobLine,
    MatchOptions,
    Rubric,
    RubricItem,
)
from app.features.applicant_match.policy import load_match_policy
from app.features.applicant_match.profile import VProfile
from app.features.applicant_match.rubric import JobSource, compile_rubric
from app.features.applicant_match.service import MatchDeps, ResumeInput, analyze
from app.llm.providers.openai_compat import OpenAICompatibleProvider
from app.llm.types import CallContext, ModelInfo


class UnavailableLLM:
    """A provider stub that deterministically simulates exhausted OpenRouter credits."""

    def __init__(self):
        self.steps = []

    def describe(self, profile_id=None):
        return ModelInfo(
            profile=profile_id or "openrouter-default",
            provider="openrouter",
            model="openrouter/free",
            label="OpenRouter test profile",
            fingerprint="test",
        )

    def context_tokens(self, _ctx):
        return 32000

    async def chat_json(self, step, *_args, **_kwargs):
        self.steps.append(step)
        raise LLMUnavailable(
            "OpenRouter credits are unavailable for this request (HTTP 402)."
        )


def test_openrouter_402_is_non_retryable_provider_unavailability():
    response = httpx.Response(
        402,
        request=httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions"),
        text='{"error":{"message":"insufficient credits"}}',
    )

    provider = object.__new__(OpenAICompatibleProvider)
    provider.profile = SimpleNamespace(base_url="https://openrouter.ai/api/v1")

    with pytest.raises(LLMUnavailable, match="HTTP 402"):
        provider._raise_for_status(response, response.text)

    assert LLMUnavailable.retryable is False


def test_rubric_compiler_uses_source_grounded_rules_when_ai_is_unavailable():
    llm = UnavailableLLM()
    job = JobSource(
        title="Backend Developer",
        lines=[JobLine(id="J01", section="must", text="Python and SQL", origin="source")],
        required_years=None,
        job_ref="text:demo",
    )

    rubric, notes = asyncio.run(
        compile_rubric(job, llm, CallContext(request_id="rubric-fallback-test"),
                       Settings(), load_match_policy(), fast=False)
    )

    assert {item.label for item in rubric.items} == {"Python", "SQL"}
    assert any(note.code == "rules_fallback" for note in notes)
    assert llm.steps == ["match_rubric"]


def test_resume_match_returns_limited_rules_only_result_when_ai_credits_are_unavailable():
    llm = UnavailableLLM()
    resume_text = """Jordan Example
Software Engineer
Experience
2020 - 2024
Built Python services and SQL queries for internal reporting.
Maintained data pipelines and APIs for internal teams.
Improved automated test coverage and deployment reliability.
Collaborated with product and engineering teams on delivery.
Skills
Python, SQL, Docker, REST APIs
Education
Bachelor's degree in Computer Science
Projects
Created a reporting service using Python and SQL.
Documented API behaviour and supported production releases.
"""
    rubric = Rubric(
        title="Backend Developer",
        required_years=3,
        education=EducationRequirement(min_level="bachelor"),
        items=[
            RubricItem(
                id="R01", label="Python", type="skill", group="coding",
                importance="must", aliases=["Python"],
            ),
            RubricItem(
                id="R02", label="SQL", type="skill", group="coding",
                importance="must", aliases=["SQL"],
            ),
            RubricItem(
                id="R03", label="stakeholder management", type="other", group="soft",
                importance="must", aliases=[],
            ),
        ],
    )
    deps = MatchDeps(
        llm=llm,
        store=None,
        settings=Settings(),
        jd_policy=None,
    )

    card = asyncio.run(
        analyze(rubric, ResumeInput(text=resume_text), options=MatchOptions(),
                as_of=date(2026, 11, 3), deps=deps)
    )

    assert card.status == "complete"
    assert "rules_only_assessment" in card.flags
    assert "experience_not_assessed" in card.flags
    assert card.profile.roles == []
    assert card.profile.total_years is None
    assert card.profile.education_level == "bachelor"
    assert card.scores.experience.pct is None
    assert card.scores.experience.required_years == 3
    evidence = {item.label: item.status for item in card.evidence}
    assert evidence["Python"] == "met"
    assert evidence["SQL"] == "met"
    assert evidence["stakeholder management"] == "unclear"
    assert card.summary.status == "fallback"
    assert "directly matched resume text only" in card.reason
    assert card.performance.assessment_mode == "rules_only"
    assert card.performance.input_mode == "pasted_text"
    assert card.performance.total_ms >= card.performance.provider_round_trip_ms >= 0
    # The fallback does not make a third provider call to generate a summary.
    assert sorted(llm.steps) == ["match_judge", "match_profile"]



def test_rubric_compiler_fast_mode_uses_rules_without_calling_model():
    llm = UnavailableLLM()
    job = JobSource(
        title="Backend Developer",
        lines=[JobLine(id="J01", section="must", text="Python, FastAPI and SQL", origin="source")],
        required_years=None,
        job_ref="text:fast",
    )

    rubric, notes = asyncio.run(
        compile_rubric(job, llm, CallContext(request_id="rubric-fast-test"),
                       Settings(), load_match_policy(), fast=True)
    )

    assert {item.label for item in rubric.items} == {"Python", "FastAPI", "SQL"}
    assert any(note.code == "fast_rules" for note in notes)
    assert llm.steps == []


def test_successful_applicant_match_uses_template_summary_without_extra_model_call(monkeypatch):
    llm = UnavailableLLM()
    resume_text = """Jordan Example
Software Engineer
Experience
2020 - 2024
Built Python services and SQL queries for internal reporting.
Maintained data pipelines and APIs for internal teams.
Improved automated test coverage and deployment reliability.
Collaborated with product and engineering teams on delivery.
Skills
Python, SQL, Docker, REST APIs
Education
Bachelor's degree in Computer Science
Projects
Created a reporting service using Python and SQL.
Documented API behaviour and supported production releases.
"""

    async def fake_profile(*_args, **_kwargs):
        return VProfile()

    async def fake_judgments(*_args, **_kwargs):
        return {}

    monkeypatch.setattr("app.features.applicant_match.service.extract_profile", fake_profile)
    monkeypatch.setattr("app.features.applicant_match.service.judge_items", fake_judgments)

    rubric = Rubric(
        title="Backend Developer",
        items=[
            RubricItem(
                id="R01", label="Python", type="skill", group="coding",
                importance="must", aliases=["Python"],
            ),
        ],
    )
    deps = MatchDeps(llm=llm, store=None, settings=Settings(), jd_policy=None)

    card = asyncio.run(
        analyze(rubric, ResumeInput(text=resume_text), options=MatchOptions(),
                as_of=date(2026, 11, 11), deps=deps)
    )

    assert card.summary.status == "template"
    assert card.summary.reason and "without an extra model call" in card.summary.reason
    assert "summary_fallback" not in card.flags
    assert llm.steps == []
