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

Optional header: `x-api-key`.

### Example

```bash
curl -s -X POST "$API/v1/resume-authorship/assess" \
  -H "Content-Type: application/json" \
  -d '{"text":"<resume text >= 100 chars>"}'
```

### Response shape

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

## Signals (v0.2)

| Code | Meaning |
|------|---------|
| `limited_text_sample` | Under ~500 characters |
| `repeated_content` | Duplicate long lines |
| `uniform_bullet_lengths` | Very consistent bullet lengths |
| `generic_corporate_phrases` | Multiple known filler phrases |

## Integrations

1. Resume Lab — review button on extracted text
2. AI Hiring Studio — panel component `ResumeAuthorshipReviewPanel`
3. Feature registry — `GET /v1/features`
4. Partners — OpenAPI only; do not map signals to hiring decisions

## Safety

- No LLM call on this path
- Upload not persisted
- Scanned PDFs without text are rejected (OCR required)
