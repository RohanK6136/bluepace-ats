from app.services.model_router import (
    ASSISTANT_MODEL,
    DEFAULT_MODEL,
    DEEP_REASONING_MODEL,
    MATCHING_MODEL,
    VALIDATION_MODEL,
    free_openrouter_model,
    model_for,
)


def test_routing_defaults_are_consistent():
    assert model_for("default") == DEFAULT_MODEL
    assert model_for("assistant") == ASSISTANT_MODEL
    assert model_for("validation") == VALIDATION_MODEL
    assert model_for("matching_summary") == MATCHING_MODEL


def test_deep_reasoning_is_explicit():
    assert model_for("deep_reasoning", deep=True) == DEEP_REASONING_MODEL



def test_paid_environment_model_ids_are_sanitized_to_free_router():
    assert free_openrouter_model("google/gemini-3.8-flash") == "openrouter/free"
    assert free_openrouter_model("openai/gpt-5.5") == "openrouter/free"
    assert free_openrouter_model("meta-llama/llama-3.3-70b-instruct:free") == (
        "meta-llama/llama-3.3-70b-instruct:free"
    )
    assert DEFAULT_MODEL == "openrouter/free"
    assert ASSISTANT_MODEL == "openrouter/free"
    assert VALIDATION_MODEL == "openrouter/free"
    assert MATCHING_MODEL == "openrouter/free"
    assert DEEP_REASONING_MODEL == "openrouter/free"
