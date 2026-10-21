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
- `ZOHO_SYNC_INTERVAL_MINUTES`: scheduled reconciliation interval, minimum 5 minutes (default 15)
- `ZOHO_WEBHOOK_SECRET`: long random secret shared with the Zoho webhook custom parameter
- `ZOHO_ORGANIZATION_ID`: numeric BluePace organization ID that owns this Zoho tenant; required for scheduled sync to prevent cross-organization data mixing

Create a Zoho OAuth client and authorize it with the narrowest read scopes available for Candidates and Job Openings. Generate an offline refresh token. Do not commit these values or paste them into chat. Set them in Railway → backend service → Variables, then redeploy. Set `ZOHO_ORGANIZATION_ID` to the intended BluePace organization ID. Automatic sync only targets that organization to prevent cross-tenant data mixing. Use one backend replica while the in-process scheduler is enabled; multiple replicas would each poll. Zoho Recruit API quotas apply.

Current inbound fields include candidate name/email/phone/LinkedIn and job title/description/department/location/status/employment type. Sync uses a local mapping table for idempotency and only writes into the authenticated user's organization. It does not upload resume files, delete local records, or write changes back to Zoho. Verify field API names and scopes against the tenant's Zoho Recruit API version before enabling production sync.


### Real-time webhook + reconciliation

The backend exposes `POST /integrations/zoho/webhook`. Set `ZOHO_WEBHOOK_SECRET` to a long random value in Railway. In Zoho Recruit, open **Setup → Automation → Actions → Webhooks**, create a POST webhook targeting the backend URL plus `/integrations/zoho/webhook`, and add a custom parameter named `webhook_token` containing the same secret. Associate the webhook with workflow rules for candidate and job-opening create/update events. Test with a non-production record.

The receiver accepts JSON or URL-encoded webhook parameters, compares the shared secret in constant time, and rejects requests when the secret is missing or incorrect. It does not trust incoming candidate/job fields: a valid event triggers a background reconciliation that re-reads records from Zoho using OAuth. The existing scheduler performs periodic reconciliation to recover missed webhook events. Configure `ZOHO_SYNC_ENABLED=true`, `ZOHO_ORGANIZATION_ID`, and the interval variable to enable this behaviour.

**Operational note:** this first version uses FastAPI background tasks and an in-process scheduler, so use one backend replica while enabled. A durable queue (e.g. Redis/Celery) is the next reliability step if webhook volume or uptime requirements grow. Webhook notifications can be retried by Zoho; reconciliation must remain idempotent. Do not include the secret in query strings if your Zoho setup allows a POST custom parameter body; URLs can be retained in access logs.
