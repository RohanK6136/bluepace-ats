from __future__ import annotations

from pathlib import Path

import yaml

from app.llm.registry import ModelRegistry


def test_openrouter_is_the_safe_hosted_default() -> None:
    config_path = Path(__file__).parents[1] / "config" / "models.yaml"
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))

    assert data["default_profile"] == "${LLM_PROFILE:-openrouter}"
    profile = data["profiles"]["openrouter"]
    assert profile["base_url"] == "https://openrouter.ai/api/v1"
    assert profile["model"] == "${OPENROUTER_MODEL:-google/gemini-2.5-flash}"
    assert profile["api_key_env"] == "OPENROUTER_API_KEY"
    assert profile["pricing"]["input_per_mtok"] == "${OPENROUTER_INPUT_PRICE:-0}"
    assert profile["pricing"]["output_per_mtok"] == "${OPENROUTER_OUTPUT_PRICE:-0}"


def test_openrouter_profile_is_disabled_without_provider_secret(monkeypatch) -> None:
    # The model id/config can be parsed without credentials, but the registry must not
    # mark this hosted provider usable until its key is securely supplied at runtime.
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    config_path = Path(__file__).parents[1] / "config" / "models.yaml"
    registry = ModelRegistry.from_file(config_path)

    profile = registry.get("openrouter")
    assert profile.model == "google/gemini-2.5-flash"
    assert registry.disabled_reason(profile) == "set OPENROUTER_API_KEY to enable"
