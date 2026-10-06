import { useEffect, useMemo, useState } from "react";
import axios from "axios";

const configuredApiUrl = import.meta.env.VITE_API_URL?.trim();
const API_URL = (
  configuredApiUrl ||
  (import.meta.env.PROD ? "https://bluepace-ats-11.onrender.com" : "http://localhost:8000")
).replace(/\/+$/, "");
const REQUEST_TIMEOUT_MS = 90_000;
const RETRY_DELAYS_MS = [1_000, 2_000, 4_000];

function wait(ms) { return new Promise((resolve) => setTimeout(resolve, ms)); }

async function postToApi(path, data, config = {}, authToken = "") {
  for (let attempt = 0; ; attempt += 1) {
    try {
      return await axios.post(`${API_URL}${path}`, data, {
        timeout: REQUEST_TIMEOUT_MS,
        ...config,
        headers: {
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
          ...(config.headers || {}),
        },
      });
    } catch (error) {
      const status = error.response?.status;
      const retryable = !error.response || [502, 503, 504].includes(status);
      if (!retryable || attempt >= RETRY_DELAYS_MS.length) throw error;
      await wait(RETRY_DELAYS_MS[attempt]);
    }
  }
}

function apiErrorMessage(error, fallback) {
  const detail = error.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((item) => item.msg || String(item)).join("; ");
  if (error.response) return `The ATS API returned HTTP ${error.response.status}.`;
  if (error.code === "ECONNABORTED" || error.code === "ETIMEDOUT") {
    return "The extraction service is taking longer than usual. It may be waking from sleep; retry once.";
  }
  if (error.request) return `Cannot reach the ATS API at ${API_URL}.`;
  return error.message || fallback;
}

const labelMap = {
  name: "Name", email: "Email", phone: "Phone", linkedin: "LinkedIn", github: "GitHub",
  skills: "Skills", experience: "Experience", education: "Education", projects: "Projects",
  certifications: "Certifications", years_of_experience: "Experience years",
  current_location: "Current location", preferred_location: "Preferred location",
  notice_period: "Notice period", work_authorization: "Work authorization",
};

function scoreTone(value) {
  const score = Number(value);
  if (score >= 0.85) return "text-emerald-700 bg-emerald-50 border-emerald-100";
  if (score >= 0.65) return "text-amber-700 bg-amber-50 border-amber-100";
  return "text-ink-600 bg-ink-50 border-ink-100";
}

function Score({ value }) {
  if (value === null || value === undefined) return <span className="text-ink-400">—</span>;
  const score = Number(value);
  return <span className={`inline-flex rounded-full border px-2 py-1 text-xs font-semibold ${scoreTone(score)}`}>{Math.round(score * 100)}%</span>;
}

function FieldValue({ value }) {
  if (value === null || value === undefined || value === "") return <span className="text-ink-400">Not found</span>;
  if (Array.isArray(value)) return <span>{value.length ? value.join(", ") : "Not found"}</span>;
  if (typeof value === "object") return <span>{JSON.stringify(value)}</span>;
  return <span>{String(value)}</span>;
}

export default function App({ theme = "light", onToggleTheme = () => {}, token = "" }) {
  const [file, setFile] = useState(null);
  const [jsonData, setJsonData] = useState(null);
  const [jobDescription, setJobDescription] = useState("");
  const [validationResult, setValidationResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [validating, setValidating] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [validationError, setValidationError] = useState("");
  const [uploadTiming, setUploadTiming] = useState(null);
  const [validationTiming, setValidationTiming] = useState(null);
  const [showJson, setShowJson] = useState(false);
  const [showRawText, setShowRawText] = useState(false);
  const [bulkFiles, setBulkFiles] = useState([]);
  const [bulkBatchId, setBulkBatchId] = useState("");
  const [bulkJobs, setBulkJobs] = useState([]);
  const [bulkUploading, setBulkUploading] = useState(false);
  const [bulkError, setBulkError] = useState("");
  const [expandedBulkJobId, setExpandedBulkJobId] = useState(null);

  const quality = jsonData?.resume_quality || {};
  const evidence = jsonData?.extraction_evidence || [];
  const confidence = jsonData?.extraction_confidence || {};
  const requiredFields = ["name", "email", "phone", "skills", "experience", "education"];
  const extractedCount = useMemo(
    () => requiredFields.filter((field) => jsonData?.[field] && (!Array.isArray(jsonData[field]) || jsonData[field].length)).length,
    [jsonData],
  );

  function handleFileChange(event) {
    const selected = event.target.files?.[0] || null;
    setJsonData(null);
    setValidationResult(null);
    setValidationError("");
    setUploadTiming(null);
    if (!selected) { setFile(null); setUploadError(""); return; }
    if (!/\.(pdf|docx)$/i.test(selected.name)) {
      setFile(null); setUploadError("Choose a PDF or DOCX resume."); event.target.value = ""; return;
    }
    if (selected.size > 10 * 1024 * 1024) {
      setFile(null); setUploadError("Resume must be 10MB or smaller."); event.target.value = ""; return;
    }
    setFile(selected); setUploadError("");
  }

  async function handleExtract() {
    if (!file) { setUploadError("Choose a PDF or DOCX resume first."); return; }
    setLoading(true); setJsonData(null); setValidationResult(null); setUploadError(""); setUploadTiming(null);
    const started = performance.now();
    const body = new FormData();
    body.append("file", file);
    try {
      const response = await postToApi("/extract/", body);
      if (!response.data?.data || typeof response.data.data !== "object") throw new Error("The ATS API returned an invalid extraction response.");
      setJsonData(response.data.data);
      setUploadTiming({
        totalMs: Math.round(performance.now() - started),
        serverMs: Number(response.headers["x-process-time-ms"] || 0),
      });
    } catch (error) {
      console.error(error);
      setUploadError(apiErrorMessage(error, "Extraction failed. Please retry."));
    } finally { setLoading(false); }
  }

  async function queueBulkResumes() {
    if (!token) {
      setBulkError("Sign in to the recruiter workspace before using high-volume resume intake.");
      return;
    }
    const validFiles = bulkFiles.filter((item) => /\.(pdf|docx)$/i.test(item.name) && item.size <= 10 * 1024 * 1024);
    if (!validFiles.length) {
      setBulkError("Choose at least one PDF or DOCX resume up to 10MB.");
      return;
    }

    const batchId = bulkBatchId || (globalThis.crypto?.randomUUID ? globalThis.crypto.randomUUID() : `batch-${Date.now()}`);
    setBulkBatchId(batchId);
    setBulkError("");
    setBulkUploading(true);
    setBulkJobs(validFiles.map((file) => ({ filename: file.name, status: "uploading" })));

    let nextIndex = 0;
    const workers = Array.from({ length: Math.min(16, validFiles.length) }, async () => {
      while (nextIndex < validFiles.length) {
        const index = nextIndex;
        nextIndex += 1;
        const file = validFiles[index];
        const body = new FormData();
        body.append("file", file);
        body.append("batch_id", batchId);
        try {
          const response = await postToApi("/resume-processing/queue", body, {}, token);
          setBulkJobs((current) => current.map((job, jobIndex) => (
            jobIndex === index
              ? {
                  ...job,
                  status: "queued",
                  id: response.data?.job_id,
                  acceptedMs: response.data?.accepted_handler_ms,
                }
              : job
          )));
        } catch (error) {
          setBulkJobs((current) => current.map((job, jobIndex) => (
            jobIndex === index
              ? { ...job, status: "failed", error: apiErrorMessage(error, "Upload failed.") }
              : job
          )));
        }
      }
    });

    await Promise.all(workers);
    setBulkUploading(false);
  }

  async function refreshBulkJobs(batchId = bulkBatchId) {
    if (!token || !batchId) return;
    try {
      const response = await axios.get(`${API_URL}/resume-processing/jobs`, {
        timeout: REQUEST_TIMEOUT_MS,
        params: { batch_id: batchId, limit: 1000, include_result: true },
        headers: { Authorization: `Bearer ${token}` },
      });
      const rows = Array.isArray(response.data) ? response.data : [];
      setBulkJobs((current) => {
        const byId = new Map(rows.map((row) => [String(row.job_id), row]));
        const byName = new Map(rows.map((row) => [row.filename, row]));
        return current.map((job) => {
          const row = job.id ? (byId.get(String(job.id)) || byName.get(job.filename)) : byName.get(job.filename);
          if (!row) return job;
          return {
            ...job,
            id: row.job_id,
            status: row.status,
            error: row.error_message || null,
            result: row.result || null,
          };
        });
      });
    } catch (error) {
      setBulkError(apiErrorMessage(error, "Could not refresh batch status."));
    }
  }

  useEffect(() => {
    if (!bulkBatchId || !token || !bulkJobs.length) return undefined;
    const terminalCount = bulkJobs.filter((job) => ["completed", "failed"].includes(job.status)).length;
    if (terminalCount === bulkJobs.length) return undefined;
    const intervalId = window.setInterval(() => {
      void refreshBulkJobs();
    }, 2000);
    void refreshBulkJobs();
    return () => window.clearInterval(intervalId);
  }, [bulkBatchId, token, bulkJobs.length, bulkJobs.filter((job) => ["completed", "failed"].includes(job.status)).length]);

  async function handleValidate() {
    if (!jsonData || !jobDescription.trim()) {
      setValidationError("Extract a resume and enter a job description first.");
      return;
    }
    setValidating(true); setValidationResult(null); setValidationError(""); setValidationTiming(null);
    const started = performance.now();
    try {
      const response = await postToApi("/validate/", {
        resume_json: jsonData,
        job_description: jobDescription.trim(),
      });
      setValidationResult(response.data.validation);
      setValidationTiming({
        totalMs: Math.round(performance.now() - started),
        serverMs: Number(response.headers["x-process-time-ms"] || 0),
      });
    } catch (error) {
      console.error(error);
      setValidationError(apiErrorMessage(error, "Validation failed. Please retry."));
    } finally { setValidating(false); }
  }

  const candidateRows = [
    ["name", jsonData?.name], ["email", jsonData?.email], ["phone", jsonData?.phone],
    ["current_location", jsonData?.current_location], ["preferred_location", jsonData?.preferred_location],
    ["notice_period", jsonData?.notice_period], ["work_authorization", jsonData?.work_authorization],
    ["years_of_experience", jsonData?.years_of_experience], ["highest_education", jsonData?.highest_education],
  ];

  return (
    <div className="min-h-screen bg-[#f3f4f1] text-ink-900">
      <header className="sticky top-0 z-20 border-b border-ink-100 bg-white/95 backdrop-blur">
        <div className="mx-auto flex max-w-[1200px] items-center justify-between gap-4 px-4 py-4 sm:px-7">
          <div>
            <p className="text-xs font-medium text-ink-500">Candidate intelligence</p>
            <h1 className="text-lg font-semibold tracking-tight">Resume Lab</h1>
          </div>
          <button onClick={onToggleTheme} className="inline-flex h-9 items-center rounded-md border border-ink-100 bg-white px-3 text-xs font-semibold text-ink-700 hover:bg-ink-50" type="button">
            {theme === "light" ? "Dark mode" : "Light mode"}
          </button>
        </div>
      </header>

      <main className="mx-auto max-w-[1200px] px-4 py-6 sm:px-7 sm:py-8">
        <div className="mb-7 max-w-3xl">
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-blue-700">Extraction pipeline</p>
          <h2 className="mt-2 text-2xl font-semibold tracking-tight sm:text-3xl">Resume → structured evidence → validation</h2>
          <p className="mt-2 text-sm leading-6 text-ink-600">
            The first pass uses deterministic PDF/DOCX extraction. Structured fields are validated before they enter the ATS; AI enrichment stays optional.
          </p>
        </div>

        {token && (
          <section className="mb-6 border border-ink-100 bg-white p-5 sm:p-6">
            <div className="flex flex-wrap items-end justify-between gap-4">
              <div>
                <p className="text-xs font-semibold text-ink-500">High-volume intake</p>
                <h3 className="mt-1 text-lg font-semibold">Queue thousands of resumes</h3>
                <p className="mt-1 max-w-2xl text-sm leading-6 text-ink-600">
                  Upload resumes in parallel. The API acknowledges each accepted file and moves extraction to the background queue instead of parsing during the upload request.
                </p>
              </div>
              {bulkBatchId && <span className="text-xs text-ink-500">Batch {bulkBatchId}</span>}
            </div>
            <div className="mt-5 grid gap-3 sm:grid-cols-[1fr_auto] sm:items-end">
              <label className="grid gap-1.5 text-xs font-semibold text-ink-700">
                Resumes
                <input
                  type="file"
                  multiple
                  accept=".pdf,.docx"
                  className="rounded-md border border-ink-100 bg-white px-3 py-2.5 text-sm"
                  onChange={(event) => setBulkFiles(Array.from(event.target.files || []))}
                />
                <span className="text-[11px] font-normal text-ink-400">Select hundreds or thousands. Each file must be PDF/DOCX and ≤10MB.</span>
              </label>
              <button type="button" onClick={queueBulkResumes} disabled={bulkUploading || !bulkFiles.length} className="inline-flex items-center justify-center rounded-md bg-[#c49a4a] px-4 py-2.5 text-sm font-semibold text-[#10131c] disabled:opacity-50">
                {bulkUploading ? "Uploading…" : `Queue ${bulkFiles.length || 0} resumes`}
              </button>
            </div>
            {bulkError && <p role="alert" className="mt-3 text-sm text-rose-700">{bulkError}</p>}
            {bulkJobs.length > 0 && (
              <div className="mt-5 border-t border-ink-100 pt-4">
                <div className="flex flex-wrap gap-4 text-xs text-ink-500">
                  <span>Accepted/queued: {bulkJobs.filter((job) => job.status !== "uploading" && job.status !== "failed").length}</span>
                  <span>Processing: {bulkJobs.filter((job) => job.status === "processing").length}</span>
                  <span>Completed: {bulkJobs.filter((job) => job.status === "completed").length}</span>
                  <span>Failed: {bulkJobs.filter((job) => job.status === "failed").length}</span>
                </div>
                <div className="mt-3 max-h-48 overflow-auto border-y border-ink-100">
                  {bulkJobs.slice(0, 100).map((job, index) => (
                    <div key={`${job.filename}-${index}`} className="border-b border-ink-50 py-2 text-xs">
                      <div className="flex items-center justify-between gap-3">
                        <span className="min-w-0 truncate">{job.filename}</span>
                        <div className="flex shrink-0 items-center gap-2">
                          <span className="font-semibold capitalize text-ink-600">{job.status}</span>
                          {job.status === "completed" && job.result && (
                            <button
                              type="button"
                              className="font-semibold text-blue-700 hover:underline"
                              onClick={() => setExpandedBulkJobId((current) => current === job.id ? null : job.id)}
                            >
                              {expandedBulkJobId === job.id ? "Hide result" : "View result"}
                            </button>
                          )}
                        </div>
                      </div>
                      {job.error && <p className="mt-1 text-rose-700">{job.error}</p>}
                      {expandedBulkJobId === job.id && job.result && (
                        <pre className="mt-2 max-h-72 overflow-auto rounded border border-ink-100 bg-[#fafaf8] p-3 text-[11px] leading-5 text-ink-700">{JSON.stringify(job.result, null, 2)}</pre>
                      )}
                    </div>
                  ))}
                  {bulkJobs.length > 100 && <p className="py-2 text-xs text-ink-400">Showing the first 100 files.</p>}
                </div>
              </div>
            )}
          </section>
        )}

        <div className="grid gap-6 lg:grid-cols-[0.85fr_1.15fr]">
          <section className="border border-ink-100 bg-white p-5 sm:p-6">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-xs font-semibold text-ink-500">01 · Extract</p>
                <h3 className="mt-1 text-lg font-semibold">Upload a resume</h3>
              </div>
              {uploadTiming && <span className="text-right text-[11px] text-ink-500">Server {uploadTiming.serverMs.toFixed(0)} ms<br />Round trip {uploadTiming.totalMs} ms</span>}
            </div>
            <label className="mt-5 grid cursor-pointer gap-2 border border-dashed border-ink-200 bg-[#fafaf8] p-6 text-center hover:border-gold-400">
              <input className="sr-only" type="file" accept=".pdf,.docx" onChange={handleFileChange} />
              <span className="text-sm font-semibold">{file ? file.name : "Choose PDF or DOCX"}</span>
              <span className="text-xs text-ink-500">Text-based documents up to 10MB</span>
            </label>
            {file && <div className="mt-3 flex items-center justify-between gap-3 text-xs text-ink-500"><span>{(file.size / 1024).toFixed(0)} KB</span><button type="button" className="font-semibold text-ink-700 hover:underline" onClick={() => setFile(null)}>Remove</button></div>}
            <button type="button" onClick={handleExtract} disabled={!file || loading} className="mt-5 inline-flex w-full items-center justify-center rounded-md bg-[#c49a4a] px-4 py-3 text-sm font-semibold text-[#10131c] hover:bg-[#d4b06a] disabled:opacity-50">
              {loading ? "Extracting…" : "Extract & validate structure"}
            </button>
            {uploadError && <p role="alert" className="mt-3 text-sm text-rose-700">{uploadError}</p>}
            {jsonData && (
              <div className="mt-5 border-t border-ink-100 pt-5">
                <div className="flex items-center justify-between">
                  <div><p className="text-sm font-semibold">Extraction quality</p><p className="text-xs text-ink-500">{extractedCount}/{requiredFields.length} core fields present</p></div>
                  <span className="text-sm font-semibold">{quality.suspicious_fields?.length ? "Review needed" : "Ready"}</span>
                </div>
                <div className="mt-4 h-1.5 bg-ink-100"><div className="h-full bg-gold-500" style={{ width: `${Math.round((extractedCount / requiredFields.length) * 100)}%` }} /></div>
                {quality.missing_fields?.length > 0 && <p className="mt-3 text-xs text-ink-500">Missing: {quality.missing_fields.map((field) => labelMap[field] || field).join(", ")}</p>}
                {quality.suspicious_fields?.length > 0 && <div className="mt-3 border-l-2 border-amber-500 bg-amber-50 p-3 text-xs text-amber-900">{quality.suspicious_fields.map((item, i) => <p key={i}>{item.field}: {item.reason}</p>)}</div>}
              </div>
            )}
          </section>

          <section className="border border-ink-100 bg-white p-5 sm:p-6">
            <p className="text-xs font-semibold text-ink-500">02 · Review evidence</p>
            <h3 className="mt-1 text-lg font-semibold">Candidate profile</h3>
            {!jsonData ? (
              <div className="mt-5 border-t border-ink-100 py-10 text-sm text-ink-500">Extract a resume to see structured fields and their source evidence.</div>
            ) : (
              <>
                <div className="mt-5 grid gap-x-8 gap-y-4 border-t border-ink-100 pt-5 sm:grid-cols-2">
                  {candidateRows.map(([field, value]) => <div key={field}><p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-ink-400">{labelMap[field] || field}</p><p className="mt-1 text-sm"><FieldValue value={value} /></p></div>)}
                </div>
                <div className="mt-6 grid gap-5 sm:grid-cols-2">
                  <div><p className="text-xs font-semibold text-ink-500">Skills</p><div className="mt-2 flex flex-wrap gap-1.5">{(jsonData.skills || []).map((skill) => <span key={skill} className="border border-ink-100 bg-[#fafaf8] px-2 py-1 text-xs">{skill}</span>)}</div></div>
                  <div><p className="text-xs font-semibold text-ink-500">Confidence</p><div className="mt-2 grid gap-2">{Object.entries(confidence).slice(0, 6).map(([field, value]) => <div key={field} className="flex items-center justify-between gap-3 text-xs"><span>{labelMap[field] || field}</span><Score value={value} /></div>)}</div></div>
                </div>
                <div className="mt-6 flex flex-wrap gap-2 border-t border-ink-100 pt-4">
                  <button type="button" className="text-xs font-semibold text-ink-700 hover:underline" onClick={() => setShowJson((value) => !value)}>{showJson ? "Hide JSON" : "View JSON"}</button>
                  <button type="button" className="text-xs font-semibold text-ink-700 hover:underline" onClick={() => setShowRawText((value) => !value)}>{showRawText ? "Hide extracted text" : "View extracted text"}</button>
                </div>
                {showJson && <pre className="mt-3 max-h-72 overflow-auto bg-ink-950 p-4 text-xs leading-5 text-white">{JSON.stringify(jsonData, null, 2)}</pre>}
                {showRawText && <pre className="mt-3 max-h-72 overflow-auto whitespace-pre-wrap border border-ink-100 bg-[#fafaf8] p-4 text-xs leading-5 text-ink-700">{jsonData.raw_text || "No raw text returned."}</pre>}
              </>
            )}
          </section>
        </div>

        {jsonData && (
          <section className="mt-6 border border-ink-100 bg-white p-5 sm:p-6">
            <div className="flex flex-wrap items-end justify-between gap-4">
              <div><p className="text-xs font-semibold text-ink-500">03 · Validate</p><h3 className="mt-1 text-lg font-semibold">Compare against a job description</h3></div>
              {validationTiming && <span className="text-xs text-ink-500">Server {validationTiming.serverMs.toFixed(0)} ms · Round trip {validationTiming.totalMs} ms</span>}
            </div>
            <textarea rows={7} value={jobDescription} onChange={(event) => setJobDescription(event.target.value)} placeholder="Paste the job description here…" className="mt-5 w-full resize-y border border-ink-100 bg-[#fafaf8] p-4 text-sm leading-6 outline-none focus:border-gold-500" />
            <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
              <p className="text-xs text-ink-500">Matching is deterministic and decision-support only. It does not make a hiring decision.</p>
              <button type="button" onClick={handleValidate} disabled={validating || !jobDescription.trim()} className="inline-flex items-center justify-center rounded-md bg-[#c49a4a] px-4 py-2.5 text-sm font-semibold text-[#10131c] hover:bg-[#d4b06a] disabled:opacity-50">
                {validating ? "Validating…" : "Validate candidate"}
              </button>
            </div>
            {validationError && <p role="alert" className="mt-3 text-sm text-rose-700">{validationError}</p>}
          </section>
        )}

        {validationResult && (
          <section className="mt-6 border border-ink-100 bg-white p-5 sm:p-6">
            <div className="flex flex-wrap items-start justify-between gap-4 border-b border-ink-100 pb-5">
              <div><p className="text-xs font-semibold text-ink-500">Validation result</p><h3 className="mt-1 text-xl font-semibold">{validationResult.summary}</h3></div>
              <div className="text-right"><p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-ink-400">Match signal</p><p className="mt-1 text-3xl font-semibold">{Number(validationResult.match_score || 0)}%</p><p className="text-xs text-ink-500">{validationResult.recommendation || "Manual review"}</p></div>
            </div>
            <div className="grid gap-4 py-5 sm:grid-cols-3">
              {[["Required skills", validationResult.mandatory_skills_match_score], ["Coding skills", validationResult.coding_skills_score], ["Experience", validationResult.behavioral_skills_score]].map(([label, value]) => <div key={label} className="flex items-center justify-between border-b border-ink-50 py-2 text-sm"><span>{label}</span><strong>{Number(value || 0)}%</strong></div>)}
            </div>
            <div className="grid gap-6 lg:grid-cols-2">
              <div><p className="text-xs font-semibold uppercase tracking-[0.12em] text-ink-500">Evidence found</p><div className="mt-3 flex flex-wrap gap-2">{(validationResult.mandatory_skills_met || []).map((skill) => <span key={skill} className="border border-emerald-100 bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-700">{skill}</span>)}</div></div>
              <div><p className="text-xs font-semibold uppercase tracking-[0.12em] text-ink-500">Gaps</p><div className="mt-3 flex flex-wrap gap-2">{(validationResult.mandatory_skills_missed || []).map((skill) => <span key={skill} className="border border-rose-100 bg-rose-50 px-2.5 py-1 text-xs font-semibold text-rose-700">{skill}</span>)}</div></div>
            </div>
          </section>
        )}

        {jsonData && (
          <section className="mt-6 border-t border-ink-100 pt-5">
            <p className="text-xs font-semibold uppercase tracking-[0.12em] text-ink-500">Evidence trace</p>
            <div className="mt-3 grid gap-2">
              {evidence.slice(0, 12).map((item, index) => (
                <div key={`${item.field}-${index}`} className="grid gap-2 border-b border-ink-100 py-3 sm:grid-cols-[150px_90px_1fr] sm:items-start">
                  <span className="text-xs font-semibold">{labelMap[item.field] || item.field}</span>
                  <Score value={item.confidence} />
                  <div className="text-xs leading-5 text-ink-500">{(item.source_lines || []).join(" · ") || "No exact source line matched; review the extracted value."}</div>
                </div>
              ))}
              {!evidence.length && <p className="text-sm text-ink-500">No field-level evidence was returned.</p>}
            </div>
          </section>
        )}
      </main>
    </div>
  );
}
