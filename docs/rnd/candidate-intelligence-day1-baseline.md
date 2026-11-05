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

## 3. Initial risks and questions to verify

These are audit questions, not confirmed production defects.

1. Does every successful upload create a durable `CandidateDocument` row and retain the original object in storage?
2. Does the Resume Lab processing path update `Candidate.resume_storage_key`, or only the structured profile?
3. What happens to the prior document and extracted profile when a candidate uploads a replacement CV?
4. Are profile updates merged field-by-field, and can recruiter-entered values be overwritten?
5. Are original documents downloadable only by authorised users belonging to the candidate's organisation?
6. Are storage keys opaque and private, with access mediated by an authenticated backend route or short-lived signed URL?
7. What are the configured retention and deletion behaviours for original CVs, temporary files, extracted text, embeddings, and processing results?
8. Which database migration mechanism is used, and how are new document-version records deployed safely?
9. Are candidate merges updating all document references and preserving an audit trail?
10. Which frontend views and APIs currently show the original CV and document history?

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
- [ ] Trace all upload endpoints and frontend entry points.
- [ ] Trace storage writes, downloads, deletion and retention.
- [ ] Inspect migrations and relevant automated tests.
- [ ] Confirm current profile overwrite/merge semantics.
- [ ] Produce a complete API/data-flow map and implementation specification.

## 8. Change and verification log

- Created isolated branch `feature/candidate-cv-version-history` from the inspected main branch.
- No source files have been modified yet.
- No automated tests have been run in a local checkout.
- No commits have been made to `main`.
- No deployment has been initiated.
