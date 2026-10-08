# BluePace ATS — Deep Engineering Audit

**Scope:** current repository architecture, document intake, AI/matching, recruiter workflow, interview/offer pipeline, storage and careers-site flow.

## 1. End-to-end architecture

```
Job creation
  -> JD URL / JD PDF / JD DOCX
  -> document extraction
  -> normalized JD fields
  -> JD analysis
  -> job embedding
  -> search / matching / reranking
  -> application
  -> resume ingestion
  -> candidate profile
  -> candidate-job match
  -> recruiter assistant / comparison
  -> interview
  -> scorecard
  -> offer
  -> hire
```

## 2. Stage audit

| Stage | Input | Processing | Output | Database | API | AI/model | Storage | Error handling |
|---|---|---|---|---|---|---|---|---|
| Job creation | Title/JD fields or URL/file | Validate, extract, normalize, analyze | Job + JD analysis | `jobs`, `stages` | `/jobs`, `/jobs/from-url`, `/jobs/from-document/preview`, `/jobs/from-document` | Matching parser; optional LLM paths elsewhere | JD binary storage is still not universally separated from DB metadata | 4xx validation, extraction errors |
| Document extraction | PDF/DOCX bytes | Docling first, legacy fallback | Parsed text + normalized resume/JD | Candidate/job after sync/create | `/extract/`, job preview | Docling; optional OpenRouter enrichment | In-memory conversion; upload storage handled separately | 5 MB cap, unsupported format, conversion error |
| JD analysis | Job description | Requirement/skill/location/work-mode parsing | Required/preferred skills, experience, location, responsibilities | `jobs.jd_analysis` | `/jobs/{id}/analyze` | Deterministic parser; optional model routing | N/A | Stored analysis can be recomputed |
| Embedding | Job/candidate text | Embedding generation | Vector | `jobs.embedding`, `candidates.embedding` | Internal/background | `text-embedding-3-small` by default | PostgreSQL/pgvector | Embedding failures do not block normal workflow |
| Matching | Job + candidate | Hard requirement checks + semantic signals | Match score, breakdown, gaps, evidence | `candidate_job_matches` | `/jobs/{id}/matches` and candidate search | Deterministic scorer; optional Cohere reranker | N/A | Safe fallback when reranker unavailable |
| Application | Job + candidate or public resume | Validate duplicate, create application, queue email | Application in Applied stage | `applications`, `candidate_job_matches` | `/applications`, `/public/jobs/{id}/apply` | Matching on creation | Private document storage reference | 409 duplicate, 4xx validation |
| Resume processing | Resume bytes/reference | Queue, extract, validate, enrich, candidate upsert | Candidate profile + match | `resume_processing_jobs`, `candidates`, `applications` | `/resume-processing/queue`, bulk presign/upload/finalize | Docling, optional SLM/OpenRouter | R2/B2/local provider abstraction | Retry/queue failure states |
| Candidate profile | Parsed resume | Merge profile, summary, embedding | Canonical candidate record | `candidates` | `/candidates/from-resume`, `/candidates/{id}/resume`, Resume Lab sync | Extraction + optional SLM | Resume reference + metadata | Duplicate-safe organization scoping |
| Recruiter assistant | Candidate + JD + ATS evidence | Grounded prompt, evidence retrieval | Summary/answers | Existing ATS records | Assistant endpoints in `next_features` | OpenRouter assistant/deep reasoning models | N/A | Model output constrained as decision support |
| Interview | Application + interviewer availability | Schedule, participants, reminders | Interview record/calendar | `interviews`, `interview_participants`, availability | Interview management endpoints | Optional AI preparation paths | Calendar/meeting URLs | Scheduling validation and status transitions |
| Scorecard | Interview feedback | Structured ratings and recommendation | Scorecard | `scorecards` | Scorecard endpoints | AI can summarize; humans own assessment | N/A | Structured fields |
| Offer | Application + compensation | Create/review/send/respond | Offer state | `offers` | Offer management router | Optional assistant/supporting AI | Offer document URL/reference | Status/revision/approval workflow |
| Hire | Offer/application terminal state | Stage/status transition | Hired pipeline state | `applications`, audit logs | Application stage endpoints | No automatic hiring authority | Existing document references | Terminal-state safeguards |
| Careers search | Candidate text/filters | Hard filters + ranked retrieval | Relevant open jobs | `jobs` | `/public/jobs`, new `/public/career-assistant` | Embeddings when available; lexical fallback | Public site only | Query validation; no sensitive candidate access |

## 3. AI policy

BluePace should use a layered decision-support architecture:

```
Hard filters
  -> semantic retrieval
  -> embeddings
  -> optional reranking
  -> evidence extraction
  -> AI reasoning/summarization
  -> human review/approval
```

No AI endpoint should directly publish a job, reject a candidate, or make a final hiring decision.

## 4. Current model routing

- Default routine model: configurable through `OPENROUTER_MODEL`.
- Assistant model: `OPENROUTER_ASSISTANT_MODEL`.
- Validation model: `OPENROUTER_VALIDATION_MODEL`.
- Deep reasoning model: `OPENROUTER_DEEP_REASONING_MODEL`.
- Embeddings: `MATCHING_EMBEDDING_MODEL`, default `text-embedding-3-small`.
- Optional reranker: Cohere through `RERANK_ENABLED`.

The model-routing abstraction is centralized in `backend/app/services/model_router.py`.

## 5. Storage audit

### Private ATS documents

Target architecture:

```
PostgreSQL
  metadata only:
  candidate_id / filename / content_type / size / storage_key / timestamps

R2
  resumes/
  job-descriptions/
  offers/
  candidate-documents/
```

The repository now supports R2, B2 and local storage through `private_storage.py`. The connected Cloudflare account currently reports that R2 must first be enabled, so production R2 activation is an environment/configuration prerequisite.

### Public media

Cloudinary is intentionally separated for careers-site media such as logos, marketing images and public visual assets. Private candidate resumes should remain in R2.

## 6. Key technical risks identified

1. Document extraction is CPU/model intensive and should stay off latency-sensitive application paths.
2. Local filesystem storage is not durable across service replacement; R2 should be enabled before production scale-up.
3. Embedding freshness must be tied to material changes in job/candidate text.
4. AI-generated outputs need source/evidence references and human approval.
5. Duplicate candidate/application controls must remain organization-scoped.
6. Public career search must never expose private candidate fields.
7. Bulk ingestion needs idempotent batch handling and storage-path validation.

## 7. Recommended next engineering increments

- Persist a dedicated `candidate_documents` metadata record whenever non-resume candidate documents are uploaded.
- Move JD binary storage to R2 using the same provider abstraction.
- Add an extraction benchmark fixture suite covering normal, multi-column, table-heavy and scanned documents.
- Add telemetry for extraction engine, latency, failure category, extraction confidence and post-extraction field coverage.
- Add retrieval evaluation metrics: Recall@K, Precision@K, NDCG@K, apply conversion and recruiter override rate.
- Add structured AI audit records containing prompt/model version, evidence IDs, latency and outcome.
