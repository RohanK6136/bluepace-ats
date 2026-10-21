"""Provider adapters for AI Hiring Studio.

Hosted APIs use fixed provider URLs. Ollama allows only loopback URLs so this
authenticated endpoint cannot be turned into a general SSRF proxy.
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any
from fastapi import HTTPException

PROVIDER_LABELS = {
    "openrouter": "OpenRouter", "openai": "OpenAI / ChatGPT",
    "claude": "Claude (Anthropic)", "deepseek": "DeepSeek",
    "cloudflare": "Cloudflare Workers AI", "ollama": "Local Ollama",
}
DEFAULT_MODELS = {
    "openrouter": "openrouter/free", "openai": "gpt-5.4",
    "claude": "claude-sonnet-4-6", "deepseek": "deepseek-v4-flash",
    "cloudflare": "@cf/qwen/qwen3.8-27b", "ollama": "qwen3.5:4b",
}
KEY_ENV = {
    "openrouter": ("OPENROUTER_API_KEY",), "openai": ("OPENAI_API_KEY",),
    "claude": ("ANTHROPIC_API_KEY", "CLAUDE_API_KEY"),
    "deepseek": ("DEEPSEEK_API_KEY",),
    "cloudflare": ("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_API_KEY"), "ollama": (),
}
MODEL_ENV = {
    "openrouter": ("OPENROUTER_MODEL",), "openai": ("OPENAI_MODEL",),
    "claude": ("ANTHROPIC_MODEL", "CLAUDE_MODEL"),
    "deepseek": ("DEEPSEEK_MODEL",), "cloudflare": ("CLOUDFLARE_MODEL",),
    "ollama": ("OLLAMA_MODEL",),
}
ALIASES = {
    "chatgpt": "openai", "anthropic": "claude",
    "cloudflare_workers_ai": "cloudflare", "workers_ai": "cloudflare",
    "local": "ollama", "qwen": "ollama", "ollama_local": "ollama",
}


def provider_name(value: str | None = None) -> str:
    candidate = (value or os.getenv("AI_PROVIDER") or "openrouter").strip().lower()
    candidate = ALIASES.get(candidate, candidate)
    if candidate not in PROVIDER_LABELS:
        raise ValueError("Choose OpenRouter, OpenAI, Claude, DeepSeek, Cloudflare Workers AI, or Ollama.")
    return candidate


def provider_label(provider: str) -> str:
    return PROVIDER_LABELS[provider_name(provider)]


def default_model(provider: str) -> str:
    provider = provider_name(provider)
    for name in MODEL_ENV[provider]:
        if os.getenv(name, "").strip():
            return os.environ[name].strip()
    return DEFAULT_MODELS[provider]


def model_name(value: str | None, provider: str) -> str:
    name = (value or default_model(provider)).strip()
    if not name or len(name) > 200:
        raise HTTPException(422, "Enter a valid model identifier.")
    return name


def resolve_api_key(value: str | None, provider: str) -> str:
    if value and value.strip():
        return value.strip()
    for name in KEY_ENV[provider_name(provider)]:
        if os.getenv(name, "").strip():
            return os.environ[name].strip()
    return ""


def provider_has_server_key(provider: str) -> bool:
    provider = provider_name(provider)
    return provider == "ollama" or any(os.getenv(name, "").strip() for name in KEY_ENV[provider])


def local_chat_completions_url(value: str | None = None) -> str:
    raw = (value or os.getenv("OLLAMA_BASE_URL") or "http://localhost:11434/v1").strip()
    parsed = None
    try:
        parsed = urllib.parse.urlsplit(raw)
        _ = parsed.port
        valid = (
            parsed.scheme == "http"
            and (parsed.hostname or "").lower() in {"localhost", "127.0.0.1", "::1"}
            and parsed.path.rstrip("/") in {"", "/", "/v1"}
            and parsed.username is None and parsed.password is None
            and not parsed.query and not parsed.fragment
        )
    except ValueError:
        valid = False
    if not valid or parsed is None:
        raise HTTPException(422, "Ollama base URL must be a loopback HTTP URL such as http://localhost:11434/v1. Remote URLs are not accepted.")
    root = raw.rstrip("/")
    if parsed.path.rstrip("/") in {"", "/"}:
        root += "/v1"
    return root + "/chat/completions"


def _error_text(body: str, status: int, provider: str) -> str:
    message = ""
    try:
        payload = json.loads(body)
        error = payload.get("error")
        if isinstance(error, dict):
            message = str(error.get("message") or "")
        elif isinstance(error, str):
            message = error
        message = message or str(payload.get("message") or "")
        if not message and isinstance(payload.get("errors"), list):
            message = "; ".join(str(item.get("message") or "") for item in payload["errors"] if isinstance(item, dict))
    except (ValueError, AttributeError, TypeError):
        pass
    label = provider_label(provider)
    if status == 401:
        return f"{label} rejected the API key. Check the key in AI Hiring Studio settings."
    if status == 402:
        return f"{label} reports insufficient credits or account balance."
    if status == 403:
        return f"{label} denied access. Check model permissions and account settings."
    if status == 404:
        return f"{label} could not find the requested model or API endpoint. Check the model identifier."
    if status == 429:
        return f"{label} rate limit reached. Wait briefly or select another model."
    return message[:350] if message else f"{label} request failed with HTTP {status}."


def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str], provider: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={**headers, "Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read(2048).decode("utf-8", errors="replace")
        raise HTTPException(502, _error_text(body, error.code, provider)) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        if provider == "ollama":
            raise HTTPException(504, "Cannot reach local Ollama. Start Ollama and ensure this backend runs on the same machine.") from None
        raise HTTPException(504, f"{provider_label(provider)} is unreachable or timed out.") from None
    if not isinstance(data, dict):
        raise HTTPException(502, "The AI provider returned an unexpected response.")
    return data


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "\n".join(
            item["text"] for item in value
            if isinstance(item, dict) and isinstance(item.get("text"), str)
        ).strip()
    return ""


def call_ai_provider(
    provider: str, api_key_value: str | None, model: str,
    system_prompt: str, user_prompt: str, max_tokens: int = 1800,
    base_url: str | None = None, account_id: str | None = None,
    json_mode: bool = True,
) -> dict[str, Any]:
    """Call a selected provider and normalize content, token usage, and model metadata."""
    provider = provider_name(provider)
    key = resolve_api_key(api_key_value, provider)
    if provider != "ollama" and not key:
        names = ", ".join(KEY_ENV[provider])
        raise HTTPException(400, f"Add a {provider_label(provider)} API key in settings or configure {names} on the backend.")

    if provider == "claude":
        url = "https://api.anthropic.com/v1/messages"
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
        payload = {
            "model": model, "max_tokens": max_tokens, "temperature": 0.2,
            "system": system_prompt, "messages": [{"role": "user", "content": user_prompt}],
        }
        data = _post_json(url, payload, headers, provider)
        content = _text(data.get("content"))
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        prompt_tokens, completion_tokens = usage.get("input_tokens"), usage.get("output_tokens")
        usage_out = {
            "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
            "total_tokens": ((prompt_tokens or 0) + (completion_tokens or 0))
            if prompt_tokens is not None or completion_tokens is not None else None,
        }
        actual_model, count = str(data.get("model") or model), 1
    else:
        if provider == "openrouter":
            url = "https://openrouter.ai/api/v1/chat/completions"
            headers = {
                "Authorization": "Bearer " + key,
                "HTTP-Referer": os.getenv("PUBLIC_APP_URL", "https://bluepace-frontend-production.up.railway.app"),
                "X-Title": "BluePace ATS AI Hiring Studio",
            }
        elif provider == "openai":
            url, headers = "https://api.openai.com/v1/chat/completions", {"Authorization": "Bearer " + key}
        elif provider == "deepseek":
            url, headers = "https://api.deepseek.com/chat/completions", {"Authorization": "Bearer " + key}
        elif provider == "cloudflare":
            account = (account_id or os.getenv("CLOUDFLARE_ACCOUNT_ID") or "").strip()
            if not account:
                raise HTTPException(400, "Enter your Cloudflare Account ID or configure CLOUDFLARE_ACCOUNT_ID on the backend.")
            if len(account) > 128 or not all(ch.isalnum() or ch in "-_" for ch in account):
                raise HTTPException(422, "The Cloudflare Account ID contains invalid characters.")
            url = f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/v1/chat/completions"
            headers = {"Authorization": "Bearer " + key}
        elif provider == "ollama":
            url, headers = local_chat_completions_url(base_url), {"Authorization": "Bearer ollama"}
        else:
            raise HTTPException(422, "The selected AI provider is not supported.")

        payload = {
            "model": model, "messages": [
                {"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt},
            ],
        }
        if provider == "openai":
            # New GPT models use max_completion_tokens; some do not permit a
            # non-default temperature on the Chat Completions endpoint.
            payload["max_completion_tokens"] = max_tokens
        else:
            payload["temperature"] = 0.2
            payload["max_tokens"] = max_tokens
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        data, count = {}, 0
        for structured in ((True, False) if json_mode else (False,)):
            call_payload = dict(payload)
            if not structured:
                call_payload.pop("response_format", None)
            count += 1
            try:
                data = _post_json(url, call_payload, headers, provider)
                break
            except HTTPException as error:
                unsupported = structured and error.status_code == 502 and any(
                    item in str(error.detail).lower()
                    for item in ("response_format", "json_object", "unsupported parameter")
                )
                if not unsupported:
                    raise
        choices = data.get("choices") or []
        message = (choices[0].get("message") or {}) if choices else {}
        content = _text(message.get("content"))
        if not content and provider == "cloudflare" and isinstance(data.get("result"), dict):
            content = _text(data["result"].get("response"))
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        usage_out = {key: usage.get(key) for key in ("prompt_tokens", "completion_tokens", "total_tokens")}
        actual_model = str(data.get("model") or model)
        count = max(count, 1)

    if not content:
        raise HTTPException(502, f"{provider_label(provider)} returned an empty response.")
    return {
        "content": content, "usage": usage_out,
        "actual_model": model if provider == "openrouter" else provider + "/" + actual_model,
        "call_count": count,
    }
