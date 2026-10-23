"""Provider-neutral execution wrapper for the AI gateway.

The application supplies an invoke callable for its existing provider SDK and a
usage_sink that persists normalized events. This keeps provider SDKs and storage
dependencies out of the core module. The callable must return (result, UsageInput).
Do not log result or request payloads here.
"""
from __future__ import annotations

from time import monotonic
from typing import Callable, Optional, TypeVar

from .model_router import (
    ModelRoute,
    RateCard,
    UsageEvent,
    UsageInput,
    build_usage_event,
)

T = TypeVar("T")


class AIInvocationError(RuntimeError):
    """Provider invocation failed; the original exception is chained, not logged."""


def execute_task(
    *,
    task: str,
    route: ModelRoute,
    invoke: Callable[[ModelRoute], tuple[T, UsageInput]],
    usage_sink: Callable[[UsageEvent], None],
    rate_card: Optional[RateCard] = None,
) -> T:
    """Execute a provider call and emit sanitized usage metadata.

    The invoke callable must implement a provider-specific timeout using
    route.timeout_seconds. Usage is provider-reported. On invocation failure,
    an error event with zero usage is emitted because some providers do not expose
    token counts on failed responses.
    """
    started = monotonic()
    try:
        result, usage = invoke(route)
    except TimeoutError as exc:
        event = build_usage_event(
            task=task,
            route=route,
            usage=UsageInput(0, 0),
            started_at=started,
            status="timeout",
            rate_card=rate_card,
        )
        usage_sink(event)
        raise AIInvocationError(f"AI task '{task}' timed out") from exc
    except Exception as exc:
        event = build_usage_event(
            task=task,
            route=route,
            usage=UsageInput(0, 0),
            started_at=started,
            status="error",
            rate_card=rate_card,
        )
        usage_sink(event)
        raise AIInvocationError(f"AI task '{task}' failed") from exc

    if not isinstance(usage, UsageInput):
        event = build_usage_event(
            task=task,
            route=route,
            usage=UsageInput(0, 0),
            started_at=started,
            status="error",
            rate_card=rate_card,
        )
        usage_sink(event)
        raise TypeError("Provider adapter must return UsageInput as its usage result")

    event = build_usage_event(
        task=task,
        route=route,
        usage=usage,
        started_at=started,
        status="success",
        rate_card=rate_card,
    )
    usage_sink(event)
    return result
