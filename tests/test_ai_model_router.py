"""Unit tests for the provider-neutral AI routing/usage module."""
import unittest
from decimal import Decimal
from time import monotonic

from engineering.ai_gateway.model_router import (
    MissingRouteError,
    ModelRoute,
    RateCard,
    UsageInput,
    build_usage_event,
    estimate_cost,
    select_route,
)


class ModelRouterTests(unittest.TestCase):
    def setUp(self):
        self.routes = {
            "jd_generation": ModelRoute("provider-a", "generation-small", 800, 20),
            "complex_qa": ModelRoute("provider-b", "reasoning-model", 2000, 45),
        }

    def test_selects_task_specific_model(self):
        self.assertEqual(select_route("jd_generation", self.routes).model, "generation-small")
        self.assertEqual(select_route("complex_qa", self.routes).provider, "provider-b")

    def test_missing_route_fails_closed(self):
        with self.assertRaises(MissingRouteError):
            select_route("unknown_task", self.routes)

    def test_rejects_invalid_limits(self):
        with self.assertRaises(ValueError):
            select_route("bad", {"bad": ModelRoute("p", "m", 0, 5)})

    def test_estimates_cost_from_versioned_rate_card(self):
        usage = UsageInput(input_tokens=2000, output_tokens=500, cached_input_tokens=200)
        rates = RateCard(Decimal("2.00"), Decimal("8.00"), "test-v1")
        self.assertEqual(estimate_cost(usage, rates), Decimal("0.00800000"))

    def test_rejects_negative_usage(self):
        with self.assertRaises(ValueError):
            estimate_cost(UsageInput(-1, 2), RateCard(Decimal("1"), Decimal("1")))

    def test_cached_tokens_must_be_subset_of_input(self):
        with self.assertRaises(ValueError):
            estimate_cost(UsageInput(5, 2, 6), RateCard(Decimal("1"), Decimal("1")))

    def test_event_contains_operational_metadata_not_prompt_text(self):
        route = select_route("jd_generation", self.routes)
        event = build_usage_event(
            task="jd_generation",
            route=route,
            usage=UsageInput(100, 25),
            started_at=monotonic(),
            status="success",
            rate_card=RateCard(Decimal("1"), Decimal("2"), "test-v1"),
            request_id="test-request-1",
        )
        self.assertEqual(event.request_id, "test-request-1")
        self.assertEqual(event.status, "success")
        self.assertEqual(event.pricing_version, "test-v1")
        self.assertEqual(event.estimated_cost_usd, Decimal("0.00015000"))
        self.assertFalse(hasattr(event, "prompt"))
        self.assertFalse(hasattr(event, "resume_text"))

    def test_unknown_pricing_is_not_fabricated(self):
        event = build_usage_event(
            task="complex_qa",
            route=self.routes["complex_qa"],
            usage=UsageInput(0, 0),
            started_at=monotonic(),
            status="error",
        )
        self.assertIsNone(event.estimated_cost_usd)
        self.assertIsNone(event.pricing_version)


if __name__ == "__main__":
    unittest.main()
