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


## Zoho Recruit inbound sync

The companion now has a **Zoho Recruit** workspace. Sign in with a BluePace admin/recruiter account to check integration status or trigger a one-off sync. OAuth secrets must only be configured on the backend service.

### Railway backend variables

- `ZOHO_CLIENT_ID`: Zoho API Console OAuth client ID
- `ZOHO_CLIENT_SECRET`: matching OAuth client secret
- `ZOHO_REFRESH_TOKEN`: offline OAuth refresh token authorized for the Zoho Recruit tenant
- `ZOHO_ACCOUNTS_DOMAIN`: Zoho Accounts data centre suffix, e.g. `in`, `com`, or `eu`
- `ZOHO_RECRUIT_API_BASE`: API base for your data centre, e.g. `https://recruit.zoho.in/recruit/v2`
- `ZOHO_SYNC_ENABLED`: set to `true` to enable automatic polling
- `ZOHO_SYNC_INTERVAL_MINUTES`: polling interval, minimum 5 minutes (default 15)
- `ZOHO_ORGANIZATION_ID`: numeric BluePace organization ID that owns this Zoho tenant; required for scheduled sync to prevent cross-organization data mixing

Create a Zoho OAuth client and authorize it with the narrowest read scopes available for Candidates and Job Openings. Generate an offline refresh token. Do not commit these values or paste them into chat. Set them in Railway → backend service → Variables, then redeploy. Set `ZOHO_ORGANIZATION_ID` to the intended BluePace organization ID. Automatic sync only targets that organization to prevent cross-tenant data mixing. Use one backend replica while the in-process scheduler is enabled; multiple replicas would each poll. Zoho Recruit API quotas apply.

Current inbound fields include candidate name/email/phone/LinkedIn and job title/description/department/location/status/employment type. Sync uses a local mapping table for idempotency and only writes into the authenticated user's organization. It does not upload resume files, delete local records, or write changes back to Zoho. Verify field API names and scopes against the tenant's Zoho Recruit API version before enabling production sync.
