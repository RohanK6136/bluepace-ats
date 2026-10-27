"""Provider-neutral types for the LLM gateway."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ProviderKind = Literal["openai_compatible", "anthropic"]


class Pricing(BaseModel):
    """USD per million tokens. Zero for local models."""

    model_config = ConfigDict(extra="forbid")
    input_per_mtok: float = 0.0
    output_per_mtok: float = 0.0

    def cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        return round(prompt_tokens * self.input_per_mtok / 1e6 + completion_tokens * self.output_per_mtok / 1e6, 8)


class ModelProfile(BaseModel):
    """One named, configured model endpoint. Loaded from config/models.yaml; never holds a secret value."""

    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    provider: ProviderKind
    model: str = ""
    base_url: str | None = None
    api_key_env: str | None = Field(default=None, description="Name of the env var holding the API key")
    local: bool = False
    description: str = ""

    # request shaping
    structured_output: Literal["json_schema", "prompt_only"] = "json_schema"
    # JSON-schema keywords the endpoint rejects; the gateway still validates them client-side
    schema_drop_keywords: list[str] = Field(default_factory=list)
    temperature: float | None = 0.0
    top_p: float | None = 1.0
    seed: int | None = 42
    max_tokens_param: Literal["max_tokens", "max_completion_tokens"] = "max_tokens"
    max_tokens_floor: int = 0
    extra_body: dict[str, Any] = Field(default_factory=dict)
    effort: Literal["low", "medium", "high", "xhigh", "max"] | None = None  # anthropic
    server_fallbacks: bool = False  # anthropic: fallbacks="default" on refusals

    # limits
    context_tokens: int = 8192
    concurrency: int = 1
    timeout_s: float = 120.0
    stall_timeout_s: float = 20.0

    pricing: Pricing = Field(default_factory=Pricing)
    fingerprint: str = ""

    @property
    def fingerprint_or_unpinned(self) -> str:
        return self.fingerprint or "unpinned"


class ModelInfo(BaseModel):
    """Which model served a run — recorded on every run row."""

    profile: str | None = None
    provider: str | None = None
    model: str | None = None
    label: str | None = None
    fingerprint: str | None = None


class ProfileStatus(BaseModel):
    """What the UI and /v1/models show: the profile minus anything secret, plus whether it is usable."""

    id: str
    label: str
    provider: ProviderKind
    model: str
    local: bool
    description: str
    enabled: bool
    disabled_reason: str | None = None
    is_default: bool = False
    pricing: Pricing
    context_tokens: int


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated: bool = False

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @classmethod
    def estimate(cls, chars_per_token: float, prompt_text: str, completion_text: str) -> Usage:
        return cls(math.ceil(len(prompt_text) / chars_per_token), math.ceil(len(completion_text) / chars_per_token),
                   estimated=True)


@dataclass
class ProviderRequest:
    step: str
    system: str
    user: str
    schema: dict[str, Any]
    max_tokens: int


@dataclass
class ProviderResponse:
    text: str
    finish_reason: str  # "stop" | "length" | "refusal" | provider-specific
    usage: Usage | None
    provider_request_id: str | None = None


@dataclass
class LLMResult:
    parsed: dict[str, Any]
    raw: str
    finish_reason: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    cache_hit: bool
    call_id: str
    cost_usd: float = 0.0
    usage_estimated: bool = False


@dataclass
class CallContext:
    """Per-run bookkeeping shared by every LLM call of one feature run."""

    request_id: str
    use_cache: bool = True
    profile_id: str | None = None
    feature: str = "unknown"
    records: list[dict[str, Any]] = field(default_factory=list)
    repairs: int = 0

    # aggregates (filled by the gateway)
    @property
    def prompt_tokens(self) -> int:
        return sum(r.get("prompt_tokens") or 0 for r in self.records)

    @property
    def completion_tokens(self) -> int:
        return sum(r.get("completion_tokens") or 0 for r in self.records)

    @property
    def cost_usd(self) -> float:
        return round(sum(r.get("cost_usd") or 0.0 for r in self.records), 8)

    @property
    def cache_hits(self) -> int:
        return sum(1 for r in self.records if r.get("cache_hit"))
