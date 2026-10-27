"""OpenAI-compatible Chat Completions provider: LM Studio, Ollama, vLLM, llama.cpp server, OpenAI, OpenRouter…"""

from __future__ import annotations

import json
import os
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

_FINISH = {"stop": "stop", "length": "length", "content_filter": "refusal"}


class OpenAICompatibleProvider:
    def __init__(self, profile: ModelProfile, json_instruction: str,
                 transport: httpx.AsyncBaseTransport | None = None):
        self.profile = profile
        self.json_instruction = json_instruction
        headers = {}
        if profile.api_key_env:
            headers["Authorization"] = f"Bearer {os.environ.get(profile.api_key_env, '')}"
        self._http = httpx.AsyncClient(base_url=(profile.base_url or "").rstrip("/"), headers=headers,
                                       timeout=profile.timeout_s, transport=transport)

    async def aclose(self) -> None:
        await self._http.aclose()

    # ------------------------------------------------------------------ request
    def build_body(self, req: ProviderRequest, *, stream: bool) -> dict[str, Any]:
        p = self.profile
        schema = sanitize_schema(req.schema, set(p.schema_drop_keywords))
        user = req.user
        if p.structured_output == "prompt_only":
            user = f"{user}\n\n{self.json_instruction}\n{json.dumps(schema)}"
        body: dict[str, Any] = {
            "model": p.model,
            "messages": [{"role": "system", "content": req.system}, {"role": "user", "content": user}],
            p.max_tokens_param: max(req.max_tokens, p.max_tokens_floor),
            "stream": stream,
        }
        for key, value in (("temperature", p.temperature), ("top_p", p.top_p), ("seed", p.seed)):
            if value is not None:
                body[key] = value
        if p.structured_output == "json_schema":
            body["response_format"] = {"type": "json_schema",
                                       "json_schema": {"name": req.step, "strict": True, "schema": schema}}
        if stream:
            body["stream_options"] = {"include_usage": True}
        body.update(p.extra_body)
        return body

    @staticmethod
    def _raise_for_status(resp: httpx.Response, body_text: str) -> None:
        code = resp.status_code
        if code < 400:
            return
        detail = f"HTTP {code}: {body_text[:300]}"
        if code in (401, 403):
            raise LLMConfigError(f"credentials rejected ({detail})")
        if code == 404:
            raise LLMConfigError(f"model or endpoint not found ({detail})")
        if code == 429:
            raise LLMRateLimited(detail)
        if code in (502, 503, 504):
            raise LLMUnavailable(detail)
        if code < 500:
            raise LLMRejected(detail)
        raise LLMBadResponse(detail)

    @staticmethod
    def _usage(data: dict[str, Any] | None) -> Usage | None:
        if not data:
            return None
        return Usage(int(data.get("prompt_tokens") or 0), int(data.get("completion_tokens") or 0))

    # ------------------------------------------------------------------ calls
    async def complete(self, req: ProviderRequest) -> ProviderResponse:
        try:
            resp = await self._http.post("/chat/completions", json=self.build_body(req, stream=False))
        except httpx.TimeoutException as e:
            raise LLMTimeout(str(e) or "timeout") from None
        except httpx.TransportError as e:
            raise LLMUnavailable(str(e) or type(e).__name__) from None
        self._raise_for_status(resp, resp.text)
        try:
            data = resp.json()
            choice = data["choices"][0]
        except (ValueError, KeyError, IndexError) as e:
            raise LLMBadResponse(f"malformed response: {e}") from None
        text = (choice.get("message") or {}).get("content") or ""  # reasoning_content ignored on purpose
        finish = _FINISH.get(choice.get("finish_reason") or "stop", choice.get("finish_reason") or "stop")
        return ProviderResponse(text, finish, self._usage(data.get("usage")), data.get("id"))

    async def stream(self, req: ProviderRequest) -> AsyncIterator[StreamEvent]:
        p = self.profile
        parts: list[str] = []
        finish, usage, rid = "stop", None, None
        timeout = httpx.Timeout(p.timeout_s, read=p.stall_timeout_s)
        try:
            async with self._http.stream("POST", "/chat/completions", json=self.build_body(req, stream=True),
                                         timeout=timeout) as resp:
                if resp.status_code >= 400:
                    await resp.aread()
                    self._raise_for_status(resp, resp.text)
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    rid = chunk.get("id") or rid
                    usage = self._usage(chunk.get("usage")) or usage
                    for choice in chunk.get("choices") or []:
                        delta = (choice.get("delta") or {}).get("content")
                        if delta:
                            parts.append(delta)
                            yield delta
                        if choice.get("finish_reason"):
                            finish = _FINISH.get(choice["finish_reason"], choice["finish_reason"])
        except httpx.TimeoutException:
            raise LLMTimeout(f"no output from {p.id} for {p.stall_timeout_s:g}s") from None
        except httpx.TransportError as e:
            raise LLMUnavailable(str(e) or type(e).__name__) from None
        yield ProviderResponse("".join(parts), finish, usage, rid)

    # ------------------------------------------------------------------ health
    async def list_models(self) -> list[str]:
        try:
            resp = await self._http.get("/models", timeout=5.0)
        except httpx.TransportError as e:
            raise LLMUnavailable(str(e) or type(e).__name__) from None
        self._raise_for_status(resp, resp.text)
        return [m.get("id", "") for m in resp.json().get("data", [])]

    async def probe(self, timeout_s: float) -> str | None:
        p = self.profile
        body = {"model": p.model, "messages": [{"role": "user", "content": "OK"}], p.max_tokens_param: 1,
                "stream": False, **p.extra_body}
        try:
            resp = await self._http.post("/chat/completions", json=body, timeout=timeout_s)
        except httpx.TimeoutException:
            return f"model did not answer a 1-token request within {timeout_s:g}s"
        except httpx.TransportError as e:
            return f"unreachable: {e or type(e).__name__}"
        return None if resp.status_code < 400 else f"HTTP {resp.status_code}: {resp.text[:200]}"
