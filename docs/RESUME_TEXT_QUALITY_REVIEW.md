# Resume Text Quality Review

## Purpose

Surface **observable** resume text issues for recruiter review. This is **not** an AI-vs-human classifier.

- Always returns `assessment: "undetermined"` and `confidence: "not_assessed"`
- Never produces an AI probability or binary verdict
- Must not auto-reject, rank, or score candidates

Detector version: `text-quality-signals-0.2.0`

## OpenAPI

Live schema: `GET /openapi.json` (tag: **Resume Authorship Review**)

| Method | Path | Body |
|--------|------|------|
| `POST` | `/v1/resume-authorship/assess` | JSON `{ "text": "..." }` (100–60000 chars) |
| `POST` | `/v1/resume-authorship/assess/upload` | multipart `file` **or** `text` |

Optional header: `x-api-key` (same pattern as other `/v1` lab routes).

### Example

```bash
curl -s -X POST "$API/v1/resume-authorship/assess" \
  -H "Content-Type: application/json" \
  -d '{"text":"<resume text >= 100 chars>"}'
```

### Response (shape)

```json
{
  "assessment": "undetermined",
  "status": "no_text_quality_alerts",
  "confidence": "not_assessed",
  "text_characters": 864,
  "signals": [],
  "limitations": ["..."],
  "human_review_required": true,
  "detector_version": "text-quality-signals-0.2.0"
}
```

`status` enum:

- `insufficient_evidence` — short sample
- `review_recommended` — one or more non-length signals
- `no_text_quality_alerts` — no signals beyond empty

## Signals (v0.2)

| Code | Meaning |
|------|---------|
| `limited_text_sample` | Under ~500 characters |
| `repeated_content` | Duplicate long lines |
| `uniform_bullet_lengths` | Very consistent bullet lengths |
| `generic_corporate_phrases` | Multiple known filler phrases |

## Integrations

1. **Resume Lab** (`App.jsx`) — button on extracted `raw_text`
2. **AI Hiring Studio** — tab **Text quality review** (`ResumeAuthorshipReviewPanel`)
3. **Feature registry** — `GET /v1/features` → `resume_authorship_review`
4. **Partner / external** — OpenAPI clients only; do not map signals to hiring decisions
5. **Zoho / imports** — optional post-extract call; store review for recruiters, never as "AI-generated" fact

## Implementation files

- `backend/app/features/resume_authorship/analysis.py` — heuristics
- `backend/app/features/resume_authorship/routes.py` — HTTP + local extract
- `frontend-vite/src/ResumeAuthorshipReviewPanel.jsx` — studio UI
- `frontend-vite/src/App.jsx` — Resume Lab UI
- `backend/tests/test_resume_authorship_*.py`

## Safety

- No LLM call on this path
- Upload not persisted
- Scanned PDFs without text are rejected (OCR required)
