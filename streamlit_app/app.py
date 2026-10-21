import io
import os
import time
from typing import Any
import requests
import streamlit as st

APP_TITLE = "BluePace ATS | Streamlit Workspace"
DEFAULT_API_URL = "https://bluepace-ats-production.up.railway.app"
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
ALLOWED_EXTENSIONS = {"pdf", "docx", "txt"}

st.set_page_config(page_title=APP_TITLE, page_icon="🧭", layout="wide", initial_sidebar_state="expanded")
st.markdown("""<style>
.stApp { background: #0b1020; color: #e7ecf5; }
[data-testid="stSidebar"] { background: #11182a; border-right: 1px solid #26334b; }
[data-testid="stMetric"] { background: #121b2e; border: 1px solid #26334b; padding: 16px; border-radius: 12px; }
.bp-muted { color: #9eabc2; font-size: .92rem; }
.bp-card { background: #121b2e; border: 1px solid #26334b; padding: 18px; border-radius: 14px; }
</style>""", unsafe_allow_html=True)

st.title("BluePace ATS")
st.caption("Recruiting operations workspace · Streamlit companion")
st.markdown('<p class="bp-muted">A lightweight companion for service checks and first-pass resume review. The main ATS remains the system of record.</p>', unsafe_allow_html=True)

with st.sidebar:
    st.subheader("Connection")
    api_url = st.text_input("Backend API URL", value=os.getenv("ATS_API_URL", DEFAULT_API_URL)).strip().rstrip("/")
    st.caption("Keep API keys and passwords in Streamlit Secrets or service environment variables. Never paste secrets into the app.")
    st.divider()
    page = st.radio("Workspace", ["Overview", "Resume review", "Zoho Recruit", "Integration guide"])
    st.divider()
    st.markdown("[Open main ATS](https://bluepace-ats-frontend.vercel.app/?mode=admin)")
    st.markdown("[Backend API docs](" + api_url + "/docs)")


def check_endpoint(base_url: str, path: str) -> tuple[bool, str, float]:
    started = time.perf_counter()
    try:
        response = requests.get(f"{base_url}{path}", timeout=(3, 8))
        elapsed = (time.perf_counter() - started) * 1000
        return response.ok, f"HTTP {response.status_code}", elapsed
    except requests.RequestException as exc:
        return False, str(exc)[:180], (time.perf_counter() - started) * 1000


def extract_text(uploaded_file: Any) -> str:
    suffix = uploaded_file.name.rsplit(".", 1)[-1].lower()
    raw = uploaded_file.getvalue()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ValueError("Files must be 5 MB or smaller.")
    if suffix not in ALLOWED_EXTENSIONS:
        raise ValueError("Supported formats are PDF, DOCX and TXT.")
    if suffix == "txt":
        return raw.decode("utf-8", errors="replace")
    if suffix == "pdf":
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(raw))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    from docx import Document
    document = Document(io.BytesIO(raw))
    paragraphs = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
    for table in document.tables:
        for row in table.rows:
            paragraphs.append(" | ".join(cell.text.strip() for cell in row.cells))
    return "\n".join(paragraphs)


def tokens(text: str) -> set[str]:
    import re
    return {word for word in re.findall(r"[a-zA-Z][a-zA-Z0-9+#.-]{1,}", text.lower())}


if page == "Overview":
    st.subheader("Service health")
    st.write("Checks public liveness and database readiness endpoints. No credentials are sent.")
    if st.button("Run health checks", type="primary"):
        with st.spinner("Checking backend…"):
            st.session_state["bp_health"] = {
                "live": check_endpoint(api_url, "/healthz"),
                "ready": check_endpoint(api_url, "/readyz"),
                "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
    health = st.session_state.get("bp_health")
    if health:
        left, middle, right = st.columns(3)
        live, ready = health["live"], health["ready"]
        left.metric("API liveness", "Healthy" if live[0] else "Unavailable", f"{live[2]:.0f} ms")
        middle.metric("Database readiness", "Ready" if ready[0] else "Not ready", f"{ready[2]:.0f} ms")
        right.metric("Last checked", health["checked_at"])
        if live[0] and ready[0]:
            st.success("Backend and database readiness endpoints responded successfully.")
        else:
            st.error("One or more checks failed. Inspect Railway logs and the endpoint result below.")
        with st.expander("Technical details"):
            st.write({"healthz": live[1], "readyz": ready[1]})
    else:
        st.info("Run a health check to see the current service status.")
    st.divider()
    st.subheader("Quick links")
    a, b, c = st.columns(3)
    a.markdown('<div class="bp-card"><strong>Main ATS</strong><p class="bp-muted">Recruiting application</p><a href="https://bluepace-ats-frontend.vercel.app/?mode=admin" target="_blank">Open ATS ↗</a></div>', unsafe_allow_html=True)
    b.markdown(f'<div class="bp-card"><strong>API documentation</strong><p class="bp-muted">Explore backend routes</p><a href="{api_url}/docs" target="_blank">Open API docs ↗</a></div>', unsafe_allow_html=True)
    c.markdown(f'<div class="bp-card"><strong>Readiness endpoint</strong><p class="bp-muted">Database dependency check</p><a href="{api_url}/readyz" target="_blank">Open readiness ↗</a></div>', unsafe_allow_html=True)

elif page == "Resume review":
    st.subheader("First-pass resume review")
    st.caption("Extracts text in this Streamlit session and compares job requirements with resume wording. It does not upload resumes to the ATS backend or make hiring decisions.")
    jd = st.text_area("Job description / required skills", height=180, placeholder="Paste the role summary, responsibilities and required skills…")
    files = st.file_uploader("Upload resumes (PDF, DOCX, TXT · max 5 MB each)", type=["pdf", "docx", "txt"], accept_multiple_files=True)
    if files and any(file.size > MAX_UPLOAD_BYTES for file in files):
        st.error("Each file must be 5 MB or smaller.")
    if st.button("Review resumes", type="primary", disabled=not jd.strip() or not files):
        required = tokens(jd)
        results = []
        progress = st.progress(0)
        for index, file in enumerate(files):
            try:
                resume_text = extract_text(file)
                resume_tokens = tokens(resume_text)
                matched = sorted(required & resume_tokens)
                missing = sorted(required - resume_tokens)
                score = round((len(matched) / len(required)) * 100) if required else 0
                results.append({"Resume": file.name, "Keyword overlap": score, "Matched terms": ", ".join(matched[:35]) or "None found", "Terms to verify": ", ".join(missing[:35]) or "None"})
            except Exception as exc:
                results.append({"Resume": file.name, "Keyword overlap": None, "Matched terms": "Could not process", "Terms to verify": str(exc)[:200]})
            progress.progress((index + 1) / len(files))
        st.session_state["bp_resume_results"] = results
    results = st.session_state.get("bp_resume_results")
    if results:
        st.dataframe(results, use_container_width=True, hide_index=True)
        st.caption("Keyword overlap is a basic text comparison, not a suitability score. Review each resume fairly and verify skills in context.")
        import csv
        csv_buffer = io.StringIO()
        writer = csv.DictWriter(csv_buffer, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(results)
        st.download_button("Download review as CSV", csv_buffer.getvalue(), file_name="bluepace_resume_review.csv", mime="text/csv")

elif page == "Zoho Recruit":
    st.subheader("Zoho Recruit → BluePace")
    st.caption("Read-only inbound sync for candidates and job openings. OAuth secrets stay on the backend.")
    with st.form("zoho_admin_login"):
        email = st.text_input("BluePace recruiter email")
        password = st.text_input("BluePace password", type="password")
        login = st.form_submit_button("Connect to BluePace")
    if login:
        try:
            response = requests.post(f"{api_url}/auth/token", data={"username": email, "password": password}, timeout=(3, 15))
            if response.ok and response.json().get("access_token"):
                st.session_state["bp_zoho_access_token"] = response.json()["access_token"]
                st.success("Connected to BluePace backend.")
            else:
                st.error("Login failed. Check your BluePace credentials and backend URL.")
        except requests.RequestException:
            st.error("Could not reach the BluePace backend.")
    token = st.session_state.get("bp_zoho_access_token")
    if token:
        headers = {"Authorization": f"Bearer {token}"}
        left, right = st.columns(2)
        if left.button("Check Zoho integration status", type="primary"):
            try:
                response = requests.get(f"{api_url}/integrations/zoho/status", headers=headers, timeout=(3, 15))
                if response.ok:
                    st.session_state["bp_zoho_status"] = response.json()
                else:
                    st.error(f"Status check failed (HTTP {response.status_code}).")
            except requests.RequestException:
                st.error("Could not reach the BluePace backend.")
        status_data = st.session_state.get("bp_zoho_status")
        if status_data:
            a, b, d = st.columns(3)
            a.metric("OAuth configuration", "Configured" if status_data.get("configured") else "Missing")
            b.metric("Automatic sync", "Enabled" if status_data.get("automatic_sync_enabled") else "Disabled")
            d.metric("Polling interval", f"{status_data.get('interval_minutes', 15)} min")
            st.caption("Direction: Zoho Recruit → BluePace ATS. Credential values are never returned.")
        if right.button("Run sync now"):
            try:
                response = requests.post(f"{api_url}/integrations/zoho/sync", headers=headers, timeout=(5, 120))
                if response.ok:
                    st.success("Sync completed.")
                    st.json(response.json())
                elif response.status_code == 503:
                    st.error("Zoho OAuth credentials are not configured on the backend yet.")
                else:
                    st.error(f"Sync failed (HTTP {response.status_code}). Check Railway logs and Zoho permissions.")
            except requests.RequestException:
                st.error("Sync request failed or timed out. Check backend logs before retrying.")
        if st.button("Disconnect this workspace"):
            st.session_state.pop("bp_zoho_access_token", None)
            st.session_state.pop("bp_zoho_status", None)
            st.rerun()
    else:
        st.caption("Sign in with a BluePace admin or recruiter account to inspect or trigger sync.")
    st.markdown("**Backend environment variables**")
    st.markdown("**Zoho webhook setup**")
    st.markdown("In Zoho Recruit, open **Setup → Automation → Actions → Webhooks**, create a POST webhook pointing at the endpoint above, and add a custom parameter named `webhook_token` with the same value as `ZOHO_WEBHOOK_SECRET`. Associate it with workflow rules for Candidates and Job Openings create/update events, then test using a non-production record. The endpoint treats webhook data only as a wake-up signal and reloads canonical records through the OAuth API.")
    st.caption("Zoho workflow webhooks require Manage Workflow permission. Keep the webhook secret private; do not put it in public documentation or screenshots.")
    st.code("ZOHO_CLIENT_ID\nZOHO_CLIENT_SECRET\nZOHO_REFRESH_TOKEN\nZOHO_ACCOUNTS_DOMAIN=in\nZOHO_RECRUIT_API_BASE=https://recruit.zoho.in/recruit/v2\nZOHO_ORGANIZATION_ID=<BluePace organization ID>\nZOHO_SYNC_ENABLED=true\nZOHO_SYNC_INTERVAL_MINUTES=15", language="text")

else:
    st.subheader("Integration guide")
    st.markdown("""
**Deploy as a separate Streamlit app** so it does not interfere with the Vercel frontend or Railway API.

1. Select this repository in Streamlit Community Cloud.
2. Set the app file path to streamlit_app/app.py.
3. Use Python 3.11 or a compatible runtime.
4. Deploy, then use the sidebar to point at the Railway backend.
5. No API keys are required for the included features.

**Current scope**
- Backend liveness and readiness checks
- Local PDF/DOCX/TXT text extraction with a 5 MB per-file cap
- Basic keyword overlap report with CSV export

Resume content is processed in the running app session. Do not upload confidential production resumes to a public demo deployment.
""")
    st.code("streamlit run streamlit_app/app.py", language="bash")
