# BluePace ATS — AI features implementation and demo plan

Last reviewed: 2026-11-02
Repository: RohanK6136/bluepace-ats
Deployment target: Railway project `melodious-expression`, backend service `bluepace-ats`

## 1. Evidence-based baseline

| Area | Evidence found | Status |
|---|---|---|
| JD Standardization | Existing `backend/app/features/jd_standardizer/routes.py`; router is imported and mounted in `backend/app/main.py`; ZIP contains the JD Standardizer pipeline and fixtures. | Implemented in code; live end-to-end use not verified |
| AI Assistance / Applicant Match | Existing `backend/app/features/applicant_match/routes.py`; router is imported and mounted; ZIP documents rubric drafting, resume redaction, evidence extraction and deterministic weighted scoring. | Implemented in code; live end-to-end use not verified |
| AI-generated resume detection | A conservative text-quality review foundation now exists, but it explicitly does not identify AI authorship or produce an authorship probability. | Review foundation implemented; actual detector not implemented |
| ATS integration | JD & Applicant Match UI calls the frontend same-origin `/v1` handler (`frontend-vite/api/v1/[...path].js`); Resume Lab and the new resume-review API call the Railway FastAPI backend. Resume Lab has an optional recruiter-triggered text-quality panel. | UI/code paths connected; end-to-end live workflow still needs verification |
| Model integrations | `backend/config/models.yaml` defines OpenRouter profiles for Gemini, DeepSeek and other providers, plus OpenAI-compatible and Anthropic profiles. Railway backend service variable names did not include `OPENROUTER_API_KEY` at review time. | Provider profiles configured; hosted inference not verified and default OpenRouter credential appears absent |
| OpenAPI | Railway FastAPI app creates `BluePace Tech ATS API` v0.4.0 and serves its generated schema/docs by default. The frontend same-origin Node `/v1` handler is a separate API surface and is not described by the FastAPI schema. | FastAPI schema/docs generated in code; Node API contract and public endpoint access still need verification |
| Current PR | PR #108 includes Applicant Match hardening, the resume-review API and file extraction, a Resume Lab review panel, tests, documentation, and a frontend lockfile security fix. | Open; not merged or deployed |
| CI | Backend dependency installation and `pytest backend` passed in run 41400002288. The lockfile was then updated from `follow-redirects` 1.16.1 to patched 1.16.2; CI for that new head (run 41400192809) was still in progress at the time of this update. | Backend pass; full CI pending |
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

### Phase D — OpenAPI and API contract alignment

1. Verify the deployed FastAPI `/openapi.json` and `/docs` endpoints.
2. Keep the API execution paths explicit: JD & Applicant Match currently run through the frontend same-origin Node handler under `frontend-vite/api/v1/`; Resume Lab and Resume Text Quality Review use the Railway FastAPI backend.
3. Publish a contract for the Node handler as well (or consolidate the route surface deliberately in a separately tested change); do not imply the FastAPI schema describes the Node handler.
4. Ensure both surfaces document authentication, upload formats/limits, model-provider headers, error responses, rate limits and examples.
5. Add contract tests for representative success and failure responses, and publish a versioned developer integration guide.

## 3. Demo script (8–10 minutes)

1. Open the existing ATS and select a test job.
2. Paste/upload a rough JD; generate and review the standardized JD.
3. Save the reviewed JD and create a candidate assessment rubric.
4. Upload two synthetic/consented resumes; show extracted evidence, missing requirements, parse warnings and explainable match scores.
5. Open the optional Resume Lab text-quality review panel. Explain that its observations are not an AI-authorship detector and must not influence hiring.
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


## 6. Resume authorship review foundation added to the PR

The existing ZIP's conservative `resume_authorship` module has been carried into the ATS backend and extended.

- `POST /v1/resume-authorship/assess` accepts extracted text.
- `POST /v1/resume-authorship/assess/upload` accepts PDF, DOCX, TXT or Markdown files, or a multipart text field. File text is extracted in memory; scanned/image-only PDFs are rejected with OCR guidance.
- The implementation uses deterministic text-quality signals (repeated long lines and unusually uniform bullet formatting); it does not call an LLM, persist file contents, or return an authorship probability.
- The API always returns `assessment: "undetermined"` and `confidence: "not_assessed"`.
- The feature is registered as beta and an optional recruiter-triggered review panel is connected to Resume Lab. The panel clearly states that the result is not an AI detector and is excluded from candidate matching.
- API tests cover text, PDF, DOCX, minimum length, unsupported extensions, scanned PDF handling, source validation and the 5 MB upload cap.

This remains **a resume text-quality review, not the completed AI-generated resume detector**. A calibrated detector needs a representative labelled dataset, reproducible evaluation and false-positive/false-negative reporting before any production claim. The signal must not affect candidate ranking or hiring decisions.
