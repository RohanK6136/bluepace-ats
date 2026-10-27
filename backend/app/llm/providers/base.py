"""Provider interface and the helpers every provider shares.

A provider only translates wire formats: it turns a ProviderRequest into one HTTP/SDK call and maps the
answer (text, finish reason, token usage) and its failures onto the provider-neutral types and errors.
Caching, retries, token budgets, cost, audit records and metrics live in the gateway, once, for every provider.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from typing import Any, Protocol

from app.core.errors import LLMInvalidJSON
from app.llm.types import ModelProfile, ProviderRequest, ProviderResponse

_THINK_RE = re.compile(r"<think>.*?</think>", re.S | re.I)
_OPEN_THINK_RE = re.compile(r"^\s*<think>.*", re.S | re.I)

# A stream yields text deltas and, last, exactly one ProviderResponse with finish reason and usage.
StreamEvent = str | ProviderResponse


class Provider(Protocol):
    profile: ModelProfile

    async def complete(self, req: ProviderRequest) -> ProviderResponse: ...

    def stream(self, req: ProviderRequest) -> AsyncIterator[StreamEvent]: ...

    async def list_models(self) -> list[str]: ...

    async def probe(self, timeout_s: float) -> str | None:
        """Generate one token; None = healthy, else a human-readable reason."""
        ...

    async def aclose(self) -> None: ...


def strip_think(content: str) -> str:
    """Remove reasoning blocks some local models put in the content channel."""
    content = _THINK_RE.sub("", content)
    if _OPEN_THINK_RE.match(content) and "</think>" not in content:
        brace = content.find("{")
        content = content[brace:] if brace >= 0 else ""
    return content.strip()


def parse_json_tolerant(content: str) -> dict[str, Any]:
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        start, end = content.find("{"), content.rfind("}")
        if start < 0 or end <= start:
            raise LLMInvalidJSON("no JSON object in content") from None
        try:
            data = json.loads(content[start:end + 1])
        except json.JSONDecodeError as e:
            raise LLMInvalidJSON(f"unparseable JSON: {e}") from None
    if not isinstance(data, dict):
        raise LLMInvalidJSON("top-level JSON is not an object")
    return data


def sanitize_schema(schema: Any, drop: set[str]) -> Any:
    """Copy of `schema` without keywords the endpoint rejects. The gateway still validates the full schema."""
    if not drop:
        return schema
    if isinstance(schema, dict):
        return {k: sanitize_schema(v, drop) for k, v in schema.items() if k not in drop}
    if isinstance(schema, list):
        return [sanitize_schema(v, drop) for v in schema]
    return schema
