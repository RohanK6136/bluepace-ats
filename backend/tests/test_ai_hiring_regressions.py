"""Regression tests for fractional minimum-experience support.

These cover the API boundary and deterministic job-description parser without
calling an external AI provider or modifying production data.
"""
import app.main as api
from app.schemas import JobCreate, JobUpdate


def test_job_description_parser_keeps_fractional_minimum_experience():
    analysis = api.matching_service.parse_job_description(
        "Backend Engineer",
        "Requirements: minimum of 1.5 years of experience with Python and APIs.",
        use_llm=False,
    )

    assert analysis["minimum_experience_years"] == 1.5


def test_job_description_parser_keeps_fractional_experience_ranges():
    analysis = api.matching_service.parse_job_description(
        "Platform Engineer",
        "Candidates should have 1.5 to 3.5 years experience with Python.",
        use_llm=False,
    )

    assert analysis["minimum_experience_years"] == 1.5
    assert analysis["maximum_experience_years"] == 3.5


def test_analysis_normalization_does_not_truncate_fractional_years():
    normalized = api.matching_service._normalize_analysis(
        {"minimum_experience_years": 2.5},
        {"minimum_experience_years": None},
    )

    assert normalized["minimum_experience_years"] == 2.5


def test_job_create_schema_accepts_fractional_experience():
    job = JobCreate(
        title="Data Engineer",
        description="Build data pipelines.",
        minimum_experience_years=1.5,
    )

    assert job.minimum_experience_years == 1.5


def test_job_update_schema_accepts_fractional_experience():
    update = JobUpdate(minimum_experience_years=0.5)

    assert update.minimum_experience_years == 0.5


def test_invalid_model_output_is_recorded_as_failed_run():
    from types import SimpleNamespace

    import pytest
    from fastapi import HTTPException

    from app.routers.ai_hiring_studio import _mark_run_failed

    class FakeDatabase:
        commits = 0

        def commit(self):
            self.commits += 1

    db = FakeDatabase()
    run = SimpleNamespace(status="success", error_message=None, raw_model_output='{"job_description": ""}')

    with pytest.raises(HTTPException) as error:
        _mark_run_failed(db, run, "Model response did not include a job description. Retry.")

    assert error.value.status_code == 502
    assert run.status == "failed"
    assert run.error_message == "Model response did not include a job description. Retry."
    assert run.raw_model_output == '{"job_description": ""}'
    assert db.commits == 1


def test_rubric_weights_are_normalized_to_100():
    from app.routers.ai_hiring_studio import _normalize_rubric_result

    rubric = _normalize_rubric_result({
        "title": "Platform Engineer",
        "criteria": [
            {"name": "Python", "weight": 2, "required": True},
            {"name": "APIs", "weight": 1, "required": True},
            {"name": "Cloud", "weight": 1, "required": False},
        ],
    })

    assert [item["weight"] for item in rubric["criteria"]] == [50.0, 25.0, 25.0]
    assert rubric["total_weight"] == 100.0


def test_rubric_normalizer_rejects_zero_total_weights():
    import pytest

    from app.routers.ai_hiring_studio import _normalize_rubric_result

    with pytest.raises(ValueError, match="no positive weights"):
        _normalize_rubric_result({
            "criteria": [
                {"name": "Python", "weight": 0},
                {"name": "APIs", "weight": 0},
            ],
        })


def test_rubric_normalizer_rejects_non_object_criteria():
    import pytest

    from app.routers.ai_hiring_studio import _normalize_rubric_result

    with pytest.raises(ValueError, match="no usable rubric criteria"):
        _normalize_rubric_result({"criteria": ["not an object", None]})



def test_default_model_uses_free_openrouter_router(monkeypatch):
    from app.routers.ai_hiring_studio import DEFAULT_MODEL, _model_name

    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    assert DEFAULT_MODEL == "openrouter/free"
    assert _model_name(None) == "openrouter/free"


def test_ai_configuration_status_reports_missing_server_key(monkeypatch):
    from app.routers.ai_hiring_studio import _configuration_status

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    status = _configuration_status()

    assert status["server_key_configured"] is False
    assert status["key_source"] == "not configured"
    assert status["default_model"]


def test_ai_configuration_status_never_returns_server_key(monkeypatch):
    from app.routers.ai_hiring_studio import _configuration_status

    sentinel = "test-secret-must-never-be-returned"
    monkeypatch.setenv("OPENROUTER_API_KEY", sentinel)
    status = _configuration_status()

    assert status["server_key_configured"] is True
    assert status["key_source"] == "server environment"
    assert sentinel not in repr(status)



def test_saved_rubric_preparation_normalizes_weights_and_keeps_title():
    from app.routers.ai_hiring_studio import SavedRubricRequest, _prepare_saved_rubric

    normalized = _prepare_saved_rubric(SavedRubricRequest(
        title="Platform Engineer v1",
        job_title="Platform Engineer",
        rubric={
            "title": "Generated title",
            "criteria": [
                {"name": "Python", "weight": 2, "required": True, "category": "Coding"},
                {"name": "Cloud", "weight": 1, "required": False, "category": "Cloud & tools"},
            ],
        },
    ))

    assert normalized["title"] == "Platform Engineer v1"
    assert [item["weight"] for item in normalized["criteria"]] == [66.67, 33.33]
    assert normalized["total_weight"] == 100.0


def test_saved_rubric_preparation_rejects_blank_title():
    import pytest
    from fastapi import HTTPException

    from app.routers.ai_hiring_studio import SavedRubricRequest, _prepare_saved_rubric

    with pytest.raises(HTTPException, match="Enter a name"):
        _prepare_saved_rubric(SavedRubricRequest(
            title=" ",
            job_title="Engineer",
            rubric={"criteria": [{"name": "Python", "weight": 100}]},
        ))



def test_resume_pii_is_removed_before_model_input():
    from app.routers.ai_hiring_studio import _redact_resume_pii

    resume = {
        "name": "Aisha Khan",
        "email": "aisha.khan@example.com",
        "phone": "+91 98765 43210",
        "age": 29,
        "gender": "Female",
        "nationality": "Indian",
        "skills": ["Python", "FastAPI"],
        "raw_text": (
            "Aisha Khan\nEmail: aisha.khan@example.com\nPhone: +91 98765 43210\n"
            "Age: 29\nGender: Female\nNationality: Indian\n"
            "Built REST APIs with Python."
        ),
    }

    redacted = _redact_resume_pii(resume)
    rendered = repr(redacted)

    assert "Aisha Khan" not in rendered
    assert "aisha.khan@example.com" not in rendered
    assert "98765 43210" not in rendered
    assert "Female" not in rendered
    assert "Indian" not in rendered
    assert "Python" in rendered
    assert "FastAPI" in rendered
    assert "Built REST APIs with Python." in rendered
    assert resume["name"] == "Aisha Khan"  # Redaction never mutates caller data.


def test_ephemeral_assessment_does_not_persist_resume_or_model_content(monkeypatch):
    from types import SimpleNamespace

    import app.routers.ai_hiring_studio as studio

    class FakeDatabase:
        def add(self, item):
            self.run = item

        def commit(self):
            pass

        def refresh(self, item):
            pass

    monkeypatch.setattr(
        studio,
        "_call_openrouter",
        lambda *args, **kwargs: {
            "content": '{"overall_score": 80}',
            "usage": {"total_tokens": 3},
            "call_count": 1,
            "actual_model": "test/model",
        },
    )
    db = FakeDatabase()
    result, run = studio._run_model(
        SimpleNamespace(model="test/model", api_key="not-used-by-mock"),
        SimpleNamespace(id=10, organization_id=20),
        db,
        "analyze_resume",
        "private system prompt",
        '{"resume_evidence": "private resume content"}',
        {"resume_data": {"name": "Aisha Khan"}, "rubric": {"criteria": []}},
        100,
        persist_prompt_content=False,
    )

    assert result == {"overall_score": 80}
    assert run.input_data == {"privacy_mode": "ephemeral_assessment"}
    assert run.system_prompt == "[not stored: ephemeral assessment]"
    assert run.user_prompt == "[not stored: ephemeral assessment]"
    assert run.output_data is None
    assert run.raw_model_output is None
    assert run.token_usage == {"total_tokens": 3}
    assert run.status == "success"



def test_nested_profile_name_is_redacted_from_free_text():
    from app.routers.ai_hiring_studio import _redact_resume_pii

    redacted = _redact_resume_pii({
        "profile": {"full_name": "Aisha Khan"},
        "resume_text": "Aisha Khan led Python API deployments.",
    })

    assert "Aisha Khan" not in repr(redacted)
    assert "Python API deployments" in repr(redacted)



def test_resume_name_redaction_does_not_change_larger_words():
    from app.routers.ai_hiring_studio import _redact_resume_pii

    redacted = _redact_resume_pii({
        "name": "Ann",
        "summary": "Ann built annual reporting pipelines.",
    })

    assert "Ann" not in redacted["summary"]
    assert "annual reporting pipelines" in redacted["summary"]



def test_unlabelled_inline_email_and_phone_are_redacted():
    from app.routers.ai_hiring_studio import _redact_resume_pii

    redacted = _redact_resume_pii({
        "summary": "Email aisha.khan@example.com or call +91 98765 43210 for details.",
    })

    assert "aisha.khan@example.com" not in repr(redacted)
    assert "98765 43210" not in repr(redacted)



def test_rubric_content_hash_is_stable_and_tracks_content():
    from app.routers.ai_hiring_studio import _rubric_content_hash

    rubric = {"title": "Platform Engineer", "criteria": [{"name": "Python", "weight": 100}]}
    first = _rubric_content_hash("Platform Engineer", "Platform Engineer", rubric)
    repeat = _rubric_content_hash("Platform Engineer", "Platform Engineer", rubric)
    changed = _rubric_content_hash(
        "Platform Engineer", "Platform Engineer",
        {"title": "Platform Engineer", "criteria": [{"name": "Python", "weight": 90}]},
    )
    assert first == repeat
    assert len(first) == 64
    assert first != changed


def test_saving_rubric_edit_creates_next_immutable_version():
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from app.routers.ai_hiring_studio import (
        AIHiringRubric, SavedRubricRequest, update_saved_rubric, _rubric_content_hash,
    )

    original_rubric = {
        "title": "Platform Engineer",
        "criteria": [{"name": "Python", "weight": 100, "required": True}],
        "total_weight": 100,
    }
    now = datetime.now(timezone.utc)
    original = AIHiringRubric(
        id=1, rubric_id="rubric-version-one", organization_id=7, user_id=8,
        title="Platform Engineer", job_title="Platform Engineer", rubric_data=original_rubric,
        family_id="rubric-family-one", version=1,
        content_hash=_rubric_content_hash("Platform Engineer", "Platform Engineer", original_rubric),
        created_at=now, updated_at=now,
    )

    class FakeDatabase:
        def __init__(self):
            self.added, self.scalar_calls, self.commits = [], 0, 0

        def scalar(self, _query):
            self.scalar_calls += 1
            return original if self.scalar_calls == 1 else 1

        def add(self, value):
            self.added.append(value)

        def commit(self):
            self.commits += 1

        def refresh(self, _value):
            pass

    db = FakeDatabase()
    user = SimpleNamespace(id=9, organization_id=7)
    request = SavedRubricRequest(
        title="Platform Engineer",
        job_title="Platform Engineer",
        rubric={
            "title": "Platform Engineer",
            "criteria": [
                {"name": "Python", "weight": 70, "required": True},
                {"name": "REST APIs", "weight": 30, "required": True},
            ],
        },
    )
    saved = update_saved_rubric("rubric-version-one", request, user, db)
    assert len(db.added) == 1
    newer = db.added[0]
    assert newer.rubric_id != original.rubric_id
    assert newer.family_id == original.family_id
    assert newer.version == 2
    assert newer.content_hash != original.content_hash
    assert newer.rubric_data == saved["rubric"]
    assert saved["rubric_id"] == newer.rubric_id
    assert saved["version"] == 2
    assert saved["family_id"] == "rubric-family-one"
    assert original.version == 1
    assert original.rubric_data == original_rubric
    assert original.content_hash == _rubric_content_hash(
        "Platform Engineer", "Platform Engineer", original_rubric
    )
    assert db.commits == 1



def test_resume_assessment_uses_server_saved_rubric_snapshot(monkeypatch):
    import json
    from datetime import datetime, timezone
    from types import SimpleNamespace

    import app.routers.ai_hiring_studio as studio

    saved_rubric = {
        "title": "Platform Engineer",
        "criteria": [{"name": "Python", "weight": 100, "required": True}],
        "total_weight": 100,
    }
    now = datetime.now(timezone.utc)
    row = studio.AIHiringRubric(
        id=1,
        rubric_id="rubric-version-one",
        organization_id=7,
        user_id=8,
        title="Platform Engineer",
        job_title="Platform Engineer",
        rubric_data=saved_rubric,
        family_id="rubric-family-one",
        version=3,
        content_hash=studio._rubric_content_hash("Platform Engineer", "Platform Engineer", saved_rubric),
        created_at=now,
        updated_at=now,
    )

    class FakeDatabase:
        def scalar(self, _query):
            return row

    captured = {}

    def fake_run_model(*args, **kwargs):
        captured["prompt"] = args[5]
        captured["input_data"] = args[6]
        captured["privacy_metadata"] = kwargs["privacy_metadata"]
        return (
            {"criteria": [{"name": "Python", "score": 80}], "overall_score": 80},
            SimpleNamespace(
                request_id="request-test",
                model="test/model",
                latency_ms=2,
                token_usage={"total_tokens": 5},
                model_call_count=1,
            ),
        )

    monkeypatch.setattr(studio, "_run_model", fake_run_model)
    request = studio.AnalyzeResumeRequest(
        rubric_id="rubric-version-one",
        resume_data={"skills": ["Python"]},
        # A browser could send stale or edited criteria; the server must ignore this.
        rubric={"title": "Tampered", "criteria": [{"name": "Attacker criterion", "weight": 100}]},
    )
    response = studio.analyze_resume(
        request,
        SimpleNamespace(id=8, organization_id=7),
        FakeDatabase(),
    )

    prompt = json.loads(captured["prompt"])
    assert prompt["rubric"] == saved_rubric
    assert "Attacker criterion" not in captured["prompt"]
    assert response["rubric_id"] == "rubric-version-one"
    assert response["rubric_family_id"] == "rubric-family-one"
    assert response["rubric_version"] == 3
    assert response["rubric_hash"] == row.content_hash
    assert captured["privacy_metadata"]["rubric_hash"] == row.content_hash
    assert "resume_data" in captured["input_data"]
