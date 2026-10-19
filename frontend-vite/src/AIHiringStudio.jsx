import { useEffect, useState } from "react";

const DEFAULT_MODEL = "openrouter/free";
const MAX_FILE_BYTES = 5 * 1024 * 1024;
const tabs = [
  { id: "generate", label: "Generate JD" },
  { id: "rubric", label: "Assessment rubric" },
  { id: "resume", label: "Resume analysis" },
  { id: "history", label: "Run history" },
  { id: "settings", label: "Settings" },
];

function explainError(error) {
  const detail = error?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (detail?.message) return detail.message;
  if (typeof error?.message === "string") return error.message;
  return "The request failed. Review the configuration and try again.";
}

function displayDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}

function MetaPill({ children, tone = "neutral" }) {
  const styles = {
    neutral: "bg-slate-100 text-slate-700",
    good: "bg-emerald-50 text-emerald-700",
    warn: "bg-amber-50 text-amber-800",
    bad: "bg-rose-50 text-rose-700",
    blue: "bg-blue-50 text-blue-700",
  };
  return <span className={"inline-flex items-center rounded-full px-2.5 py-1 text-xs font-semibold " + (styles[tone] || styles.neutral)}>{children}</span>;
}

function Metric({ label, value }) {
  return <div className="rounded-xl border border-slate-200 bg-white px-4 py-3"><p className="text-xs font-medium text-slate-500">{label}</p><p className="mt-1 text-xl font-semibold text-slate-900">{value}</p></div>;
}

export default function AIHiringStudio({ token, apiRequest, jobs = [], onSaved }) {
  const [tab, setTab] = useState("generate");
  const [apiKey, setApiKey] = useState(() => {
    try { return sessionStorage.getItem("bluepace_openrouter_key") || ""; } catch { return ""; }
  });
  const [model, setModel] = useState(() => {
    try { const saved = sessionStorage.getItem("bluepace_openrouter_model"); return !saved || saved === "openai/gpt-4o-mini" ? DEFAULT_MODEL : saved; } catch { return DEFAULT_MODEL; }
  });
  const [connection, setConnection] = useState(null);
  const [serverKeyConfigured, setServerKeyConfigured] = useState(null);
  const [sourceText, setSourceText] = useState("");
  const [selectedJobId, setSelectedJobId] = useState("");
  const [mode, setMode] = useState("detailed");
  const [jobDescription, setJobDescription] = useState("");
  const [jobDetails, setJobDetails] = useState({
    job_title: "", employment_type: "", work_mode: "", location: "",
    minimum_experience_years: "", fresher_allowed: false,
  });
  const [suggestions, setSuggestions] = useState([]);
  const [generationMeta, setGenerationMeta] = useState(null);
  const [jdFileName, setJdFileName] = useState("");
  const [rubric, setRubric] = useState(null);
  const [rubricMeta, setRubricMeta] = useState(null);
  const [resumeFile, setResumeFile] = useState(null);
  const [resumeData, setResumeData] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [analysisMeta, setAnalysisMeta] = useState(null);
  const [history, setHistory] = useState([]);
  const [historyDetail, setHistoryDetail] = useState(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const credentials = () => ({
    model: model.trim() || DEFAULT_MODEL,
    ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}),
  });

  function saveSettings() {
    try {
      if (apiKey.trim()) sessionStorage.setItem("bluepace_openrouter_key", apiKey.trim());
      else sessionStorage.removeItem("bluepace_openrouter_key");
      sessionStorage.setItem("bluepace_openrouter_model", model.trim() || DEFAULT_MODEL);
      setNotice("Settings saved for this browser tab session. The API key is not written to AI run history.");
      setError("");
    } catch {
      setError("Browser session storage is unavailable. The key will remain in memory until this page is closed.");
    }
  }

  async function testConnection() {
    setBusy("test");
    setError("");
    setNotice("");
    setConnection(null);
    try {
      const response = await apiRequest(token, "post", "/ai-hiring/test", { data: credentials(), timeout: 25000 });
      setConnection(response.data);
      try {
        if (apiKey.trim()) sessionStorage.setItem("bluepace_openrouter_key", apiKey.trim());
        sessionStorage.setItem("bluepace_openrouter_model", model.trim() || DEFAULT_MODEL);
      } catch {}
      setNotice(response.data?.message || "OpenRouter connection checked.");
    } catch (requestError) {
      setError(explainError(requestError));
    } finally {
      setBusy("");
    }
  }

  async function importJDFile(event) {
    const input = event.currentTarget;
    const file = input.files && input.files[0];
    setError("");
    setNotice("");
    if (!file) return;
    if (!/\.(pdf|docx)$/i.test(file.name)) {
      input.value = "";
      setError("Choose a PDF or DOCX job description.");
      return;
    }
    if (file.size === 0 || file.size > MAX_FILE_BYTES) {
      input.value = "";
      setError(file.size === 0 ? "The selected file is empty." : "Job description files must be 5 MB or smaller.");
      return;
    }
    setBusy("jd-upload");
    try {
      const body = new FormData();
      body.append("file", file);
      const response = await apiRequest(token, "post", "/resume-processing/job-description", { data: body });
      const extracted = String(response.data?.description || "").trim();
      if (!extracted) throw new Error("No text could be extracted from that document.");
      setSourceText(extracted);
      setJdFileName(file.name);
      setNotice("Text extracted from " + file.name + ". Review it, then generate the job description.");
    } catch (requestError) {
      setError(explainError(requestError));
    } finally {
      setBusy("");
      input.value = "";
    }
  }

  async function generateJD(overrides = null) {
    if (sourceText.trim().length < 5) {
      setError("Paste recruiter notes or import a job description before generating.");
      setTab("generate");
      return;
    }
    setBusy("generate");
    setError("");
    setNotice("");
    try {
      const chosenDetails = overrides || jobDetails;
      const cleanOverrides = {};
      Object.entries(chosenDetails).forEach(([key, value]) => {
        if (value !== "" && value !== null && value !== undefined) {
          cleanOverrides[key] = key === "minimum_experience_years" ? Number(value) : value;
        }
      });
      const response = await apiRequest(token, "post", "/ai-hiring/generate-jd", {
        data: { ...credentials(), source_text: sourceText.trim(), mode, overrides: cleanOverrides },
        timeout: 90000,
      });
      const result = response.data?.result || {};
      const details = result.details || {};
      setJobDescription(String(result.job_description || ""));
      setJobDetails({
        job_title: String(details.job_title || chosenDetails.job_title || ""),
        employment_type: String(details.employment_type || chosenDetails.employment_type || ""),
        work_mode: String(details.work_mode || chosenDetails.work_mode || ""),
        location: String(details.location || chosenDetails.location || ""),
        minimum_experience_years: details.minimum_experience_years ?? chosenDetails.minimum_experience_years ?? "",
        fresher_allowed: Boolean(details.fresher_allowed ?? chosenDetails.fresher_allowed),
      });
      setSuggestions(Array.isArray(result.missing_fields) ? result.missing_fields : []);
      setGenerationMeta(response.data);
      setNotice("Draft generated. Review the fields and job description before saving it as an ATS draft.");
      setRubric(null);
      setAnalysis(null);
    } catch (requestError) {
      setError(explainError(requestError));
    } finally {
      setBusy("");
    }
  }

  function useSuggestion(suggestion) {
    const aliases = {
      title: "job_title", job_title: "job_title", employment: "employment_type",
      employment_type: "employment_type", work_mode: "work_mode", location: "location",
      experience: "minimum_experience_years", minimum_experience_years: "minimum_experience_years",
      fresher_allowed: "fresher_allowed",
    };
    const key = aliases[String(suggestion?.field || "").toLowerCase().replaceAll(" ", "_")];
    if (!key || suggestion.suggested_value === undefined) return;
    setJobDetails((previous) => ({
      ...previous,
      [key]: key === "minimum_experience_years" ? String(suggestion.suggested_value) : key === "fresher_allowed" ? Boolean(suggestion.suggested_value) : String(suggestion.suggested_value),
    }));
  }

  async function saveDraftJob() {
    if (!jobDescription.trim()) {
      setError("Generate or edit a job description first.");
      return;
    }
    const title = jobDetails.job_title.trim() || jobDescription.split(/\r?\n/).map((line) => line.replace(/^#+\s*/, "").trim()).find(Boolean)?.slice(0, 200) || "New role";
    const exp = jobDetails.minimum_experience_years === "" ? null : Number(jobDetails.minimum_experience_years);
    if (exp !== null && (!Number.isFinite(exp) || exp < 0 || exp > 60)) {
      setError("Minimum experience must be between 0 and 60 years.");
      return;
    }
    const modeValue = String(jobDetails.work_mode || "").toLowerCase();
    const workMode = modeValue.includes("remote") ? "remote" : modeValue.includes("hybrid") ? "hybrid" : "onsite";
    setBusy("save-job");
    setError("");
    try {
      const response = await apiRequest(token, "post", "/jobs", {
        data: {
          title, description: jobDescription.trim(), department: null,
          location: jobDetails.location.trim() || null,
          employment_type: jobDetails.employment_type || null,
          work_mode: workMode, status: "draft", required_skills: [],
          minimum_experience_years: exp, fresher_allowed: Boolean(jobDetails.fresher_allowed),
        },
      });
      setNotice("Saved as draft ATS job: " + (response.data?.title || title) + ". It has not been published.");
      if (onSaved) await onSaved();
    } catch (requestError) {
      setError(explainError(requestError));
    } finally {
      setBusy("");
    }
  }

  async function buildRubric() {
    if (jobDescription.trim().length < 10) {
      setError("Generate or paste a job description before building the rubric.");
      return;
    }
    setBusy("rubric");
    setError("");
    try {
      const response = await apiRequest(token, "post", "/ai-hiring/rubric", {
        data: { ...credentials(), job_description: jobDescription.trim() },
        timeout: 90000,
      });
      setRubric(response.data?.rubric || null);
      setRubricMeta(response.data);
      setAnalysis(null);
      setNotice("Rubric created. Review criterion weights and requirements before using it.");
    } catch (requestError) {
      setError(explainError(requestError));
    } finally {
      setBusy("");
    }
  }

  async function extractResume(event) {
    const input = event.currentTarget;
    const file = input.files && input.files[0];
    setError("");
    setNotice("");
    setAnalysis(null);
    if (!file) return;
    if (!/\.(pdf|docx)$/i.test(file.name)) {
      input.value = "";
      setResumeFile(null);
      setError("Choose a PDF or DOCX resume.");
      return;
    }
    if (file.size === 0 || file.size > MAX_FILE_BYTES) {
      input.value = "";
      setResumeFile(null);
      setError(file.size === 0 ? "The selected resume is empty." : "Resume files must be 5 MB or smaller.");
      return;
    }
    setResumeFile(file);
    setBusy("resume-extract");
    try {
      const body = new FormData();
      body.append("file", file);
      const response = await apiRequest(token, "post", "/extract/", { data: body, timeout: 90000 });
      const data = response.data?.data || response.data?.resume_json || null;
      if (!data || typeof data !== "object") throw new Error("The extraction service returned no structured resume data.");
      setResumeData(data);
      setNotice("Resume extracted for rubric-based analysis. It has not been saved as a candidate record.");
    } catch (requestError) {
      setResumeFile(null);
      setResumeData(null);
      setError(explainError(requestError));
    } finally {
      setBusy("");
      input.value = "";
    }
  }

  async function analyzeResume() {
    if (!resumeData) {
      setError("Upload a PDF or DOCX resume first.");
      return;
    }
    if (!rubric?.criteria?.length) {
      setError("Build an assessment rubric first.");
      setTab("rubric");
      return;
    }
    setBusy("analysis");
    setError("");
    setNotice("");
    try {
      const response = await apiRequest(token, "post", "/ai-hiring/analyze-resume", {
        data: { ...credentials(), resume_data: resumeData, rubric },
        timeout: 90000,
      });
      setAnalysis(response.data?.analysis || null);
      setAnalysisMeta(response.data);
      setNotice("Assessment completed. Review evidence and gaps; the output supports human review only.");
    } catch (requestError) {
      setError(explainError(requestError));
    } finally {
      setBusy("");
    }
  }

  async function loadHistory() {
    setBusy("history");
    setError("");
    try {
      const response = await apiRequest(token, "get", "/ai-hiring/history", { params: { limit: 50 } });
      setHistory(Array.isArray(response.data?.runs) ? response.data.runs : []);
    } catch (requestError) {
      setError(explainError(requestError));
    } finally {
      setBusy("");
    }
  }

  async function openHistoryDetail(id) {
    setBusy("history-detail");
    setError("");
    try {
      const response = await apiRequest(token, "get", "/ai-hiring/history/" + encodeURIComponent(id));
      setHistoryDetail(response.data);
    } catch (requestError) {
      setError(explainError(requestError));
    } finally {
      setBusy("");
    }
  }

  useEffect(() => {
    if (tab === "history") void loadHistory();
  }, [tab]);

  useEffect(() => {
    let active = true;
    apiRequest(token, "get", "/ai-hiring/status")
      .then((response) => {
        if (active) setServerKeyConfigured(Boolean(response.data?.server_key_configured));
      })
      .catch(() => {
        if (active) setServerKeyConfigured(null);
      });
    return () => { active = false; };
  }, [token, apiRequest]);

  function updateJobDetail(field, value) {
    setJobDetails((previous) => ({ ...previous, [field]: value }));
  }

  const fieldClass = "w-full rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-900 outline-none transition focus:border-amber-500 focus:ring-2 focus:ring-amber-100";
  const btnPrimary = "inline-flex items-center justify-center rounded-lg bg-slate-950 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50";
  const btnSecondary = "inline-flex items-center justify-center rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm font-semibold text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50";

  return (
    <div className="space-y-5 pb-10">
      <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="border-b border-slate-200 bg-slate-950 px-5 py-6 text-white sm:px-7">
          <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-amber-300">BluePace · AI-assisted recruitment</p>
          <div className="mt-2 flex flex-wrap items-end justify-between gap-4">
            <div><h2 className="text-2xl font-semibold tracking-tight">AI Hiring Studio</h2><p className="mt-1 max-w-2xl text-sm text-slate-300">Turn job notes into editable job descriptions, build a transparent rubric, and inspect resume evidence.</p></div>
            <MetaPill tone={connection?.status === "connected" && connection?.model_listed ? "good" : "neutral"}>{connection?.status === "connected" ? "OpenRouter checked" : "Human review required"}</MetaPill>
          </div>
        </div>
        <div className="flex gap-1 overflow-x-auto border-b border-slate-200 px-3 py-2 sm:px-5" role="tablist" aria-label="AI Hiring Studio sections">
          {tabs.map((item) => <button key={item.id} type="button" role="tab" aria-selected={tab === item.id} onClick={() => { setTab(item.id); setError(""); }} className={"whitespace-nowrap rounded-lg px-3 py-2 text-sm font-semibold transition " + (tab === item.id ? "bg-slate-950 text-white" : "text-slate-600 hover:bg-slate-100")}>{item.label}</button>)}
        </div>
        {(error || notice) && <div className="px-5 pt-4 sm:px-7">{error ? <div role="alert" className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">{error}</div> : <div role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">{notice}</div>}</div>}
        {serverKeyConfigured === false && !apiKey.trim() && <div className="px-5 pt-4 sm:px-7"><div role="status" className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900"><p><strong>AI connection needs setup.</strong> No shared OpenRouter key is configured on the backend. Enter a key in Settings for this tab, or configure <code>OPENROUTER_API_KEY</code> in Railway backend variables.</p><button type="button" className="shrink-0 font-semibold underline underline-offset-2" onClick={() => setTab("settings")}>Open AI settings</button></div></div>}

        <div className="p-5 sm:p-7">
          {tab === "generate" && <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
            <div className="space-y-4">
              <div><p className="text-xs font-semibold uppercase tracking-wide text-amber-700">01 · Source</p><h3 className="mt-1 text-lg font-semibold text-slate-900">Start from recruiter notes or an existing job</h3><p className="mt-1 text-sm text-slate-500">Upload a PDF/DOCX (5 MB max), paste content, or use an existing ATS job as the starting point.</p></div>
              <label className="block text-sm font-semibold text-slate-700">Use an existing ATS job
                <select className={fieldClass + " mt-1.5"} value={selectedJobId} onChange={(event) => { const id = event.target.value; setSelectedJobId(id); const job = jobs.find((item) => String(item.id) === id); if (job) { setSourceText(String(job.description || "")); setJobDetails((previous) => ({ ...previous, job_title: job.title || previous.job_title, employment_type: job.employment_type || previous.employment_type, location: job.location || previous.location })); } }}>
                  <option value="">Choose an existing job (optional)</option>
                  {jobs.filter((job) => job.status !== "archived").map((job) => <option key={job.id} value={String(job.id)}>{job.title}</option>)}
                </select>
              </label>
              <label className="block text-sm font-semibold text-slate-700">Import job description file
                <input type="file" accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" className="mt-1.5 block w-full rounded-lg border border-slate-200 bg-white p-3 text-sm font-normal" onChange={importJDFile} disabled={Boolean(busy)} />
                <span className="mt-1 block text-xs font-normal text-slate-500">{jdFileName ? "Extracted from " + jdFileName : "PDF or DOCX only. Text is extracted by the ATS backend."}</span>
              </label>
              <label className="block text-sm font-semibold text-slate-700">Paste notes or current description
                <textarea className={fieldClass + " mt-1.5 min-h-56 resize-y leading-6"} placeholder="Example: Python developer, APIs, PostgreSQL, 2+ years, Edinburgh, full-time. Include the responsibilities and requirements you know." value={sourceText} onChange={(event) => setSourceText(event.target.value)} />
              </label>
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs font-semibold text-slate-600">Output style</span>
                <button type="button" onClick={() => setMode("concise")} aria-pressed={mode === "concise"} className={mode === "concise" ? btnPrimary : btnSecondary}>Concise</button>
                <button type="button" onClick={() => setMode("detailed")} aria-pressed={mode === "detailed"} className={mode === "detailed" ? btnPrimary : btnSecondary}>Detailed</button>
                <button type="button" onClick={() => void generateJD()} disabled={Boolean(busy)} className={btnPrimary}>{busy === "generate" ? "Generating…" : "Generate job description"}</button>
              </div>
            </div>

            <div className="space-y-4">
              <div><p className="text-xs font-semibold uppercase tracking-wide text-amber-700">02 · Review</p><h3 className="mt-1 text-lg font-semibold text-slate-900">Editable job description</h3><p className="mt-1 text-sm text-slate-500">Review the generated text and correct the role details before saving a draft.</p></div>
              {generationMeta && <div className="flex flex-wrap gap-2"><MetaPill tone="good">Generated</MetaPill><MetaPill>{generationMeta.model}</MetaPill><MetaPill>{generationMeta.latency_ms ?? "—"} ms</MetaPill><MetaPill>{generationMeta.token_usage?.total_tokens ?? "Tokens n/a"} tokens</MetaPill></div>}
              <label className="block text-sm font-semibold text-slate-700">Job description
                <textarea className={fieldClass + " mt-1.5 min-h-64 resize-y leading-6"} placeholder="Your generated job description will appear here." value={jobDescription} onChange={(event) => setJobDescription(event.target.value)} />
              </label>
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="text-sm font-semibold text-slate-700">Job title<input className={fieldClass + " mt-1.5"} value={jobDetails.job_title} onChange={(event) => updateJobDetail("job_title", event.target.value)} placeholder="Role title" /></label>
                <label className="text-sm font-semibold text-slate-700">Employment type
                  <select className={fieldClass + " mt-1.5"} value={jobDetails.employment_type} onChange={(event) => updateJobDetail("employment_type", event.target.value)}><option value="">Not specified</option><option>Full-time</option><option>Part-time</option><option>Contract</option><option>Freelance</option><option>Temporary</option><option>Internship</option></select>
                </label>
                <label className="text-sm font-semibold text-slate-700">Work mode
                  <select className={fieldClass + " mt-1.5"} value={jobDetails.work_mode} onChange={(event) => updateJobDetail("work_mode", event.target.value)}><option value="">Not specified</option><option>On-site</option><option>Hybrid</option><option>Remote</option></select>
                </label>
                <label className="text-sm font-semibold text-slate-700">Location<input className={fieldClass + " mt-1.5"} value={jobDetails.location} onChange={(event) => updateJobDetail("location", event.target.value)} placeholder="City or remote" /></label>
                <label className="text-sm font-semibold text-slate-700">Minimum experience (years)<input type="number" min="0" max="60" step="0.5" className={fieldClass + " mt-1.5"} value={jobDetails.minimum_experience_years} onChange={(event) => updateJobDetail("minimum_experience_years", event.target.value)} placeholder="e.g. 1.5" /></label>
                <label className="flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-3 text-sm font-semibold text-slate-700"><input type="checkbox" checked={jobDetails.fresher_allowed} onChange={(event) => updateJobDetail("fresher_allowed", event.target.checked)} className="h-4 w-4 accent-amber-600" />Freshers are eligible</label>
              </div>
              {suggestions.length > 0 && <div className="rounded-xl border border-amber-200 bg-amber-50/60 p-4"><h4 className="text-sm font-semibold text-slate-900">Suggested missing details</h4><p className="mt-1 text-xs text-slate-600">Suggestions are not facts. Apply only the values that the hiring team confirms.</p><div className="mt-3 grid gap-2">{suggestions.map((item, index) => <div key={String(item.field || index) + "-" + index} className="rounded-lg border border-amber-100 bg-white p-3"><div className="flex flex-wrap items-center justify-between gap-2"><p className="text-sm font-semibold text-slate-800">{String(item.field || "Missing field").replaceAll("_", " ")}</p><button type="button" onClick={() => useSuggestion(item)} className="text-xs font-semibold text-amber-800 underline underline-offset-2">Use suggestion</button></div><p className="mt-1 text-sm text-slate-700">{String(item.suggested_value ?? "No suggestion")}</p><p className="mt-1 text-xs leading-5 text-slate-500">{String(item.reason || "Review with the hiring team.")}</p></div>)}</div><button type="button" onClick={() => void generateJD(jobDetails)} disabled={Boolean(busy)} className={btnSecondary + " mt-3"}>Regenerate using edited fields</button></div>}
              <div className="flex flex-wrap gap-2"><button type="button" className={btnSecondary} onClick={() => { setSourceText(jobDescription); setTab("rubric"); }}>Use this JD for rubric</button><button type="button" className={btnPrimary} disabled={Boolean(busy) || !jobDescription.trim()} onClick={() => void saveDraftJob()}>{busy === "save-job" ? "Saving…" : "Save as ATS draft"}</button></div>
              <p className="text-xs leading-5 text-slate-500">Saving creates a draft only. It does not publish the role. Fractional experience values are supported and saved to the ATS job record.</p>
            </div>
          </div>}

          {tab === "settings" && <div className="mx-auto max-w-2xl space-y-5">
            <div><p className="text-xs font-semibold uppercase tracking-wide text-amber-700">Configuration</p><h3 className="mt-1 text-lg font-semibold text-slate-900">OpenRouter connection</h3><p className="mt-1 text-sm leading-6 text-slate-500">The API key is sent over HTTPS to the backend only when you run an AI task. It is excluded from AI run history. For a shared production key, set OPENROUTER_API_KEY in Railway backend variables.</p><div className="mt-3 flex flex-wrap items-center gap-2">{serverKeyConfigured === true ? <MetaPill tone="good">Server key configured</MetaPill> : serverKeyConfigured === false ? <MetaPill tone="warn">Server key missing</MetaPill> : <MetaPill>Configuration status unavailable</MetaPill>}<MetaPill>{model.trim() || DEFAULT_MODEL}</MetaPill></div></div>
            <label className="block text-sm font-semibold text-slate-700">OpenRouter API key<input type="password" autoComplete="new-password" className={fieldClass + " mt-1.5 font-mono"} value={apiKey} onChange={(event) => { setApiKey(event.target.value); setConnection(null); }} placeholder="sk-or-v1-…" /></label>
            <label className="block text-sm font-semibold text-slate-700">Model identifier<input className={fieldClass + " mt-1.5 font-mono"} value={model} onChange={(event) => { setModel(event.target.value); setConnection(null); }} placeholder={DEFAULT_MODEL} /><span className="mt-1 block text-xs font-normal text-slate-500">Default: {DEFAULT_MODEL}. You can enter another OpenRouter model ID.</span></label>
            <div className="flex flex-wrap gap-2"><button type="button" onClick={saveSettings} className={btnSecondary}>Save for this tab session</button><button type="button" onClick={() => void testConnection()} disabled={Boolean(busy)} className={btnPrimary}>{busy === "test" ? "Testing…" : "Test OpenRouter connection"}</button></div>
            {connection && <div className={"rounded-xl border p-4 " + (connection.model_listed ? "border-emerald-200 bg-emerald-50" : "border-amber-200 bg-amber-50")}><div className="flex flex-wrap items-center gap-2"><MetaPill tone={connection.model_listed ? "good" : "warn"}>{connection.model_listed ? "Connection successful" : "API key accepted"}</MetaPill><MetaPill>{connection.latency_ms} ms</MetaPill></div><p className="mt-2 text-sm text-slate-800">{connection.message}</p><p className="mt-1 text-xs text-slate-600">Selected model: {connection.model} · {connection.available_model_count} model IDs listed · Key source: {connection.key_source}</p></div>}
            <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm leading-6 text-slate-600"><strong className="text-slate-800">Deployment note:</strong> OpenRouter calls run on the backend. Do not put API keys in Vite environment variables or commit them to GitHub. The default openrouter/free router chooses an available free model; capacity, quality, and rate limits can vary. Check provider data-use terms before sending candidate data. Paid models may incur charges.</div>
          </div>}

          {tab === "rubric" && <div className="space-y-5">
            <div className="flex flex-wrap items-end justify-between gap-3"><div><p className="text-xs font-semibold uppercase tracking-wide text-amber-700">Assessment framework</p><h3 className="mt-1 text-lg font-semibold text-slate-900">Build a weighted rubric from the job description</h3><p className="mt-1 text-sm text-slate-500">Includes must-have/nice-to-have skills, experience, relevant certifications and language requirements where appropriate.</p></div><button type="button" className={btnPrimary} disabled={Boolean(busy) || !jobDescription.trim()} onClick={() => void buildRubric()}>{busy === "rubric" ? "Building rubric…" : "Generate assessment rubric"}</button></div>
            <label className="block text-sm font-semibold text-slate-700">Job description used for scoring<textarea className={fieldClass + " mt-1.5 min-h-40 leading-6"} value={jobDescription} onChange={(event) => setJobDescription(event.target.value)} placeholder="Generate a JD in the first tab or paste the job description here." /></label>
            {rubricMeta && <div className="flex flex-wrap gap-2"><MetaPill tone="good">Rubric generated</MetaPill><MetaPill>{rubricMeta.model}</MetaPill><MetaPill>{rubricMeta.latency_ms} ms</MetaPill><MetaPill>Total weight {rubric?.total_weight ?? 100}%</MetaPill></div>}
            {rubric && <div className="overflow-hidden rounded-xl border border-slate-200"><div className="border-b border-slate-200 bg-slate-50 p-4"><h4 className="font-semibold text-slate-900">{rubric.title || "Assessment rubric"}</h4><p className="mt-1 text-sm text-slate-600">{rubric.rubric_summary || "Job-related criteria for structured human review."}</p></div><div className="divide-y divide-slate-100">{rubric.criteria.map((item, index) => <div key={String(item.name || index) + index} className="grid gap-2 p-4 sm:grid-cols-[minmax(0,1fr)_140px]"><div><div className="flex flex-wrap items-center gap-2"><p className="font-semibold text-slate-900">{item.name}</p><MetaPill tone={item.required ? "blue" : "neutral"}>{item.required ? "Must-have" : "Nice-to-have"}</MetaPill><MetaPill>{item.category}</MetaPill></div><p className="mt-1 text-sm leading-5 text-slate-600">{item.description || item.scoring_guide?.strong || "Review against evidence from the resume."}</p>{item.keywords?.length > 0 && <p className="mt-2 text-xs text-slate-500">Keywords: {item.keywords.join(", ")}</p>}{item.minimum_years !== null && item.minimum_years !== undefined && <p className="mt-1 text-xs text-slate-500">Experience reference: {item.minimum_years} year(s)</p>}</div><div className="sm:text-right"><p className="text-2xl font-semibold text-slate-900">{item.weight}%</p><p className="text-xs text-slate-500">Weight</p></div></div>)}</div><div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-200 bg-slate-50 p-4"><span className="text-sm text-slate-600">{rubric.criteria.length} criteria · weights normalized to {rubric.total_weight}%</span><button type="button" onClick={() => setTab("resume")} className={btnPrimary}>Analyze a resume against rubric</button></div></div>}
          </div>}

          {tab === "resume" && <div className="space-y-5">
            <div><p className="text-xs font-semibold uppercase tracking-wide text-amber-700">Evidence-based review</p><h3 className="mt-1 text-lg font-semibold text-slate-900">Compare a resume with the rubric</h3><p className="mt-1 text-sm text-slate-500">The resume is extracted for this analysis only and is not automatically added to the ATS candidate database.</p></div>
            {!rubric && <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">Create an assessment rubric first. <button type="button" onClick={() => setTab("rubric")} className="font-semibold underline underline-offset-2">Build rubric</button></div>}
            {rubric && <div className="flex flex-wrap items-center gap-2"><MetaPill tone="good">Rubric ready</MetaPill><MetaPill>{rubric.criteria.length} criteria</MetaPill><button type="button" className={btnSecondary} onClick={() => setTab("rubric")}>Review rubric</button></div>}
            <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 p-5">
              <label className="block text-sm font-semibold text-slate-800">Resume file (PDF/DOCX, up to 5 MB)<input type="file" accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" className="mt-2 block w-full rounded-lg border border-slate-200 bg-white p-3 text-sm font-normal" onChange={extractResume} disabled={Boolean(busy)} /></label>
              {resumeFile && <p className="mt-2 text-sm text-slate-600">Selected: {resumeFile.name} · {(resumeFile.size / 1024).toFixed(0)} KB</p>}
              {busy === "resume-extract" && <p className="mt-2 text-sm text-slate-500">Extracting resume content…</p>}
              <button type="button" className={btnPrimary + " mt-4"} disabled={Boolean(busy) || !resumeData || !rubric} onClick={() => void analyzeResume()}>{busy === "analysis" ? "Analyzing…" : "Analyze resume against rubric"}</button>
            </div>
            {analysisMeta && <div className="flex flex-wrap gap-2"><MetaPill tone="good">Analysis complete</MetaPill><MetaPill>{analysisMeta.model}</MetaPill><MetaPill>{analysisMeta.latency_ms} ms</MetaPill><MetaPill>{analysisMeta.token_usage?.total_tokens ?? "Tokens n/a"} tokens</MetaPill></div>}
            {analysis && <div className="space-y-4">
              <div className="grid gap-3 sm:grid-cols-3"><Metric label="Overall alignment" value={String(Math.round(Number(analysis.overall_score || 0))) + "%"} /><Metric label="Criteria scored" value={String(analysis.criteria?.length || 0)} /><Metric label="Recommendation" value={analysis.recommendation || "Human review"} /></div>
              <div className="rounded-xl border border-slate-200 p-4"><h4 className="font-semibold text-slate-900">Assessment summary</h4><p className="mt-2 text-sm leading-6 text-slate-600">{analysis.summary || "Review individual evidence below."}</p><p className="mt-2 text-xs text-slate-500">Decision support only. Do not use this score as the sole basis for a hiring decision.</p></div>
              {analysis.criteria?.map((item, index) => <div key={String(item.name || index) + index} className="rounded-xl border border-slate-200 bg-white p-4"><div className="flex flex-wrap items-start justify-between gap-3"><div><h4 className="font-semibold text-slate-900">{item.name || "Criterion"}</h4><p className="mt-1 text-xs text-slate-500">{item.assessment || "Review evidence."}</p></div><div className="text-right"><p className="text-xl font-semibold text-slate-900">{Math.round(Number(item.score || 0))}%</p><p className="text-xs text-slate-500">Weight {item.weight ?? 0}%</p></div></div><div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-amber-500" style={{ width: Math.max(0, Math.min(100, Number(item.score || 0))) + "%" }} /></div><div className="mt-3 grid gap-3 sm:grid-cols-2"><div><p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Evidence</p>{item.evidence?.length ? <ul className="mt-1 list-disc space-y-1 pl-4 text-sm text-slate-700">{item.evidence.map((evidence, i) => <li key={i}>{String(evidence)}</li>)}</ul> : <p className="mt-1 text-sm text-slate-500">No explicit evidence returned.</p>}</div><div><p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Gap / follow-up</p><p className="mt-1 text-sm leading-5 text-slate-700">{item.gap || "No gap specified."}</p></div></div></div>)}
              <div className="grid gap-4 sm:grid-cols-3"><div className="rounded-xl border border-slate-200 p-4"><h4 className="font-semibold text-slate-900">Strengths</h4><ul className="mt-2 list-disc space-y-1 pl-4 text-sm text-slate-600">{(analysis.strengths || []).map((v, i) => <li key={i}>{String(v)}</li>)}</ul></div><div className="rounded-xl border border-slate-200 p-4"><h4 className="font-semibold text-slate-900">Concerns</h4><ul className="mt-2 list-disc space-y-1 pl-4 text-sm text-slate-600">{(analysis.concerns || []).map((v, i) => <li key={i}>{String(v)}</li>)}</ul></div><div className="rounded-xl border border-slate-200 p-4"><h4 className="font-semibold text-slate-900">Missing requirements</h4><ul className="mt-2 list-disc space-y-1 pl-4 text-sm text-slate-600">{(analysis.missing_requirements || []).map((v, i) => <li key={i}>{String(v)}</li>)}</ul></div></div>
            </div>}
          </div>}

          {tab === "history" && <div className="space-y-4">
            <div className="flex flex-wrap items-end justify-between gap-3"><div><p className="text-xs font-semibold uppercase tracking-wide text-amber-700">Observability</p><h3 className="mt-1 text-lg font-semibold text-slate-900">AI run history</h3><p className="mt-1 text-sm text-slate-500">Inspect model calls, prompts, output, latency, available token usage and failures.</p></div><button type="button" onClick={() => void loadHistory()} disabled={Boolean(busy)} className={btnSecondary}>{busy === "history" ? "Refreshing…" : "Refresh history"}</button></div>
            {history.length === 0 ? <div className="rounded-xl border border-dashed border-slate-300 p-8 text-center"><p className="font-semibold text-slate-800">No AI runs recorded yet</p><p className="mt-1 text-sm text-slate-500">Generate a JD, build a rubric, or analyze a resume to create a run record.</p></div> : <div className="overflow-x-auto rounded-xl border border-slate-200"><table className="w-full min-w-[760px] border-collapse text-left text-sm"><thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500"><tr><th className="px-4 py-3">Task</th><th className="px-4 py-3">Status</th><th className="px-4 py-3">Model</th><th className="px-4 py-3">Latency</th><th className="px-4 py-3">Tokens</th><th className="px-4 py-3">Calls</th><th className="px-4 py-3">Created</th><th className="px-4 py-3">Details</th></tr></thead><tbody className="divide-y divide-slate-100">{history.map((run) => <tr key={run.request_id} className="align-top"><td className="px-4 py-3 font-medium text-slate-800">{String(run.task_type).replaceAll("_", " ")}</td><td className="px-4 py-3"><MetaPill tone={run.status === "success" ? "good" : run.status === "failed" ? "bad" : "warn"}>{run.status}</MetaPill>{run.error_message && <p className="mt-1 max-w-48 text-xs text-rose-700">{run.error_message}</p>}</td><td className="max-w-44 break-words px-4 py-3 text-xs text-slate-600">{run.model}</td><td className="px-4 py-3 text-slate-700">{run.latency_ms == null ? "—" : run.latency_ms + " ms"}</td><td className="px-4 py-3 text-slate-700">{run.token_usage?.total_tokens ?? "—"}</td><td className="px-4 py-3 text-slate-700">{run.model_call_count ?? 0}</td><td className="px-4 py-3 text-xs text-slate-500">{displayDate(run.created_at)}</td><td className="px-4 py-3"><button type="button" className="font-semibold text-amber-800 underline underline-offset-2" onClick={() => void openHistoryDetail(run.request_id)}>Open</button></td></tr>)}</tbody></table></div>}
            {historyDetail && <section className="space-y-3 rounded-xl border border-slate-200 bg-slate-50 p-4"><div className="flex flex-wrap items-center justify-between gap-2"><div><h4 className="font-semibold text-slate-900">Run details</h4><p className="break-all font-mono text-xs text-slate-500">{historyDetail.request_id}</p></div><button type="button" className={btnSecondary} onClick={() => setHistoryDetail(null)}>Close details</button></div><div className="grid gap-2 sm:grid-cols-4"><MetaPill>{historyDetail.task_type}</MetaPill><MetaPill>{historyDetail.model}</MetaPill><MetaPill>{historyDetail.latency_ms ?? "—"} ms</MetaPill><MetaPill>{historyDetail.model_call_count ?? 0} model call(s)</MetaPill></div><details><summary className="cursor-pointer py-2 text-sm font-semibold text-slate-800">System prompt</summary><pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded-lg bg-white p-3 text-xs leading-5 text-slate-700">{historyDetail.system_prompt}</pre></details><details><summary className="cursor-pointer py-2 text-sm font-semibold text-slate-800">User prompt and input data</summary><pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-lg bg-white p-3 text-xs leading-5 text-slate-700">{historyDetail.user_prompt}</pre><pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap rounded-lg bg-white p-3 text-xs leading-5 text-slate-700">{JSON.stringify(historyDetail.input_data, null, 2)}</pre></details><details><summary className="cursor-pointer py-2 text-sm font-semibold text-slate-800">Structured result</summary><pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-lg bg-white p-3 text-xs leading-5 text-slate-700">{JSON.stringify(historyDetail.output_data, null, 2)}</pre></details><details><summary className="cursor-pointer py-2 text-sm font-semibold text-slate-800">Raw model output</summary><pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-lg bg-white p-3 text-xs leading-5 text-slate-700">{historyDetail.raw_model_output || historyDetail.error_message || "No raw model output."}</pre></details></section>}
          </div>}
        </div>
      </section>
      <p className="px-1 text-xs leading-5 text-slate-500">Recruiter review is required. AI scores can be incomplete or incorrect and must not be used as the sole basis for hiring decisions. Candidate data and prompts are stored in organisation-scoped run history for troubleshooting; only upload data your organisation is authorised to process.</p>
    </div>
  );
}
