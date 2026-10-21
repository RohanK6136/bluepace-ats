from types import SimpleNamespace

from app.services.llm_validator import LLMValidator, VALIDATION_MODEL


VALID_RESPONSE = """
{
  "match_score": 82,
  "coding_skills_score": 80,
  "behavioral_skills_score": 75,
  "mandatory_skills_match_score": 90,
  "mandatory_skills_met": ["Python"],
  "mandatory_skills_missed": [],
  "summary": "Relevant backend experience.",
  "missing_skills": [],
  "recommendation": "Yes",
  "is_fresher": false,
  "highest_education": "Bachelor's degree",
  "extracted_experience": [],
  "extracted_education": [],
  "extracted_hobbies": [],
  "extracted_university_projects": []
}
"""


class FakeChatCompletions:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        message = SimpleNamespace(content=VALID_RESPONSE)
        choice = SimpleNamespace(message=message)
        return SimpleNamespace(choices=[choice])


class FakeClient:
    def __init__(self, completions=None):
        self.chat = SimpleNamespace(completions=completions or FakeChatCompletions())


def test_validator_sends_ordered_fallback_models_and_throughput_routing(monkeypatch):
    monkeypatch.setenv(
        "OPENROUTER_FALLBACK_MODELS",
        "meta-llama/llama-3.3-70b-instruct, google/gemini-2.5-flash",
    )
    validator = LLMValidator()
    validator.client = FakeClient()

    result = validator.validate_resume({"skills": ["Python"]}, "Python engineer")

    assert result["match_score"] == 82
    request = validator.client.chat.completions.calls[0]
    assert request["model"] == VALIDATION_MODEL
    assert request["extra_body"]["models"] == [
        "meta-llama/llama-3.3-70b-instruct",
        "google/gemini-2.5-flash",
    ]
    assert request["extra_body"]["provider"]["sort"] == "throughput"
    assert request["extra_body"]["provider"]["allow_fallbacks"] is True


class SimulatedRateLimit(Exception):
    status_code = 429

    def __init__(self):
        super().__init__("429 upstream provider rate-limited user_id=must-not-leak")
        self.response = SimpleNamespace(headers={"retry-after": "0"})


class RateLimitedOnce:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            raise SimulatedRateLimit()
        message = SimpleNamespace(content=VALID_RESPONSE)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class AlwaysRateLimited:
    def create(self, **_kwargs):
        raise SimulatedRateLimit()


def test_validator_retries_transient_rate_limit(monkeypatch):
    monkeypatch.setenv("OPENROUTER_429_RETRIES", "1")
    validator = LLMValidator()
    completions = RateLimitedOnce()
    validator.client = FakeClient(completions)
    delays = []
    validator.sleep = delays.append

    result = validator.validate_resume({"skills": ["Python"]}, "Python engineer")

    assert result["match_score"] == 82
    assert len(completions.calls) == 2
    assert delays == [0.0]


def test_exhausted_rate_limit_returns_safe_manual_review(monkeypatch):
    monkeypatch.setenv("OPENROUTER_429_RETRIES", "0")
    validator = LLMValidator()
    validator.client = FakeClient(AlwaysRateLimited())

    result = validator.validate_resume({"skills": ["Python"]}, "Python engineer")

    assert result["recommendation"] == "Manual Review"
    assert "temporarily rate-limited" in result["error"]
    assert "user_id" not in result["error"]


def test_validator_bounds_upstream_requests_and_does_not_retry_timeouts(monkeypatch):
    class TimedOut:
        def __init__(self):
            self.calls = 0

        def create(self, **_kwargs):
            self.calls += 1
            raise TimeoutError("upstream request timed out")

    monkeypatch.setenv("OPENROUTER_429_RETRIES", "2")
    validator = LLMValidator()
    completions = TimedOut()
    validator.client = FakeClient(completions)

    result = validator.validate_resume({"skills": ["Python"]}, "Python engineer")

    assert result["recommendation"] == "Manual Review"
    assert result["error"] == "upstream request timed out"
    assert completions.calls == 1
def test_validator_records_non_sensitive_request_telemetry(monkeypatch):
    validator = LLMValidator()
    validator.client = FakeClient()

    result = validator.validate_resume({"skills": ["Python"]}, "Python engineer")

    assert result["match_score"] == 82
    assert validator.last_call_meta["model"] == VALIDATION_MODEL
    assert validator.last_call_meta["attempts"] == 1
    assert validator.last_call_meta["latency_ms"] >= 0
    assert "api_key" not in validator.last_call_meta
