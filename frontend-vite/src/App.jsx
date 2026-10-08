import { useEffect, useMemo, useState } from "react";
import { MAX_DOCUMENT_SIZE_BYTES, MAX_DOCUMENT_SIZE_LABEL } from "./constants/documentLimits.js";
import axios from "axios";

const configuredApiUrl = import.meta.env.VITE_API_URL?.trim();
const API_URL = (
  configuredApiUrl ||
  (import.meta.env.PROD ? "https://bluepace-ats-production.up.railway.app" : "http://localhost:8000")
).replace(/\/+$/, "");
const REQUEST_TIMEOUT_MS = 90_000;
const RETRY_DELAYS_MS = [1_000, 2_000, 4_000];

function wait(ms) { return new Promise((resolve) => setTimeout(resolve, ms)); }

let resumeLabRefreshInFlight = null;

async function refreshResumeLabToken(currentToken) {
  if (!currentToken) throw new Error("No access token available.");
  if (!resumeLabRefreshInFlight) {
    resumeLabRefreshInFlight = axios.post(
      `${API_URL}/auth/refresh`,
      null,
      { timeout: 15_000, headers: { Authorization: `Bearer ${currentToken}` } },
    )
      .then((response) => {
        const refreshedToken = response.data?.access_token;
        if (!refreshedToken) throw new Error("The ATS API did not return a refreshed access token.");
        sessionStorage.setItem("bluepace_token", refreshedToken);
        return refreshedToken;
      })
      .finally(() => { resumeLabRefreshInFlight = null; });
  }
  return resumeLabRefreshInFlight;
}

async function postToApi(path, data, config = {}, authToken = "") {
  let requestToken = sessionStorage.getItem("bluepace_token") || authToken || "";
  let refreshed = false;
  for (let attempt = 0; ; attempt += 1) {
    try {
      return await axios.post(`${API_URL}${path}`, data, {
        timeout: REQUEST_TIMEOUT_MS,
        ...config,
        headers: {
          ...(requestToken ? { Authorization: `Bearer ${requestToken}` } : {}),
          ...(config.headers || {}),
        },
      });
    } catch (error) {
      if (error.response?.status === 401 && requestToken && !refreshed && !path.startsWith("/auth/")) {
        requestToken = await refreshResumeLabToken(requestToken);
        refreshed = true;
        continue;
      }
      const status = error.response?.status;
      const retryable = !error.response || [502, 503, 504].includes(status);
      if (!retryable || attempt >= RETRY_DELAYS_MS.length) throw error;
      await wait(RETRY_DELAYS_MS[attempt]);
      requestToken = sessionStorage.getItem("bluepace_token") || requestToken;
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
  const [jdFile, setJdFile] = useState(null);
  const [jobDescriptionUrl, setJobDescriptionUrl] = useState("");
  const [jdLoading, setJdLoading] = useState(false);
  const [jdError, setJdError] = useState("");
  const [validationResult, setValidationResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [validating, setValidating] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [uploadValidation, setUploadValidation] = useState(null);
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
  const [resumeLabJobs, setResumeLabJobs] = useState([]);
  const [resumeLabJobId, setResumeLabJobId] = useState("");
  const [resumeLabSyncStatus, setResumeLabSyncStatus] = useState("");

  const quality = jsonData?.resume_quality || {};
  const evidence = jsonData?.extraction_evidence || [];
  const confidence = jsonData?.extraction_confidence || {};
  const requiredFields = ["name", "email", "phone", "skills", "experience", "education"];
  const extractedCount = useMemo(
    () => requiredFields.filter((field) => jsonData?.[field] && (!Array.isArray(jsonData[field]) || jsonData[field].length)).length,
    [jsonData],
  );

  useEffect(() => {
    if (!token) return undefined;
    let active = true;
    axios.get(`${API_URL}/jobs`, {
      timeout: REQUEST_TIMEOUT_MS,
      headers: { Authorization: `Bearer ${sessionStorage.getItem("bluepace_token") || token}` },
      params: { limit: 100 },
    })
      .then((response) => {
        if (!active) return;
        const rows = Array.isArray(response.data) ? response.data.filter((job) => job.status === "open") : [];
        setResumeLabJobs(rows);
        setResumeLabJobId((current) => current || String(rows[0]?.id || ""));
      })
      .catch(() => {});
    return () => { active = false; };
  }, [token]);

  async function loadJobDescriptionFromFile() {
    if (!jdFile) {
      setJdError("Choose a JD PDF or DOCX file first.");
      return;
    }
    if (jdFile.size > MAX_DOCUMENT_SIZE_BYTES) {
      setJdError(`JD file must be ${MAX_DOCUMENT_SIZE_LABEL} or smaller.`);
      return;
    }
    setJdLoading(true);
    setJdError("");
    try {
      const body = new FormData();
      body.append("file", jdFile);
      const response = await postToApi("/resume-processing/job-description", body, {}, token);
      setJobDescription(response.data?.description || "");
      setJobDescriptionUrl("");
      if (!response.data?.description) throw new Error("No job description text was extracted.");
    } catch (error) {
      setJdError(apiErrorMessage(error, "Could not read the JD file."));
    } finally {
      setJdLoading(false);
    }
  }

  async function loadJobDescriptionFromUrl() {
    const value = jobDescriptionUrl.trim();
    if (!value) {
      setJdError("Enter a public job description URL first.");
      return;
    }
    setJdLoading(true);
    setJdError("");
    try {
      const body = new FormData();
      body.append("job_url", value);
      const response = await postToApi("/resume-processing/job-description", body, {}, token);
      setJobDescription(response.data?.description || "");
      if (response.data?.title) {
        setJdError("");
      }
      if (!response.data?.description) throw new Error("No job description text was extracted from the link.");
    } catch (error) {
      setJdError(apiErrorMessage(error, "Could not import the job description from that link."));
    } finally {
      setJdLoading(false);
    }
  }

  function handleFileChange(event) {
    const selected = event.target.files?.[0] || null;
    setJsonData(null);
    setUploadValidation(null);
    setValidationResult(null);
    setValidationError("");
    setUploadTiming(null);
    if (!selected) { setFile(null); setUploadError(""); return; }
    if (!/\.(pdf|docx)$/i.test(selected.name)) {
      setFile(null); setUploadError("Choose a PDF or DOCX resume."); event.target.value = ""; return;
    }
    if (selected.size > MAX_DOCUMENT_SIZE_BYTES) {
      setFile(null); setUploadError("Resume must be 5 MB or smaller."); event.target.value = ""; return;
    }
    setFile(selected); setUploadError("");
  }

  async function handleExtract() {
    if (!file) { setUploadError("Choose a PDF or DOCX resume first."); return; }
    if (!jobDescription.trim()) { setUploadError("Paste the job description first so the candidate fit can be calculated."); return; }

    setLoading(true);
    setJsonData(null);
    setUploadValidation(null);
    setValidationResult(null);
    setValidationError("");
    setUploadError("");
    setResumeLabSyncStatus("");
    setUploadTiming(null);

    const started = performance.now();
    const body = new FormData();
    body.append("file", file);

    try {
      const response = await postToApi("/extract/", body);
      if (!response.data?.data || typeof response.data.data !== "object") {
        throw new Error("The ATS API returned an invalid extraction response.");
      }

      const extracted = response.data.data;
      setJsonData(extracted);
      setUploadValidation(response.data?.resume_validation || extracted.resume_validation || null);

      setUploadTiming({
        totalMs: Math.round(performance.now() - started),
        serverMs: Number(response.headers["x-process-time-ms"] || 0),
      });

      // Do not block Resume Lab on JD matching. Extraction result is shown
      // immediately; candidate-vs-JD validation runs independently.
      setValidating(true);
      const validationStarted = performance.now();
      void postToApi("/validate/", {
        resume_json: extracted,
        job_description: jobDescription.trim(),
      })
        .then((validationResponse) => {
          setValidationResult(validationResponse.data?.validation || null);
          setValidationTiming({
            totalMs: Math.round(performance.now() - validationStarted),
            serverMs: Number(validationResponse.headers["x-process-time-ms"] || 0),
          });
        })
        .catch((error) => {
          setValidationError(apiErrorMessage(error, "Validation failed. Please retry."));
        })
        .finally(() => {
          setValidating(false);
        });

      // ATS sync is also best-effort and must never delay the extraction UI.
      if (token && response.data?.resume_validation?.status !== "invalid") {
        void postToApi("/resume-processing/sync", {
          resume_json: extracted,
          job_id: resumeLabJobId ? Number(resumeLabJobId) : null,
          job_fit: null,
        }, {}, token)
          .then((syncResponse) => {
            setResumeLabSyncStatus(
              syncResponse.data?.application_id
                ? "Resume extracted and synced to Candidates, Applications, matching, and the Applied email template."
                : "Resume extracted and synced to the ATS Candidate record.",
            );
          })
          .catch((syncError) => {
            setResumeLabSyncStatus(
              "Resume extracted successfully, but ATS sync needs attention: " +
              apiErrorMessage(syncError, "sync failed"),
            );
          });
      } else if (response.data?.resume_validation?.status === "invalid") {
        setResumeLabSyncStatus(
          "Resume was extracted, but ATS sync was blocked by upload validation. Review the validation errors and upload a corrected resume.",
        );
      }
    } catch (error) {
      console.error(error);
      setUploadError(apiErrorMessage(error, "Extraction failed. Please retry."));
    } finally {
      setLoading(false);
    }
  }

  async function uploadToStorage(upload, file, authToken) {
    const rawUploadUrl = String(upload.upload_url || "").trim();
    if (!rawUploadUrl) throw new Error("The ATS API did not return a storage upload URL.");
    const uploadUrl = rawUploadUrl.replace(/^http:\/\//i, "https://");
    const response = await fetch(uploadUrl, {
      method: "PUT",
      headers: {
        "Content-Type": upload.content_type || file.type || "application/octet-stream",
        ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
      },
      body: file,
    });
    if (!response.ok) {
      let detail = "";
      try {
        const payload = await response.json();
        detail = payload?.detail ? ` ${payload.detail}` : "";
      } catch (_) {
        // Keep a concise fallback for non-JSON upstream errors.
      }
      throw new Error(`Storage upload returned HTTP ${response.status}.${detail}`);
    }
  }

  async function queueBulkResumes() {
    if (!token) {
      setBulkError("Sign in to the recruiter workspace before using high-volume resume intake.");
      return;
    }
    if (!jobDescription.trim()) {
      setBulkError("Paste the job description before queueing resumes so every candidate can be evaluated for fit.");
      return;
    }

    const validFiles = bulkFiles.filter((item) =>
      /\.(pdf|docx)$/i.test(item.name) && item.size > 0 && item.size <= MAX_DOCUMENT_SIZE_BYTES
    );
    if (!validFiles.length) {
      setBulkError("Choose at least one PDF or DOCX resume up to 5 MB.");
      return;
    }

    const batchId = globalThis.crypto?.randomUUID ? globalThis.crypto.randomUUID() : `batch-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    const chunkSize = 100;
    const uploadConcurrency = 12;
    setBulkBatchId(batchId);
    setBulkError("");
    setBulkUploading(true);
    setBulkJobs(validFiles.map((file) => ({ filename: file.name, status: "preparing", size_bytes: file.size })));

    try {
      for (let start = 0; start < validFiles.length; start += chunkSize) {
        const chunk = validFiles.slice(start, start + chunkSize);
        const chunkStartIndex = start;

        const manifest = chunk.map((file) => ({
          filename: file.name,
          size_bytes: file.size,
          content_type: file.type || (
            /\.pdf$/i.test(file.name)
              ? "application/pdf"
              : "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
          ),
        }));

        const presignResponse = await postToApi(
          "/resume-processing/batch/presign",
          { batch_id: batchId, files: manifest },
          {},
          token,
        );
        const uploads = Array.isArray(presignResponse.data?.uploads) ? presignResponse.data.uploads : [];
        if (uploads.length !== chunk.length) {
          throw new Error("The ATS API did not return a complete bulk upload manifest.");
        }

        setBulkJobs((current) => current.map((job, index) =>
          index >= chunkStartIndex && index < chunkStartIndex + chunk.length
            ? { ...job, status: "uploading" }
            : job
        ));

        let nextIndex = 0;
        const successfulUploads = new Array(chunk.length);
        const workers = Array.from(
          { length: Math.min(uploadConcurrency, chunk.length) },
          async () => {
            while (nextIndex < chunk.length) {
              const localIndex = nextIndex;
              nextIndex += 1;
              const file = chunk[localIndex];
              const upload = uploads[localIndex];
              try {
                await uploadToStorage(upload, file, token);
                successfulUploads[localIndex] = {
                  filename: file.name,
                  storage_path: upload.storage_path,
                  size_bytes: file.size,
                  content_type: upload.content_type,
                };
                setBulkJobs((current) => current.map((job, index) =>
                  index === chunkStartIndex + localIndex ? { ...job, status: "uploaded" } : job
                ));
              } catch (error) {
                setBulkJobs((current) => current.map((job, index) =>
                  index === chunkStartIndex + localIndex
                    ? { ...job, status: "failed", error: error.message || "Backblaze upload failed." }
                    : job
                ));
              }
            }
          },
        );
        await Promise.all(workers);

        const readyForQueue = successfulUploads.filter(Boolean);
        if (!readyForQueue.length) continue;

        const finalizeResponse = await postToApi(
          "/resume-processing/batch/finalize",
          {
            batch_id: batchId,
            files: readyForQueue,
            job_description: jobDescription.trim(),
            job_id: resumeLabJobId ? Number(resumeLabJobId) : null,
          },
          {},
          token,
        );

        const queuedJobs = Array.isArray(finalizeResponse.data?.jobs) ? finalizeResponse.data.jobs : [];
        readyForQueue.forEach((item, readyIndex) => {
          const sourceIndex = successfulUploads.findIndex((value) => value === item);
          const queueRow = queuedJobs[readyIndex];
          setBulkJobs((current) => current.map((job, index) =>
            index === chunkStartIndex + sourceIndex
              ? {
                  ...job,
                  id: queueRow?.job_id,
                  status: "queued",
                  acceptedMs: finalizeResponse.data?.accepted_handler_ms,
                }
              : job
          ));
        });
      }
    } catch (error) {
      console.error(error);
      setBulkError(apiErrorMessage(error, "Bulk resume intake failed."));
    } finally {
      setBulkUploading(false);
    }
  }

  async function refreshBulkJobs(batchId = bulkBatchId) {
    if (!batchId) return;
    let requestToken = sessionStorage.getItem("bluepace_token") || token || "";
    try {
      let response;
      try {
        response = await axios.get(`${API_URL}/resume-processing/jobs`, {
          timeout: REQUEST_TIMEOUT_MS,
          params: { batch_id: batchId, limit: 10000, include_result: false },
          headers: requestToken ? { Authorization: `Bearer ${requestToken}` } : {},
        });
      } catch (error) {
        if (error.response?.status !== 401 || !requestToken) throw error;
        requestToken = await refreshResumeLabToken(requestToken);
        response = await axios.get(`${API_URL}/resume-processing/jobs`, {
          timeout: REQUEST_TIMEOUT_MS,
          params: { batch_id: batchId, limit: 10000, include_result: false },
          headers: { Authorization: `Bearer ${requestToken}` },
        });
      }
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
            error: row.error_message || job.error || null,
            result: row.result ?? job.result ?? null,
          };
        });
      });
    } catch (error) {
      setBulkError(apiErrorMessage(error, "Could not refresh batch status."));
    }
  }

  async function handleBulkResultToggle(jobId) {
    if (expandedBulkJobId === jobId) {
      setExpandedBulkJobId(null);
      return;
    }
    setExpandedBulkJobId(jobId);
    const existing = bulkJobs.find((job) => String(job.id) === String(jobId));
    if (existing?.result) return;

    try {
      let requestToken = sessionStorage.getItem("bluepace_token") || token || "";
      let response;
      try {
        response = await axios.get(`${API_URL}/resume-processing/jobs/${jobId}`, {
          timeout: REQUEST_TIMEOUT_MS,
          headers: requestToken ? { Authorization: `Bearer ${requestToken}` } : {},
        });
      } catch (error) {
        if (error.response?.status !== 401 || !requestToken) throw error;
        requestToken = await refreshResumeLabToken(requestToken);
        response = await axios.get(`${API_URL}/resume-processing/jobs/${jobId}`, {
          timeout: REQUEST_TIMEOUT_MS,
          headers: { Authorization: `Bearer ${requestToken}` },
        });
      }
      const result = response.data?.result || null;
      setBulkJobs((current) => current.map((job) =>
        String(job.id) === String(jobId) ? { ...job, result } : job
      ));
    } catch (error) {
      setBulkError(apiErrorMessage(error, "Could not load the resume result."));
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
                  Upload hundreds or thousands at once. Files go directly to private Backblaze B2 in 100-file chunks; Render only handles small manifests and background processing.
                </p>
              </div>
              {bulkBatchId && <span className="text-xs text-ink-500">Batch {bulkBatchId}</span>}
            </div>
            <div className="mt-5 grid gap-3">
              <label className="grid gap-1.5 text-xs font-semibold text-ink-700">
                Job description for matching
                <select value={resumeLabJobId} onChange={(event) => setResumeLabJobId(event.target.value)} className="w-full rounded-md border border-ink-100 bg-white p-3 text-sm outline-none focus:border-gold-500">
                  <option value="">No ATS job — Resume Lab only</option>
                  {resumeLabJobs.map((job) => <option key={job.id} value={job.id}>Sync to: {job.title}</option>)}
                </select>
                <textarea
                  rows={5}
                  value={jobDescription}
                  onChange={(event) => { setJobDescription(event.target.value); setJdError(""); }}
                  placeholder="Paste the specific job description. Or import it from a file or public link below."
                  className="w-full resize-y rounded-md border border-ink-100 bg-[#fafaf8] p-3 text-sm leading-6 outline-none focus:border-gold-500"
                />
              </label>
              <div className="grid gap-3 md:grid-cols-2">
                <div className="rounded-md border border-ink-100 bg-[#fafaf8] p-3">
                  <p className="text-xs font-semibold text-ink-700">Upload JD</p>
                  <input type="file" accept=".pdf,.docx" className="mt-2 w-full text-xs" onChange={(event) => { const selected = event.target.files?.[0] || null; if (selected && selected.size > MAX_DOCUMENT_SIZE_BYTES) { setJdFile(null); setJdError(`JD file must be ${MAX_DOCUMENT_SIZE_LABEL} or smaller.`); event.target.value = ""; return; } setJdFile(selected); setJdError(""); }} />
                  <button type="button" onClick={loadJobDescriptionFromFile} disabled={!jdFile || jdLoading} className="mt-2 rounded-md border border-ink-200 bg-white px-3 py-2 text-xs font-semibold disabled:opacity-50">{jdLoading ? "Loading…" : "Use uploaded JD"}</button>
                </div>
                <div className="rounded-md border border-ink-100 bg-[#fafaf8] p-3">
                  <p className="text-xs font-semibold text-ink-700">Upload link</p>
                  <input value={jobDescriptionUrl} onChange={(event) => { setJobDescriptionUrl(event.target.value); setJdError(""); }} placeholder="https://..." className="mt-2 w-full rounded-md border border-ink-100 bg-white px-3 py-2 text-xs outline-none focus:border-gold-500" />
                  <button type="button" onClick={loadJobDescriptionFromUrl} disabled={!jobDescriptionUrl.trim() || jdLoading} className="mt-2 rounded-md border border-ink-200 bg-white px-3 py-2 text-xs font-semibold disabled:opacity-50">{jdLoading ? "Loading…" : "Use JD link"}</button>
                </div>
              </div>
              {jdError && <p role="alert" className="text-xs text-rose-700">{jdError}</p>}
              <div className="grid gap-3 sm:grid-cols-[1fr_auto] sm:items-end">
              <label className="grid gap-1.5 text-xs font-semibold text-ink-700">
                Resumes
                <input
                  type="file"
                  multiple
                  accept=".pdf,.docx"
                  className="rounded-md border border-ink-100 bg-white px-3 py-2.5 text-sm"
                  onChange={(event) => { const selectedFiles = Array.from(event.target.files || []); const oversized = selectedFiles.filter((item) => item.size > MAX_DOCUMENT_SIZE_BYTES); if (oversized.length) { setBulkFiles(selectedFiles.filter((item) => item.size <= MAX_DOCUMENT_SIZE_BYTES)); setBulkError(`${oversized.length} resume${oversized.length === 1 ? "" : "s"} exceed ${MAX_DOCUMENT_SIZE_LABEL}. They were removed from the batch.`); event.target.value = ""; return; } setBulkFiles(selectedFiles); setBulkError(""); }}
                />
                <span className="text-[11px] font-normal text-ink-400">Select hundreds or thousands. Each file is checked locally and must be PDF/DOCX and ≤5 MB.</span>
              </label>
              <button type="button" onClick={queueBulkResumes} disabled={bulkUploading || !bulkFiles.length || !jobDescription.trim()} className="inline-flex items-center justify-center rounded-md bg-[#c49a4a] px-4 py-2.5 text-sm font-semibold text-[#10131c] disabled:opacity-50">
                {bulkUploading ? "Uploading…" : `Queue ${bulkFiles.length || 0} resumes`}
              </button>
              </div>
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
                          {job.status === "completed" && job.id && (
                            <button
                              type="button"
                              className="font-semibold text-blue-700 hover:underline"
                              onClick={() => handleBulkResultToggle(job.id)}
                            >
                              {expandedBulkJobId === job.id ? "Hide result" : (job.result ? "View result" : "Load result")}
                            </button>
                          )}
                        </div>
                      </div>
                      {job.error && <p className="mt-1 text-rose-700">{job.error}</p>}
                      {job.result?.job_fit && (
                        <div className="mt-2 rounded border border-ink-100 bg-[#fafaf8] p-3">
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <span className="text-xs font-semibold">{job.result.job_fit.fit}</span>
                            <span className="text-sm font-semibold">{job.result.job_fit.match_score}% match</span>
                          </div>
                          <p className="mt-1 text-xs leading-5 text-ink-600">{job.result.job_fit.summary}</p>
                          <p className="mt-2 text-xs font-semibold text-ink-900">Recommendation: {job.result.job_fit.final_recommendation || job.result.job_fit.recommendation || "Manual review"}</p>
                          {job.result.job_fit.gaps?.length > 0 && <p className="mt-1 text-[11px] text-rose-700">Gaps: {job.result.job_fit.gaps.slice(0, 5).join(", ")}</p>}
                        </div>
                      )}
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
            <label className="mt-5 grid gap-1.5 text-xs font-semibold text-ink-700">
              Target ATS job (optional)
              <select value={resumeLabJobId} onChange={(event) => setResumeLabJobId(event.target.value)} className="w-full border border-ink-100 bg-white p-3 text-sm outline-none focus:border-gold-500">
                <option value="">Resume Lab only</option>
                {resumeLabJobs.map((job) => <option key={job.id} value={job.id}>{job.title}</option>)}
              </select>
            </label>
            <label className="mt-5 grid gap-1.5 text-xs font-semibold text-ink-700">
              Job description for candidate fit
              <textarea
                rows={6}
                value={jobDescription}
                onChange={(event) => { setJobDescription(event.target.value); setJdError(""); }}
                placeholder="Paste the specific job description to calculate fit, strengths, skill gaps and evidence."
                className="w-full resize-y border border-ink-100 bg-[#fafaf8] p-3 text-sm leading-6 outline-none focus:border-gold-500"
              />
              <span className="text-[11px] font-normal text-ink-400">The candidate summary is decision-support only and is based on resume-to-JD evidence.</span>
            </label>
            <div className="mt-3 grid gap-3 md:grid-cols-2">
              <div className="border border-ink-100 bg-[#fafaf8] p-3">
                <p className="text-xs font-semibold text-ink-700">Upload JD</p>
                <input type="file" accept=".pdf,.docx" className="mt-2 w-full text-xs" onChange={(event) => { const selected = event.target.files?.[0] || null; if (selected && selected.size > MAX_DOCUMENT_SIZE_BYTES) { setJdFile(null); setJdError(`JD file must be ${MAX_DOCUMENT_SIZE_LABEL} or smaller.`); event.target.value = ""; return; } setJdFile(selected); setJdError(""); }} />
                <button type="button" onClick={loadJobDescriptionFromFile} disabled={!jdFile || jdLoading} className="mt-2 rounded-md border border-ink-200 bg-white px-3 py-2 text-xs font-semibold disabled:opacity-50">{jdLoading ? "Loading…" : "Use uploaded JD"}</button>
              </div>
              <div className="border border-ink-100 bg-[#fafaf8] p-3">
                <p className="text-xs font-semibold text-ink-700">Upload link</p>
                <input value={jobDescriptionUrl} onChange={(event) => { setJobDescriptionUrl(event.target.value); setJdError(""); }} placeholder="https://..." className="mt-2 w-full border border-ink-100 bg-white px-3 py-2 text-xs outline-none focus:border-gold-500" />
                <button type="button" onClick={loadJobDescriptionFromUrl} disabled={!jobDescriptionUrl.trim() || jdLoading} className="mt-2 rounded-md border border-ink-200 bg-white px-3 py-2 text-xs font-semibold disabled:opacity-50">{jdLoading ? "Loading…" : "Use JD link"}</button>
              </div>
            </div>
            {jdError && <p role="alert" className="mt-3 text-xs text-rose-700">{jdError}</p>}
            <label className="mt-5 grid cursor-pointer gap-2 border border-dashed border-ink-200 bg-[#fafaf8] p-6 text-center hover:border-gold-400">
              <input className="sr-only" type="file" accept=".pdf,.docx" onChange={handleFileChange} />
              <span className="text-sm font-semibold">{file ? file.name : "Choose PDF or DOCX"}</span>
              <span className="text-xs text-ink-500">Text-based documents up to 5 MB</span>
            </label>
            {file && <div className="mt-3 flex items-center justify-between gap-3 text-xs text-ink-500"><span>{(file.size / 1024).toFixed(0)} KB</span><button type="button" className="font-semibold text-ink-700 hover:underline" onClick={() => setFile(null)}>Remove</button></div>}
            <button type="button" onClick={handleExtract} disabled={!file || loading} className="mt-5 inline-flex w-full items-center justify-center rounded-md bg-[#c49a4a] px-4 py-3 text-sm font-semibold text-[#10131c] hover:bg-[#d4b06a] disabled:opacity-50">
              {loading ? "Extracting…" : "Extract & validate structure"}
            </button>
            {uploadError && <p role="alert" className="mt-3 text-sm text-rose-700">{uploadError}</p>}
            {uploadValidation && (
              <div className="mt-4 border border-ink-100 bg-[#fafaf8] p-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-[0.12em] text-ink-500">Resume validation</p>
                    <p className="mt-1 text-sm font-semibold">
                      {uploadValidation.status === "valid" ? "Valid resume" : uploadValidation.status === "needs_review" ? "Needs review" : "Invalid resume"}
                    </p>
                  </div>
                  <span className={
                    uploadValidation.status === "valid"
                      ? "rounded-full border border-emerald-100 bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-700"
                      : uploadValidation.status === "needs_review"
                        ? "rounded-full border border-amber-100 bg-amber-50 px-2.5 py-1 text-xs font-semibold text-amber-700"
                        : "rounded-full border border-rose-100 bg-rose-50 px-2.5 py-1 text-xs font-semibold text-rose-700"
                  }>
                    {Number(uploadValidation.score || 0)}%
                  </span>
                </div>
                <p className="mt-2 text-xs leading-5 text-ink-600">{uploadValidation.message}</p>
                {uploadValidation.errors?.length > 0 && (
                  <div className="mt-3 space-y-1 text-xs text-rose-700">
                    {uploadValidation.errors.map((item, index) => <p key={"validation-error-" + index}>• {item}</p>)}
                  </div>
                )}
                {uploadValidation.warnings?.length > 0 && (
                  <div className="mt-3 space-y-1 text-xs text-amber-700">
                    {uploadValidation.warnings.map((item, index) => <p key={"validation-warning-" + index}>• {item}</p>)}
                  </div>
                )}
              </div>
            )}
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

        {resumeLabSyncStatus && <div role="status" className="mt-6 border-l-2 border-emerald-600 bg-white px-4 py-3 text-sm text-ink-700">{resumeLabSyncStatus}</div>}

        {validationResult && (
          <section className="mt-6 border border-ink-100 bg-white p-5 sm:p-6">
            <div className="flex flex-wrap items-start justify-between gap-4 border-b border-ink-100 pb-5">
              <div><p className="text-xs font-semibold text-ink-500">Validation result</p><h3 className="mt-1 text-xl font-semibold">{validationResult.summary}</h3></div>
              <div className="text-right"><p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-ink-400">Match signal</p><p className="mt-1 text-3xl font-semibold">{Number(validationResult.match_score || 0)}%</p><p className="text-xs text-ink-500">{validationResult.fit || "Manual review"}</p></div>
            </div>
            <div className="mb-1 rounded-lg border border-blue-100 bg-blue-50 p-4">
              <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-blue-700">Final recommendation</p>
              <p className="mt-1 text-sm font-semibold text-ink-900">{validationResult.final_recommendation || validationResult.recommendation || "Manual review required"}</p>
              <p className="mt-1 text-xs leading-5 text-ink-600">Evidence-based decision support from the current resume and job description. Final hiring decisions remain with the recruiting team.</p>
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
