# BluePace ATS — AI Integration and Observability Implementation

## Objective
Introduce a provider-neutral AI gateway so ATS features can choose a model by task, record usage, estimate cost from configured rates, and expose operational metrics without logging candidate PII or secrets.

## Scope for this iteration
- Centralized task-to-model routing with environment-driven configuration.
- Normalized request/response contracts for provider adapters.
- Usage events for input/output tokens, latency, outcome, and estimated cost.
- Safe-by-default observability: never log prompts, resume text, API keys, or raw provider responses.
- Unit tests for routing, usage calculation, and redaction boundaries.
- No production deployment or live provider claim until CI and deployed health checks are actually verified.

## Suggested task routing
| ATS task | Initial route | Fallback / alternative |
|---|---|---|
| Resume text extraction | PDF/DOCX parser or OCR pipeline | Alternate parser; LLM only for extraction from difficult layouts |
| Job-description drafting | General-purpose generation model | Lower-cost generation model if quality tests pass |
| Resume classification | Small/fast model or deterministic classifier | General-purpose model |
| Candidate-job retrieval | Embeddings model + vector/keyword search | PostgreSQL full-text search |
| Candidate reranking | Dedicated reranker or evaluated LLM | Deterministic scoring with explainable features |
| Complex recruiter Q&A | Strong model with retrieval (RAG) | Curated knowledge search and explicit abstention |

Do not use model names or prices as assumptions: configure them from current provider documentation and validate quality, privacy terms, latency, and price before enabling.

## Architecture
1. ATS feature calls the internal AI gateway with a task identifier and structured input.
2. Router selects an allowed provider/model based on server-side configuration.
3. Provider adapter enforces timeout, output limits, and provider-specific schema.
4. Response validator checks required output schema before ATS workflows use it.
5. Usage recorder stores model, task, request ID, token counts, latency, status, and estimated cost.
6. Logs contain operational metadata only. Store prompts/resume content only when explicitly required, access-controlled, and governed by retention policy.

## Usage event contract
- request_id, timestamp, feature, provider, model
- input_tokens, output_tokens, cached_input_tokens (when supplied by provider)
- latency_ms, status, retry_count
- estimated_cost_usd and pricing_version

Cost formula should use provider-reported usage and a versioned rate card:
`cost = input_tokens / 1_000_000 * input_rate + output_tokens / 1_000_000 * output_rate`.
Do not estimate billed cost for providers whose pricing dimensions are not represented by this formula; mark it unknown until the rate card supports them.

## Security and reliability checklist
- Keep provider credentials on the backend; never expose them to browser or Streamlit client bundles.
- Use least-privilege credentials and secret-manager/environment configuration.
- Enforce authentication/authorization before invoking tools or retrieving candidate records.
- Set request timeouts, output token limits, bounded retries, and per-tenant budgets.
- Treat resume text as untrusted input; defend against prompt injection and never let model text directly authorize actions.
- Validate structured output; use idempotency for retried writes.
- Add a human review step for consequential hiring decisions.
- Do not send sensitive candidate data to a provider without approved data-processing and retention settings.

## Verification plan
1. Run unit tests for routing, missing configuration, token math, and failure cases.
2. Run existing repository test/lint/type-check commands once identified.
3. Test provider adapter with a mocked response and malformed output.
4. Verify usage records contain no prompts, resume text, or credentials.
5. Deploy only after review; then verify health endpoint, provider call, token event, and rollback path.

## Manager update
This iteration establishes a documented implementation baseline for model routing, cost observability, security, and verification. It does not claim live provider integration or production deployment until those checks are run and recorded.
