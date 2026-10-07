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
