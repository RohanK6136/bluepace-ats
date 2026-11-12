import asyncio
from datetime import date

import pytest

from app.config import Settings
from app.features.applicant_match.models import MatchOptions, Rubric, RubricItem
from app.features.applicant_match.profile import VProfile
from app.features.applicant_match.service import MatchDeps, ResumeInput, analyze
from app.llm.types import ModelInfo


RESUME = """Alex Morgan
Software Engineer
Experience
2020 - 2024
Built Python services and SQL queries for internal reporting.
Maintained APIs and automated tests for production systems.
Skills
Python, SQL, REST APIs
Education
Bachelor's degree in Computer Science
Projects
Created reporting tools for internal teams.
"""


class StubLLM:
    def describe(self, profile_id=None):
        return ModelInfo(
            profile=profile_id or "test-profile",
            provider="test",
            model="stub",
            label="Applicant Match timing test",
            fingerprint="test",
        )

    def context_tokens(self, _ctx):
        return 32000


@pytest.mark.parametrize(
    ("resume_input", "expected_input_mode"),
    [
        (ResumeInput(text=RESUME), "pasted_text"),
        (ResumeInput(filename="candidate.txt", data=RESUME.encode("utf-8")), "uploaded_file"),
    ],
)
def test_analysis_returns_real_processing_timings_and_input_mode(
    monkeypatch, resume_input, expected_input_mode
):
    async def fake_profile(_resume, _llm, ctx, *_args):
        await asyncio.sleep(0.01)
        ctx.records.append({"latency_ms": 125})
        return VProfile()

    async def fake_judge(_items, _resume, _resume_text, _llm, ctx, *_args):
        await asyncio.sleep(0.01)
        ctx.records.append({"latency_ms": 225})
        return {}

    monkeypatch.setattr("app.features.applicant_match.service.extract_profile", fake_profile)
    monkeypatch.setattr("app.features.applicant_match.service.judge_items", fake_judge)

    rubric = Rubric(
        title="Software Engineer",
        items=[
            RubricItem(
                id="R01",
                label="Python",
                type="skill",
                group="coding",
                importance="must",
                aliases=["Python"],
            )
        ],
    )
    deps = MatchDeps(
        llm=StubLLM(),
        store=None,
        settings=Settings(),
        jd_policy=None,
    )

    card = asyncio.run(
        analyze(
            rubric,
            resume_input,
            MatchOptions(),
            as_of=date(2026, 11, 12),
            deps=deps,
        )
    )

    assert card.performance.input_mode == expected_input_mode
    assert card.performance.assessment_mode == "model"
    assert card.performance.resume_extraction_ms >= 0
    assert card.performance.preprocessing_ms >= 0
    assert card.performance.provider_round_trip_ms > 0
    assert card.performance.model_call_time_ms == 350
    assert card.performance.total_ms >= card.performance.provider_round_trip_ms
