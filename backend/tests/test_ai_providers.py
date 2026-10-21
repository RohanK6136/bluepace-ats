"""Unit tests for multi-provider AI support."""
import json
import pytest
from fastapi import HTTPException
from app.services import ai_providers
from app.routers.ai_hiring_studio import _configuration_status


def test_provider_aliases_and_defaults(monkeypatch):
    monkeypatch.delenv("AI_PROVIDER", raising=False)
    assert ai_providers.provider_name("chatgpt") == "openai"
    assert ai_providers.provider_name("anthropic") == "claude"
    assert ai_providers.provider_name("qwen") == "ollama"
    assert ai_providers.provider_name("google") == "gemini"
    assert ai_providers.provider_name("google_genai") == "gemini"
    assert ai_providers.default_model("gemini") == "gemini-2.5-flash"
    assert ai_providers.default_model("ollama") == "qwen3.5:4b"
    assert ai_providers.default_model("deepseek") == "deepseek-flash"
    assert ai_providers.default_model("cloudflare") == "@cf/qwen/qwen3.8-27b"


def test_unknown_provider_is_rejected():
    with pytest.raises(ValueError, match="Choose OpenRouter"):
        ai_providers.provider_name("not-a-provider")


def test_ollama_loopback_url_and_path():
    assert ai_providers.local_chat_completions_url() == "http://localhost:11434/v1/chat/completions"
    assert ai_providers.local_chat_completions_url("http://127.0.0.1:11434") == "http://127.0.0.1:11434/v1/chat/completions"


@pytest.mark.parametrize("url", [
    "https://example.com/v1", "http://192.168.1.10:11434/v1",
    "http://169.254.169.254/latest/meta-data", "http://localhost:11434/admin",
    "http://user:pass@localhost:11434/v1",
])
def test_ollama_url_rejects_remote_hosts_and_unsafe_paths(url):
    with pytest.raises(HTTPException) as error:
        ai_providers.local_chat_completions_url(url)
    assert error.value.status_code == 422


def test_claude_adapter_uses_native_messages_schema(monkeypatch):
    seen = {}
    class FakeResponse:
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def read(self):
            return json.dumps({
                "model": "claude-sonnet-4-6",
                "content": [{"type": "text", "text": "{\"ok\": true}"}],
                "usage": {"input_tokens": 12, "output_tokens": 7},
            }).encode()
    def fake_urlopen(request, timeout=45):
        seen["url"] = request.full_url
        seen["payload"] = json.loads(request.data.decode())
        return FakeResponse()
    monkeypatch.setattr(ai_providers.urllib.request, "urlopen", fake_urlopen)
    result = ai_providers.call_ai_provider("claude", "test-key", "claude-sonnet-4-6", "system", "user", 20, json_mode=False)
    assert seen["url"] == "https://api.anthropic.com/v1/messages"
    assert seen["payload"]["system"] == "system"
    assert result["content"] == '{"ok": true}'
    assert result["usage"]["total_tokens"] == 19
    assert result["actual_model"] == "claude/claude-sonnet-4-6"


def test_openai_adapter_sends_json_mode(monkeypatch):
    seen = {}
    class FakeResponse:
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def read(self):
            return json.dumps({
                "model": "gpt-5.4", "choices": [{"message": {"content": "{\"ok\": true}"}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
            }).encode()
    def fake_urlopen(request, timeout=45):
        seen["url"] = request.full_url
        seen["payload"] = json.loads(request.data.decode())
        return FakeResponse()
    monkeypatch.setattr(ai_providers.urllib.request, "urlopen", fake_urlopen)
    result = ai_providers.call_ai_provider("openai", "test-key", "gpt-5.4", "system", "user", 20)
    assert seen["url"] == "https://api.openai.com/v1/chat/completions"
    assert seen["payload"]["response_format"] == {"type": "json_object"}
    assert seen["payload"]["max_completion_tokens"] == 20
    assert "max_tokens" not in seen["payload"]
    assert "temperature" not in seen["payload"]
    assert result["usage"]["total_tokens"] == 7


def test_cloudflare_requires_account_id():
    with pytest.raises(HTTPException) as error:
        ai_providers.call_ai_provider("cloudflare", "test-token", "@cf/qwen/qwen3.8-27b", "system", "user")
    assert error.value.status_code == 400
    assert "Account ID" in error.value.detail


def test_provider_key_resolution_uses_server_environment(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "provider-key-sentinel")
    assert ai_providers.provider_has_server_key("openai") is True
    assert ai_providers.resolve_api_key(None, "openai") == "provider-key-sentinel"


def test_ollama_does_not_claim_a_server_api_key_is_configured():
    assert ai_providers.provider_has_server_key("ollama") is False
    status = _configuration_status("ollama")
    assert status["requires_api_key"] is False
    assert status["server_key_configured"] is False
    assert status["key_source"] == "local endpoint (no API key required)"


def test_cloudflare_configuration_status_includes_account_id_state(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-token")
    monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID", raising=False)
    status = _configuration_status("cloudflare")
    assert status["server_key_configured"] is True
    assert status["account_id_configured"] is False
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "test-account")
    assert _configuration_status("cloudflare")["account_id_configured"] is True



def test_gemini_adapter_uses_official_sdk_and_normalizes_usage(monkeypatch):
    import sys
    import types

    captured = {}
    class FakeUsage:
        prompt_token_count = 11
        candidates_token_count = 9
        total_token_count = 20
    class FakeResponse:
        text = '{"ok": true}'
        usage_metadata = FakeUsage()
    class FakeModels:
        def generate_content(self, **kwargs):
            captured.update(kwargs)
            return FakeResponse()
    class FakeClient:
        def __init__(self, api_key):
            captured["api_key"] = api_key
            self.models = FakeModels()
    class FakeConfig:
        def __init__(self, **kwargs):
            captured["config"] = kwargs
    fake_genai = types.ModuleType("google.genai")
    fake_genai.Client = FakeClient
    fake_types = types.ModuleType("google.genai.types")
    fake_types.GenerateContentConfig = FakeConfig
    fake_google = types.ModuleType("google")
    fake_google.genai = fake_genai
    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", fake_types)

    result = ai_providers.call_ai_provider(
        "gemini", "test-key", "gemini-2.5-flash", "system instructions",
        "write JSON", max_tokens=100, json_mode=True,
    )
    assert captured["api_key"] == "test-key"
    assert captured["model"] == "gemini-2.5-flash"
    assert captured["contents"] == "write JSON"
    assert captured["config"]["system_instruction"] == "system instructions"
    assert captured["config"]["response_mime_type"] == "application/json"
    assert result["content"] == '{"ok": true}'
    assert result["usage"]["total_tokens"] == 20
    assert result["actual_model"] == "gemini/gemini-2.5-flash"
