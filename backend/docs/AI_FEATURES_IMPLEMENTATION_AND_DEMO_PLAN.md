# BluePace ATS — AI features implementation and demo plan

Last reviewed: 2026-11-02
Repository: RohanK6136/bluepace-ats
Deployment target: Railway project `melodious-expression`, backend service `bluepace-ats`

## 1. Evidence-based baseline

| Area | Evidence found | Status |
|---|---|---|
| JD Standardization | Existing `backend/app/features/jd_standardizer/routes.py`; router is imported and mounted in `backend/app/main.py`; ZIP contains the JD Standardizer pipeline and fixtures. | Implemented in code; live end-to-end use not verified |
| AI Assistance / Applicant Match | Existing `backend/app/features/applicant_match/routes.py`; router is imported and mounted; ZIP documents rubric drafting, resume redaction, evidence extraction and deterministic weighted scoring. | Implemented in code; live end-to-end use not verified |
| AI-generated resume detection | No detector implementation or tests were found in the supplied experiment source. No matching detector implementation was found in the repository search during this review. | Not implemented / not verified |
| ATS integration | Existing FastAPI application mounts the JD and Match routers. The ATS remains the system of record. | Code integration exists; live workflow needs verification |
| Model integrations | `backend/config/models.yaml` defines OpenRouter profiles for Gemini, DeepSeek and other providers, plus OpenAI-compatible and Anthropic profiles. Railway backend service variable names did not include `OPENROUTER_API_KEY` at review time. | Provider profiles configured; hosted inference not verified and default OpenRouter credential appears absent |
| OpenAPI | Backend creates a FastAPI application with title `BluePace Tech ATS API` and version `0.4.0`; default FastAPI docs/schema routes have not been disabled in the app constructor. | Schema/docs generation is expected from code; public deployment access not verified |
| Current PR | PR #108 has three commits and three changed files: Applicant Match list-limit validation, regression tests, and integration notes. | Open; not merged or deployed |
| CI | Backend dependency installation and `pytest backend` passed. Frontend job failed at production dependency audit because `follow-redirects` 1.16.0–1.16.1 has a high-severity advisory; lint/build/feature tests were skipped after that gate. | Partial CI pass; release gate not green |
| Railway | Production backend service is configured to deploy from `main`, root directory `backend`. Latest deployment metadata reported FAILED; public HTTP checks could not be completed from this environment. | Deployment health not verified |

## 2. Delivery plan

### Phase A — Make the existing two AI features demonstrable

**JD Standardization**
1. Confirm API key/authentication and provider readiness.
2. Test pasted JD input and PDF/DOCX/TXT upload.
3. Generate structured JD fields and sections.
4. Verify source facts are preserved and unknown facts are flagged rather than invented.
5. Review and edit AI-drafted content before saving or publishing.
6. Test invalid files, empty input, conflicting facts and provider failure.

**Applicant Match / AI Assistance**
1. Select a saved standardized JD or paste raw JD text.
2. Draft a rubric and show it to the recruiter for editing/approval.
3. Upload PDF/DOCX/TXT resumes.
4. Confirm personal identifiers are redacted before model calls where specified by the feature.
5. Show each requirement's status and resume evidence, gaps, parse-quality warnings and score explanation.
6. Verify score calculations are deterministic and no endpoint automatically shortlists, rejects or hires.
7. Connect the reviewed assessment to the relevant ATS candidate/application without creating a parallel candidate record.

**Acceptance evidence:** request/response captures, test logs, a sample JD, two or three consented/synthetic resumes, and a recorded end-to-end demo.

### Phase B — AI-generated resume assessment

Do not ship a binary "AI-written / human-written" verdict. Passive text detectors can produce false positives and false negatives, especially on edited, hybrid, paraphrased, translated or short text.

Build a recruiter-facing **authorship risk indicators** feature:
1. Preserve source file and extracted text provenance; distinguish metadata evidence from stylistic signals.
2. Offer optional detector-provider integration only after security, privacy, cost and contractual review.
3. If a model/classifier is used, calibrate it on a representative, labelled resume dataset covering human-written, AI-generated and hybrid/edited examples, different languages, roles and resume lengths.
4. Return an interpretable status such as `insufficient_evidence`, `no_strong_signal`, or `review_recommended`, with confidence band, evidence, limitations and detector version.
5. Never use the signal as an automatic rejection, shortlist or ranking factor. A recruiter must review it independently.
6. Measure false-positive rate, false-negative rate, precision/recall and subgroup performance before release; define thresholds with HR/legal review.

**Acceptance evidence:** labelled evaluation dataset, reproducible evaluation report, calibration notes, false-positive analysis and reviewer-facing explanation.

### Phase C — Integrations

1. Verify one approved hosted LLM provider end-to-end (Gemini or DeepSeek through OpenRouter, or another approved provider); store credentials only in Railway secrets.
2. Add provider readiness and failure states in the admin experience; do not show a model as available if its credential or health check is missing.
3. Integrate JD Standardization and Applicant Match with existing ATS job, candidate and application records.
4. Define stable internal contracts, idempotency, timeouts, retries, rate limits, audit logs and data-retention rules.
5. Only add external HRIS/job-board/calendar integrations when the business owner confirms the required systems and access scopes.

### Phase D — OpenAPI

1. Verify the deployed `/openapi.json` and `/docs` endpoints.
2. Ensure JD, Match, resume-authorship assessment and integration endpoints have tags, summaries, request/response schemas and error models.
3. Document authentication, upload formats/limits, pagination, rate limits and examples.
4. Add contract tests that validate representative success and failure responses against the schema.
5. Publish a versioned API contract and a short integration guide for external developers.

## 3. Demo script (8–10 minutes)

1. Open the existing ATS and select a test job.
2. Paste/upload a rough JD; generate and review the standardized JD.
3. Save the reviewed JD and create a candidate assessment rubric.
4. Upload two synthetic/consented resumes; show extracted evidence, missing requirements, parse warnings and explainable match scores.
5. Open the authorship-risk panel only when its calibrated implementation is available; explain that it is an indicator, not proof.
6. Show the configured provider readiness and one successful model request.
7. Open Swagger UI and the OpenAPI JSON; show one JD endpoint and one Match endpoint.
8. Finish by showing test evidence and stating any remaining limitations.

## 4. Release gates

- No production release while required CI jobs are failing.
- No live-AI claim until a hosted provider call succeeds from the deployed backend.
- No detector release without labelled, representative evaluation and false-positive reporting.
- No autonomous hiring decisions.
- No SMTP dependency for the AI demo.
- Do not enable payload retention or change privacy settings without approval.
- Do not promise thousands of resumes at 1–100 ms each until a queue-backed load test proves throughput and latency.

## 5. Evidence to collect for every demo

- Commit SHA and deployment ID.
- API request and response (with secrets and personal data removed).
- Model/provider ID and readiness state.
- Test command and pass/fail summary.
- Sample input and expected output.
- Known limitations and manual review steps.
