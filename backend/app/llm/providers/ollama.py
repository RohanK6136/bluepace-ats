"""Native Ollama /api/chat adapter.

Uses Ollama's native API rather than its OpenAI-compatible shim so hybrid models such as
Qwen3 can disable the reasoning phase with think=false. This avoids generating discarded
reasoning tokens for structured recruiting workflows.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.core.errors import (
    LLMBadResponse,
    LLMConfigError,
    LLMRateLimited,
    LLMRejected,
    LLMTimeout,
    LLMUnavailable,
)
from app.llm.providers.base import StreamEvent, sanitize_schema
from app.llm.types import ModelProfile, ProviderRequest, ProviderResponse, Usage


class OllamaNativeProvider:
    def __init__(
        self,
        profile: ModelProfile,
        json_instruction: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.profile = profile
        self.json_instruction = json_instruction
        self._http = httpx.AsyncClient(
            base_url=(profile.base_url or "http://127.0.0.1:11434").rstrip("/"),
            timeout=httpx.Timeout(profile.timeout_s, read=profile.stall_timeout_s),
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    def build_body(self, req: ProviderRequest, *, stream: bool) -> dict[str, Any]:
        p = self.profile
        schema = sanitize_schema(req.schema, set(p.schema_drop_keywords))
        user = req.user
        if p.structured_output == "prompt_only":
            user = f"{user}\n\n{self.json_instruction}\n{json.dumps(schema)}"

        body: dict[str, Any] = {
            "model": p.model,
            "messages": [
                {"role": "system", "content": req.system},
                {"role": "user", "content": user},
            ],
            "stream": stream,
        }
        body["format"] = schema if p.structured_output == "json_schema" else "json"

        # Ollama-specific controls live in profile.extra_body. In particular, think=false
        # is supported on the native API and is not reliably honoured by /v1/chat/completions.
        if "think" in p.extra_body:
            body["think"] = p.extra_body["think"]
        if "keep_alive" in p.extra_body:
            body["keep_alive"] = p.extra_body["keep_alive"]

        options: dict[str, Any] = {
            "num_predict": max(req.max_tokens, p.max_tokens_floor),
        }
        if p.context_tokens:
            options["num_ctx"] = p.context_tokens
        for key, value in (
            ("temperature", p.temperature),
            ("top_p", p.top_p),
            ("seed", p.seed),
        ):
            if value is not None:
                options[key] = value
        extra_options = p.extra_body.get("options")
        if isinstance(extra_options, dict):
            options.update(extra_options)
        body["options"] = options
        return body

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        code = response.status_code
        if code < 400:
            return
        detail = f"HTTP {code}: {response.text[:300]}"
        if code in (401, 403):
            raise LLMConfigError(f"Ollama rejected the local request ({detail})")
        if code == 404:
            raise LLMConfigError(f"Ollama model or endpoint not found ({detail})")
        if code == 429:
            raise LLMRateLimited(detail)
        if code in (502, 503, 504):
            raise LLMUnavailable(detail)
        if code < 500:
            raise LLMRejected(detail)
        raise LLMBadResponse(detail)

    @staticmethod
    def _response(data: dict[str, Any]) -> ProviderResponse:
        message = data.get("message") or {}
        text = message.get("content") or ""
        done_reason = data.get("done_reason") or "stop"
        finish = "length" if done_reason in {"length", "max_tokens"} else "stop"
        usage = Usage(
            prompt_tokens=int(data.get("prompt_eval_count") or 0),
            completion_tokens=int(data.get("eval_count") or 0),
        )
        return ProviderResponse(text, finish, usage, data.get("created_at"))

    async def complete(self, req: ProviderRequest) -> ProviderResponse:
        try:
            response = await self._http.post("/api/chat", json=self.build_body(req, stream=False))
        except httpx.TimeoutException as error:
            raise LLMTimeout(str(error) or "Ollama request timed out") from None
        except httpx.TransportError as error:
            raise LLMUnavailable(str(error) or "Ollama is unreachable") from None
        self._raise_for_status(response)
        try:
            data = response.json()
        except ValueError:
            raise LLMBadResponse("Ollama returned a non-JSON response") from None
        if not isinstance(data, dict):
            raise LLMBadResponse("Ollama returned an invalid response")
        return self._response(data)

    async def stream(self, req: ProviderRequest) -> AsyncIterator[StreamEvent]:
        final: ProviderResponse | None = None
        try:
            async with self._http.stream("POST", "/api/chat", json=self.build_body(req, stream=True)) as response:
                if response.status_code >= 400:
                    await response.aread()
                    self._raise_for_status(response)
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    message = data.get("message") or {}
                    content = message.get("content")
                    if content:
                        yield content
                    if data.get("done"):
                        final = self._response(data)
            if final is None:
                raise LLMUnavailable("Ollama stream ended without a final response")
        except httpx.TimeoutException:
            raise LLMTimeout(f"no output from {self.profile.id} for {self.profile.stall_timeout_s:g}s") from None
        except httpx.TransportError as error:
            raise LLMUnavailable(str(error) or "Ollama is unreachable") from None
        yield final

    async def list_models(self) -> list[str]:
        try:
            response = await self._http.get("/api/tags", timeout=5.0)
        except httpx.TransportError as error:
            raise LLMUnavailable(str(error) or "Ollama is unreachable") from None
        self._raise_for_status(response)
        try:
            return [item.get("name", "") for item in response.json().get("models", [])]
        except (ValueError, AttributeError):
            raise LLMBadResponse("Ollama returned an invalid model list") from None

    async def probe(self, timeout_s: float) -> str | None:
        body = {
            "model": self.profile.model,
            "messages": [{"role": "user", "content": "Reply with OK."}],
            "stream": False,
            "think": False,
            "options": {"num_predict": 1, "num_ctx": min(self.profile.context_tokens, 2048)},
        }
        try:
            response = await self._http.post("/api/chat", json=body, timeout=timeout_s)
        except httpx.TimeoutException:
            return f"model did not answer a 1-token request within {timeout_s:g}s"
        except httpx.TransportError as error:
            return f"unreachable: {error or type(error).__name__}"
        if response.status_code >= 400:
            return f"HTTP {response.status_code}: {response.text[:200]}"
        return None
