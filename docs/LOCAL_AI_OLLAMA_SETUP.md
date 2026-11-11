# Run JD Standardizer and Applicant Match with a local Ollama model

This setup lets the hosted BluePace ATS interface send **only JD Standardizer and Applicant Match AI requests** to an AI service running on your own Windows computer. The rest of the ATS (login, jobs, applications and recruiter workflow) remains on the hosted ATS API.

The local service uses Ollama with Qwen3 8B. The BluePace local profile calls Ollama's native `/api/chat` endpoint, disables Qwen3's separate thinking phase for structured recruiter tasks (`think: false`), and keeps the model warm for 30 minutes between requests. No OpenRouter key, paid model subscription or inference credits are needed. The model runs on your own CPU/GPU, so speed still depends on your computer.

## One-time setup

1. Install Ollama for Windows: https://ollama.com/download/windows
2. Make sure the Ollama desktop app is running.
3. Open PowerShell in the BluePace repository folder.
4. Run:

   `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`

   ```powershell
Set-Location backend
.\start-local-ai.ps1
```

The script downloads `qwen3:8b` if it is not already installed, creates a small Python virtual environment, installs only the dependencies needed by the local AI API, and starts the service at `http://127.0.0.1:8000`. The first model download is about 5.2 GB.

Keep the PowerShell window open while using the local model. Stop it with Ctrl+C.

## Connect BluePace ATS

1. Open BluePace ATS and go to **JD & Applicant Match**.
2. In the **Local Ollama connection** area, enter `http://127.0.0.1:8000`.
3. Select **Connect local model**.
4. Wait for the inference check to confirm that **Qwen3 8B · local Ollama** is ready.
5. Select that model in the model selector. Use **Standardize JD** for the fast one-model-call path, then **Automate JD + match setup** to prepare the rubric. The default generated draft is **Concise**; change the detail selector to **Detailed** only when you need the longer draft. **Full validation (slower)** runs the more extensive 12-stage standardization pipeline.

The local endpoint is saved in this browser's local storage. To return to hosted inference, choose **Use hosted AI** in the same area. That switches JD & Applicant Match back to the hosted model API.

## What runs where

- The browser connects to the local API at `127.0.0.1:8000`.
- The local AI API calls Ollama's native API at `127.0.0.1:11434` and requests structured JSON output with thinking disabled.
- The local API binds to loopback only; it is not exposed as a public network service.
- Only `/v1/*` JD & Applicant Match calls are sent to the local API. The main ATS backend continues to handle recruiter login, jobs, candidates and applications.
- Resume text and job-description content are processed locally by Ollama. The local AI run store is in-memory and is cleared when the local service stops. The model weights remain installed in Ollama.

## Updating the local companion after BluePace code changes

The hosted Vercel frontend and the local Ollama companion are separate processes. A Vercel deployment does **not** update Python files already running from a Windows checkout. After pulling a BluePace backend fix, stop the old local service with Ctrl+C and restart it from the updated checkout:

```powershell
Set-Location "C:\Users\Rohan\Projects\bluepace-ats"
git status --short
git pull --ff-only origin main
.\backend\start-local-ai.ps1
```

Keep the new PowerShell window open. If `git status --short` reports local edits, review them before pulling; do not discard them with a hard reset. Reconnect the local model in the browser after the service restarts.

A local model can time out before its first streamed token. BluePace keeps the source-based JD draft and records the local model outage as a review warning; missing required job facts, missing qualifications, and unaccepted AI-generated content remain publication blockers. A timeout is not evidence that the model completed the generation.

## Troubleshooting

**Local API is unreachable:** confirm the PowerShell window still shows Uvicorn running at port 8000. In another PowerShell window, run:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/healthz
Invoke-RestMethod http://127.0.0.1:11434/api/tags
```

The first command should return `status = ok` and `service = bluepace-local-ai`. The second should return the Ollama model list. Do not close the BluePace local AI PowerShell window while using local AI.

**Ollama is unreachable:** open the Ollama desktop app. In another PowerShell window run `ollama list`; confirm `qwen3:8b` appears.

**The browser reports a CORS error:** use the official BluePace Vercel or Render frontend URL included in the local service allow-list. If you use another frontend hostname, set `LOCAL_AI_ALLOWED_ORIGINS` to its exact origin before starting the script.

**Model is slow:** Qwen3 8B is a local model; CPU-only systems can take noticeably longer than hosted inference. Close other memory-heavy applications or choose a smaller Ollama model and set `OLLAMA_MODEL` to the exact installed model tag before starting the server.

**Local model not listed:** reconnect after the local service starts. The service uses the `local-ollama` profile from `backend/config/models.yaml`.

Local inference removes model-provider charges, but it still uses your computer's memory, processor/GPU, electricity and disk space.

## Browser permission for local access

Open the BluePace ATS website over its normal HTTPS address. The first time you press **Connect local model**, Microsoft Edge 143+ or a recent Chromium browser may display a Local Network Access / Loopback network permission prompt because the hosted site is connecting to a service on your computer. Choose **Allow**.

If the prompt was previously blocked in Edge, open **Settings → Privacy, search, and services → Site permissions → All permissions → Local network access**, and allow access for the BluePace site. You can also open the site information icon beside the address bar and choose **Site permissions**. Then return to JD & Applicant Match and press **Reconnect local model**.

The app checks permission only after you press the connection button. If `http://127.0.0.1:8000/healthz` works in a separate browser tab but the hosted site still cannot connect, check this browser permission and the local service's allowed frontend origins. If the health URL does not open, restart `backend/start-local-ai.ps1` and make sure Ollama is running. The local API is bound to `127.0.0.1` and is not exposed to other devices on your network.

The local API is bound to `127.0.0.1` and is not exposed to other devices on your network. Keep the PowerShell window running while you use local inference. If you close it or stop Ollama, local AI requests will fail until you start the service again.

## Local-mode feature boundary

JD text standardization, rubric drafting and resume-file analysis in the JD & Applicant Match workspace are routed to local Ollama after connection. The separate action that reads a resume already stored privately on an ATS candidate profile still uses the hosted ATS backend, so that action is disabled while local mode is active. Upload the resume in Applicant Match to process it locally instead.

Likewise, a run created by the local companion service is not yet a verified run in the hosted ATS database. In local mode, assessment results remain in the browser workspace; linking that local run to a shared ATS application is disabled rather than sending it to a hosted inference path or pretending it was verified by the server.
