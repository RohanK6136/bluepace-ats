# Run JD Standardizer and Applicant Match with a local Ollama model

This setup lets the hosted BluePace ATS interface send **only JD Standardizer and Applicant Match AI requests** to an AI service running on your own Windows computer. The rest of the ATS (login, jobs, applications and recruiter workflow) remains on the hosted ATS API.

The local service uses Ollama with Qwen3 8B. No OpenRouter key, paid model subscription or inference credits are needed. The model runs on your own CPU/GPU, so speed depends on your computer.

## One-time setup

1. Install Ollama for Windows: https://ollama.com/download/windows
2. Make sure the Ollama desktop app is running.
3. Open PowerShell in the BluePace repository folder.
4. Run:

   `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`

   `.ackend\start-local-ai.ps1`

The script downloads `qwen3:8b` if it is not already installed, creates a small Python virtual environment, installs only the dependencies needed by the local AI API, and starts the service at `http://127.0.0.1:8000`. The first model download is about 5.2 GB.

Keep the PowerShell window open while using the local model. Stop it with Ctrl+C.

## Connect BluePace ATS

1. Open BluePace ATS and go to **JD & Applicant Match**.
2. In the **Local Ollama connection** area, enter `http://127.0.0.1:8000`.
3. Select **Connect local model**.
4. Wait for the inference check to confirm that **Qwen3 8B · local Ollama** is ready.
5. Select that model in the model selector. Run JD Standardizer, build a rubric, and assess resumes.

The local endpoint is saved in this browser's local storage. To return to hosted inference, choose **Use hosted AI** in the same area. That switches JD & Applicant Match back to the hosted model API.

## What runs where

- The browser connects to the local API at `127.0.0.1:8000).
- The local AI API calls Ollama at `127.0.0.1:11434`.
- The local API binds to loopback only; it is not exposed as a public network service.
- Only `/v1/*` JD & Applicant Match calls are sent to the local API. The main ATS backend continues to handle recruiter login, jobs, candidates and applications.
- Resume text and job-description content are processed locally by Ollama. The local AI run store is in-memory and is cleared when the local service stops. The model weights remain installed in Ollama.

## Troubleshooting

**Local API is unreachable:** confirm the PowerShell window still shows Uvicorn running at port 8000. Do not close that window while using local AI.

**Ollama is unreachable:** open the Ollama desktop app. In another PowerShell window run `ollama list`; confirm `qwen3:8b` appears.

**The browser reports a CORS error:** use the official BluePace Vercel or Render frontend URL included in the local service allow-list. If you use another frontend hostname, set `LOCAL_AI_ALLOWED_ORIGINS` to its exact origin before starting the script.

**Model is slow:** Qwen3 8B is a local model; CPU-only systems can take noticeably longer than hosted inference. Close other memory-heavy applications or choose a smaller Ollama model and set `OLLAMA_MODEL` to the exact installed model tag before starting the server.

**Local model not listed:** reconnect after the local service starts. The service uses the `local-ollama` profile from `backend/config/models.yaml`.

Local inference removes model-provider charges, but it still uses your computer's memory, processor/GPU, electricity and disk space.
