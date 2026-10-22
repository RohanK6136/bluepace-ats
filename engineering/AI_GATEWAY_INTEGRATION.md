# AI Gateway integration and rollout guide

## Current implementation boundary
The gateway currently accepts an injected provider adapter and usage sink. It is intentionally provider-neutral and is not yet wired to production routes. This avoids assuming the installed provider SDK, database library, current schema, or environment configuration.

## Adapter contract
Implement an adapter callable with the following contract:

- Input: a validated `ModelRoute` selected server-side.
- Output: `(validated_result, UsageInput)`, where token counts come from the provider response usage fields.
- Apply the route timeout using the SDK's supported timeout option.
- Validate provider output against the ATS feature's expected schema before using it.
- Do not expose API credentials to browser code or Streamlit UI code.
- Do not log prompts, resume text, raw provider responses, or credentials.

Example wiring (illustrative; adapt names and SDK to the existing application):

```python
from engineering.ai_gateway.gateway import execute_task
from engineering.ai_gateway.model_router import ModelRoute, UsageInput

routes = {
    "jd_generation": ModelRoute(
        provider="approved-provider",
        model="model-configured-by-environment",
        max_output_tokens=1200,
        timeout_seconds=30,
    )
}

def invoke_provider(route):
    # Call the existing provider SDK here, with route.timeout_seconds.
    # Extract result.usage.prompt_tokens / completion_tokens (or provider equivalents).
    # Return the validated result and UsageInput(actual_input, actual_output, cached_input).
    raise NotImplementedError("Connect to the repository's configured provider SDK")

def persist_usage(event):
    # Insert only normalized event fields into ai_usage_events.
    # Use a parameterized query and the existing database connection pool.
    # Enforce tenant authorization before assigning tenant_id / actor_id.
    raise NotImplementedError("Connect to the application's persistent database")

# result = execute_task(
#     task="jd_generation",
#     route=routes["jd_generation"],
#     invoke=invoke_provider,
#     usage_sink=persist_usage,
# )
```

The placeholders are intentional: do not ship them as live application wiring. First confirm the repository's actual provider SDK, database library, dependency injection, and migration conventions.

## Persistent usage storage
See `usage_schema.sql` for a PostgreSQL table that stores operational metadata only. Review it against the existing migration framework before applying it. Do not run ad hoc DDL directly against production.

Recommended controls:
- Restrict table access to the backend service role and approved analytics roles.
- Set retention based on business need and privacy requirements.
- Avoid storing email, candidate names, prompts, resumes, and provider payloads in telemetry.
- If tenant identifiers are stored, apply the application's tenant-level access controls to analytics queries.
- Keep pricing rates versioned and treat cost as an estimate until reconciled with provider billing.

## Model routing policy
Configure task routes on the server. Do not accept arbitrary model names from user requests. A model route should be approved against a representative evaluation set and checked for provider availability, context window, data handling terms, output schema support, latency, and cost.

Suggested initial tasks:
- Resume extraction: parser/OCR first; LLM only for difficult structure.
- Job-description drafting: generation model with schema validation.
- Classification: deterministic rules or small model where quality is adequate.
- Candidate retrieval: embeddings plus keyword search.
- Candidate reranking: evaluated reranker or LLM.
- Recruiter Q&A: retrieval-grounded model with citations and abstention.

## Rollout checklist
1. Identify current provider calls and actual dependencies in backend and Streamlit app.
2. Add provider adapter tests with mocked usage responses.
3. Add migration using the existing migration system; test against disposable PostgreSQL.
4. Wire the gateway into one low-risk feature first.
5. Verify request/response schemas and that no candidate content is written to telemetry.
6. Compare provider-reported token counts with stored records and provider usage reports.
7. Add per-tenant limits, budget alerts, timeouts, and bounded retries.
8. Run full CI and security tests; review the PR.
9. Deploy to staging, verify health and one controlled test request, then use the established release process.
10. Expand feature-by-feature only after monitoring confirms expected quality, cost, and latency.

## Acceptance criteria
- No API key appears in frontend bundles, logs, or telemetry.
- Missing task routes fail closed.
- Provider-reported token usage is captured when available.
- Unknown pricing remains null instead of fabricating cost.
- Database writes are parameterized, access-controlled, and tested.
- Provider failures do not silently produce fabricated AI output.
- Existing ATS behavior remains unchanged until a route is explicitly migrated and validated.
