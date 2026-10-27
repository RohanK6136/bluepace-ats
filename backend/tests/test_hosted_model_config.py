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

def test_direct_provider_profiles_are_registered_and_disabled_without_keys(monkeypatch) -> None:
    config_path = Path(__file__).parents[1] / "config" / "models.yaml"
    for name in ("GOOGLE_API_KEY", "DEEPSEEK_API_KEY", "XAI_API_KEY", "GITHUB_MODELS_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    registry = ModelRegistry.from_file(config_path)

    expected = {
        "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", "gemini-2.5-flash", "GOOGLE_API_KEY"),
        "deepseek": ("https://api.deepseek.com", "deepseek-chat", "DEEPSEEK_API_KEY"),
        "grok": ("https://api.x.ai/v1", "grok-3-mini", "XAI_API_KEY"),
        "github-models": ("https://models.github.ai/inference", "openai/gpt-4.1", "GITHUB_MODELS_TOKEN"),
    }
    for profile_id, (base_url, model, key_env) in expected.items():
        profile = registry.get(profile_id)
        assert profile.base_url == base_url
        assert profile.model == model
        assert profile.api_key_env == key_env
        assert registry.disabled_reason(profile) == f"set {key_env} to enable"
