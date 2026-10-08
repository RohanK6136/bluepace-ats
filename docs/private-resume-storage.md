# Private resume storage

BluePace ATS stores uploaded resumes and queued resume-processing documents through `app.services.private_storage`.

## Cloudflare R2

Set these backend service environment variables in Render:

- `R2_ENDPOINT` — Cloudflare R2 S3 API endpoint for the account
- `R2_ACCESS_KEY_ID`
- `R2_SECRET_ACCESS_KEY`
- `R2_BUCKET`
- `R2_REGION` — normally `auto`

When all four required connection values are present, uploads are written to R2 and database storage references use the `r2://` scheme. The ATS reads and deletes those objects through the same adapter.

Without the R2 variables, development/test environments use the configured local upload directory. This keeps local setup compatible while allowing production to use private object storage.

Resumes should remain private. Do not expose the R2 bucket publicly. Use short-lived presigned URLs for any future recruiter download surface.
