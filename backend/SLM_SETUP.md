# Optional SLM enrichment

BluePace keeps the existing deterministic PDF/DOCX extraction and matching unchanged.

An optional Small Language Model (SLM) stage can be enabled for background/Celery processing:

- ENABLE_SLM_RESUME_ENRICHMENT=true
- SLM_MODEL=qwen2.5:3b
- SLM_BASE_URL=http://<slm-host>:11434/v1 for an OpenAI-compatible local/self-hosted endpoint
- SLM_API_KEY=<key> when the SLM endpoint requires authentication
- SLM_TIMEOUT_SECONDS=2.0

When the flag is false (the default), there is no SLM call and the existing behavior is unchanged.

When enabled, the SLM runs after deterministic extraction inside the background task. It adds a `slm_enrichment` object to the extracted JSON result. A failed/slow SLM call never fails the deterministic extraction.

For high-volume processing, keep SLM work on Celery workers and do not call it from the synchronous public upload request path.
