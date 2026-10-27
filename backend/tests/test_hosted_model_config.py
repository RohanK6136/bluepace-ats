from __future__ import annotations

import os
from pathlib import Path

import yaml


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


def test_openrouter_profile_parses_without_provider_secrets(monkeypatch) -> None:
    # No credentials are needed just to parse the configuration. The profile will be
    # marked unavailable by the registry until OPENROUTER_API_KEY is configured.
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    config_path = Path(__file__).parents[1] / "config" / "models.yaml"
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    profile = data["profiles"]["openrouter"]
    assert profile["api_key_env"] == "OPENROUTER_API_KEY"
    assert "OPENROUTER_API_KEY" not in repr(profile)
