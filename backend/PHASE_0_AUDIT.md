# Phase 0 Audit

## Current State

- Frontend: React 19, Vite, and Tailwind. The recruiter workspace now provides sign-in, jobs, candidates, and application pipeline views; the original resume evaluation remains available as Resume Lab. It calls the authenticated backend API, with port `8000` as the local fallback.
- Backend: FastAPI provides authenticated, organization-scoped job and candidate management, application stages, filters, bulk transitions, CSV export, resume parsing, audit logs, and an SMTP outbox. Resume extraction uses OpenRouter when configured and a regex fallback otherwise.
- Tests: `test_api.py` is a manual OpenRouter connectivity check that requires a live API key. It is not deterministic API test coverage.
- Infrastructure: Docker and a Render web-service blueprint exist. Celery/Redis are configured in code, but the Render blueprint does not provision a worker, Redis, PostgreSQL, or a distinct staging environment. A GitHub Actions CI workflow has been added for backend tests and the frontend build; Sentry and PostHog are not configured.
- File handling: uploads are processed in memory. There is no S3/R2 storage integration or durable resume reference.

## Stack Decision

- Keep the existing React/Vite/Tailwind frontend and Python/FastAPI backend.
- Use SQLAlchemy with PostgreSQL and pgvector for organization-scoped records and candidate embeddings. SQLite remains the local/test default.
- Keep Celery with Redis for background work.
- This first implementation uses short-lived JWT access tokens and Argon2 password hashes. It does not introduce a hosted identity provider.
- Resume storage, migrations, continuous deployment, observability, and staging resource provisioning remain follow-up work.

## Roles

| Role | Initial access |
| --- | --- |
| Admin | Manage organization users; read and write jobs and candidates |
| Recruiter | Read and write jobs and candidates |
| Hiring Manager | Read organization jobs and candidates |
| Interviewer | Read organization jobs and candidates |
| Candidate | No recruiter-side resource access |

## Data Model

- `Organization` owns users, jobs, candidates, applications, notes, and emails.
- `User` belongs to one organization and has one of the five roles above.
- `Job` belongs to an organization and its creator; it has title, description, department, location, employment type, status, and timestamps.
- `Candidate` belongs to an organization and its creator; it has contact/source fields, an optional resume storage key, and a pgvector embedding column.
- `Application` joins a job and candidate within an organization. `Stage` defines an ordered pipeline for a job; applications may reference the current stage.
- `Note`, `Scorecard`, `Interview`, and `Email` attach collaboration, evaluation, scheduling, and communication records to applications.

## Implemented In This Phase

- Organization registration creates an initial admin; admins can create organization users.
- JWT authentication protects ATS endpoints. All job and candidate reads/writes are scoped to the signed-in user's organization.
- CRUD endpoints are available for jobs and candidates. Admins/recruiters may write; hiring managers/interviewers are read-only.
- Database tables are initialized on app startup, and PostgreSQL enables the `vector` extension.
- Focused API tests cover authentication, CRUD, role restrictions, duplicate candidates, and cross-organization isolation.
- GitHub Actions runs the backend test suite and builds the frontend; the local frontend API fallback now targets FastAPI's default port.
- Phase 1 adds job archiving, default application stages, application create/list/stage APIs, source/skill/stage/date filters, bulk stage movement and rejection, CSV export, and organization-scoped audit history.
- Candidate resume uploads are parsed into structured JSON, with work history and education fallback extraction; application received and stage-change messages enter the email outbox.
- The recruiter workspace exposes job editing/archiving, candidate creation and resume upload, pipeline filters, bulk actions, and export.

## Staging Gates

Staging is not deployed by this workspace change. The Render blueprint now selects staging mode, generates `JWT_SECRET`, and requires explicit PostgreSQL/Redis URLs, the OpenRouter key, and frontend origin. Provision those resources and a Celery worker in Render before syncing; startup rejects a deployed environment that falls back to SQLite or localhost Redis. A separate production service/environment still needs to be created and configured.

Before production use, add versioned Alembic migrations, invitation/email verification and password reset flows, login rate limiting, durable private resume storage, backup/retention policy, and Sentry/PostHog with candidate PII excluded. Configure SMTP credentials, `VITE_API_URL`, and the staging API origin. The Phase 1 parser accuracy target remains unmeasured and requires a labeled human-reviewed evaluation set.

## Phase 1 Notes

- The hybrid parser uses OpenRouter when `OPENROUTER_API_KEY` is configured and falls back to local regex/section parsing. The 90% accuracy target has not been measured; it needs a labeled resume set and human-reviewed evaluation before being treated as achieved.
- Resume uploads currently go to the private local `RESUME_STORAGE_DIR` (default `backend/private_uploads`) and parsed structured JSON is stored on the candidate. Use durable private object storage before relying on deployed uploads.
- Application notifications are queued in the email table and sent through SMTP when configured (`SMTP_HOST`, `SMTP_PORT`, `SMTP_FROM`, and optionally `SMTP_USER`/`SMTP_PASSWORD`). Delivery failures are retained in the outbox.