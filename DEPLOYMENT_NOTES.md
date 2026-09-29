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
