# AI Feature Implementation Audit

**Reviewed:** 29 October 2026  
**Repository:** `RohanK6136/bluepace-ats`  
**Scope:** the uploaded `recruiterportal-experiments` ZIP, especially `jd-standardizer/SPEC.md`, `docs/PROCESS_AND_WORKFLOWS.md`, `docs/APPLICANT_MATCH_SPEC.md` and `docs/APPLICATION_ASSESSMENT.md`.

## Status summary

The two core features are present in the ATS repository and are wired into its FastAPI app: JD Standardizer and Applicant Match (Application Assessment). The front end also contains the JD Standardizer / Applicant Match workspace and AI Hiring Studio. This does **not** mean every item in the prototype documents is complete. The documents explicitly defer some features and require owner/legal inputs.

| Requirement | Status | Implementation notes |
|---|---|---|
| Accept pasted JDs and PDF/DOCX/TXT/MD uploads | Implemented | API validates file type and size; extraction is text-based. |
| Normalize JD facts; retain provenance; flag conflict/missing facts; support overrides | Implemented | Strict pipeline includes deterministic clean/segment/validate/gap-plan/assemble stages. |
| Fast full-JD generation and streaming | Implemented | Separate generate endpoint; generated content is marked for recruiter review. |
| Model profiles, provider gateway, structured output, limited retries/cache | Implemented | Model registry and gateway are shared with Applicant Match. Live use still requires a reachable provider and credentials. |
| Run/model-call observability and usage summaries | Implemented | Runs, model calls, metrics and traces are available from the platform API. |
| Compile a job rubric, recruiter review, immutable rubric version | Implemented | Rubrics have stable content-derived IDs and hashes. |
| Resume redaction, cited evidence, deterministic score calculation, gaps and summary fallback | Implemented | Assessment is decision support. It must not make an autonomous hiring decision. |
| ATS route registration | Implemented | JD and Applicant Match routers are included in `backend/app/main.py`. |
| Delete an individual AI run and associated stored payloads | Added in this branch | API requires configured `API_KEYS`; it refuses to enable erasure when no keys are configured. Pending CI/merge/deploy. |
| Automatic expiry of stored prompts/results/cache | Added in this branch | Configure `PAYLOAD_RETENTION_DAYS` to a positive number to enable a startup purge and daily purge. Default is `0` (disabled) so an unapproved retention policy will not silently delete history. Pending CI/merge/deploy. |

## Known gaps / explicit deferrals

1. **Quality evaluation against a labelled test set is incomplete.** The uploaded project says `scripts/eval_quality.py` and `tests/expected/*.yaml` were not built. The specified sample set is incomplete, so scores for precision/recall should not be fabricated.
2. **`mode=rewrite` is not implemented.** The prototype currently falls back to light normalization and reports an informational flag. This was explicitly marked optional in `DEVIATIONS.md`; it should not be described as available.
3. **Scanned-PDF OCR is not included.** These documents need manual text or a separate OCR capability.
4. **A server-side Applicant Match batch API/queue is not included in this prototype.** The ATS has client-side bulk workflows, but that is not equivalent to a durable, restart-safe queue at thousands-of-resumes scale. The current architecture is not a guarantee of 1–100 ms per LLM assessment.
5. **AI-authorship detection is not part of the uploaded spec and is not implemented.** Text alone cannot reliably prove a resume was written by AI. If added later, it should be an experimental, explainable signal only—not a candidate rejection reason.
6. **Production governance still needs owner/legal input:** approved retention duration; legal review and candidate notices; official EEO text; approved hosted model/provider policy; and a recruiter-labelled quality set. Extend `taxonomy.json` with the actual skills used by the business.
7. **Production model readiness is environment-dependent.** CI can validate the code using mocks; it cannot prove the provider key/model is configured or that production inference succeeds. Verify the model connection in the deployed portal.
8. **The ZIP contains local SQLite run databases, Git metadata and a virtual environment.** Do not commit or redistribute those runtime databases or environment folders. The run database may contain prompts, outputs and redacted resume text.

## Retention and erasure added in this branch

- Set `PAYLOAD_RETENTION_DAYS=30` on the backend only after the owner approves 30 days (or choose another approved positive value). A value of `0` disables automatic expiry.
- The purge preserves run-level operational metrics but clears stored input previews/text, options/overrides, result/trace JSON, model prompts/raw/parsed outputs and old cache entries. It also clears payload-bearing fields in legacy request rows.
- `DELETE /v1/runs/{run_id}` permanently deletes a single run, its model-call rows, its legacy request row and its associated response-cache keys. Call it with `X-API-Key`; the endpoint refuses erasure if `API_KEYS` is unset.
- These controls cover the AI Feature Platform's `runs` store. They are not a blanket erasure policy for the separate ATS candidate/application database or private resume object storage.

## Verification record

- At the time of review, the repository's latest main CI run for commit `450807e3a963e0f14395ce233707889747841c7a` reported success.
- The newly added retention/erasure tests and this branch's production integration still need to pass CI before the changes are called merged or deployed.
- A live provider call and deployed Railway API smoke test remain separate from CI and must be verified against the current environment.
