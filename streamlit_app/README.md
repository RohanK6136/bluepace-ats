# BluePace ATS Streamlit Companion

A lightweight, separate Streamlit workspace for BluePace ATS.

## Features
- Public backend liveness (`/healthz`) and readiness (`/readyz`) checks
- Local first-pass resume text extraction for PDF, DOCX and TXT
- 5 MB maximum per uploaded file
- Basic keyword overlap review and CSV export
- Links to the existing Vercel ATS and FastAPI docs

The review tool is a keyword aid, not a hiring recommendation or automated decision. Uploaded files are not sent to the backend by this app. Avoid using confidential production resumes in public demo deployments.

## Run locally
```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r streamlit_app/requirements.txt
streamlit run streamlit_app/app.py
```

Optionally set `ATS_API_URL` to override the default backend URL.

## Deploy on Streamlit Community Cloud
- Connect the GitHub repository.
- Set the main file path to `streamlit_app/app.py`.
- Deploy using the requirements file at `streamlit_app/requirements.txt`.
- No API keys are required for the included features.
