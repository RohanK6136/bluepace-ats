import { useCallback, useEffect, useState } from "react";
import { buildBulkMatchCsv, MAX_BULK_RESUMES, validateBulkResume } from "./bulkMatchUtils.mjs";

const primaryButton = "inline-flex items-center justify-center gap-2 rounded-md bg-[#c49a4a] px-4 py-2.5 text-sm font-semibold text-[#11141c] transition hover:bg-[#d4b06a] disabled:cursor-not-allowed disabled:opacity-50";
const secondaryButton = "inline-flex items-center justify-center gap-2 rounded-md border border-ink-200 bg-white px-3 py-2 text-sm font-semibold text-ink-800 transition hover:bg-ink-50 disabled:cursor-not-allowed disabled:opacity-50";
const fieldClass = "w-full rounded-md border border-ink-200 bg-white px-3 py-2.5 text-sm text-ink-900 outline-none placeholder:text-ink-400 focus:border-gold-500 focus:ring-2 focus:ring-gold-100";
const MAX_FILE_BYTES = 5 * 1024 * 1024;

function readSavedRubrics() {
  try {
    const value = JSON.parse(sessionStorage.getItem("bluepace_feature_saved_rubrics") || "[]");
    return Array.isArray(value) ? value : [];
  } catch { return []; }
}
function writeSavedRubrics(rows) {
  try { sessionStorage.setItem("bluepace_feature_saved_rubrics", JSON.stringify(rows.slice(0, 50))); } catch { /* session-only convenience */ }
}
function sessionProviderKey(provider) {
  try {
    const key = sessionStorage.getItem("bluepace_ai_" + provider + "_key");
    if (key) return key.trim();
    if (provider === "openrouter") return (sessionStorage.getItem("bluepace_openrouter_key") || "").trim();
  } catch { /* session storage is optional */ }
  return "";
}

function explainError(error) {
  const status = error?.response?.status;
  const requestedPath = error?.config?.url || "";
  const detail = error?.response?.data?.detail;
  // A generic FastAPI 404 body ("Not Found") hid the more useful deployment mismatch.
  if (status === 404 && requestedPath.includes("/v1/models")) {
    return "The backend answered, but GET /v1/models is missing. Its deployed version is older than this AI workspace. Deploy the compatible backend revision before using JD Standardizer or Applicant Match.";
  }
  if (status === 404) {
    return "The backend answered, but the requested AI feature route is missing. The compatible JD Standardizer / Applicant Match backend revision has not been deployed to this API host yet.";
  }
  if (status === 503) {
    return typeof detail === "string" ? detail : "The backend is reachable, but its AI feature platform or model registry is unavailable. Check backend startup configuration.";
  }
  if (typeof detail === "string") return detail;
  if (detail?.message) return detail.message;
  if (detail?.detail) return String(detail.detail);
  if (Array.isArray(detail)) return detail.map((item) => item.msg || String(item)).join("; ");
  if (status === 401 || status === 403) return "The backend rejected this request. Check the optional X-API-Key in API access settings.";
  if (error?.response) return `AI Feature API returned HTTP ${status}.`;
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
  const [apiKeyDraft, setApiKeyDraft] = useState(() => {
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
  const [batchFiles, setBatchFiles] = useState([]);
  const [batchRunning, setBatchRunning] = useState(false);
  const [batchCurrentName, setBatchCurrentName] = useState("");
  const [batchProgress, setBatchProgress] = useState({ done: 0, total: 0 });
  const [batchError, setBatchError] = useState("");
  const [notice, setNotice] = useState("");

  const request = useCallback((method, path, data, options = {}) => {
    const headers = { ...(options.headers || {}) };
    if (apiKey.trim()) headers["X-API-Key"] = apiKey.trim();
    // Model credentials are entered in AI Hiring Studio Settings and remain in this browser tab.
    // Only JD & Applicant Match calls the same-origin Vercel function with these headers.
    const keys = [
      ["openrouter", "X-OpenRouter-Api-Key"],
      ["gemini", "X-Google-Api-Key"],
      ["deepseek", "X-DeepSeek-Api-Key"],
      ["xai", "X-XAI-Api-Key"],
      ["openai", "X-OpenAI-Api-Key"],
    ];
    for (const [provider, header] of keys) {
      const value = sessionProviderKey(provider);
      if (value) headers[header] = value;
    }
    const isFeatureRoute = String(path || "").startsWith("/v1/");
    const requestOptions = { ...options, headers, ...(isFeatureRoute ? { baseURL: window.location.origin } : {}) };
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
      setSelectedProfile((current) => rows.find((model) => model.id === current && model.enabled)?.id || rows.find((model) => model.enabled && model.is_default)?.id || rows.find((model) => model.enabled)?.id || "");
      setJdError("");
      setRubricError((current) => current.includes("does not expose") ? "" : current);
    } catch (error) {
      setModels([]);
      setConnection("unavailable");
      setConnectionMessage(explainError(error));
    }
  }, [request]);

  const refreshSavedRubrics = useCallback(async () => {
    const localRows = readSavedRubrics();
    setSavedRubrics(localRows);
    try {
      const response = await request("get", "/v1/match/rubrics", undefined, { params: { limit: 50 }, timeout: 10000 });
      const remoteRows = Array.isArray(response.data) ? response.data : [];
      const merged = [...localRows];
      for (const row of remoteRows) if (!merged.some((saved) => saved.rubric_id === row.rubric_id)) merged.push(row);
      setSavedRubrics(merged.slice(0, 50));
    } catch {
      // Serverless deployment is stateless; reviewed rubric versions are kept in this tab's session.
      setSavedRubrics(localRows);
    }
  }, [request]);

  useEffect(() => {
    refreshConnection();
  }, [refreshConnection]);

  useEffect(() => {
    if (activeTab === "match" && connection === "connected") refreshSavedRubrics();
  }, [activeTab, connection, refreshSavedRubrics]);


  function applyApiKey() {
    const value = apiKeyDraft.trim();
    setApiKey(value);
    try {
      if (value) sessionStorage.setItem("bluepace_feature_api_key", value);
      else sessionStorage.removeItem("bluepace_feature_api_key");
    } catch {
      // Continue with an in-memory key if session storage is disabled.
    }
    setNotice(value ? "API key kept for this browser session only." : "Optional API key cleared.");
    if (value === apiKey) refreshConnection();
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
      const local = readSavedRubrics().find((item) => item.rubric_id === id);
      if (local) {
        setRubric(local);
        setCandidateCard(null);
        setNotice(`Loaded rubric ${id} from this browser session.`);
      } else {
        const response = await request("get", `/v1/match/rubrics/${encodeURIComponent(id)}`, undefined, { timeout: 10000 });
        setRubric(response.data);
        setCandidateCard(null);
        setNotice(`Loaded rubric ${id}.`);
      }
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
      const saved = response.data;
      const existing = readSavedRubrics().filter((item) => item.rubric_id !== saved.rubric_id);
      writeSavedRubrics([saved, ...existing]);
      setRubric(saved);
      setSelectedRubricId(saved.rubric_id || "");
      setNotice(`Rubric version saved in this browser session · ${saved.rubric_id || "saved"}`);
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
      if (rubric) body.append("rubric", JSON.stringify(rubric));
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


  function handleBatchFileSelection(event) {
    const selected = Array.from(event.target.files || []);
    event.target.value = "";
    if (!selected.length) return;

    const nextRows = [...batchFiles];
    const issues = [];
    for (const file of selected) {
      if (nextRows.length >= MAX_BULK_RESUMES) {
        issues.push(`The queue is limited to ${MAX_BULK_RESUMES} resumes. Remove files before adding more.`);
        break;
      }
      const validation = validateBulkResume(file, nextRows.map((row) => row.file));
      if (!validation.valid) {
        issues.push(`${file.name}: ${validation.reason}`);
        continue;
      }
      nextRows.push({
        id: `${Date.now()}-${nextRows.length}-${file.name}`,
        file,
        status: "queued",
        result: null,
        error: "",
      });
    }
    setBatchFiles(nextRows);
    setBatchError(issues.slice(0, 4).join(" "));
    setBatchProgress({ done: 0, total: 0 });
  }

  function updateBatchRow(id, patch) {
    setBatchFiles((current) => current.map((row) => row.id === id ? { ...row, ...patch } : row));
  }

  function removeBatchRow(id) {
    if (batchRunning) return;
    setBatchFiles((current) => current.filter((row) => row.id !== id));
    setBatchError("");
  }

  function clearBatchQueue() {
    if (batchRunning) return;
    setBatchFiles([]);
    setBatchCurrentName("");
    setBatchProgress({ done: 0, total: 0 });
    setBatchError("");
  }

  function downloadBulkCsv() {
    if (!batchFiles.length) return;
    const blob = new Blob([buildBulkMatchCsv(batchFiles)], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `bluepace-applicant-match-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  async function runBatchMatches(retryOnly = false, onlyIds = null) {
    if (!selectedRubricId) {
      setBatchError("Select a saved rubric or save the draft rubric before running bulk matching.");
      return;
    }
    if (connection !== "connected") {
      setBatchError("The AI API is not connected. Restore the feature API connection before processing resumes.");
      return;
    }
    const queue = batchFiles.filter((row) => {
      if (onlyIds?.length) return onlyIds.includes(row.id) && ["queued", "failed"].includes(row.status);
      return retryOnly ? row.status === "failed" : row.status === "queued";
    });
    if (!queue.length) {
      setBatchError(retryOnly ? "There are no failed resumes to retry." : "Add at least one queued resume first.");
      return;
    }

    setBatchRunning(true);
    setBatchError("");
    setNotice("");
    setBatchCurrentName("");
    setBatchProgress({ done: 0, total: queue.length });
    let complete = 0;
    let manual = 0;
    let failed = 0;

    for (let index = 0; index < queue.length; index += 1) {
      const row = queue[index];
      setBatchCurrentName(row.file.name);
      updateBatchRow(row.id, { status: "processing", error: "" });
      const body = new FormData();
      body.append("rubric_id", selectedRubricId);
      if (rubric) body.append("rubric", JSON.stringify(rubric));
      body.append("file", row.file);
      if (selectedProfile) body.append("profile", selectedProfile);

      try {
        const response = await request("post", "/v1/match/analyze", body, { timeout: 120000 });
        const result = response.data;
        const status = result?.status === "manual" ? "manual" : "complete";
        updateBatchRow(row.id, { status, result, error: "" });
        if (status === "manual") manual += 1;
        else complete += 1;
      } catch (error) {
        const message = explainError(error);
        updateBatchRow(row.id, { status: "failed", error: message, result: null });
        failed += 1;

        // Authentication, route, and service-availability errors affect the whole batch.
        // Mark the remaining rows so users can see and retry them without sending
        // dozens of identical requests to an unavailable API.
        const httpStatus = error?.response?.status;
        if ([401, 403, 404, 503].includes(httpStatus)) {
          for (const remaining of queue.slice(index + 1)) {
            updateBatchRow(remaining.id, { status: "failed", error: message });
            failed += 1;
          }
          setBatchProgress({ done: queue.length, total: queue.length });
          break;
        }
      }
      setBatchProgress({ done: index + 1, total: queue.length });
    }

    setBatchCurrentName("");
    setBatchRunning(false);
    setNotice(`Bulk match finished: ${complete} completed, ${manual} needing manual review, ${failed} failed. Review each result before making any recruiting decision.`);
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

  const jdTitle = jdResult?.fields?.title?.value || jdResult?.fields?.title?.raw || jdResult?.title?.text || "Job description review";
  const descriptionOutput = jdResult?.description_markdown || jdResult?.long_description || jdResult?.long_description_annotated || jdResult?.long_description_text || "";
  const matchScore = candidateCard?.scores?.match;
  const batchQueuedCount = batchFiles.filter((row) => row.status === "queued").length;
  const batchFailedCount = batchFiles.filter((row) => row.status === "failed").length;
  const batchTerminalCount = batchFiles.filter((row) => ["complete", "manual", "failed"].includes(row.status)).length;

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
              <input type="password" autoComplete="off" value={apiKeyDraft} onChange={(event) => setApiKeyDraft(event.target.value)} placeholder="Paste API key only if your backend requires one" className={fieldClass} />
            </Field>
            <button type="button" className={secondaryButton} onClick={applyApiKey}>Apply key & test connection</button>
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
                    {descriptionOutput && <details open className="rounded-lg border border-ink-100 bg-white p-4"><summary className="cursor-pointer text-sm font-semibold">Full job description</summary><pre className="mt-3 max-h-[520px] overflow-auto whitespace-pre-wrap text-sm leading-6 text-ink-700">{descriptionOutput}</pre></details>}
                    <button type="button" className={primaryButton} onClick={() => { setActiveTab("match"); setRubricError(""); }} disabled={!descriptionOutput && !jdText.trim()}>Continue to Applicant Match</button>
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


              <section className="space-y-4 border-t border-ink-200 pt-6">
                <SectionHeading
                  eyebrow="Step 05"
                  title="Bulk resume comparison"
                  detail={`Match up to ${MAX_BULK_RESUMES} resumes against the selected saved rubric. Processing runs one resume at a time; failures do not discard successful results.`}
                  action={<button type="button" className={secondaryButton} onClick={downloadBulkCsv} disabled={!batchFiles.length}>Export CSV</button>}
                />
                <div className="rounded-lg border border-ink-100 bg-white p-4">
                  <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
                    <Field label="Resume files" hint="PDF, DOCX, TXT or MD · each file up to 5 MB · maximum 50 files in the queue">
                      <input
                        className={fieldClass}
                        type="file"
                        accept=".pdf,.docx,.txt,.md"
                        multiple
                        disabled={batchRunning || batchFiles.length >= MAX_BULK_RESUMES}
                        onChange={handleBatchFileSelection}
                      />
                    </Field>
                    <div className="flex flex-wrap gap-2">
                      <button type="button" className={primaryButton} onClick={() => runBatchMatches(false)} disabled={batchRunning || connection !== "connected" || !selectedRubricId || !batchQueuedCount}>
                        {batchRunning ? "Matching…" : `Run queued (${batchQueuedCount})`}
                      </button>
                      <button type="button" className={secondaryButton} onClick={() => runBatchMatches(true)} disabled={batchRunning || connection !== "connected" || !selectedRubricId || !batchFailedCount}>
                        Retry failed ({batchFailedCount})
                      </button>
                      <button type="button" className={secondaryButton} onClick={clearBatchQueue} disabled={batchRunning || !batchFiles.length}>Clear</button>
                    </div>
                  </div>
                  {!selectedRubricId && <p className="mt-3 text-xs leading-5 text-amber-800">Choose a saved rubric above or save the reviewed draft before starting a batch.</p>}
                  {batchError && <ErrorNotice>{batchError}</ErrorNotice>}
                  {batchRunning && (
                    <div className="mt-4" aria-live="polite">
                      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-ink-600">
                        <span>Processing {batchProgress.done} of {batchProgress.total}</span>
                        <span className="max-w-full truncate">{batchCurrentName}</span>
                      </div>
                      <div className="mt-2 h-2 overflow-hidden rounded-full bg-ink-100" role="progressbar" aria-valuemin={0} aria-valuemax={batchProgress.total || 1} aria-valuenow={batchProgress.done} aria-label="Bulk resume analysis progress">
                        <div className="h-full rounded-full bg-[#c49a4a] transition-all" style={{ width: `${batchProgress.total ? Math.round(batchProgress.done / batchProgress.total * 100) : 0}%` }} />
                      </div>
                    </div>
                  )}
                  {batchFiles.length > 0 && (
                    <div className="mt-4 flex flex-wrap gap-2 text-xs">
                      <Pill>{batchFiles.length}/{MAX_BULK_RESUMES} queued</Pill>
                      <Pill tone="good">{batchFiles.filter((row) => row.status === "complete").length} complete</Pill>
                      <Pill tone="warn">{batchFiles.filter((row) => row.status === "manual").length} manual review</Pill>
                      <Pill tone="bad">{batchFailedCount} failed</Pill>
                      {batchTerminalCount > 0 && <span className="self-center text-ink-500">{batchTerminalCount} attempted</span>}
                    </div>
                  )}
                </div>

                {batchFiles.length === 0 ? (
                  <EmptyPanel title="No resumes in this batch" detail="Select multiple resume files to compare them against the same saved rubric. You can export the results when processing finishes." />
                ) : (
                  <div className="overflow-x-auto rounded-lg border border-ink-100 bg-white">
                    <table className="w-full min-w-[1040px] border-collapse text-left text-sm">
                      <thead className="bg-[#fafaf8] text-[11px] uppercase tracking-wide text-ink-500">
                        <tr>
                          <th className="px-3 py-3 font-semibold">Resume</th>
                          <th className="px-3 py-3 font-semibold">Status</th>
                          <th className="px-3 py-3 font-semibold">Candidate ref</th>
                          <th className="px-3 py-3 font-semibold">Match</th>
                          <th className="px-3 py-3 font-semibold">Required skills</th>
                          <th className="px-3 py-3 font-semibold">Experience</th>
                          <th className="px-3 py-3 font-semibold">Gaps to review</th>
                          <th className="px-3 py-3 font-semibold">Action</th>
                        </tr>
                      </thead>
                      <tbody>
                        {batchFiles.map((row) => {
                          const result = row.result;
                          const statusLabel = {
                            queued: "Queued",
                            processing: "Processing",
                            complete: "Complete",
                            manual: "Manual review",
                            failed: "Failed",
                          }[row.status] || row.status;
                          const tone = row.status === "complete" ? "good" : row.status === "manual" || row.status === "failed" ? "warn" : "neutral";
                          const gaps = (result?.gaps || []).filter((gap) => gap.importance === "must" || gap.status !== "met");
                          return (
                            <tr key={row.id} className="border-t border-ink-100 align-top">
                              <td className="max-w-[240px] px-3 py-3">
                                <p className="break-all text-xs font-semibold text-ink-800">{row.file.name}</p>
                                <p className="mt-1 text-[11px] text-ink-500">{(row.file.size / 1024).toFixed(0)} KB</p>
                              </td>
                              <td className="px-3 py-3">
                                <Pill tone={tone}>{statusLabel}</Pill>
                                {row.error && <p className="mt-2 max-w-[260px] text-xs leading-5 text-rose-700">{row.error}</p>}
                                {result?.status === "manual" && <p className="mt-2 max-w-[260px] text-xs leading-5 text-amber-800">{result.reason || "Review the resume manually."}</p>}
                              </td>
                              <td className="px-3 py-3 font-mono text-xs text-ink-600">{result?.applicant_id || "—"}</td>
                              <td className="px-3 py-3 font-semibold tabular-nums">{result?.scores?.match == null ? "—" : `${result.scores.match}%`}</td>
                              <td className="px-3 py-3 tabular-nums">{result?.scores?.required_skills?.pct == null ? "—" : `${result.scores.required_skills.pct}%`}</td>
                              <td className="px-3 py-3 tabular-nums">{result?.scores?.experience?.pct == null ? "—" : `${result.scores.experience.pct}%`}</td>
                              <td className="max-w-[240px] px-3 py-3 text-xs leading-5 text-ink-600">{gaps.length ? gaps.map((gap) => gap.label).join(", ") : result ? "No unverified gaps returned" : "—"}</td>
                              <td className="px-3 py-3">
                                <div className="flex flex-wrap gap-2">
                                  {row.status === "failed" && !batchRunning && <button type="button" className="text-xs font-semibold text-blue-700 underline" onClick={() => runBatchMatches(false, [row.id])} disabled={connection !== "connected" || !selectedRubricId}>Retry</button>}
                                  {!batchRunning && <button type="button" className="text-xs font-semibold text-ink-500 underline" onClick={() => removeBatchRow(row.id)}>Remove</button>}
                                </div>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                    <p className="border-t border-ink-100 bg-[#fafaf8] px-3 py-3 text-xs leading-5 text-ink-500">
                      Match scores summarize evidence against this rubric; they do not rank candidates for automatic rejection or hiring. Verify the cited evidence and review flags before deciding.
                    </p>
                  </div>
                )}
              </section>

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
