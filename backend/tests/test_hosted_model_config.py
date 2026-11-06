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
    assert profile["model"] == "openrouter/free"
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
    assert profile.model == "openrouter/free"
    assert registry.disabled_reason(profile) == "set OPENROUTER_API_KEY to enable"

def test_direct_provider_profiles_are_registered_and_disabled_without_keys(monkeypatch) -> None:
    config_path = Path(__file__).parents[1] / "config" / "models.yaml"
    for name in ("OPENROUTER_API_KEY", "GITHUB_MODELS_TOKEN", "GITHUB_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    registry = ModelRegistry.from_file(config_path)

    expected = {
        "gemini": ("https://openrouter.ai/api/v1", "google/gemini-2.5-flash", "OPENROUTER_API_KEY"),
        "deepseek": ("https://openrouter.ai/api/v1", "deepseek/deepseek-chat", "OPENROUTER_API_KEY"),
        "grok": ("https://openrouter.ai/api/v1", "x-ai/grok-3-mini", "OPENROUTER_API_KEY"),
        "openrouter-openai": ("https://openrouter.ai/api/v1", "openai/gpt-4.1", "OPENROUTER_API_KEY"),
        "github-models": ("https://models.github.ai/inference", "openai/gpt-4.1", "GITHUB_MODELS_TOKEN"),
    }
    for profile_id, (base_url, model, key_env) in expected.items():
        profile = registry.get(profile_id)
        assert profile.base_url == base_url
        assert profile.model == model
        assert profile.api_key_env == key_env
        if profile_id == "github-models":
            assert registry.disabled_reason(profile) == f"set {key_env} or GITHUB_TOKEN to enable"
        else:
            assert registry.disabled_reason(profile) == f"set {key_env} to enable"

    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    assert registry.disabled_reason(registry.get("github-models")) is None
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-token")
    assert registry.disabled_reason(registry.get("openrouter")) is None
    for profile_id in ("gemini", "deepseek", "grok", "openrouter-openai"):
        assert registry.disabled_reason(registry.get(profile_id)) == (
            "paid OpenRouter models are disabled; select OpenRouter Free Models (automatic)"
        )


def test_stale_paid_openrouter_profile_override_falls_back_to_free_default() -> None:
    config_path = Path(__file__).parents[1] / "config" / "models.yaml"

    registry = ModelRegistry.from_file(config_path, default_override="gemini")

    assert registry.default_id == "openrouter"
    assert registry.get(registry.default_id).model == "openrouter/free"


def test_local_ollama_profile_is_ready_without_a_provider_key(monkeypatch) -> None:
    config_path = Path(__file__).parents[1] / "config" / "models.yaml"
    monkeypatch.setenv("LLM_PROFILE", "local-ollama")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3:8b")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    registry = ModelRegistry.from_file(config_path)
    profile = registry.get("local-ollama")

    assert registry.default_id == "local-ollama"
    assert profile.model == "qwen3:8b"
    assert profile.base_url == "http://127.0.0.1:11434"
    assert profile.provider == "ollama"
    assert profile.structured_output == "json_schema"
    assert profile.extra_body["think"] is False
    assert profile.extra_body["keep_alive"] == "1h"
    assert profile.local is True
    assert profile.api_key_env is None
    assert profile.pricing.cost(1000, 1000) == 0
    assert registry.disabled_reason(profile) is None
