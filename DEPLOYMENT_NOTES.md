## Final Deployment (In Progress)

- The code is currently being pushed to GitHub after fixing the API key security issue.
- Backend: Deploying to Render using the Dockerfile. Need to configure the OPENROUTER_API_KEY environment variable on the Render dashboard.

## 2. Final LLM Test & UI Polish

- The extraction works perfectly. The LLM is receiving responses from OpenRouter, but I am fine-tuning the JSON parsing so the scores render perfectly on the dashboard (currently showing a placeholder % while we debug the fallback parsing). This will be fixed today.

## 3. High-Volume Scaling Architecture (Celery + Redis)

- Currently, the app processes one resume at a time synchronously. To handle thousands of resumes, we need to upgrade to an Asynchronous Background Queue:
- FastAPI will accept bulk uploads and push tasks to Redis.
- Celery workers will process extraction and LLM validation in parallel.
- Results will be stored in a PostgreSQL database.

## 4. Deep Fine-Tuning Research Report

- As requested, I have prepared a technical analysis regarding model parameters, quantization (4-bit GGUF to reduce RAM from 8GB to 1.5GB), and LoRA fine-tuning strategies for small open-source models (Qwen 2.5 1.5B).


## Private document storage — Backblaze B2

The ATS private document storage now uses the Backblaze B2 S3-compatible API through boto3. Configure these environment variables on the backend deployment:

```text
B2_ENDPOINT=https://s3.<your-region>.backblazeb2.com
B2_ACCESS_KEY_ID=<backblaze-application-key-id>
B2_SECRET_ACCESS_KEY=<backblaze-application-key>
B2_BUCKET=<backblaze-bucket-name>
B2_REGION=<your-region>
```

Do not commit the real key ID or application key. Backblaze requires a manually created application key for the S3-compatible API; the master application key is not supported. The endpoint format is `https://s3.<region>.backblazeb2.com`. The B2 application key ID maps to the S3 access key ID and the application key maps to the S3 secret access key. citeturn995526search0turn995526search2

After setting the variables, the backend stores new private documents using `b2://...` references and generates short-lived presigned download URLs. When B2 is not configured, development/test environments continue using the existing local `RESUME_STORAGE_DIR` fallback.
