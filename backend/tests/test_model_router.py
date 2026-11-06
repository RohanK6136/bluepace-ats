from app.services.model_router import (
    ASSISTANT_MODEL,
    DEFAULT_MODEL,
    DEEP_REASONING_MODEL,
    MATCHING_MODEL,
    VALIDATION_MODEL,
    model_for,
)


def test_routing_defaults_are_consistent():
    assert model_for("default") == DEFAULT_MODEL
    assert model_for("assistant") == ASSISTANT_MODEL
    assert model_for("validation") == VALIDATION_MODEL
    assert model_for("matching_summary") == MATCHING_MODEL


def test_deep_reasoning_is_explicit():
    assert model_for("deep_reasoning", deep=True) == DEEP_REASONING_MODEL



def test_paid_environment_overrides_are_rejected(monkeypatch):
    from app.services.model_router import free_model_from_env, is_free_openrouter_model

    monkeypatch.setenv("OPENROUTER_MODEL", "google/gemini-2.5-flash")
    monkeypatch.setenv("OPENROUTER_DEEP_REASONING_MODEL", "openai/gpt-5.5")
    assert free_model_from_env("OPENROUTER_MODEL") == "openrouter/free"
    assert free_model_from_env("OPENROUTER_DEEP_REASONING_MODEL") == "openrouter/free"
    assert is_free_openrouter_model("openrouter/free")
    assert is_free_openrouter_model("meta-llama/llama-3.3-70b-instruct:free")
    assert not is_free_openrouter_model("google/gemini-2.5-flash")
