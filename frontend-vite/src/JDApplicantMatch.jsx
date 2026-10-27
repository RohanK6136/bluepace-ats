import { useCallback, useEffect, useMemo, useState } from "react";

const primaryButton = "inline-flex items-center justify-center gap-2 rounded-md bg-[#c49a4a] px-4 py-2.5 text-sm font-semibold text-[#11141c] transition hover:bg-[#d4b06a] disabled:cursor-not-allowed disabled:opacity-50";
const secondaryButton = "inline-flex items-center justify-center gap-2 rounded-md border border-ink-200 bg-white px-3 py-2 text-sm font-semibold text-ink-800 transition hover:bg-ink-50 disabled:cursor-not-allowed disabled:opacity-50";
const fieldClass = "w-full rounded-md border border-ink-200 bg-white px-3 py-2.5 text-sm text-ink-900 outline-none placeholder:text-ink-400 focus:border-gold-500 focus:ring-2 focus:ring-gold-100";
const MAX_FILE_BYTES = 5 * 1024 * 1024;

function explainError(error) {
  const detail = error?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (detail?.message) return detail.message;
  if (detail?.detail) return String(detail.detail);
  if (Array.isArray(detail)) return detail.map((item) => item.msg || String(item)).join("; ");
  if (error?.response?.status === 404) return "This backend does not expose the JD Standardizer / Applicant Match API routes yet. The frontend is deployed, but the backend needs a compatible deployment.";
  if (error?.response?.status === 401 || error?.response?.status === 403) return "The backend rejected this request. Check the optional X-API-Key in API access settings.";
  if (error?.response) return `AI Feature API returned HTTP ${error.response.status}.`;
  if (error?.request) return "The backend could not be reached. Confirm the API service is running and configured for this frontend.";
  return error?.message || "The request failed. Review the configuration and try again.";
}

function Pill({ children, tone = "neutral" }) {
  const tones = {
    neutral: "border-ink-200 bg-ink-50 text-ink-600",
    good: "border-emerald-200 bg-emerald-50 text-emerald-800",
    warn: "border-amber-200 bg-amber-50 text-amber-800",
    bad: "border-rose-200 bg-rose-50 text-rose-800",
    gold: "border-[#e5d2a6] bg-[#fbf6e9] text-[#72541d]",
  };
  return <span className={`inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-semibold ${tones[tone] || tones.neutral}`}>{children}</span>;
}

function SectionHeading({ eyebrow, title, detail, action }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div>
        {eyebrow && <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-500">{eyebrow}</p>}
        <h2 className="mt-1 text-lg font-semibold tracking-tight text-ink-950">{title}</h2>
        {detail && <p className="mt-1 max-w-3xl text-sm leading-6 text-ink-500">{detail}</p>}
      </div>
      {action}
    </div>
  );
}

function Field({ label, children, hint }) {
  return <label className="grid gap-1.5 text-xs font-semibold text-ink-700"><span>{label}</span>{children}{hint && <span className="font-normal leading-5 text-ink-500">{hint}</span>}</label>;
}

function ScoreMetric({ label, value, detail }) {
  return <div className="rounded-lg border border-ink-100 bg-white p-4"><p className="text-[11px] font-semibold uppercase tracking-wide text-ink-500">{label}</p><p className="mt-2 text-2xl font-semibold tabular-nums text-ink-950">{value ?? "—"}</p>{detail && <p className="mt-1 text-xs text-ink-500">{detail}</p>}</div>;
}

function ErrorNotice({ children }) {
  if (!children) return null;
  return <div role="alert" className="rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm leading-6 text-rose-900">{children}</div>;
}

function EmptyPanel({ title, detail }) {
  return <div className="rounded-lg border border-dashed border-ink-200 bg-white px-5 py-9 text-center"><p className="text-sm font-semibold text-ink-800">{title}</p><p className="mx-auto mt-1 max-w-lg text-sm leading-6 text-ink-500">{detail}</p></div>;
}

export default function JDApplicantMatch({ token, apiRequest }) {
  const [activeTab, setActiveTab] = useState("jd");
  const [apiKey, setApiKey] = useState(() => {
    try { return sessionStorage.getItem("bluepace_feature_api_key") || ""; } catch { return ""; }
  });
  const [models, setModels] = useState([]);
  const [selectedProfile, setSelectedProfile] = useState("");
  const [connection, setConnection] = useState("checking");
  const [connectionMessage, setConnectionMessage] = useState("Checking the AI Feature API…");
  const [jdText, setJdText] = useState("");
  const [jdMode, setJdMode] = useState("light");
  const [jdDetail, setJdDetail] = useState("detailed");
  const [jdResult, setJdResult] = useState(null);
  const [jdLoading, setJdLoading] = useState(false);
  const [jdError, setJdError] = useState("");
  const [rubric, setRubric] = useState(null);
  const [rubricNotes, setRubricNotes] = useState([]);
  const [savedRubrics, setSavedRubrics] = useState([]);
  const [selectedRubricId, setSelectedRubricId] = useState("");
  const [rubricLoading, setRubricLoading] = useState(false);
  const [rubricError, setRubricError] = useState("");
  const [resumeFile, setResumeFile] = useState(null);
  const [resumeText, setResumeText] = useState("");
  const [candidateCard, setCandidateCard] = useState(null);
  const [matchLoading, setMatchLoading] = useState(false);
  const [matchError, setMatchError] = useState("");
  const [notice, setNotice] = useState("");

  const request = useCallback((method, path, data, options = {}) => {
    const headers = { ...(options.headers || {}) };
    if (apiKey.trim()) headers["X-API-Key"] = apiKey.trim();
    const requestOptions = { ...options, headers };
    if (data !== undefined) requestOptions.data = data;
    return apiRequest(token, method, path, requestOptions);
  }, [apiKey, apiRequest, token]);

  const refreshConnection = useCallback(async () => {
    setConnection("checking");
    setConnectionMessage("Checking the AI Feature API…");
    try {
      const response = await request("get", "/v1/models", undefined, { timeout: 8000 });
      const rows = Array.isArray(response.data) ? response.data : [];
      setModels(rows);
      setConnection("connected");
      setConnectionMessage(rows.length ? `${rows.filter((model) => model.enabled).length} model profile(s) ready` : "API reachable; no model profiles were returned");
      setSelectedProfile((current) => current || rows.find((model) => model.enabled && model.is_default)?.id || rows.find((model) => model.enabled)?.id || "");
      setJdError("");
      setRubricError((current) => current.includes("does not expose") ? "" : current);
    } catch (error) {
      setModels([]);
      setConnection("unavailable");
      setConnectionMessage(explainError(error));
    }
  }, [request]);

  const refreshSavedRubrics = useCallback(async () => {
    try {
      const response = await request("get", "/v1/match/rubrics", undefined, { params: { limit: 50 }, timeout: 10000 });
      setSavedRubrics(Array.isArray(response.data) ? response.data : []);
    } catch (error) {
      // Connection feedback is shown in the workspace banner. Do not replace a
      // successfully rendered draft with a secondary list request failure.
      setRubricError((current) => current || explainError(error));
    }
  }, [request]);

  useEffect(() => {
    refreshConnection();
  }, [refreshConnection]);

  useEffect(() => {
    if (activeTab === "match" && connection === "connected") refreshSavedRubrics();
  }, [activeTab, connection, refreshSavedRubrics]);


  function updateApiKey(value) {
    setApiKey(value);
    try {
      if (value) sessionStorage.setItem("bluepace_feature_api_key", value);
      else sessionStorage.removeItem("bluepace_feature_api_key");
    } catch {
      // Continue with an in-memory key if session storage is disabled.
    }
    setNotice(value ? "API key kept for this browser session only." : "Optional API key cleared.");
  }

  async function runJD(mode) {
    if (!jdText.trim()) {
      setJdError("Paste a job description or a role brief before running the standardizer.");
      return;
    }
    setJdLoading(true);
    setJdError("");
    setNotice("");
    setJdResult(null);
    try {
      const payload = {
        text: jdText.trim(),
        options: { mode: jdMode, detail: jdDetail, ...(selectedProfile ? { profile: selectedProfile } : {}) },
        overrides: {},
      };
      const response = await request("post", mode === "fast" ? "/v1/jd/generate" : "/v1/jd/standardize", payload, { timeout: 120000 });
      setJdResult(response.data);
      if (response.data?.request_id) setNotice(`Run completed · ${response.data.request_id}`);
    } catch (error) {
      setJdError(explainError(error));
    } finally {
      setJdLoading(false);
    }
  }

  async function compileRubric() {
    if (!jdText.trim()) {
      setRubricError("Add a job description on the JD Standardizer tab first, or paste it into the field below.");
      return;
    }
    setRubricLoading(true);
    setRubricError("");
    setNotice("");
    setCandidateCard(null);
    try {
      const response = await request("post", "/v1/match/rubrics", {
        jd_text: jdText.trim(),
        options: selectedProfile ? { profile: selectedProfile } : {},
      }, { timeout: 120000 });
      const nextRubric = response.data?.rubric || response.data;
      setRubric(nextRubric);
      setSelectedRubricId(nextRubric?.rubric_id || "");
      setRubricNotes(response.data?.notes || []);
      setNotice("Rubric draft created. Review the requirements and weights before saving.");
      await refreshSavedRubrics();
    } catch (error) {
      setRubricError(explainError(error));
    } finally {
      setRubricLoading(false);
    }
  }

  async function loadRubric(id) {
    setSelectedRubricId(id);
    setRubricError("");
    if (!id) {
      setRubric(null);
      setCandidateCard(null);
      return;
    }
    setRubricLoading(true);
    try {
      const response = await request("get", `/v1/match/rubrics/${encodeURIComponent(id)}`, undefined, { timeout: 10000 });
      setRubric(response.data);
      setCandidateCard(null);
      setNotice(`Loaded rubric ${id}.`);
    } catch (error) {
      setRubricError(explainError(error));
    } finally {
      setRubricLoading(false);
    }
  }

  async function saveRubric() {
    if (!rubric) return;
    setRubricLoading(true);
    setRubricError("");
    setNotice("");
    try {
      const response = await request("post", "/v1/match/rubrics", { rubric }, { timeout: 30000 });
      setRubric(response.data);
      setSelectedRubricId(response.data?.rubric_id || "");
      setNotice(`Rubric version saved · ${response.data?.rubric_id || "saved"}`);
      await refreshSavedRubrics();
    } catch (error) {
      setRubricError(explainError(error));
    } finally {
      setRubricLoading(false);
    }
  }

  async function analyzeResume() {
    if (!selectedRubricId) {
      setMatchError("Select a saved rubric or save the draft rubric first.");
      return;
    }
    if (!resumeFile && !resumeText.trim()) {
      setMatchError("Upload a resume (PDF, DOCX or TXT up to 5 MB) or paste resume text.");
      return;
    }
    if (resumeFile && resumeFile.size > MAX_FILE_BYTES) {
      setMatchError("Resume must be 5 MB or smaller.");
      return;
    }
    setMatchLoading(true);
    setMatchError("");
    setCandidateCard(null);
    setNotice("");
    try {
      const body = new FormData();
      body.append("rubric_id", selectedRubricId);
      if (resumeFile) body.append("file", resumeFile);
      else body.append("text", resumeText.trim());
      if (selectedProfile) body.append("profile", selectedProfile);
      const response = await request("post", "/v1/match/analyze", body, { timeout: 120000 });
      setCandidateCard(response.data);
      setNotice("Analysis complete. Review the evidence before making any recruiting decision.");
    } catch (error) {
      setMatchError(explainError(error));
    } finally {
      setMatchLoading(false);
    }
  }

  function updateRubricItem(index, patch) {
    setRubric((current) => current ? {
      ...current,
      rubric_id: null,
      rubric_hash: null,
      created_at: null,
      items: current.items.map((item, itemIndex) => itemIndex === index ? { ...item, ...patch } : item),
    } : current);
    setSelectedRubricId("");
    setCandidateCard(null);
  }

  function updateRubricWeight(key, value) {
    setRubric((current) => current ? {
      ...current,
      rubric_id: null,
      rubric_hash: null,
      created_at: null,
      weights: { ...current.weights, [key]: Number(value) },
    } : current);
    setSelectedRubricId("");
    setCandidateCard(null);
  }

  const jdTitle = jdResult?.fields?.title?.value || jdResult?.fields?.title?.raw || "Job description review";
  const matchScore = candidateCard?.scores?.match;

  return (
    <div className="space-y-6">
      <section className="overflow-hidden rounded-xl border border-ink-200 bg-white shadow-sm">
        <div className="bg-ink-950 px-5 py-6 text-white sm:px-7">
          <div className="flex flex-wrap items-start justify-between gap-5">
            <div className="max-w-3xl">
              <div className="flex flex-wrap items-center gap-2">
                <Pill tone="gold">NEW WORKSPACE</Pill>
                <span className="text-xs font-medium text-ink-300">JD Standardizer · Applicant Match</span>
              </div>
              <h1 className="mt-3 text-2xl font-semibold tracking-tight sm:text-3xl">From job brief to evidence-based candidate review</h1>
              <p className="mt-2 max-w-2xl text-sm leading-6 text-ink-200">Standardize a job description, turn its requirements into a reviewable rubric, then analyze resumes against job-related evidence. Recruiters remain responsible for decisions.</p>
            </div>
            <div className="min-w-[210px] rounded-lg border border-white/15 bg-white/5 p-4">
              <p className="text-[10px] font-semibold uppercase tracking-[0.13em] text-ink-300">AI service status</p>
              <div className="mt-2 flex items-center gap-2">
                <span className={`h-2.5 w-2.5 rounded-full ${connection === "connected" ? "bg-emerald-400" : connection === "checking" ? "animate-pulse bg-amber-300" : "bg-rose-400"}`} />
                <span className="text-sm font-semibold">{connection === "connected" ? "Connected" : connection === "checking" ? "Checking" : "Not connected"}</span>
              </div>
              <p className="mt-2 text-xs leading-5 text-ink-300">{connectionMessage}</p>
              <button type="button" onClick={refreshConnection} disabled={connection === "checking"} className="mt-3 text-xs font-semibold text-gold-300 underline underline-offset-4 disabled:opacity-50">Retry connection</button>
            </div>
          </div>
        </div>
        <div className="flex flex-wrap gap-2 border-b border-ink-100 bg-[#fafaf8] px-4 py-3 sm:px-6" role="tablist" aria-label="AI feature workflows">
          <button type="button" role="tab" aria-selected={activeTab === "jd"} onClick={() => setActiveTab("jd")} className={`rounded-md px-4 py-2 text-sm font-semibold ${activeTab === "jd" ? "bg-ink-950 text-white" : "text-ink-600 hover:bg-ink-100"}`}>1 · JD Standardizer</button>
          <button type="button" role="tab" aria-selected={activeTab === "match"} onClick={() => setActiveTab("match")} className={`rounded-md px-4 py-2 text-sm font-semibold ${activeTab === "match" ? "bg-ink-950 text-white" : "text-ink-600 hover:bg-ink-100"}`}>2 · Applicant Match</button>
          <div className="ml-auto flex items-center gap-2">
            <span className="hidden text-xs text-ink-500 sm:inline">Model</span>
            <select aria-label="AI model profile" value={selectedProfile} onChange={(event) => setSelectedProfile(event.target.value)} className="max-w-[230px] rounded-md border border-ink-200 bg-white px-2.5 py-2 text-xs text-ink-700">
              <option value="">Backend default</option>
              {models.map((model) => <option key={model.id} value={model.id} disabled={!model.enabled}>{model.label}{model.enabled ? "" : " · unavailable"}</option>)}
            </select>
          </div>
        </div>
        <details className="border-b border-ink-100 px-5 py-3 sm:px-6">
          <summary className="cursor-pointer text-xs font-semibold text-ink-600">API access settings (optional)</summary>
          <div className="mt-3 grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
            <Field label="X-API-Key" hint="Kept in session storage for this browser tab session. Never sent to GitHub or stored by this UI. Leave blank if the backend does not require API-key authentication.">
              <input type="password" autoComplete="off" value={apiKey} onChange={(event) => updateApiKey(event.target.value)} placeholder="Paste API key only if your backend requires one" className={fieldClass} />
            </Field>
            <button type="button" className={secondaryButton} onClick={refreshConnection}>Test API connection</button>
          </div>
        </details>
        <div className="px-5 py-5 sm:px-7 sm:py-6">
          {notice && <div role="status" className="mb-4 rounded-md border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-900">{notice}</div>}
          {connection === "unavailable" && (
            <div className="mb-5 rounded-md border border-amber-200 bg-amber-50 px-4 py-3">
              <p className="text-sm font-semibold text-amber-950">The interface is deployed; the AI API is not confirmed available.</p>
              <p className="mt-1 text-sm leading-6 text-amber-900">{connectionMessage}</p>
              <p className="mt-2 text-xs leading-5 text-amber-900">The front end and AI backend deploy separately. This panel will not fabricate results or silently switch to local mock output.</p>
            </div>
          )}

          {activeTab === "jd" && (
            <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(330px,0.9fr)]">
              <div className="space-y-4">
                <SectionHeading eyebrow="Step 01" title="Job description input" detail="Paste the recruiter brief or current job description. The API supports strict standardization and a faster draft mode." />
                <Field label="Job description or brief" hint={`${jdText.length.toLocaleString()} characters · API input limit is deployment-configured`}>
                  <textarea value={jdText} onChange={(event) => setJdText(event.target.value)} rows={13} maxLength={60000} placeholder={"Example: Senior Data Engineer\nLocation: Hyderabad / Hybrid\nRequired: Python, SQL, Airflow, cloud data platforms\nResponsibilities: Build reliable data pipelines, own data quality, and partner with analytics teams."} className={`${fieldClass} resize-y leading-6`} />
                </Field>
                <div className="grid gap-3 sm:grid-cols-2">
                  <Field label="Writing mode">
                    <select value={jdMode} onChange={(event) => setJdMode(event.target.value)} className={fieldClass}>
                      <option value="verbatim">Verbatim · preserve source</option>
                      <option value="light">Light edit · improve clarity</option>
                      <option value="rewrite">Rewrite · restructure language</option>
                    </select>
                  </Field>
                  <Field label="Fast draft detail">
                    <select value={jdDetail} onChange={(event) => setJdDetail(event.target.value)} className={fieldClass}>
                      <option value="detailed">Detailed draft</option>
                      <option value="concise">Concise draft</option>
                    </select>
                  </Field>
                </div>
                <ErrorNotice>{jdError}</ErrorNotice>
                <div className="flex flex-wrap gap-2">
                  <button type="button" className={primaryButton} onClick={() => runJD("strict")} disabled={jdLoading || connection !== "connected" || !jdText.trim()}>{jdLoading ? "Processing…" : "Standardize JD"}</button>
                  <button type="button" className={secondaryButton} onClick={() => runJD("fast")} disabled={jdLoading || connection !== "connected" || !jdText.trim()}>{jdLoading ? "Processing…" : "Generate fast draft"}</button>
                  <button type="button" className={secondaryButton} onClick={() => { setJdText(""); setJdResult(null); setJdError(""); setNotice(""); }}>Clear</button>
                </div>
              </div>
              <div className="space-y-4">
                <SectionHeading eyebrow="Step 02" title="Standardized output" detail="Review flags and missing details before using the content in a live requisition." />
                {!jdResult && <EmptyPanel title="Your result will appear here" detail="Run either workflow to see the pipeline status, publication blockers, extracted facts, and standardized description." />}
                {jdResult && (
                  <div className="space-y-4">
                    <div className="flex flex-wrap items-center gap-2">
                      <Pill tone={jdResult.publishable ? "good" : jdResult.status === "ok" ? "warn" : "neutral"}>{jdResult.status || "complete"}</Pill>
                      <Pill tone={jdResult.publishable ? "good" : "warn"}>{jdResult.publishable ? "Ready for recruiter review" : "Review required"}</Pill>
                      {jdResult.meta?.latency_ms != null && <Pill>{(jdResult.meta.latency_ms / 1000).toFixed(1)}s</Pill>}
                      {jdResult.meta?.llm_calls != null && <Pill>{jdResult.meta.llm_calls} model calls</Pill>}
                    </div>
                    {Array.isArray(jdResult.publish_blockers) && jdResult.publish_blockers.length > 0 && <div className="rounded-md border border-rose-200 bg-rose-50 p-3"><p className="text-xs font-semibold uppercase tracking-wide text-rose-900">Publication blockers</p><ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-rose-900">{jdResult.publish_blockers.map((item, index) => <li key={index}>{item}</li>)}</ul></div>}
                    {Array.isArray(jdResult.flags) && jdResult.flags.length > 0 && <div className="rounded-md border border-amber-200 bg-amber-50 p-3"><p className="text-xs font-semibold uppercase tracking-wide text-amber-900">Review flags</p><ul className="mt-2 space-y-2 text-sm text-amber-950">{jdResult.flags.map((flag, index) => <li key={index}><span className="font-semibold">{flag.severity || "info"}:</span> {flag.message || flag.code}</li>)}</ul></div>}
                    <div className="rounded-lg border border-ink-100 bg-white p-4">
                      <p className="text-sm font-semibold text-ink-900">{jdTitle}</p>
                      <p className="mt-1 text-xs text-ink-500">Request ID: {jdResult.request_id || "not supplied"}</p>
                      <div className="mt-4 grid grid-cols-2 gap-3">
                        <ScoreMetric label="Status" value={jdResult.status || "—"} detail="Pipeline outcome" />
                        <ScoreMetric label="Est. model cost" value={jdResult.meta?.cost_usd != null ? `$${Number(jdResult.meta.cost_usd).toFixed(4)}` : "—"} detail="Provider-reported / configured estimate" />
                      </div>
                    </div>
                    {(jdResult.needs_input || []).length > 0 && <div className="rounded-md border border-amber-200 bg-amber-50 p-3"><p className="text-sm font-semibold text-amber-950">Details to confirm</p><ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-amber-900">{jdResult.needs_input.map((item, index) => <li key={index}>{item.field}: {item.reason}</li>)}</ul></div>}
                    {(jdResult.sections || []).map((section) => <div key={section.id} className="rounded-lg border border-ink-100 bg-white p-4"><div className="flex flex-wrap items-center justify-between gap-2"><h3 className="text-sm font-semibold">{section.heading}</h3><Pill>{section.status}</Pill></div><ul className="mt-3 list-disc space-y-1.5 pl-5 text-sm leading-6 text-ink-700">{(section.items || []).map((item, index) => <li key={index}>{item.text}{item.origin === "ai_draft" && <span className="ml-2 text-[10px] font-semibold uppercase text-amber-700">AI draft</span>}</li>)}</ul></div>)}
                    {jdResult.description_markdown && <details open className="rounded-lg border border-ink-100 bg-white p-4"><summary className="cursor-pointer text-sm font-semibold">Full job description</summary><pre className="mt-3 max-h-[520px] overflow-auto whitespace-pre-wrap text-sm leading-6 text-ink-700">{jdResult.description_markdown}</pre></details>}
                    <button type="button" className={primaryButton} onClick={() => { setActiveTab("match"); setRubricError(""); }} disabled={!jdResult.description_markdown && !jdText.trim()}>Continue to Applicant Match</button>
                  </div>
                )}
              </div>
            </div>
          )}

          {activeTab === "match" && (
            <div className="space-y-7">
              <div className="grid gap-5 xl:grid-cols-2">
                <div className="space-y-4">
                  <SectionHeading eyebrow="Step 03" title="Build a reviewable rubric" detail="Create a draft from the job description, check the requirements, then save an immutable rubric version before assessing resumes." />
                  <Field label="Saved rubric version">
                    <select value={selectedRubricId} onChange={(event) => loadRubric(event.target.value)} className={fieldClass} disabled={rubricLoading}>
                      <option value="">Choose a saved rubric…</option>
                      {savedRubrics.map((item) => <option key={item.rubric_id} value={item.rubric_id}>{item.title || "Untitled role"} · {item.items} requirements · {item.rubric_id}</option>)}
                    </select>
                  </Field>
                  <div className="flex flex-wrap gap-2">
                    <button type="button" className={primaryButton} onClick={compileRubric} disabled={rubricLoading || connection !== "connected" || !jdText.trim()}>{rubricLoading ? "Building…" : "Build rubric from JD text"}</button>
                    <button type="button" className={secondaryButton} onClick={refreshSavedRubrics} disabled={connection !== "connected" || rubricLoading}>Refresh saved rubrics</button>
                  </div>
                  <ErrorNotice>{rubricError}</ErrorNotice>
                  {rubricNotes.length > 0 && <div className="rounded-md border border-amber-200 bg-amber-50 p-3"><p className="text-xs font-semibold uppercase tracking-wide text-amber-900">Compiler notes</p><ul className="mt-2 space-y-1 text-sm text-amber-950">{rubricNotes.map((note, index) => <li key={index}>{note.message || note.code}</li>)}</ul></div>}
                  {rubric && (
                    <div className="space-y-4 rounded-lg border border-ink-100 bg-[#fafaf8] p-4">
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div><p className="text-sm font-semibold text-ink-950">{rubric.title || "Job assessment rubric"}</p><p className="mt-1 text-xs text-ink-500">Review and adjust importance / weight before saving.</p></div>
                        <Pill tone={rubric.rubric_id ? "good" : "gold"}>{rubric.rubric_id ? `Saved · ${rubric.rubric_id}` : "Draft · not saved"}</Pill>
                      </div>
                      <div className="grid gap-3 sm:grid-cols-2">
                        <Field label="Minimum years of experience">
                          <input className={fieldClass} type="number" min="0" max="40" step="0.5" value={rubric.required_years ?? ""} onChange={(event) => { setRubric({ ...rubric, rubric_id: null, rubric_hash: null, required_years: event.target.value === "" ? null : Number(event.target.value), created_at: null }); setSelectedRubricId(""); setCandidateCard(null); }} />
                        </Field>
                        <Field label="Education minimum">
                          <select className={fieldClass} value={rubric.education?.min_level || "none"} onChange={(event) => { setRubric({ ...rubric, rubric_id: null, rubric_hash: null, education: { ...(rubric.education || {}), min_level: event.target.value }, created_at: null }); setSelectedRubricId(""); setCandidateCard(null); }}>
                            {["none", "high_school", "diploma", "associate", "bachelor", "master", "phd"].map((level) => <option key={level} value={level}>{level.replaceAll("_", " ")}</option>)}
                          </select>
                        </Field>
                      </div>
                      <div className="grid gap-3 sm:grid-cols-2">
                        {[
                          ["required_skills", "Required skills"],
                          ["experience", "Experience"],
                          ["preferred_skills", "Preferred skills"],
                          ["education", "Education"],
                        ].map(([key, label]) => <Field key={key} label={`${label} weight · ${rubric.weights?.[key] ?? 0}`}>
                          <input className="w-full accent-[#c49a4a]" type="range" min="0" max="100" value={rubric.weights?.[key] ?? 0} onChange={(event) => updateRubricWeight(key, event.target.value)} />
                        </Field>)}
                      </div>
                      <div className="space-y-2">
                        {(rubric.items || []).map((item, index) => <div key={item.id || index} className="grid gap-3 rounded-md border border-ink-100 bg-white p-3 sm:grid-cols-[minmax(0,1fr)_130px_100px] sm:items-center">
                          <div><p className="text-sm font-medium text-ink-900">{item.label}</p><p className="mt-1 text-xs text-ink-500">{item.type} · {item.group}</p></div>
                          <Field label="Importance"><select className={fieldClass} value={item.importance} onChange={(event) => updateRubricItem(index, { importance: event.target.value })}><option value="must">Must-have</option><option value="nice">Preferred</option></select></Field>
                          <Field label="Weight"><select className={fieldClass} value={item.weight || 1} onChange={(event) => updateRubricItem(index, { weight: Number(event.target.value) })}><option value="1">1 · Base</option><option value="2">2 · High</option><option value="3">3 · Critical</option></select></Field>
                        </div>)}
                        {!rubric.items?.length && <p className="text-sm text-ink-500">No rubric items were returned. Review the JD and build the rubric again.</p>}
                      </div>
                      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-ink-200 pt-4">
                        <span className="text-xs text-ink-500">{rubric.items?.length || 0} requirements · immutable versions after saving</span>
                        <button type="button" className={primaryButton} onClick={saveRubric} disabled={rubricLoading || !rubric.items?.length}>{rubricLoading ? "Saving…" : "Save rubric version"}</button>
                      </div>
                    </div>
                  )}
                </div>

                <div className="space-y-4">
                  <SectionHeading eyebrow="Step 04" title="Analyze a resume" detail="Use a saved rubric to compare a resume with job-related criteria. The API is designed to keep personal identifiers out of model inputs." />
                  <div className="rounded-lg border border-ink-100 bg-white p-4">
                    <Field label="Resume file" hint="PDF, DOCX or TXT · maximum 5 MB">
                      <input className={fieldClass} type="file" accept=".pdf,.docx,.txt,.md" onChange={(event) => { const file = event.target.files?.[0] || null; setResumeFile(file); setMatchError(file && file.size > MAX_FILE_BYTES ? "Resume must be 5 MB or smaller." : ""); if (file && file.size > MAX_FILE_BYTES) setResumeFile(null); }} />
                    </Field>
                    <div className="my-4 flex items-center gap-3 text-xs text-ink-400"><span className="h-px flex-1 bg-ink-100" />OR PASTE TEXT<span className="h-px flex-1 bg-ink-100" /></div>
                    <Field label="Resume text">
                      <textarea rows={7} value={resumeText} onChange={(event) => setResumeText(event.target.value)} placeholder="Paste resume content here when you do not have a file to upload." className={`${fieldClass} resize-y leading-6`} />
                    </Field>
                    {resumeFile && <p className="mt-2 text-xs text-ink-500">{resumeFile.name} · {(resumeFile.size / (1024 * 1024)).toFixed(2)} MB</p>}
                    <ErrorNotice>{matchError}</ErrorNotice>
                    <button type="button" className={primaryButton + " mt-4 w-full"} onClick={analyzeResume} disabled={matchLoading || connection !== "connected" || !selectedRubricId || (!resumeFile && !resumeText.trim())}>{matchLoading ? "Analyzing evidence…" : "Analyze resume against rubric"}</button>
                    <p className="mt-3 text-xs leading-5 text-ink-500">AI output is decision support only. It does not accept, reject, or shortlist a candidate automatically.</p>
                  </div>
                </div>
              </div>

              {candidateCard && (
                <section className="space-y-4 border-t border-ink-200 pt-6">
                  <SectionHeading eyebrow="Evidence review" title="Applicant assessment" detail="Review source evidence and missing or unclear information. An absent detail is not proof of a candidate's ability." />
                  <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                    <ScoreMetric label="Job match" value={matchScore == null ? "Manual review" : `${matchScore}%`} detail="Evidence-weighted result, not a hiring decision" />
                    <ScoreMetric label="Experience" value={candidateCard.scores?.experience?.pct == null ? "—" : `${candidateCard.scores.experience.pct}%`} detail={candidateCard.profile?.relevant_years == null ? "Relevant years not established" : `${candidateCard.profile.relevant_years} relevant years`} />
                    <ScoreMetric label="Required skills" value={candidateCard.scores?.required_skills?.pct == null ? "—" : `${candidateCard.scores.required_skills.pct}%`} detail={`${candidateCard.scores?.required_skills?.met ?? 0} of ${candidateCard.scores?.required_skills?.total ?? 0} evidenced`} />
                    <ScoreMetric label="Education" value={candidateCard.scores?.education?.pct == null ? "—" : `${candidateCard.scores.education.pct}%`} detail={candidateCard.profile?.education_level || "Not established"} />
                  </div>
                  <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm leading-6 text-amber-950"><strong>Recruiter review required.</strong> This assessment is based on resume-derived evidence; verify any important claim directly and apply the same criteria consistently across applicants.</div>
                  {candidateCard.summary?.value && <div className="rounded-lg border border-ink-100 bg-white p-4"><p className="text-xs font-semibold uppercase tracking-wide text-ink-500">Evidence summary · {candidateCard.summary.status}</p><p className="mt-2 text-sm leading-6 text-ink-800">{candidateCard.summary.value}</p>{candidateCard.summary.reason && <p className="mt-2 text-xs text-ink-500">{candidateCard.summary.reason}</p>}</div>}
                  {(candidateCard.evidence || []).map((item) => <div key={item.item_id} className="rounded-lg border border-ink-100 bg-white p-4"><div className="flex flex-wrap items-center justify-between gap-2"><div><p className="text-sm font-semibold text-ink-900">{item.label}</p><p className="mt-1 text-xs text-ink-500">{item.importance === "must" ? "Must-have" : "Preferred"} · {item.group}</p></div><Pill tone={item.status === "met" ? "good" : item.status === "partial" ? "warn" : "neutral"}>{item.status.replaceAll("_", " ")}</Pill></div>{item.note && <p className="mt-2 text-sm leading-6 text-ink-700">{item.note}</p>}{item.lines?.length > 0 && <ul className="mt-3 space-y-2">{item.lines.map((line) => <li key={line.id} className="border-l-2 border-gold-400 pl-3 text-sm leading-6 text-ink-600"><span className="mr-2 text-xs font-semibold text-ink-400">{line.id}</span>{line.text}</li>)}</ul>}</div>)}
                  {candidateCard.gaps?.length > 0 && <div className="rounded-lg border border-ink-100 bg-white p-4"><h3 className="text-sm font-semibold text-ink-900">Gaps and items to verify</h3><ul className="mt-3 space-y-2">{candidateCard.gaps.map((gap) => <li key={gap.item_id} className="flex flex-wrap items-start justify-between gap-2 border-b border-ink-100 pb-2 last:border-0"><span className="text-sm text-ink-800">{gap.label}{gap.note && <span className="mt-1 block text-xs leading-5 text-ink-500">{gap.note}</span>}</span><Pill tone={gap.importance === "must" ? "warn" : "neutral"}>{gap.status.replaceAll("_", " ")}</Pill></li>)}</ul></div>}
                  {candidateCard.flags?.length > 0 && <div className="rounded-lg border border-amber-200 bg-amber-50 p-4"><h3 className="text-sm font-semibold text-amber-950">Review flags</h3><ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-amber-900">{candidateCard.flags.map((flag, index) => <li key={index}>{flag}</li>)}</ul></div>}
                </section>
              )}
            </div>
          )}
        </div>
      </section>
      <p className="text-xs leading-5 text-ink-500">Privacy and audit note: AI calls require a configured backend model provider. Candidate assessments remain recruiter decision support; confirm evidence and do not use the score alone to make hiring decisions.</p>
    </div>
  );
}
