"""Provider-neutral AI model routing and usage accounting.

This module intentionally does not call a provider. Integrate provider SDKs through
adapters that return UsageInput and record the normalized UsageEvent after each call.
Never pass prompts, resumes, API keys, or raw provider responses to the recorder.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from time import monotonic
from typing import Mapping, Optional
from uuid import uuid4


@dataclass(frozen=True)
class ModelRoute:
    provider: str
    model: str
    max_output_tokens: int = 1024
    timeout_seconds: float = 30.0


@dataclass(frozen=True)
class RateCard:
    """USD per million tokens; version rates when provider pricing changes."""
    input_usd_per_million: Decimal
    output_usd_per_million: Decimal
    version: str = "unversioned"


@dataclass(frozen=True)
class UsageInput:
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int = 0


@dataclass(frozen=True)
class UsageEvent:
    request_id: str
    task: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int
    latency_ms: int
    status: str
    estimated_cost_usd: Optional[Decimal]
    pricing_version: Optional[str]


class MissingRouteError(ValueError):
    """Raised when a task has no explicitly configured route."""


def select_route(task: str, routes: Mapping[str, ModelRoute]) -> ModelRoute:
    """Select an explicitly configured route; never silently pick a default model."""
    route = routes.get(task)
    if route is None:
        raise MissingRouteError(f"No AI model route configured for task: {task}")
    if route.max_output_tokens <= 0 or route.timeout_seconds <= 0:
        raise ValueError("Output-token limit and timeout must be positive")
    return route


def estimate_cost(usage: UsageInput, rate: RateCard) -> Decimal:
    """Estimate token cost from a versioned rate card.

    Cached input tokens are a subset of input tokens. This simple rate card charges
    all input at the input rate; providers with separate cached-token pricing should
    use an adapter-specific calculator instead.
    """
    for name, value in (
        ("input_tokens", usage.input_tokens),
        ("output_tokens", usage.output_tokens),
        ("cached_input_tokens", usage.cached_input_tokens),
    ):
        if value < 0:
            raise ValueError(f"{name} cannot be negative")
    if usage.cached_input_tokens > usage.input_tokens:
        raise ValueError("cached_input_tokens cannot exceed input_tokens")
    million = Decimal(1_000_000)
    total = (
        Decimal(usage.input_tokens) * rate.input_usd_per_million
        + Decimal(usage.output_tokens) * rate.output_usd_per_million
    ) / million
    return total.quantize(Decimal("0.00000001"))


def build_usage_event(
    *,
    task: str,
    route: ModelRoute,
    usage: UsageInput,
    started_at: float,
    status: str,
    rate_card: Optional[RateCard] = None,
    request_id: Optional[str] = None,
) -> UsageEvent:
    """Build a PII-free normalized event using a monotonic start time."""
    if status not in {"success", "error", "timeout", "rate_limited"}:
        raise ValueError("Unsupported status")
    latency_ms = max(0, int((monotonic() - started_at) * 1000))
    cost = estimate_cost(usage, rate_card) if rate_card is not None else None
    return UsageEvent(
        request_id=request_id or str(uuid4()),
        task=task,
        provider=route.provider,
        model=route.model,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cached_input_tokens=usage.cached_input_tokens,
        latency_ms=latency_ms,
        status=status,
        estimated_cost_usd=cost,
        pricing_version=rate_card.version if rate_card is not None else None,
    )
