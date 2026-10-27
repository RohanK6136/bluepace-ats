"""Anthropic Messages API provider (official `anthropic` SDK, async).

Structured output uses `output_config.format` (json_schema) rather than forced tool use, which current models
reject. Keywords the API does not support (string/array/number constraints) are removed from the schema sent
and still validated client-side by the gateway. Retries are owned by the gateway, so the SDK's are disabled.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from typing import Any

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

FALLBACK_BETA = "server-side-fallback-2026-07-01"
_FINISH = {"end_turn": "stop", "stop_sequence": "stop", "max_tokens": "length", "refusal": "refusal"}


class AnthropicProvider:
    def __init__(self, profile: ModelProfile, json_instruction: str, client: Any = None):
        import anthropic  # optional dependency; the registry disables the profile when it is missing

        self._sdk = anthropic
        self.profile = profile
        self.json_instruction = json_instruction
        api_key = os.environ.get(profile.api_key_env) if profile.api_key_env else None
        self._client = client or anthropic.AsyncAnthropic(
            api_key=api_key, base_url=profile.base_url or None, max_retries=0,
            timeout=anthropic.Timeout(profile.timeout_s, read=profile.stall_timeout_s),
        )

    async def aclose(self) -> None:
        close = getattr(self._client, "close", None)
        if close is not None:
            await close()

    # ------------------------------------------------------------------ request
    def build_params(self, req: ProviderRequest) -> dict[str, Any]:
        p = self.profile
        schema = sanitize_schema(req.schema, set(p.schema_drop_keywords))
        user = req.user
        output_config: dict[str, Any] = {}
        if p.structured_output == "json_schema":
            output_config["format"] = {"type": "json_schema", "schema": schema}
        else:
            user = f"{user}\n\n{self.json_instruction}\n{json.dumps(schema)}"
        if p.effort:
            output_config["effort"] = p.effort
        params: dict[str, Any] = {
            "model": p.model,
            "max_tokens": max(req.max_tokens, p.max_tokens_floor),
            "system": req.system,
            "messages": [{"role": "user", "content": user}],
        }
        if output_config:
            params["output_config"] = output_config
        if p.temperature is not None:
            params["temperature"] = p.temperature
        if p.server_fallbacks:
            params["betas"] = [FALLBACK_BETA]
            params["fallbacks"] = "default"
        if p.extra_body:
            params["extra_body"] = p.extra_body
        return params

    def _map_error(self, e: Exception) -> Exception:
        sdk = self._sdk
        if isinstance(e, sdk.APITimeoutError):  # subclass of APIConnectionError: check first
            return LLMTimeout(f"no output from {self.profile.id} within the timeout")
        if isinstance(e, sdk.APIConnectionError):
            return LLMUnavailable(str(e) or "connection error")
        if isinstance(e, (sdk.AuthenticationError, sdk.PermissionDeniedError)):
            return LLMConfigError(f"credentials rejected: {e}")
        if isinstance(e, sdk.NotFoundError):
            return LLMConfigError(f"model or endpoint not found: {e}")
        if isinstance(e, sdk.RateLimitError):
            return LLMRateLimited(str(e))
        if isinstance(e, sdk.APIStatusError):
            if e.status_code == 529:  # overloaded
                return LLMRateLimited(str(e))
            return LLMRejected(str(e)) if e.status_code < 500 else LLMBadResponse(str(e))
        return e

    @staticmethod
    def _response(message: Any) -> ProviderResponse:
        text = "".join(b.text for b in message.content if getattr(b, "type", "") == "text")
        u = message.usage
        prompt = (u.input_tokens or 0) + (getattr(u, "cache_read_input_tokens", 0) or 0) \
            + (getattr(u, "cache_creation_input_tokens", 0) or 0)
        finish = _FINISH.get(message.stop_reason or "end_turn", message.stop_reason or "stop")
        return ProviderResponse(text, finish, Usage(prompt, u.output_tokens or 0), getattr(message, "id", None))

    # ------------------------------------------------------------------ calls
    async def complete(self, req: ProviderRequest) -> ProviderResponse:
        try:
            message = await self._client.beta.messages.create(**self.build_params(req))
        except self._sdk.APIError as e:
            raise self._map_error(e) from None
        return self._response(message)

    async def stream(self, req: ProviderRequest) -> AsyncIterator[StreamEvent]:
        try:
            async with self._client.beta.messages.stream(**self.build_params(req)) as s:
                async for text in s.text_stream:
                    if text:
                        yield text
                message = await s.get_final_message()
        except self._sdk.APIError as e:
            raise self._map_error(e) from None
        yield self._response(message)

    # ------------------------------------------------------------------ health
    async def list_models(self) -> list[str]:
        try:
            page = await self._client.models.list()
        except self._sdk.APIError as e:
            raise self._map_error(e) from None
        return [m.id for m in page.data]

    async def probe(self, timeout_s: float) -> str | None:
        """Checks credentials and the model id without spending tokens."""
        try:
            await self._client.with_options(timeout=timeout_s).models.retrieve(self.profile.model)
        except self._sdk.APIError as e:
            return str(self._map_error(e))
        return None
