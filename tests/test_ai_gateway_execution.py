import unittest
from decimal import Decimal
from time import monotonic

from engineering.ai_gateway.gateway import AIInvocationError, execute_task
from engineering.ai_gateway.model_router import ModelRoute, RateCard, UsageInput


class GatewayExecutionTests(unittest.TestCase):
    def setUp(self):
        self.route = ModelRoute("mock-provider", "mock-model", 100, 2)
        self.rates = RateCard(Decimal("1"), Decimal("2"), "test-v1")

    def test_success_returns_result_and_emits_usage(self):
        events = []
        result = execute_task(
            task="jd_generation",
            route=self.route,
            invoke=lambda route: ("generated text", UsageInput(100, 25)),
            usage_sink=events.append,
            rate_card=self.rates,
        )
        self.assertEqual(result, "generated text")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].status, "success")
        self.assertEqual(events[0].estimated_cost_usd, Decimal("0.00015000"))

    def test_timeout_emits_event_and_raises_safe_error(self):
        events = []

        def invoke(route):
            raise TimeoutError("sensitive provider details")

        with self.assertRaises(AIInvocationError) as raised:
            execute_task(
                task="resume_summary",
                route=self.route,
                invoke=invoke,
                usage_sink=events.append,
            )
        self.assertIn("timed out", str(raised.exception))
        self.assertEqual(events[0].status, "timeout")
        self.assertFalse(hasattr(events[0], "prompt"))

    def test_provider_error_emits_error_event(self):
        events = []
        with self.assertRaises(AIInvocationError):
            execute_task(
                task="resume_summary",
                route=self.route,
                invoke=lambda route: (_ for _ in ()).throw(ValueError("secret")),
                usage_sink=events.append,
            )
        self.assertEqual(events[0].status, "error")

    def test_bad_usage_contract_is_rejected(self):
        events = []
        with self.assertRaises(TypeError):
            execute_task(
                task="jd_generation",
                route=self.route,
                invoke=lambda route: ("result", {"input_tokens": 2}),
                usage_sink=events.append,
            )
        self.assertEqual(events[0].status, "error")


if __name__ == "__main__":
    unittest.main()
