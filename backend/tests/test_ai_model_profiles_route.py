from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.deps import platform
from app.llm.types import Pricing, ProfileStatus
from app.main import app


def test_ai_model_profile_routes_are_registered() -> None:
    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/v1/models" in paths
    assert "/v1/jd/models" in paths


def test_platform_dependency_returns_service_unavailable_when_not_initialized() -> None:
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(platform=None)))

    with pytest.raises(HTTPException) as raised:
        platform(request)

    assert raised.value.status_code == 503
    assert "AI feature platform is unavailable" in raised.value.detail


def test_models_endpoint_returns_safe_registry_statuses() -> None:
    registry = SimpleNamespace(
        statuses=lambda: [
            ProfileStatus(
                id="openrouter",
                label="OpenRouter (hosted)",
                provider="openai_compatible",
                model="google/gemini-2.5-flash",
                local=False,
                description="Uses the configured hosted model.",
                enabled=False,
                disabled_reason="set OPENROUTER_API_KEY to enable",
                is_default=True,
                pricing=Pricing(),
                context_tokens=128000,
            )
        ]
    )
    fake_platform = SimpleNamespace(registry=registry)
    endpoint = next(route.endpoint for route in app.routes if getattr(route, "path", None) == "/v1/models")

    payload = endpoint(fake_platform)

    assert payload[0]["id"] == "openrouter"
    assert payload[0]["is_default"] is True
    assert payload[0]["enabled"] is False
    assert payload[0]["disabled_reason"] == "set OPENROUTER_API_KEY to enable"
    # The response contains configuration status, never credential values.
    assert "OPENROUTER_API_KEY" not in payload[0].get("api_key", "")
