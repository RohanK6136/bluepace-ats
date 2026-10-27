"""Prometheus metrics, exposed at GET /metrics.

Labels are low-cardinality on purpose: feature, operation, status, profile, model, step, outcome. Never put
request ids, user text or error messages in a label.
"""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Histogram, generate_latest

REGISTRY = CollectorRegistry(auto_describe=True)

HTTP_REQUESTS = Counter("http_requests_total", "HTTP requests", ["method", "route", "status"], registry=REGISTRY)
HTTP_LATENCY = Histogram("http_request_duration_seconds", "HTTP request latency", ["method", "route"],
                         buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 20, 40, 80), registry=REGISTRY)

RUNS = Counter("feature_runs_total", "Feature runs by outcome", ["feature", "operation", "outcome"],
               registry=REGISTRY)
RUN_LATENCY = Histogram("feature_run_duration_seconds", "End-to-end feature run latency",
                        ["feature", "operation"], buckets=(0.1, 0.5, 1, 2, 3, 5, 8, 13, 20, 30, 60, 120),
                        registry=REGISTRY)

LLM_CALLS = Counter("llm_calls_total", "LLM calls by outcome", ["profile", "model", "step", "outcome"],
                    registry=REGISTRY)
LLM_TOKENS = Counter("llm_tokens_total", "LLM tokens", ["profile", "model", "kind"], registry=REGISTRY)
LLM_COST = Counter("llm_cost_usd_total", "Estimated LLM spend in USD", ["profile", "model"], registry=REGISTRY)
LLM_LATENCY = Histogram("llm_call_duration_seconds", "LLM call latency (cache hits excluded)", ["profile", "step"],
                        buckets=(0.25, 0.5, 1, 2, 3, 5, 8, 13, 20, 30, 60, 120), registry=REGISTRY)


def render() -> tuple[bytes, str]:
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
