# BluePace ATS — AI Engineering Plan

Updated: 2026-10-07

## Goal

Build an AI-assisted ATS where deterministic code controls data integrity and application state, while models are selected by task rather than used as a universal decision engine.

The product goal is useful recruiter outcomes with low UI noise:
- find the right candidates
- understand why they match
- identify missing or unverified evidence
- take the next recruiting action

## Architecture

```
Resume/JD document
  -> deterministic extraction
  -> normalized structured evidence
  -> application-side validation
  -> task-specific AI only where language/reasoning is needed
  -> schema validation
  -> evidence-backed result
  -> recruiter decision
```

Retrieval tasks use embeddings and vector search. Ranking uses deterministic rules plus semantic similarity; an optional second-stage reranker can refine the top candidate set. The reranker is fail-open: if disabled, unconfigured, rate-limited, or unavailable, the deterministic result remains authoritative. Generation and reasoning are separate from consequential ATS actions.

## Model selection by use case

| Use case | System | Default policy |
|---|---|---|
| PDF/DOCX extraction | PyPDF/python-docx or equivalent parser | Deterministic |
| Resume normalization | Small/fast instruct model | Structured output |
| JD requirement extraction | Deterministic skill/requirement parser; model only when needed | Structured output |
| Candidate ↔ JD matching | Deterministic rules + embeddings | Explainable score |
| Semantic candidate search | Embedding model + pgvector/vector DB | Retrieval problem |
| Ranking refinement | Reranker, if available | Second-stage relevance |
| Match explanation | Fast capable generation model | Evidence only |
| Recruiter assistant | Fast capable generation model + bounded ATS evidence | Grounded answer |
| Complex analysis | Strong reasoning model | Explicit escalation only |
| Scanned/visual resume | Multimodal/OCR path | Fallback when text extraction is insufficient |
| External action | Tool-calling model + explicit app action + approval | Never autonomous hiring |
| Hiring decision | Recruiter + ATS evidence | Human controlled |

## Centralized model routing

Model configuration is centralized in `backend/app/services/model_router.py`.

Supported environment variables:
- `OPENROUTER_MODEL`
- `OPENROUTER_ASSISTANT_MODEL`
- `OPENROUTER_VALIDATION_MODEL`
- `OPENROUTER_DEEP_REASONING_MODEL`
- `MATCHING_CHAT_MODEL`
- `MATCHING_EMBEDDING_MODEL`

Routing rule:
1. If code can solve it, use code.
2. If it is search/retrieval, use embeddings + retrieval.
3. If it is predictable transformation, use a small/fast model with strict output.
4. If it is routine open-ended generation, use the fast capable model.
5. Escalate to deep reasoning only for genuinely ambiguous or multi-step analysis.
6. If the result changes candidate state or sends an external message, require explicit application controls and human approval.

## Prompt engineering standard

Every production AI task should define:
1. Role
2. One specific task
3. Evidence boundary
4. Constraints
5. Output schema
6. Application-side validation

Resume, JD, comments, interview feedback and other retrieved text are untrusted data, not instructions.

Important rules:
- Missing evidence means `not evidenced`, not proof of absence.
- Never invent candidate facts.
- Do not ask a model to decide hire/reject.
- Use concise evidence statements instead of exposing hidden reasoning.
- Use low temperature for extraction/classification.
- Keep generation separate from consequential actions.
- Version prompts so regressions can be measured.

## Evaluation

Maintain a fixed evaluation set with:
- clean and sparse resumes
- contradictory dates
- unusual job titles
- synonym-heavy skills
- missing fields
- long resumes
- multilingual documents
- prompt-injection text inside resumes/JDs
- ambiguous experience

Track:
- extraction accuracy
- required-skill precision/recall
- JSON/schema validity
- groundedness
- match-score calibration
- retrieval relevance
- latency
- token/cost usage
- fallback rate

Do not change the default model or prompt only because a few manual examples look better; compare against the fixed evaluation set.

## UX direction

Primary recruiter screen should answer three questions:
1. Who is best?
2. Why?
3. What should I do next?

Keep visible:
- candidate/search
- job requirements summary
- match score
- matched skills
- gaps
- evidence/explanation
- next action

Keep secondary/collapsed:
- advanced filters
- full JD intelligence
- score formula
- embedding/retrieval implementation details
- raw JSON
- raw extracted text
- debugging telemetry

Technical diagnostics belong in developer/admin views, not the main recruiter workflow.

## Evaluation and reranking

The repository now includes an offline benchmark under `backend/evaluation/golden_matches.json` and metrics in `backend/app/evaluation/matching_eval.py`. The benchmark tracks precision@k, recall@k, reciprocal rank, and Brier score. It is intentionally model-free so prompt/model/provider changes can be compared against the same labels.

The repository also includes an optional Cohere second-stage reranker in `backend/app/services/reranker.py`. Enable only with `RERANK_ENABLED=true` and `COHERE_API_KEY`; the model defaults to `rerank-v4.0-fast` and can be changed with `RERANK_MODEL`. The first-pass ATS score is kept dominant (75%) so external relevance is a refinement, not a replacement for explicit ATS evidence.

## Immediate next engineering work

1. Add a compact evidence-backed match explanation contract to the API.
2. Add a fixed match/evidence evaluation fixture and regression test.
3. Add reranking as an optional second retrieval stage.
4. Add model/version and latency/cost telemetry without exposing it in the primary UI.
5. Add a small multimodal/OCR fallback path for scanned resumes.
6. Review every visible dashboard section against the rule: useful to a recruiter now, or move it to More/details.

## Safety and governance

BluePace is decision support. It must not silently move application stages, reject candidates, or make hiring decisions from model output. Consequential actions remain explicit application actions with recruiter control.

