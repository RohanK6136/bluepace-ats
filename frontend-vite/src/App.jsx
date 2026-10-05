import { useState } from "react";
import axios from "axios";

const configuredApiUrl = import.meta.env.VITE_API_URL?.trim();
const API_URL = (
  configuredApiUrl ||
  (import.meta.env.PROD
    ? "https://bluepace-ats-11.onrender.com"
    : "http://localhost:8000")
).replace(/\/+$/, "");
const REQUEST_TIMEOUT_MS = 90_000;
const RETRY_DELAYS_MS = [1_000, 2_000, 4_000];

function wait(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

async function postToApi(path, data, config = {}) {
  for (let attempt = 0; ; attempt += 1) {
    try {
      return await axios.post(`${API_URL}${path}`, data, { timeout: REQUEST_TIMEOUT_MS, ...config });
    } catch (error) {
      const retryableStatus = error.response?.status;
      const timedOut = ["ECONNABORTED", "ETIMEDOUT"].includes(error.code);
      if (timedOut || attempt >= RETRY_DELAYS_MS.length || (error.response && ![502, 503, 504].includes(retryableStatus))) throw error;
      await wait(RETRY_DELAYS_MS[attempt]);
    }
  }
}

function apiErrorMessage(error, fallback) {
  const detail = error.response?.data?.detail;
  if (error.response) {
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) return detail.map((item) => item.msg || String(item)).join("; ");
    return `The ATS API returned HTTP ${error.response.status}.`;
  }
  if (error.code === "ECONNABORTED" || error.code === "ETIMEDOUT") {
    return `The ATS API at ${API_URL} is taking longer than usual, possibly waking from sleep. Wait a moment and retry.`;
  }
  if (error.request) return `Cannot reach the ATS API at ${API_URL}. Check the API service and try again.`;
  return error.message || fallback;
}

export default function App({ theme = "light", onToggleTheme = () => {} }) {
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

  const handleFileChange = (event) => {
    const selectedFile = event.target.files?.[0] || null;
    setJsonData(null);
    setValidationResult(null);
    setValidationError("");
    if (!selectedFile) {
      setFile(null);
      setUploadError("");
      return;
    }
    if (!/\.(pdf|docx)$/i.test(selectedFile.name)) {
      setFile(null);
      setUploadError("Choose a PDF or DOCX resume.");
      event.target.value = "";
      return;
    }
    if (selectedFile.size > 10 * 1024 * 1024) {
      setFile(null);
      setUploadError("Resume must be 10MB or smaller.");
      event.target.value = "";
      return;
    }
    setFile(selectedFile);
    setUploadError("");
  };

  const handleUpload = async () => {
    if (!file) {
      setUploadError("Choose a PDF or DOCX resume first.");
      return;
    }
    setLoading(true);
    setJsonData(null);
    setValidationResult(null);
    setUploadError("");
    setUploadTiming(null);
    const startedAt = performance.now();
    const formData = new FormData();
    formData.append("file", file);
    try {
      const response = await postToApi("/extract/", formData);
      if (!response.data?.data || typeof response.data.data !== "object") {
        throw new Error("The ATS API returned an invalid extraction response.");
      }
      setJsonData(response.data.data);
      setUploadTiming({
        totalMs: Math.round(performance.now() - startedAt),
        serverMs: Number(response.headers.get("X-Process-Time-ms") || 0),
      });
    } catch (error) {
      console.error(error);
      setUploadError(apiErrorMessage(error, "Please try again."));
    } finally {
      setLoading(false);
    }
  };

  const handleValidate = async () => {
    if (!jsonData || !jobDescription) {
      setValidationError("Extract a resume and enter a job description first.");
      return;
    }
    setValidating(true);
    setValidationResult(null);
    setValidationError("");
    setValidationTiming(null);
    const startedAt = performance.now();
    try {
      const response = await postToApi("/validate/", {
        resume_json: jsonData,
        job_description: jobDescription,
      });
      setValidationResult(response.data.validation);
      setValidationTiming({
        totalMs: Math.round(performance.now() - startedAt),
        serverMs: Number(response.headers.get("X-Process-Time-ms") || 0),
      });
    } catch (error) {
      console.error(error);
      setValidationError(apiErrorMessage(error, "Please try again."));
    } finally {
      setValidating(false);
    }
  };

  const normalizeScore = (value) => {
    const raw = Number(String(value ?? "").replace(/[% ,]/g, ""));
    if (!Number.isFinite(raw)) return 0;
    return Math.max(0, Math.min(100, raw));
  };

  const getScoreColor = (score) => {
    const normalized = normalizeScore(score);
    if (normalized >= 75) return "text-emerald-600 dark:text-emerald-400";
    if (normalized >= 50) return "text-amber-600 dark:text-amber-400";
    return "text-rose-600 dark:text-rose-400";
  };

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 dark:bg-[#0B0F19] dark:text-slate-100 font-sans antialiased transition-colors duration-300 relative overflow-hidden">
      <div className="absolute top-[-10%] left-[-10%] w-[40%] h-[40%] bg-indigo-500/10 rounded-full blur-[120px] pointer-events-none"></div>
      <div className="absolute bottom-[-10%] right-[-10%] w-[40%] h-[40%] bg-violet-500/10 rounded-full blur-[120px] pointer-events-none"></div>

      <header className="bg-white/80 dark:bg-[#0B0F19]/70 backdrop-blur-xl border-b border-slate-200 dark:border-slate-800/60 sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3.5">
            <div className="w-10 h-10 bg-gradient-to-br from-indigo-500 to-violet-600 rounded-xl flex items-center justify-center shadow-lg">
              <span className="text-white font-bold text-lg">B</span>
            </div>
            <div>
              <h1 className="text-lg font-bold text-slate-900 dark:text-white tracking-tight">BluePace Tech</h1>
              <p className="text-[11px] text-indigo-600 dark:text-indigo-300/80 font-semibold tracking-[0.2em] uppercase">AI-Powered ATS</p>
            </div>
          </div>
          <button onClick={onToggleTheme} className="p-2.5 rounded-xl bg-slate-100 dark:bg-slate-800/80 text-slate-600 dark:text-slate-300 border border-slate-200 dark:border-slate-700">
            {theme === "light" ? "🌙" : "☀️"}
          </button>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-6 py-12 relative z-10">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 mb-10">
          <section className="bg-white/90 dark:bg-slate-900/60 backdrop-blur-xl p-8 rounded-3xl border border-slate-200 dark:border-slate-800 shadow-xl flex flex-col relative overflow-hidden">
            <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-indigo-500 to-violet-500 opacity-70"></div>
            <h2 className="text-2xl font-bold mb-2">1. Upload Resume</h2>
            <p className="text-slate-500 dark:text-slate-400 text-sm mb-6">Upload a PDF or DOCX file to extract structured data.</p>
            <div className="flex-1 flex flex-col items-center justify-center border border-dashed border-slate-300 dark:border-slate-700 rounded-2xl bg-slate-50 dark:bg-slate-950/50 p-10">
              <input type="file" accept=".pdf,.docx" onChange={handleFileChange} className="hidden" id="file-upload" />
              <label htmlFor="file-upload" className="cursor-pointer flex flex-col items-center">
                <div className="w-16 h-16 bg-white dark:bg-slate-800 rounded-2xl flex items-center justify-center mb-5 border border-slate-200 dark:border-slate-700 shadow-sm">
                  <span className="text-3xl">📄</span>
                </div>
                <span className="text-slate-700 dark:text-slate-200 font-semibold mb-2">Click to browse</span>
                <span className="text-slate-400 dark:text-slate-500 text-xs">PDF, DOCX up to 10MB</span>
              </label>
              {file && <div className="mt-6 bg-indigo-50 dark:bg-indigo-500/10 px-4 py-2.5 rounded-xl border border-indigo-100 dark:border-indigo-500/30 flex items-center gap-2.5"><span className="text-indigo-500">✓</span><span className="text-sm font-medium truncate max-w-[220px]">{file.name}</span></div>}
            </div>
            <button onClick={handleUpload} disabled={loading || !file} className="mt-8 w-full bg-gradient-to-r from-indigo-600 to-violet-600 text-white px-6 py-4 rounded-xl font-semibold disabled:from-slate-300 disabled:to-slate-300 disabled:text-slate-500 dark:disabled:from-slate-800 dark:disabled:to-slate-800">
              {loading ? "Extracting..." : "Upload & Extract JSON"}
            </button>
            {uploadError && <p role="alert" className="mt-3 text-sm text-rose-700 dark:text-rose-300">{uploadError}</p>}
          </section>

          <section className={`bg-white/90 dark:bg-slate-900/60 backdrop-blur-xl p-8 rounded-3xl border border-slate-200 dark:border-slate-800 shadow-xl flex flex-col relative overflow-hidden ${!jsonData ? 'opacity-40 pointer-events-none grayscale' : ''}`}>
            <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-violet-500 to-fuchsia-500 opacity-70"></div>
            <h2 className="text-2xl font-bold mb-2">2. Job Description</h2>
            <p className="text-slate-500 dark:text-slate-400 text-sm mb-6">Paste the JD to validate the candidate.</p>
            <textarea rows={8} placeholder="Paste JD here..." value={jobDescription} onChange={(e) => setJobDescription(e.target.value)} className="w-full flex-1 min-h-[220px] p-5 bg-slate-50 dark:bg-slate-950/50 border border-slate-200 dark:border-slate-800 rounded-2xl mb-8 text-slate-800 dark:text-slate-200 outline-none resize-none" />
            <button onClick={handleValidate} disabled={validating || !jobDescription || !jsonData} className="w-full bg-gradient-to-r from-indigo-600 to-violet-600 text-white px-6 py-4 rounded-xl font-semibold disabled:from-slate-300 disabled:to-slate-300 disabled:text-slate-500 dark:disabled:from-slate-800 dark:disabled:to-slate-800">
              {validating ? "Validating..." : "Validate Against Job Description"}
            </button>
            {validationError && <p role="alert" className="mt-3 text-sm text-rose-700 dark:text-rose-300">{validationError}</p>}
          </section>
        </div>

        {jsonData && (
          <div className="bg-slate-900 dark:bg-slate-900/80 rounded-3xl border border-slate-800 shadow-2xl overflow-hidden mb-10">
            <div className="bg-slate-950 px-6 py-4 border-b border-slate-800 flex justify-between items-center">
              <h3 className="text-slate-400 font-mono text-xs font-semibold uppercase flex items-center gap-2"><span className="w-2 h-2 rounded-full bg-indigo-500"></span> Extracted JSON Structure</h3>
            </div>
            <div className="p-6 overflow-auto max-h-96 bg-slate-950/40">
              <pre className="text-indigo-300 font-mono text-[13px]">{JSON.stringify(jsonData, null, 2)}</pre>
            </div>
          </div>
        )}

        {validationResult && (
          <div className="bg-white/90 dark:bg-slate-900/80 backdrop-blur-xl rounded-3xl border border-slate-200 dark:border-slate-800 shadow-xl overflow-hidden">
            <div className="bg-slate-50 dark:bg-slate-950/80 px-8 py-6 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between">
              <div>
                <h2 className="text-2xl font-bold">Resume Validation Results</h2>
                <p className="text-indigo-600 dark:text-indigo-400 text-sm mt-1">Fast local deterministic matching — no LLM call in the critical path</p>
                {validationTiming && (
                  <p className="text-xs text-slate-500 dark:text-slate-400 mt-2">
                    Server: {validationTiming.serverMs.toFixed(2)} ms · Total round trip: {validationTiming.totalMs} ms
                  </p>
                )}
              </div>
              {validationResult.is_fresher && (
                <span className="bg-blue-100 dark:bg-blue-500/20 text-blue-700 dark:text-blue-300 px-4 py-2 rounded-full text-sm font-bold border border-blue-200 dark:border-blue-500/30">
                  🎓 Fresher
                </span>
              )}
            </div>
            <div className="p-8">
              {validationResult.error ? (
                <div role="alert" className="border-l-2 border-amber-500 bg-amber-50 p-5 text-amber-950 dark:bg-amber-500/10 dark:text-amber-100">
                  <h3 className="font-semibold">Screening unavailable</h3>
                  <p className="mt-1 text-sm">{validationResult.summary || validationResult.error}</p>
                  <p className="mt-2 text-xs">No match score was produced. Review this candidate manually or retry screening.</p>
                  <button onClick={handleValidate} disabled={validating} className="mt-4 rounded-md border border-amber-700/30 bg-white px-3 py-2 text-sm font-semibold text-amber-950 disabled:opacity-50 dark:bg-transparent dark:text-amber-100">
                    {validating ? "Retrying..." : "Retry screening"}
                  </button>
                </div>
              ) : <>
              <div className="grid grid-cols-1 md:grid-cols-4 gap-6 mb-10">
                <div className="bg-slate-50 dark:bg-slate-950/50 p-6 rounded-2xl border border-slate-200 dark:border-slate-800 text-center">
                  <p className="text-slate-500 text-xs font-bold uppercase mb-2">Overall Match</p>
                  <p className={`text-4xl font-extrabold ${getScoreColor(validationResult.match_score)}`}>{normalizeScore(validationResult.match_score)}%</p>
                </div>
                <div className="bg-slate-50 dark:bg-slate-950/50 p-6 rounded-2xl border border-slate-200 dark:border-slate-800 text-center">
                  <p className="text-slate-500 text-xs font-bold uppercase mb-2">Mandatory Skills</p>
                  <p className={`text-4xl font-extrabold ${getScoreColor(validationResult.mandatory_skills_match_score)}`}>{normalizeScore(validationResult.mandatory_skills_match_score)}%</p>
                </div>
                <div className="bg-slate-50 dark:bg-slate-950/50 p-6 rounded-2xl border border-slate-200 dark:border-slate-800 text-center">
                  <p className="text-slate-500 text-xs font-bold uppercase mb-2">Coding Skills</p>
                  <p className={`text-4xl font-extrabold ${getScoreColor(validationResult.coding_skills_score)}`}>{normalizeScore(validationResult.coding_skills_score)}%</p>
                </div>
                <div className="bg-slate-50 dark:bg-slate-950/50 p-6 rounded-2xl border border-slate-200 dark:border-slate-800 text-center">
                  <p className="text-slate-500 text-xs font-bold uppercase mb-2">Behavioral</p>
                  <p className={`text-4xl font-extrabold ${getScoreColor(validationResult.behavioral_skills_score)}`}>{normalizeScore(validationResult.behavioral_skills_score)}%</p>
                </div>
              </div>
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 mb-10">
                <div>
                  <h3 className="text-sm font-bold mb-3 uppercase tracking-wide text-emerald-600 dark:text-emerald-400">✅ Mandatory Skills Met</h3>
                  <div className="bg-emerald-50 dark:bg-emerald-500/10 p-5 rounded-2xl border border-emerald-200 dark:border-emerald-500/20 flex flex-wrap gap-2">
                    {validationResult.mandatory_skills_met?.map((skill, i) => <span key={i} className="bg-emerald-100 dark:bg-emerald-500/20 text-emerald-700 dark:text-emerald-300 px-3 py-1 rounded-full text-xs font-semibold">{skill}</span>)}
                  </div>
                </div>
                <div>
                  <h3 className="text-sm font-bold mb-3 uppercase tracking-wide text-rose-600 dark:text-rose-400">❌ Mandatory Skills Missed</h3>
                  <div className="bg-rose-50 dark:bg-rose-500/10 p-5 rounded-2xl border border-rose-200 dark:border-rose-500/20 flex flex-wrap gap-2">
                    {validationResult.mandatory_skills_missed?.map((skill, i) => <span key={i} className="bg-rose-100 dark:bg-rose-500/20 text-rose-700 dark:text-rose-300 px-3 py-1 rounded-full text-xs font-semibold">{skill}</span>)}
                  </div>
                </div>
              </div>
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 mb-10">
                <div>
                  <h3 className="text-sm font-bold mb-3 uppercase tracking-wide">📝 Evaluation Summary</h3>
                  <p className="text-slate-600 dark:text-slate-400 text-sm bg-slate-50 dark:bg-slate-950/50 p-5 rounded-2xl border border-slate-200 dark:border-slate-800">{validationResult.summary}</p>
                </div>
                <div>
                  <h3 className="text-sm font-bold mb-3 uppercase tracking-wide">🎯 Other Missing Skills</h3>
                  <div className="bg-slate-50 dark:bg-slate-950/50 p-5 rounded-2xl border border-slate-200 dark:border-slate-800 min-h-[100px] flex flex-wrap gap-2">
                    {validationResult.missing_skills?.map((skill, i) => <span key={i} className="bg-rose-50 dark:bg-rose-500/10 text-rose-700 dark:text-rose-300 px-4 py-1.5 rounded-full text-xs font-semibold border border-rose-200 dark:border-rose-500/20">{skill}</span>)}
                  </div>
                </div>
              </div>
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-8 mb-10">
                <div className="lg:col-span-2">
                  <h3 className="text-sm font-bold mb-3 uppercase tracking-wide">🎓 Education Qualification</h3>
                  {validationResult.highest_education && (
                    <div className="mb-3 bg-indigo-50 dark:bg-indigo-500/10 p-3 rounded-xl border border-indigo-200 dark:border-indigo-500/20">
                      <span className="text-xs font-bold uppercase text-indigo-600 dark:text-indigo-400">Highest Education: </span>
                      <span className="text-sm font-semibold">{validationResult.highest_education}</span>
                    </div>
                  )}
                  <div className="space-y-3">
                    {validationResult.extracted_education?.length > 0 ? (
                      validationResult.extracted_education.map((edu, i) => (
                        <div key={i} className="bg-slate-50 dark:bg-slate-950/50 p-4 rounded-xl border border-slate-200 dark:border-slate-800">
                          <p className="font-bold text-slate-800 dark:text-slate-200">{edu.degree}</p>
                          <p className="text-sm text-slate-500 dark:text-slate-400">{edu.university} | {edu.graduation_year}</p>
                          <p className="text-sm font-semibold text-indigo-600 dark:text-indigo-400 mt-1">CGPA: {edu.cgpa || "N/A"}</p>
                        </div>
                      ))
                    ) : <p className="text-sm text-slate-500">No education details found.</p>}
                  </div>
                </div>
                <div className="space-y-6">
                  <div>
                    <h3 className="text-sm font-bold mb-3 uppercase tracking-wide">👨‍🎓 Fresher Status</h3>
                    <div className="bg-blue-50 dark:bg-blue-500/10 p-4 rounded-xl border border-blue-200 dark:border-blue-500/20 text-center">
                      <p className="text-sm font-bold text-blue-700 dark:text-blue-300">
                        {validationResult.is_fresher ? "Yes, Candidate is a Fresher" : "No, Candidate has Work Experience"}
                      </p>
                    </div>
                  </div>
                  <div>
                    <h3 className="text-sm font-bold mb-3 uppercase tracking-wide">🏫 University Projects</h3>
                    <ul className="list-disc list-inside text-sm text-slate-600 dark:text-slate-400 space-y-1 bg-slate-50 dark:bg-slate-950/50 p-4 rounded-xl border border-slate-200 dark:border-slate-800">
                      {validationResult.extracted_university_projects?.length > 0 ? validationResult.extracted_university_projects.map((p, i) => <li key={i}>{p}</li>) : <li className="italic">None listed</li>}
                    </ul>
                  </div>
                  <div>
                    <h3 className="text-sm font-bold mb-3 uppercase tracking-wide">🎨 Hobbies</h3>
                    <div className="flex flex-wrap gap-2">
                      {validationResult.extracted_hobbies?.length > 0 ? validationResult.extracted_hobbies.map((h, i) => <span key={i} className="bg-violet-50 dark:bg-violet-500/10 text-violet-700 dark:text-violet-300 px-3 py-1 rounded-full text-xs font-semibold border border-violet-200 dark:border-violet-500/20">{h}</span>) : <span className="text-sm text-slate-500 italic">Not specified</span>}
                    </div>
                  </div>
                </div>
              </div>
              <div className="pt-6 border-t border-slate-200 dark:border-slate-800 flex items-center justify-between">
                <span className="text-slate-500 text-sm font-bold uppercase tracking-wider">Final Recommendation</span>
                <span className={`px-8 py-3 rounded-xl font-bold text-lg ${
                  validationResult.recommendation?.includes("Yes") ? "bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-500/20" :
                  validationResult.recommendation === "Maybe" ? "bg-amber-50 dark:bg-amber-500/10 text-amber-700 dark:text-amber-400 border border-amber-200 dark:border-amber-500/20" :
                  "bg-rose-50 dark:bg-rose-500/10 text-rose-700 dark:text-rose-400 border border-rose-200 dark:border-rose-500/20"
                }`}>
                  {validationResult.recommendation || "N/A"}
                </span>
              </div>
              </>}
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
