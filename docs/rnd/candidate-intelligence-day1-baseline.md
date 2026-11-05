# BluePace ATS — Day 1 R&D Baseline
## Candidate Intelligence and CV Bank

**Date:** 5 November 2026  
**Repository:** RohanK6136/bluepace-ats  
**Base commit inspected:** 31141b34da4971d5c12b8befa5eb6bed3d9f1fc7  
**Working branch:** feature/candidate-cv-version-history  
**Status:** Audit in progress. No production code changed and no deployment triggered.

## 1. Objective

Establish a reliable, auditable candidate document and profile lifecycle before extending Candidate Intelligence. The first implementation target is controlled CV version history and traceability, subject to confirming the existing upload and storage lifecycle.

## 2. Confirmed foundations from source inspection

- Candidate records are organisation-scoped and contain `resume_storage_key`, structured `resume_data`, `cv_summary`, and an embedding.
- A `CandidateDocument` model exists with organisation, candidate, optional application, document name, storage key, content type, size and creation timestamp.
- A `ResumeProcessingJob` model exists with batch ID, organisation, creator, candidate/application references, filename, storage path, content type, size, task ID, status, result, error and processing timestamps.
- The resume extractor enforces a 5 MB maximum.
- The normal extraction path uses pypdf for PDFs and python-docx for DOCX. Docling can be selected explicitly and can be used as a fallback when no readable text is extracted.
- Optional LLM enrichment is gated by `ENABLE_LLM_RESUME_ENRICHMENT`; the prompt instructs the model to extract only explicit facts and return null/empty values when information is absent.
- Extracted profiles include quality flags, document validation, extraction evidence, extraction confidence, extractor version and raw-text length.
- Structured output is validated through the `ResumeData` schema.
- Candidate duplicate review and merge functionality exists in `backend/app/routers/merge_center.py`. The matching logic currently uses email, phone and name similarity signals.
- The matching service already considers required/preferred skills, experience, education, location, work mode, semantic similarity and project evidence.
- The current semantic search and talent-pool functionality should be extended rather than duplicated.

## 3. Confirmed lifecycle findings and remaining questions

The following findings are confirmed by reading the current main-branch source. They have not yet been reproduced against a running production environment.

1. **CandidateDocument is not currently wired into the inspected upload paths.** The model exists and is imported in `main.py`, but no `CandidateDocument(...)` creation was found in the inspected backend source.
2. **Public-application source CV deletion risk:** `public_apply` stores the uploaded CV in private storage, sets that same reference as `candidate.resume_storage_key`, and sets it as `ResumeProcessingJob.storage_path`. After successful extraction, `process_resume_ingest_job` deletes `job.storage_path`. Therefore, on this path, the worker appears to delete the same object referenced by the candidate profile. This is a confirmed code-path conflict and a high-priority fix; production impact still needs runtime verification.
3. **Resume Lab / bulk ingestion retention gap:** when the worker creates or updates a candidate from a queued job, it updates structured `resume_data` but does not set `candidate.resume_storage_key` or create a `CandidateDocument` in the inspected task. The worker then deletes the queue object's `job.storage_path` after success. This means the source CV is not retained for this path.
4. **Recruiter candidate creation path:** `/candidates/from-resume` writes the original file directly under `RESUME_STORAGE_DIR` and sets `resume_storage_key`, but does not create a `CandidateDocument` record in the inspected route.
5. **Candidate CV replacement path:** `/candidates/{candidate_id}/resume` writes a new private-storage object and overwrites `candidate.resume_storage_key` and `candidate.resume_data`. The old reference is captured in the audit event's before-state, but no version record is created in the inspected route. The route does not preserve the old CV as a first-class history item.
6. The replacement route replaces the full structured profile with the latest extracted payload. Recruiter-entered profile preservation needs a dedicated test and a defined merge policy.
7. Frontend entry points, document retrieval routes, role permissions and organisation isolation need a complete pass before adding a download/history API.
8. Retention and deletion policies for original CVs, temporary files, extracted text, embeddings and processing results remain to be verified.
9. The application uses `initialize_database()` with `Base.metadata.create_all` and incremental `upgrade_phase*` functions in `backend/app/database.py`; a new schema change must follow this existing mechanism and be tested on both SQLite and PostgreSQL-compatible behaviour.
10. Candidate merge handling of document records and storage objects remains to be verified.

## 4. Proposed first feature: CV Version History

Proposed user experience:
- A candidate profile shows the current CV and a chronological document history.
- Each version records upload time, uploader, original filename, content type, file size, processing status and extraction version.
- Each version links to the extracted profile snapshot and its evidence, so a recruiter can understand which document produced which fields.
- Replacing a CV creates a new version; it does not silently destroy the prior source document.
- Recruiters can select a version for review. Restoring an older version should be an explicit, audited action and should not erase later versions.
- Access is organisation-scoped and role-authorised.
- Retention/deletion policy is explicit; version history must not become indefinite storage by default.

Do not assume the current `CandidateDocument` model is sufficient for versioning until all upload paths, storage adapters, migrations and deletion paths have been inspected.

## 5. Engineering constraints

- Preserve the existing React/Vite + FastAPI architecture unless repository inspection proves a change is necessary.
- Preserve the current 5 MB PDF/DOC/DOCX upload limit.
- Keep the current Vercel deployment direction; do not introduce Railway.
- Keep storage private and avoid exposing raw storage paths or public object URLs.
- Preserve organisation isolation in every read/write query.
- Do not automatically reject candidates or make hiring decisions.
- Do not overwrite recruiter-entered facts with uncertain extraction output.
- No production deployment or main-branch merge without verification and explicit release readiness.

## 6. Evaluation plan

Create a consented, de-identified or synthetic benchmark covering:
- text PDF, DOCX with tables, multi-column PDF and scanned PDF;
- missing and malformed contact details;
- varied date formats and overlapping employment;
- multiple CV versions for one candidate;
- identical names with different contact information;
- duplicate CVs with changed filenames;
- corrupted, encrypted, oversized and unsupported files;
- cross-organisation access attempts.

Measure:
- field-level precision, recall and F1;
- date extraction accuracy;
- evidence support accuracy and unsupported-field rate;
- extraction success/failure and retry rates;
- duplicate precision/recall and false-merge rate;
- processing p50/p95 latency and resource consumption;
- document retrieval authorisation and cross-tenant isolation;
- version-history integrity and audit completeness.

Establish baseline measurements before setting numerical targets.

## 7. Day 1 acceptance criteria

- [x] Inspect candidate, resume-job and candidate-document models.
- [x] Inspect extraction engine selection and structured validation.
- [x] Inspect matching and duplicate/merge foundations.
- [x] Trace the main backend upload entry points: public application, recruiter candidate creation, candidate CV replacement, Resume Lab queue and bulk upload.
- [x] Trace the private-storage write/read/delete calls in the inspected upload and worker paths.
- [x] Confirm current profile overwrite semantics in the candidate CV replacement and Resume Lab processing paths.
- [ ] Inspect all frontend entry points, document download routes and automated test coverage.
- [ ] Confirm database migration/deployment behaviour and storage retention policy.
- [ ] Produce the complete API/data-flow map and implementation specification.

## 8. Change and verification log

- Created isolated branch `feature/candidate-cv-version-history` from the inspected main branch.
- No source files have been modified yet.
- No automated tests have been run in a local checkout.
- No commits have been made to `main`.
- No deployment has been initiated.
