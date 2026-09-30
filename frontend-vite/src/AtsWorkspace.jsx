import { useEffect, useState } from "react";
import axios from "axios";
import ResumeLab from "./App.jsx";

const configuredApiUrl = import.meta.env.VITE_API_URL?.trim();
const API_URL = (
  configuredApiUrl ||
  (import.meta.env.PROD
    ? "https://bluepace-ats-11.onrender.com"
    : "http://localhost:8000")
).replace(/\/+$/, "");
const REQUEST_TIMEOUT_MS = 90_000;
const RETRY_DELAYS_MS = [1_000, 2_000, 4_000];
const STAGES = ["Applied", "Screening", "Interview", "Offer", "Hired", "Rejected"];
const MATCH_WEIGHTS = { skills: 30, semantic: 30, experience: 15, education: 10, location: 15 };
const buttonPrimary = "inline-flex items-center justify-center gap-2 rounded-md bg-[#c49a4a] px-4 py-2 text-sm font-semibold text-[#10131c] transition hover:bg-[#d4b06a] disabled:cursor-not-allowed disabled:opacity-50";
const buttonSecondary = "inline-flex items-center justify-center gap-2 rounded-md border border-ink-100 bg-white px-3 py-2 text-sm font-semibold text-ink-800 transition hover:bg-ink-50 disabled:cursor-not-allowed disabled:opacity-50";
const inputStyle = "w-full rounded-md border border-ink-100 bg-white px-3 py-2.5 text-sm text-ink-900 outline-none transition placeholder:text-ink-400 focus:border-gold-500 focus:ring-2 focus:ring-gold-100";

function wait(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function shouldRetry(error) {
  if (["ECONNABORTED", "ETIMEDOUT"].includes(error.code)) return false;
  if (!error.response) return true;
  return [502, 503, 504].includes(error.response.status);
}

async function apiRequest(token, method, path, options = {}) {
  for (let attempt = 0; ; attempt += 1) {
    try {
      return await axios.request({
        baseURL: API_URL,
        method,
        url: path,
        timeout: REQUEST_TIMEOUT_MS,
        ...options,
        headers: {
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
          ...options.headers,
        },
      });
    } catch (error) {
      if (attempt >= RETRY_DELAYS_MS.length || !shouldRetry(error)) throw error;
      await wait(RETRY_DELAYS_MS[attempt]);
    }
  }
}

function errorText(error) {
  const response = error.response;
  if (response) {
    const detail = response.data?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) return detail.map((item) => item.msg || String(item)).join("; ");
    if (typeof response.data === "string") return `API returned HTTP ${response.status}: ${response.data}`;
    return `API returned HTTP ${response.status}.`;
  }
  if (["ECONNABORTED", "ETIMEDOUT"].includes(error.code)) {
    return `The ATS API at ${API_URL} did not respond in time. It may be waking from sleep or overloaded; wait briefly and retry.`;
  }
  if (error.request) return `Cannot reach the ATS API at ${API_URL}. Check that the backend is running and VITE_API_URL is correct.`;
  return error.message || "The request could not be completed.";
}

function Field({ label, ...props }) {
  return (
    <label className="grid gap-1.5 text-xs font-semibold text-ink-700">
      {label}
      <input className={inputStyle} {...props} />
    </label>
  );
}

function SelectField({ label, children, ...props }) {
  return (
    <label className="grid gap-1.5 text-xs font-semibold text-ink-700">
      {label}
      <select className={inputStyle} {...props}>{children}</select>
    </label>
  );
}

function EmptyState({ title, detail }) {
  return (
    <div className="border-t border-ink-100 py-16 text-center">
      <p className="font-semibold text-ink-800">{title}</p>
      <p className="mt-1 text-sm text-ink-500">{detail}</p>
    </div>
  );
}

export default function AtsWorkspace() {
  const [token, setToken] = useState(() => sessionStorage.getItem("bluepace_token"));
  const [user, setUser] = useState(null);
  const [accessMode, setAccessMode] = useState(() => (
    new URLSearchParams(window.location.search).get("mode") === "admin" ? "admin" : "public"
  ));
  const [publicJobs, setPublicJobs] = useState([]);
  const [publicLoading, setPublicLoading] = useState(false);
  const [publicApplyJob, setPublicApplyJob] = useState(null);
  const [publicResume, setPublicResume] = useState(null);
  const [publicForm, setPublicForm] = useState({ full_name: "", email: "", phone: "" });
  const [publicError, setPublicError] = useState("");
  const [publicSuccess, setPublicSuccess] = useState("");
  const [authMode, setAuthMode] = useState("login");
  const [authForm, setAuthForm] = useState({ organization_name: "", full_name: "", email: "", password: "" });
  const [authError, setAuthError] = useState("");
  const [view, setView] = useState("pipeline");
  const [jobs, setJobs] = useState([]);
  const [candidates, setCandidates] = useState([]);
  const [applications, setApplications] = useState([]);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [filters, setFilters] = useState({ search: "", skill: "", stage_name: "", source: "", applied_after: "", applied_before: "" });
  const [jobFormOpen, setJobFormOpen] = useState(false);
  const [jobEntryMode, setJobEntryMode] = useState("manual");
  const [jobDocumentFile, setJobDocumentFile] = useState(null);
  const [editingJob, setEditingJob] = useState(null);
  const [jobForm, setJobForm] = useState({
    title: "",
    description: "",
    department: "",
    location: "",
    employment_type: "Full-time",
    status: "open",
    required_skills: "",
    minimum_experience_years: "",
    fresher_allowed: false,
  });
  const [candidateFormOpen, setCandidateFormOpen] = useState(false);
  const [candidateEntryMode, setCandidateEntryMode] = useState("manual");
  const [candidateForm, setCandidateForm] = useState({ first_name: "", last_name: "", email: "", phone: "", source: "Direct", job_id: "" });
  const [resumeFile, setResumeFile] = useState(null);
  const [selectedCandidate, setSelectedCandidate] = useState(null);
  const [applicationFormOpen, setApplicationFormOpen] = useState(false);
  const [applicationEntryMode, setApplicationEntryMode] = useState("existing");
  const [applicationForm, setApplicationForm] = useState({ job_id: "", candidate_id: "" });
  const [applicationResumeFile, setApplicationResumeFile] = useState(null);
  const [selectedApplications, setSelectedApplications] = useState([]);
  const [bulkStage, setBulkStage] = useState("Screening");
  const [matchJobId, setMatchJobId] = useState("");
  const [matchAnalysis, setMatchAnalysis] = useState(null);
  const [matches, setMatches] = useState([]);
  const [matching, setMatching] = useState(false);
  const [matchFeedback, setMatchFeedback] = useState({});

  const canWrite = user && ["admin", "recruiter"].includes(user.role);

  useEffect(() => {
    if (token || accessMode !== "public") return undefined;
    let active = true;
    async function loadPublicJobs() {
      setPublicLoading(true);
      setPublicError("");
      try {
        const response = await apiRequest(null, "get", "/public/jobs");
        if (active) setPublicJobs(Array.isArray(response.data) ? response.data : []);
      } catch (requestError) {
        if (active) setPublicError(errorText(requestError));
      } finally {
        if (active) setPublicLoading(false);
      }
    }
    loadPublicJobs();
    return () => { active = false; };
  }, [token, accessMode]);

  useEffect(() => {
    if (!token) return undefined;
    let active = true;
    async function loadWorkspace() {
      setLoading(true);
      try {
        const [userResponse, jobsResponse, candidateResponse, applicationResponse] = await Promise.all([
          apiRequest(token, "get", "/auth/me"),
          apiRequest(token, "get", "/jobs", { params: { limit: 100 } }),
          apiRequest(token, "get", "/candidates", { params: { limit: 100 } }),
          apiRequest(token, "get", "/applications", { params: { limit: 100 } }),
        ]);
        if (!active) return;
        setUser(userResponse.data);
        setJobs(jobsResponse.data);
        setMatchJobId((current) => current || String(jobsResponse.data.find((job) => job.status === "open")?.id || jobsResponse.data[0]?.id || ""));
        setCandidates(candidateResponse.data);
        setApplications(applicationResponse.data);
        setError("");
      } catch (loadError) {
        if (!active) return;
        sessionStorage.removeItem("bluepace_token");
        setToken(null);
        setError(errorText(loadError));
      } finally {
        if (active) setLoading(false);
      }
    }
    loadWorkspace();
    return () => { active = false; };
  }, [token]);

  async function refreshWorkspace() {
    if (!token) return;
    const params = Object.fromEntries(Object.entries(filters).filter(([, value]) => value));
    const [jobsResponse, candidateResponse, applicationResponse] = await Promise.all([
      apiRequest(token, "get", "/jobs", { params: { limit: 100 } }),
      apiRequest(token, "get", "/candidates", { params: { limit: 100 } }),
      apiRequest(token, "get", "/applications", { params: { ...params, limit: 100 } }),
    ]);
    setJobs(jobsResponse.data);
    setCandidates(candidateResponse.data);
    setApplications(applicationResponse.data);
  }

  async function signIn(event) {
    event.preventDefault();
    setAuthError("");
    try {
      if (authMode === "register") {
        await apiRequest(null, "post", "/auth/register", { data: authForm });
      }
      const credentials = new URLSearchParams();
      credentials.set("username", authForm.email);
      credentials.set("password", authForm.password);
      const response = await apiRequest(null, "post", "/auth/token", {
        data: credentials,
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
      });
      sessionStorage.setItem("bluepace_token", response.data.access_token);
      setToken(response.data.access_token);
    } catch (authRequestError) {
      setAuthError(errorText(authRequestError));
    }
  }

  function signOut() {
    sessionStorage.removeItem("bluepace_token");
    setToken(null);
    setUser(null);
    setJobs([]);
    setCandidates([]);
    setApplications([]);
    setNotice("");
    setError("");
  }

  async function loadFilteredApplications(event) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const params = Object.fromEntries(Object.entries(filters).filter(([, value]) => value));
      const response = await apiRequest(token, "get", "/applications", { params: { ...params, limit: 100 } });
      setApplications(response.data);
      setSelectedApplications([]);
    } catch (requestError) {
      setError(errorText(requestError));
    } finally {
      setLoading(false);
    }
  }

  function resetJobForm(job = null) {
    setEditingJob(job);
    setJobEntryMode(job ? "manual" : "manual");
    setJobDocumentFile(null);
    setJobForm(job ? {
      title: job.title,
      description: job.description,
      department: job.department || "",
      location: job.location || "",
      employment_type: job.employment_type || "Full-time",
      status: job.status,
      required_skills: (job.required_skills || []).join(", "),
      minimum_experience_years: job.minimum_experience_years ?? "",
      fresher_allowed: Boolean(job.fresher_allowed),
    } : {
      title: "",
      description: "",
      department: "",
      location: "",
      employment_type: "Full-time",
      status: "open",
      required_skills: "",
      minimum_experience_years: "",
      fresher_allowed: false,
    });
    setJobFormOpen(true);
  }

  async function saveJob(event) {
    event.preventDefault();
    setError("");
    try {
      if (!editingJob && jobEntryMode === "upload") {
        if (!jobDocumentFile) {
          setError("Select a PDF or DOCX job description.");
          return;
        }
        const body = new FormData();
        body.append("file", jobDocumentFile);
        if (jobForm.title.trim()) body.append("title", jobForm.title.trim());
        if (jobForm.department.trim()) body.append("department", jobForm.department.trim());
        if (jobForm.location.trim()) body.append("location", jobForm.location.trim());
        if (jobForm.employment_type.trim()) body.append("employment_type", jobForm.employment_type.trim());
        body.append("status_value", jobForm.status);
        if (jobForm.minimum_experience_years !== "") body.append("minimum_experience_years", String(Number(jobForm.minimum_experience_years)));
        body.append("fresher_allowed", String(Boolean(jobForm.fresher_allowed)));
        await apiRequest(token, "post", "/jobs/from-document", { data: body });
        setNotice("Job document parsed, job created, and JD requirements extracted");
      } else {
        const jobPayload = {
          ...jobForm,
          required_skills: [...new Set(jobForm.required_skills.split(/[;,\n]/).map((skill) => skill.trim()).filter(Boolean))],
          minimum_experience_years: jobForm.minimum_experience_years === "" ? null : Number(jobForm.minimum_experience_years),
        };
        if (editingJob) {
          await apiRequest(token, "patch", `/jobs/${editingJob.id}`, { data: jobPayload });
          setNotice("Job updated");
        } else {
          await apiRequest(token, "post", "/jobs", { data: jobPayload });
          setNotice("Job created");
        }
      }
      setJobFormOpen(false);
      setJobDocumentFile(null);
      setJobEntryMode("manual");
      await refreshWorkspace();
    } catch (requestError) {
      setError(errorText(requestError));
    }
  }

  async function archiveJob(job) {
    if (!window.confirm(`Archive ${job.title}?`)) return;
    try {
      await apiRequest(token, "post", `/jobs/${job.id}/archive`);
      setNotice("Job archived");
      await refreshWorkspace();
    } catch (requestError) {
      setError(errorText(requestError));
    }
  }

  async function saveCandidate(event) {
    event.preventDefault();
    setError("");
    try {
      if (candidateEntryMode === "resume") {
        if (!resumeFile) {
          setError("Select a PDF or DOCX resume.");
          return;
        }
        const body = new FormData();
        body.append("file", resumeFile);
        if (candidateForm.job_id) body.append("job_id", candidateForm.job_id);
        await apiRequest(token, "post", "/candidates/from-resume", { data: body });
        setCandidateForm({ first_name: "", last_name: "", email: "", phone: "", source: "Direct", job_id: "" });
        setResumeFile(null);
        setCandidateEntryMode("manual");
        setCandidateFormOpen(false);
        setNotice(candidateForm.job_id ? "Resume parsed, candidate added, and matched to the selected job" : "Resume parsed and candidate added");
        await refreshWorkspace();
        return;
      }

      const response = await apiRequest(token, "post", "/candidates", { data: candidateForm });
      if (resumeFile) {
        const body = new FormData();
        body.append("file", resumeFile);
        await apiRequest(token, "post", `/candidates/${response.data.id}/resume`, { data: body });
      }
      if (candidateForm.job_id) {
        await apiRequest(token, "post", "/applications", {
          data: { job_id: Number(candidateForm.job_id), candidate_id: response.data.id },
        });
      }
      setCandidateForm({ first_name: "", last_name: "", email: "", phone: "", source: "Direct", job_id: "" });
      setResumeFile(null);
      setCandidateFormOpen(false);
      setNotice(
        candidateForm.job_id
          ? (resumeFile ? "Candidate added, resume parsed, and matched to the selected job" : "Candidate added and matched to the selected job")
          : (resumeFile ? "Candidate added and resume parsed" : "Candidate added")
      );
      await refreshWorkspace();
    } catch (requestError) {
      setError(errorText(requestError));
    }
  }

  async function createApplication(event) {
    event.preventDefault();
    setError("");
    try {
      if (!applicationForm.job_id) {
        setError("Choose an open job.");
        return;
      }

      if (applicationEntryMode === "upload") {
        if (!applicationResumeFile) {
          setError("Select a PDF or DOCX resume.");
          return;
        }
        const body = new FormData();
        body.append("file", applicationResumeFile);
        body.append("job_id", String(Number(applicationForm.job_id)));
        await apiRequest(token, "post", "/candidates/from-resume", { data: body });
        setNotice("Resume parsed, application added to Applied, and candidate matched to the selected job");
      } else {
        if (!applicationForm.candidate_id) {
          setError("Choose a candidate.");
          return;
        }
        await apiRequest(token, "post", "/applications", {
          data: { job_id: Number(applicationForm.job_id), candidate_id: Number(applicationForm.candidate_id) },
        });
        setNotice("Application added to Applied and matched to the selected job");
      }

      setApplicationFormOpen(false);
      setApplicationEntryMode("existing");
      setApplicationResumeFile(null);
      setApplicationForm({ job_id: "", candidate_id: "" });
      await refreshWorkspace();
    } catch (requestError) {
      setError(errorText(requestError));
    }
  }

  async function changeStage(applicationId, stageName) {
    try {
      await apiRequest(token, "post", `/applications/${applicationId}/stage`, { data: { stage_name: stageName } });
      setNotice(`Application moved to ${stageName}`);
      await refreshWorkspace();
    } catch (requestError) {
      setError(errorText(requestError));
      await refreshWorkspace();
    }
  }

  async function moveSelected(stageName = bulkStage) {
    if (!selectedApplications.length) return;
    try {
      await apiRequest(token, "post", "/applications/bulk-stage", {
        data: { application_ids: selectedApplications, stage_name: stageName },
      });
      setSelectedApplications([]);
      setNotice(`${selectedApplications.length} application(s) moved to ${stageName}`);
      await refreshWorkspace();
    } catch (requestError) {
      setError(errorText(requestError));
    }
  }

  async function exportCsv() {
    try {
      const params = Object.fromEntries(Object.entries(filters).filter(([, value]) => value));
      const response = await apiRequest(token, "get", "/applications/export.csv", { params, responseType: "blob" });
      const url = URL.createObjectURL(response.data);
      const link = document.createElement("a");
      link.href = url;
      link.download = "applications.csv";
      link.click();
      URL.revokeObjectURL(url);
    } catch (requestError) {
      setError(errorText(requestError));
    }
  }

  async function selectMatchJob(jobId) {
    setMatchJobId(jobId);
    setMatchAnalysis(null);
    setMatches([]);
    setMatchFeedback({});
    if (!jobId) return;
    try {
      const [jobResponse, matchResponse] = await Promise.all([
        apiRequest(token, "get", `/jobs/${jobId}`),
        apiRequest(token, "get", `/jobs/${jobId}/matches`),
      ]);
      setMatchAnalysis(jobResponse.data.jd_analysis);
      setMatches(matchResponse.data);
    } catch (requestError) {
      setError(errorText(requestError));
    }
  }

  async function analyzeAndRank() {
    if (!matchJobId) return;
    setMatching(true);
    setError("");
    try {
      const analysis = await apiRequest(token, "post", `/jobs/${matchJobId}/analyze`);
      setMatchAnalysis(analysis.data.jd_analysis);
      const ranked = await apiRequest(token, "post", `/jobs/${matchJobId}/matches`);
      setMatches(ranked.data);
      setMatchFeedback({});
      setNotice(`Ranked ${ranked.data.length} candidate profile(s)`);
    } catch (requestError) {
      setError(errorText(requestError));
    } finally {
      setMatching(false);
    }
  }

  function changeMatchFeedback(matchId, field, value) {
    setMatchFeedback((current) => ({
      ...current,
      [matchId]: { ...current[matchId], [field]: value },
    }));
  }

  async function saveMatchFeedback(match) {
    const form = matchFeedback[match.id] || {};
    const overrideValue = form.recruiter_override ?? (match.recruiter_override === null ? "" : String(match.recruiter_override ?? ""));
    try {
      const response = await apiRequest(token, "patch", `/candidate-matches/${match.id}/feedback`, {
        data: {
          recruiter_override: overrideValue === "" ? null : Number(overrideValue),
          recruiter_note: form.recruiter_note ?? match.recruiter_note ?? null,
        },
      });
      setMatches((current) => current
        .map((item) => item.id === match.id ? response.data : item)
        .sort((left, right) => right.effective_score - left.effective_score));
      setMatchFeedback((current) => ({ ...current, [match.id]: undefined }));
      setNotice(response.data.recruiter_override === null ? "Recruiter override cleared" : "Recruiter score saved");
    } catch (requestError) {
      setError(errorText(requestError));
    }
  }

  function toggleApplication(id) {
    setSelectedApplications((current) => current.includes(id)
      ? current.filter((selectedId) => selectedId !== id)
      : [...current, id]);
  }

  function setFilter(field, value) {
    setFilters((current) => ({ ...current, [field]: value }));
  }

  async function submitPublicApplication(event) {
    event.preventDefault();
    setPublicError("");
    setPublicSuccess("");

    if (!publicApplyJob || !publicResume) {
      setPublicError("Select a PDF or DOCX resume.");
      return;
    }
    if (!publicForm.full_name.trim() || !publicForm.email.trim()) {
      setPublicError("Name and email are required.");
      return;
    }

    const body = new FormData();
    body.append("file", publicResume);
    body.append("full_name", publicForm.full_name.trim());
    body.append("email", publicForm.email.trim());
    if (publicForm.phone.trim()) body.append("phone", publicForm.phone.trim());

    setPublicLoading(true);
    try {
      const response = await apiRequest(null, "post", `/public/jobs/${publicApplyJob.id}/apply`, {
        data: body,
      });
      setPublicSuccess(response.data?.message || "Application submitted successfully.");
      setPublicResume(null);
      setPublicForm({ full_name: "", email: "", phone: "" });
      setPublicApplyJob(null);
    } catch (requestError) {
      setPublicError(errorText(requestError));
    } finally {
      setPublicLoading(false);
    }
  }

  function switchAccessMode(mode) {
    setAccessMode(mode);
    window.history.replaceState({}, "", mode === "admin" ? "?mode=admin" : window.location.pathname);
    setAuthError("");
  }

  if (!token && accessMode === "public") {
    return (
      <main className="min-h-screen bg-[#f3f4f1] text-ink-900">
        <header className="border-b border-ink-100 bg-white/95 px-5 py-4">
          <div className="mx-auto flex max-w-6xl items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="grid h-10 w-10 place-items-center rounded-md bg-ink-950 text-xs font-bold text-gold-300">BP</div>
              <div>
                <p className="font-semibold">BluePace Tech</p>
                <p className="text-xs text-ink-500">Candidate Application Portal</p>
              </div>
            </div>
            <button className={buttonSecondary} onClick={() => switchAccessMode("admin")}>
              Admin / Recruiter Login
            </button>
          </div>
        </header>

        <section className="mx-auto max-w-6xl px-5 py-12">
          <div className="max-w-2xl">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-gold-700">BluePace Careers</p>
            <h1 className="mt-3 text-4xl font-semibold tracking-tight sm:text-5xl">Find your next opportunity.</h1>
            <p className="mt-4 text-base leading-7 text-ink-500">
              Browse open positions and submit your resume without creating an account.
            </p>
          </div>

          <div id="jobs" className="mt-10">
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-xl font-semibold">Open Positions</h2>
              {publicJobs.length > 0 && <span className="text-sm text-ink-500">{publicJobs.length} position(s)</span>}
            </div>

            {publicLoading && !publicApplyJob && (
              <div className="mt-5 rounded-xl border border-ink-100 bg-white p-8 text-center text-sm text-ink-500">
                Loading open positions…
              </div>
            )}

            {publicError && !publicApplyJob && (
              <div className="mt-5 rounded-xl border border-rose-200 bg-rose-50 p-5 text-sm text-rose-700">
                {publicError}
              </div>
            )}

            {!publicLoading && !publicError && publicJobs.length === 0 && (
              <div className="mt-5 rounded-xl border border-ink-100 bg-white p-10 text-center">
                <p className="font-medium">No open positions are available right now.</p>
                <p className="mt-1 text-sm text-ink-500">Please check again later.</p>
              </div>
            )}

            <div className="mt-5 grid gap-5 md:grid-cols-2">
              {publicJobs.map((job) => (
                <article key={job.id} className="rounded-2xl border border-ink-100 bg-white p-6 shadow-sm">
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <h3 className="text-lg font-semibold">{job.title}</h3>
                      <p className="mt-1 text-sm text-ink-500">
                        {[job.department, job.location, job.employment_type].filter(Boolean).join(" · ")}
                      </p>
                    </div>
                    {job.fresher_allowed && (
                      <span className="rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-700">Fresher friendly</span>
                    )}
                  </div>
                  <p className="mt-4 line-clamp-4 whitespace-pre-line text-sm leading-6 text-ink-600">{job.description}</p>
                  {job.required_skills?.length > 0 && (
                    <div className="mt-4 flex flex-wrap gap-2">
                      {job.required_skills.slice(0, 8).map((skill) => (
                        <span key={skill} className="rounded-full border border-ink-100 bg-[#f8f8f5] px-2.5 py-1 text-xs text-ink-600">{skill}</span>
                      ))}
                    </div>
                  )}
                  <button
                    className={`${buttonPrimary} mt-6 w-full`}
                    onClick={() => {
                      setPublicApplyJob(job);
                      setPublicError("");
                      setPublicSuccess("");
                    }}
                  >
                    Apply for this position
                  </button>
                </article>
              ))}
            </div>
          </div>
        </section>

        {publicApplyJob && (
          <div id="apply" className="fixed inset-0 z-50 overflow-y-auto bg-black/40 px-4 py-8">
            <div className="mx-auto max-w-lg rounded-2xl bg-white p-7 shadow-xl">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wider text-gold-700">Apply</p>
                  <h2 className="mt-1 text-xl font-semibold">{publicApplyJob.title}</h2>
                </div>
                <button className="text-xl text-ink-400 hover:text-ink-800" onClick={() => setPublicApplyJob(null)} aria-label="Close">×</button>
              </div>

              <form onSubmit={submitPublicApplication} className="mt-6 grid gap-4">
                <Field
                  label="Full name"
                  required
                  value={publicForm.full_name}
                  onChange={(event) => setPublicForm({ ...publicForm, full_name: event.target.value })}
                />
                <Field
                  label="Email"
                  type="email"
                  required
                  value={publicForm.email}
                  onChange={(event) => setPublicForm({ ...publicForm, email: event.target.value })}
                />
                <Field
                  label="Phone"
                  value={publicForm.phone}
                  onChange={(event) => setPublicForm({ ...publicForm, phone: event.target.value })}
                />

                <label className="grid gap-1.5 text-xs font-semibold text-ink-700">
                  Resume
                  <input
                    type="file"
                    accept=".pdf,.docx"
                    required
                    onChange={(event) => setPublicResume(event.target.files?.[0] || null)}
                    className="rounded-md border border-ink-100 bg-white px-3 py-2.5 text-sm"
                  />
                  <span className="text-[11px] font-normal text-ink-400">PDF or DOCX, up to 10MB.</span>
                </label>

                {publicError && <p role="alert" className="text-sm text-rose-700">{publicError}</p>}
                {publicSuccess && <p role="status" className="text-sm text-emerald-700">{publicSuccess}</p>}

                <div className="mt-2 flex gap-3">
                  <button type="button" className={`${buttonSecondary} flex-1`} onClick={() => setPublicApplyJob(null)}>
                    Cancel
                  </button>
                  <button type="submit" disabled={publicLoading} className={`${buttonPrimary} flex-1`}>
                    {publicLoading ? "Submitting…" : "Submit Application"}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}
      </main>
    );
  }

  if (!token) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-[#f3f4f1] px-5 py-12 text-ink-900">
        <section className="w-full max-w-md">
          <div className="mb-8 flex items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <div className="grid h-11 w-11 place-items-center rounded-md bg-ink-950 text-sm font-bold text-gold-300">BP</div>
              <div>
                <p className="font-semibold">BluePace</p>
                <p className="text-xs text-ink-500">Recruiting workspace</p>
              </div>
            </div>
            <button className={buttonSecondary} onClick={() => switchAccessMode("public")}>
              Public Portal
            </button>
          </div>
          <h1 className="text-2xl font-semibold">{authMode === "login" ? "Sign in" : "Create your workspace"}</h1>
          <p className="mt-1 text-sm text-ink-500">
            {authMode === "login" ? "Continue to your hiring pipeline." : "Set up an organization and admin account."}
          </p>
          <form onSubmit={signIn} className="mt-7 grid gap-4">
            {authMode === "register" && <>
              <Field label="Organization" required value={authForm.organization_name} onChange={(event) => setAuthForm({ ...authForm, organization_name: event.target.value })} />
              <Field label="Your name" required value={authForm.full_name} onChange={(event) => setAuthForm({ ...authForm, full_name: event.target.value })} />
            </>}
            <Field label="Work email" type="email" autoComplete="email" required value={authForm.email} onChange={(event) => setAuthForm({ ...authForm, email: event.target.value })} />
            <Field label="Password" type="password" autoComplete={authMode === "login" ? "current-password" : "new-password"} minLength={12} required value={authForm.password} onChange={(event) => setAuthForm({ ...authForm, password: event.target.value })} />
            {authError && <p role="alert" className="text-sm text-rose-700">{authError}</p>}
            <button className={`${buttonPrimary} mt-1 w-full py-3`} type="submit">
              {authMode === "login" ? "Sign in" : "Create organization"}
            </button>
          </form>
          <button className="mt-5 text-sm font-medium text-ink-600 underline decoration-ink-300 underline-offset-4" onClick={() => { setAuthMode(authMode === "login" ? "register" : "login"); setAuthError(""); }}>
            {authMode === "login" ? "Create a new organization" : "Already registered? Sign in"}
          </button>
        </section>
      </main>
    );
  }

  const navItems = [
    { id: "pipeline", label: "Applications", count: applications.length },
    { id: "jobs", label: "Jobs", count: jobs.filter((job) => job.status !== "archived").length },
    { id: "candidates", label: "Candidates", count: candidates.length },
    { id: "matching", label: "AI Match" },
    { id: "resume", label: "Resume Lab" },
  ];

  return (
    <div className="min-h-screen bg-[#f3f4f1] text-ink-900">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-60 flex-col bg-ink-950 text-white lg:flex">
        <div className="flex h-[72px] items-center gap-3 border-b border-white/10 px-5">
          <div className="grid h-9 w-9 place-items-center rounded-md bg-gold-500 text-xs font-bold text-ink-950">BP</div>
          <div>
            <p className="text-sm font-semibold">BluePace</p>
            <p className="text-[11px] text-ink-400">Recruiting workspace</p>
          </div>
        </div>
        <nav className="grid gap-1 px-3 py-5" aria-label="Workspace">
          {navItems.map((item) => (
            <button key={item.id} onClick={() => { setView(item.id); setError(""); }} className={`flex items-center justify-between rounded-md px-3 py-2.5 text-left text-sm transition ${view === item.id ? "bg-white/10 text-gold-300" : "text-ink-100 hover:bg-white/5 hover:text-white"}`}>
              <span>{item.label}</span>
              {item.count !== undefined && <span className="text-xs text-ink-400">{item.count}</span>}
            </button>
          ))}
        </nav>
        <div className="mt-auto border-t border-white/10 px-5 py-4">
          <p className="truncate text-sm font-medium">{user?.full_name}</p>
          <p className="mt-0.5 text-xs capitalize text-ink-400">{user?.role?.replaceAll("_", " ")}</p>
          <button onClick={signOut} className="mt-4 text-xs font-medium text-ink-300 hover:text-white">Sign out</button>
        </div>
      </aside>

      <div className="lg:pl-60">
        <header className="sticky top-0 z-20 flex min-h-[72px] flex-wrap items-center justify-between gap-3 border-b border-ink-100 bg-white/95 px-4 py-3 backdrop-blur sm:px-7">
          <div>
            <p className="text-xs font-medium text-ink-500">{user?.email}</p>
            <h1 className="text-lg font-semibold">{navItems.find((item) => item.id === view)?.label}</h1>
          </div>
          <div className="flex gap-2">
            {view === "pipeline" && canWrite && <button className={buttonPrimary} onClick={() => { setApplicationFormOpen(true); setError(""); }}>Add application</button>}
            {view === "jobs" && canWrite && <button className={buttonPrimary} onClick={() => resetJobForm()}>New job</button>}
            {view === "candidates" && canWrite && <button className={buttonPrimary} onClick={() => setCandidateFormOpen(true)}>Add candidate</button>}
            <button className={`${buttonSecondary} lg:hidden`} onClick={signOut}>Sign out</button>
          </div>
          <nav className="flex w-full gap-1 overflow-x-auto lg:hidden" aria-label="Workspace">
            {navItems.map((item) => <button key={item.id} onClick={() => setView(item.id)} className={`whitespace-nowrap rounded-md px-3 py-2 text-sm ${view === item.id ? "bg-ink-950 text-white" : "text-ink-600 hover:bg-ink-50"}`}>{item.label}</button>)}
          </nav>
        </header>

        <main className="mx-auto max-w-[1440px] px-4 py-6 sm:px-7 sm:py-8">
          {notice && <div role="status" className="mb-4 flex items-center justify-between border-l-2 border-emerald-600 bg-white px-4 py-3 text-sm text-ink-700"><span>{notice}</span><button aria-label="Dismiss notice" onClick={() => setNotice("")}>×</button></div>}
          {error && <div role="alert" className="mb-4 flex items-center justify-between border-l-2 border-rose-600 bg-white px-4 py-3 text-sm text-rose-800"><span>{error}</span><button aria-label="Dismiss error" onClick={() => setError("")}>×</button></div>}
          {loading && <div className="mb-3 text-xs text-ink-500">Loading workspace…</div>}

          {view === "pipeline" && <>
            <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
              <div>
                <p className="text-sm text-ink-500">{applications.length} applications in this view</p>
                <h2 className="mt-1 text-xl font-semibold">Hiring pipeline</h2>
              </div>
              <button className={buttonSecondary} onClick={exportCsv}>Export CSV</button>
            </div>
            <form onSubmit={loadFilteredApplications} className="mb-5 grid grid-cols-1 gap-2 border-y border-ink-100 bg-white p-3 sm:grid-cols-2 lg:grid-cols-7">
              <Field label="Search" placeholder="Candidate or job" value={filters.search} onChange={(event) => setFilter("search", event.target.value)} />
              <Field label="Skill" placeholder="Python" value={filters.skill} onChange={(event) => setFilter("skill", event.target.value)} />
              <SelectField label="Stage" value={filters.stage_name} onChange={(event) => setFilter("stage_name", event.target.value)}><option value="">All stages</option>{STAGES.map((stage) => <option key={stage}>{stage}</option>)}</SelectField>
              <Field label="Source" placeholder="Referral" value={filters.source} onChange={(event) => setFilter("source", event.target.value)} />
              <Field label="Applied after" type="date" value={filters.applied_after} onChange={(event) => setFilter("applied_after", event.target.value)} />
              <Field label="Applied before" type="date" value={filters.applied_before} onChange={(event) => setFilter("applied_before", event.target.value)} />
              <button type="submit" className={`${buttonPrimary} self-end`}>Apply filters</button>
            </form>
            {canWrite && selectedApplications.length > 0 && <div className="mb-3 flex flex-wrap items-center gap-2 border border-gold-300 bg-[#fbf7ef] p-3 text-sm">
              <span className="mr-2 font-medium">{selectedApplications.length} selected</span>
              <SelectField label="Move to" value={bulkStage} onChange={(event) => setBulkStage(event.target.value)}>{STAGES.map((stage) => <option key={stage}>{stage}</option>)}</SelectField>
              <button className={buttonPrimary} onClick={() => moveSelected()}>Move stage</button>
              <button className="rounded-md border border-rose-200 bg-white px-3 py-2 text-sm font-semibold text-rose-700" onClick={() => moveSelected("Rejected")}>Reject selected</button>
            </div>}
            <div className="overflow-x-auto border-y border-ink-100 bg-white">
              <table className="w-full min-w-[900px] border-collapse text-left text-sm">
                <thead className="border-b border-ink-100 bg-[#fafaf8] text-[11px] uppercase text-ink-500">
                  <tr><th className="w-10 px-3 py-3"></th><th className="px-3 py-3">Candidate</th><th className="px-3 py-3">Job</th><th className="px-3 py-3">Source</th><th className="px-3 py-3">Skills</th><th className="px-3 py-3">Applied</th><th className="px-3 py-3">Stage</th></tr>
                </thead>
                <tbody className="divide-y divide-ink-50">
                  {applications.map((application) => <tr key={application.id} className="hover:bg-[#fcfcfa]">
                    <td className="px-3 py-3"><input aria-label={`Select ${application.candidate.first_name}`} type="checkbox" checked={selectedApplications.includes(application.id)} onChange={() => toggleApplication(application.id)} disabled={!canWrite} /></td>
                    <td className="px-3 py-3"><button className="text-left font-semibold text-ink-900 hover:text-ink-600" onClick={() => { setSelectedCandidate(application.candidate_id); setView("candidates"); }}>{application.candidate.first_name} {application.candidate.last_name}</button><div className="text-xs text-ink-500">{application.candidate.email}</div></td>
                    <td className="px-3 py-3 font-medium">{application.job_title}</td>
                    <td className="px-3 py-3 text-ink-600">{application.candidate.source || "—"}</td>
                    <td className="max-w-52 px-3 py-3 text-xs text-ink-600">{(application.candidate.resume_data?.skills || []).slice(0, 5).join(", ") || "—"}</td>
                    <td className="whitespace-nowrap px-3 py-3 text-xs text-ink-500">{new Date(application.applied_at).toLocaleDateString()}</td>
                    <td className="px-3 py-3"><select aria-label={`Stage for ${application.candidate.first_name}`} className="rounded-md border border-ink-100 bg-white px-2 py-1.5 text-xs" value={application.stage_name || "Applied"} disabled={!canWrite} onChange={(event) => changeStage(application.id, event.target.value)}>{STAGES.map((stage) => <option key={stage}>{stage}</option>)}</select></td>
                  </tr>)}
                </tbody>
              </table>
              {!applications.length && <EmptyState title="No applications found" detail="Create an application or adjust your filters." />}
            </div>
          </>}

          {view === "jobs" && <>
            {jobFormOpen && <form onSubmit={saveJob} className="mb-6 border-y border-ink-100 bg-white p-4 sm:p-5">
              <div className="mb-4 flex items-center justify-between">
                <h2 className="font-semibold">{editingJob ? "Edit job" : "New job"}</h2>
                <button type="button" aria-label="Close form" onClick={() => { setJobFormOpen(false); setJobDocumentFile(null); }}>×</button>
              </div>
              {!editingJob && <div className="mb-5 flex gap-2 border-b border-ink-100 pb-3">
                <button type="button" onClick={() => setJobEntryMode("manual")} className={jobEntryMode === "manual" ? buttonPrimary : buttonSecondary}>Manual entry</button>
                <button type="button" onClick={() => setJobEntryMode("upload")} className={jobEntryMode === "upload" ? buttonPrimary : buttonSecondary}>Upload JD</button>
              </div>}
              {jobEntryMode === "upload" && !editingJob ? (
                <div className="grid gap-4">
                  <div className="rounded-xl border border-gold-200 bg-[#fbf7ef] p-4 text-sm text-ink-700">
                    Upload the job description as PDF or DOCX. BluePace will extract the text, required skills, experience, location and education requirements automatically, then use the same matching engine for applicants.
                  </div>
                  <label className="grid gap-1.5 text-xs font-semibold text-ink-700">
                    Job description document
                    <input className={`${inputStyle} p-2`} type="file" accept=".pdf,.docx" required onChange={(event) => setJobDocumentFile(event.target.files?.[0] || null)} />
                    <span className="text-[11px] font-normal text-ink-400">{jobDocumentFile ? jobDocumentFile.name : "PDF or DOCX, up to 10MB."}</span>
                  </label>
                  <div className="grid gap-3 sm:grid-cols-3">
                    <Field label="Job title override (optional)" placeholder="AI Infrastructure Engineer, pAGI" value={jobForm.title} onChange={(event) => setJobForm({ ...jobForm, title: event.target.value })} />
                    <Field label="Department override (optional)" value={jobForm.department} onChange={(event) => setJobForm({ ...jobForm, department: event.target.value })} />
                    <Field label="Location override (optional)" value={jobForm.location} onChange={(event) => setJobForm({ ...jobForm, location: event.target.value })} />
                    <SelectField label="Employment type" value={jobForm.employment_type} onChange={(event) => setJobForm({ ...jobForm, employment_type: event.target.value })}>{["Full-time", "Part-time", "Contract", "Temporary", "Internship"].map((type) => <option key={type}>{type}</option>)}</SelectField>
                    <SelectField label="Status" value={jobForm.status} onChange={(event) => setJobForm({ ...jobForm, status: event.target.value })}>{["draft", "open", "paused", "closed"].map((value) => <option key={value} value={value}>{value}</option>)}</SelectField>
                    <Field label="Minimum experience override" type="number" min="0" max="60" placeholder="Auto-detect" value={jobForm.minimum_experience_years} onChange={(event) => setJobForm({ ...jobForm, minimum_experience_years: event.target.value })} />
                  </div>
                  <label className="flex min-h-10 items-center gap-2 text-sm font-medium text-ink-700">
                    <input type="checkbox" checked={jobForm.fresher_allowed} onChange={(event) => setJobForm({ ...jobForm, fresher_allowed: event.target.checked })} />
                    Open to freshers (override)
                  </label>
                </div>
              ) : (
                <div className="grid gap-3 sm:grid-cols-2">
                  <Field label="Job title" required value={jobForm.title} onChange={(event) => setJobForm({ ...jobForm, title: event.target.value })} />
                  <Field label="Department" value={jobForm.department} onChange={(event) => setJobForm({ ...jobForm, department: event.target.value })} />
                  <Field label="Location" value={jobForm.location} onChange={(event) => setJobForm({ ...jobForm, location: event.target.value })} />
                  <SelectField label="Employment type" value={jobForm.employment_type} onChange={(event) => setJobForm({ ...jobForm, employment_type: event.target.value })}>{["Full-time", "Part-time", "Contract", "Temporary", "Internship"].map((type) => <option key={type}>{type}</option>)}</SelectField>
                  <SelectField label="Status" value={jobForm.status} onChange={(event) => setJobForm({ ...jobForm, status: event.target.value })}>{["draft", "open", "paused", "closed"].map((value) => <option key={value} value={value}>{value}</option>)}</SelectField>
                  <Field label="Required skills" placeholder="Python, PostgreSQL, AWS" value={jobForm.required_skills} onChange={(event) => setJobForm({ ...jobForm, required_skills: event.target.value })} />
                  <Field label="Minimum experience (years)" type="number" min="0" max="60" value={jobForm.minimum_experience_years} onChange={(event) => setJobForm({ ...jobForm, minimum_experience_years: event.target.value })} />
                  <label className="flex min-h-10 items-center gap-2 text-sm font-medium text-ink-700">
                    <input type="checkbox" checked={jobForm.fresher_allowed} onChange={(event) => setJobForm({ ...jobForm, fresher_allowed: event.target.checked })} />
                    Open to freshers
                  </label>
                  <label className="grid gap-1.5 text-xs font-semibold text-ink-700 sm:col-span-2">Description<textarea className={`${inputStyle} min-h-28 resize-y`} required value={jobForm.description} onChange={(event) => setJobForm({ ...jobForm, description: event.target.value })} /></label>
                </div>
              )}
              <div className="mt-4 flex gap-2"><button className={buttonPrimary} type="submit">{editingJob ? "Save changes" : jobEntryMode === "upload" ? "Upload & create job" : "Create job"}</button><button className={buttonSecondary} type="button" onClick={() => { setJobFormOpen(false); setJobDocumentFile(null); }}>Cancel</button></div>
            </form>}
            <div className="mb-5"><p className="text-sm text-ink-500">{jobs.length} total jobs</p><h2 className="mt-1 text-xl font-semibold">Job openings</h2></div>
            <div className="border-y border-ink-100 bg-white">
              <div className="grid grid-cols-[minmax(180px,2fr)_1fr_1fr_100px] gap-3 border-b border-ink-100 bg-[#fafaf8] px-4 py-3 text-[11px] font-semibold uppercase text-ink-500"><span>Role</span><span>Location</span><span>Created</span><span>Status</span></div>
              {jobs.map((job) => <div key={job.id} className="grid grid-cols-1 gap-2 border-b border-ink-50 px-4 py-4 last:border-0 sm:grid-cols-[minmax(180px,2fr)_1fr_1fr_100px] sm:items-center sm:gap-3">
                <div><button className="font-semibold hover:underline" onClick={() => resetJobForm(job)}>{job.title}</button><p className="mt-0.5 text-xs text-ink-500">{job.department || "Unassigned department"} · {job.employment_type || "Employment type not set"}</p><p className="mt-1 text-xs text-ink-500">{job.minimum_experience_years === null ? "Experience unspecified" : `${job.minimum_experience_years}+ years`}{job.fresher_allowed ? " · Freshers welcome" : ""}{job.required_skills?.length ? ` · ${job.required_skills.join(", ")}` : ""}</p></div>
                <span className="text-sm text-ink-600">{job.location || "Remote / unspecified"}</span>
                <span className="text-xs text-ink-500">{new Date(job.created_at).toLocaleDateString()}</span>
                <div className="flex items-center justify-between gap-2"><span className={`rounded-full px-2 py-1 text-[11px] font-semibold ${job.status === "open" ? "bg-emerald-50 text-emerald-800" : job.status === "archived" ? "bg-ink-100 text-ink-500" : "bg-gold-50 text-ink-700"}`}>{job.status}</span>{canWrite && job.status !== "archived" && <button className="text-xs font-medium text-ink-500 underline underline-offset-2" onClick={() => archiveJob(job)}>Archive</button>}</div>
              </div>)}
              {!jobs.length && <EmptyState title="No jobs yet" detail="Create a job to begin building your pipeline." />}
            </div>
          </>}

          {view === "matching" && <>
            <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
              <div>
                <p className="text-sm text-ink-500">Explainable ranking with recruiter review</p>
                <h2 className="mt-1 text-xl font-semibold">Candidate matching</h2>
              </div>
              <div className="flex flex-wrap items-end gap-2">
                <SelectField label="Job" value={matchJobId} onChange={(event) => selectMatchJob(event.target.value)}>
                  <option value="">Choose a job</option>
                  {jobs.filter((job) => job.status !== "archived").map((job) => <option key={job.id} value={job.id}>{job.title}</option>)}
                </SelectField>
                {canWrite && <button className={buttonPrimary} disabled={!matchJobId || matching} onClick={analyzeAndRank}>
                  {matching ? "Analyzing…" : "Analyze and rank"}
                </button>}
              </div>
            </div>
            {matchAnalysis && <section className="mb-5 border-y border-ink-100 bg-white px-4 py-4 sm:px-5">
              <div className="flex flex-wrap gap-x-8 gap-y-3 text-sm">
                <div><p className="text-[11px] font-semibold uppercase text-ink-500">Seniority</p><p className="mt-1 capitalize">{matchAnalysis.seniority || "Unspecified"}</p></div>
                <div><p className="text-[11px] font-semibold uppercase text-ink-500">Location</p><p className="mt-1">{matchAnalysis.location || "Unspecified"}</p></div>
                <div><p className="text-[11px] font-semibold uppercase text-ink-500">Minimum experience</p><p className="mt-1">{matchAnalysis.minimum_experience_years ? `${matchAnalysis.minimum_experience_years}+ years` : "Unspecified"}</p></div>
                <div><p className="text-[11px] font-semibold uppercase text-ink-500">Freshers</p><p className="mt-1">{matchAnalysis.fresher_allowed ? "Eligible" : "Experience preferred"}</p></div>
                <div className="min-w-56 flex-1"><p className="text-[11px] font-semibold uppercase text-ink-500">Education</p><p className="mt-1">{matchAnalysis.education || "No degree requirement extracted"}</p></div>
              </div>
              <div className="mt-4 grid gap-3 border-t border-ink-50 pt-3 sm:grid-cols-2">
                <div><p className="text-[11px] font-semibold uppercase text-ink-500">Required skills</p><p className="mt-1 text-sm">{(matchAnalysis.required_skills || []).join(", ") || "None extracted"}</p></div>
                <div><p className="text-[11px] font-semibold uppercase text-ink-500">Preferred skills</p><p className="mt-1 text-sm">{(matchAnalysis.preferred_skills || []).join(", ") || "None extracted"}</p></div>
              </div>
            </section>}
            {matches.length > 0 && <div className="mb-3 flex items-center justify-between text-xs text-ink-500">
              <span>{matches.length} ranked candidate profiles</span>
              <span>{matches.some((match) => match.semantic_mode === "embedding") ? "Vector similarity active" : "Text-overlap fallback · configure OPENAI_API_KEY for vector embeddings"}</span>
            </div>}
            <div className="overflow-x-auto border-y border-ink-100 bg-white">
              <table className="w-full min-w-[1100px] border-collapse text-left text-sm">
                <thead className="border-b border-ink-100 bg-[#fafaf8] text-[11px] uppercase text-ink-500">
                  <tr><th className="px-3 py-3">Rank / candidate</th><th className="px-3 py-3">Fit</th><th className="px-3 py-3">Matched skills</th><th className="px-3 py-3">Skill gaps</th><th className="px-3 py-3">Why this candidate</th><th className="px-3 py-3">CV summary</th><th className="px-3 py-3">Recruiter review</th></tr>
                </thead>
                <tbody className="divide-y divide-ink-50">
                  {matches.map((match, index) => {
                    const feedback = matchFeedback[match.id] || {};
                    const overrideValue = feedback.recruiter_override ?? (match.recruiter_override === null ? "" : String(match.recruiter_override ?? ""));
                    const noteValue = feedback.recruiter_note ?? match.recruiter_note ?? "";
                    return <tr key={match.id} className="align-top hover:bg-[#fcfcfa]">
                      <td className="whitespace-nowrap px-3 py-4"><div className="flex items-start gap-2"><span className="mt-0.5 text-xs text-ink-400">{String(index + 1).padStart(2, "0")}</span><div><p className="font-semibold">{match.candidate_name}</p><p className="text-xs text-ink-500">{match.candidate_email}</p></div></div></td>
                      <td className="min-w-32 px-3 py-4"><p className="text-lg font-semibold tabular-nums">{match.effective_score}<span className="text-xs font-normal text-ink-500"> / 100</span></p>{match.recruiter_override !== null && <p className="text-[11px] text-gold-600">Model: {match.model_score}</p>}<div className="mt-1 h-1.5 w-24 bg-ink-100"><div className="h-full bg-gold-500" style={{ width: `${match.effective_score}%` }} /></div><p className="mt-2 text-[10px] text-ink-500">{Object.entries(match.score_breakdown).map(([key, value]) => `${key} ${value}·${MATCH_WEIGHTS[key]}%`).join(" · ")}</p></td>
                      <td className="max-w-48 px-3 py-4 text-xs text-emerald-800">{match.matched_skills.join(", ") || "No direct skill matches"}</td>
                      <td className="max-w-48 px-3 py-4 text-xs text-rose-800">{match.skill_gaps.join(", ") || "No required skill gaps"}</td>
                      <td className="max-w-64 px-3 py-4"><ul className="grid gap-1 text-xs text-ink-600">{match.explanations.map((item, itemIndex) => <li key={itemIndex}>{item}</li>)}</ul></td>
                      <td className="min-w-64 px-3 py-4"><ul className="grid gap-1 text-xs text-ink-600">{match.cv_summary.map((item, itemIndex) => <li key={itemIndex}>• {item}</li>)}</ul></td>
                      <td className="min-w-56 px-3 py-4"><div className="grid gap-2"><label className="grid gap-1 text-[11px] font-medium text-ink-500">Override score<input className={`${inputStyle} py-1.5`} type="number" min="0" max="100" value={overrideValue} placeholder={String(match.model_score)} disabled={!canWrite} onChange={(event) => changeMatchFeedback(match.id, "recruiter_override", event.target.value)} /></label><label className="grid gap-1 text-[11px] font-medium text-ink-500">Review note<input className={`${inputStyle} py-1.5`} value={noteValue} placeholder="Optional rationale" disabled={!canWrite} onChange={(event) => changeMatchFeedback(match.id, "recruiter_note", event.target.value)} /></label>{canWrite && <button className={buttonSecondary} onClick={() => saveMatchFeedback(match)}>Save review</button>}</div></td>
                    </tr>;
                  })}
                </tbody>
              </table>
              {!matches.length && <EmptyState title="No ranking yet" detail={matchJobId ? "Analyze this job to extract criteria and rank candidate profiles." : "Choose a job to analyze its candidate fit."} />}
            </div>
          </>}

          {view === "candidates" && <>
            {candidateFormOpen && <form onSubmit={saveCandidate} className="mb-6 border-y border-ink-100 bg-white p-4 sm:p-5">
              <div className="mb-4 flex items-center justify-between"><h2 className="font-semibold">Add candidate</h2><button type="button" aria-label="Close form" onClick={() => setCandidateFormOpen(false)}>×</button></div>
              <div className="mb-5 flex gap-2 border-b border-ink-100 pb-3">
                <button type="button" onClick={() => setCandidateEntryMode("manual")} className={candidateEntryMode === "manual" ? buttonPrimary : buttonSecondary}>Manual entry</button>
                <button type="button" onClick={() => setCandidateEntryMode("resume")} className={candidateEntryMode === "resume" ? buttonPrimary : buttonSecondary}>Upload resume</button>
              </div>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {candidateEntryMode === "manual" ? <>
                  <Field label="First name" required value={candidateForm.first_name} onChange={(event) => setCandidateForm({ ...candidateForm, first_name: event.target.value })} />
                  <Field label="Last name" required value={candidateForm.last_name} onChange={(event) => setCandidateForm({ ...candidateForm, last_name: event.target.value })} />
                  <Field label="Email" type="email" required value={candidateForm.email} onChange={(event) => setCandidateForm({ ...candidateForm, email: event.target.value })} />
                  <Field label="Phone" value={candidateForm.phone} onChange={(event) => setCandidateForm({ ...candidateForm, phone: event.target.value })} />
                  <Field label="Source" value={candidateForm.source} onChange={(event) => setCandidateForm({ ...candidateForm, source: event.target.value })} />
                </> : (
                  <div className="rounded-xl border border-gold-200 bg-[#fbf7ef] p-4 text-sm text-ink-600 sm:col-span-2 lg:col-span-3">
                    Upload a resume and the ATS will extract the candidate details automatically.
                  </div>
                )}
                <SelectField label="Match to job (optional)" value={candidateForm.job_id} onChange={(event) => setCandidateForm({ ...candidateForm, job_id: event.target.value })}>
                  <option value="">Save profile only</option>
                  {jobs.filter((job) => job.status === "open").map((job) => <option key={job.id} value={job.id}>{job.title}</option>)}
                </SelectField>
                <label className="grid gap-1.5 text-xs font-semibold text-ink-700 sm:col-span-2 lg:col-span-2">
                  Resume (PDF or DOCX)
                  <input className={`${inputStyle} p-2`} type="file" accept=".pdf,.docx" onChange={(event) => setResumeFile(event.target.files?.[0] || null)} />
                  <span className="text-[11px] font-normal text-ink-400">{candidateEntryMode === "resume" ? "Required in upload mode." : "Optional in manual mode."}</span>
                </label>
              </div>
              <div className="mt-4 flex gap-2"><button className={buttonPrimary} type="submit">Add candidate</button><button className={buttonSecondary} type="button" onClick={() => setCandidateFormOpen(false)}>Cancel</button></div>
            </form>}
            <div className="mb-5"><p className="text-sm text-ink-500">{candidates.length} profiles</p><h2 className="mt-1 text-xl font-semibold">Candidate directory</h2></div>
            <div className="overflow-x-auto border-y border-ink-100 bg-white">
              <table className="w-full min-w-[650px] border-collapse text-left text-sm">
                <thead className="border-b border-ink-100 bg-[#fafaf8] text-[11px] uppercase text-ink-500"><tr><th className="px-4 py-3">Candidate</th><th className="px-4 py-3">Source</th><th className="px-4 py-3">Skills</th><th className="px-4 py-3">Resume</th></tr></thead>
                <tbody className="divide-y divide-ink-50">
                  {candidates.map((candidate) => <tr key={candidate.id} className="hover:bg-[#fcfcfa]">
                    <td className="px-4 py-3"><button className="font-semibold hover:underline" onClick={() => setSelectedCandidate(candidate.id)}>{candidate.first_name} {candidate.last_name}</button><p className="text-xs text-ink-500">{candidate.email}{candidate.phone ? ` · ${candidate.phone}` : ""}</p></td>
                    <td className="px-4 py-3 text-ink-600">{candidate.source || "—"}</td>
                    <td className="max-w-72 px-4 py-3 text-xs text-ink-600">{(candidate.resume_data?.skills || []).slice(0, 8).join(", ") || "Not parsed"}</td>
                    <td className="px-4 py-3 text-xs">{candidate.resume_storage_key ? <span className="text-emerald-700">Parsed</span> : <span className="text-ink-400">No resume</span>}</td>
                  </tr>)}
                </tbody>
              </table>
              {!candidates.length && <EmptyState title="No candidates yet" detail="Add a profile and upload a resume to parse it." />}
            </div>
            {selectedCandidate && (() => {
              const candidate = candidates.find((item) => item.id === selectedCandidate);
              if (!candidate) return null;
              const profile = candidate.resume_data || {};
              return <section className="mt-5 border-y border-ink-100 bg-white p-4 sm:p-5">
                <div className="flex items-start justify-between"><div><p className="text-xs uppercase text-ink-500">Candidate profile</p><h3 className="mt-1 text-lg font-semibold">{candidate.first_name} {candidate.last_name}</h3><p className="text-sm text-ink-500">{candidate.email} {candidate.phone && `· ${candidate.phone}`}</p></div><button aria-label="Close profile" onClick={() => setSelectedCandidate(null)}>×</button></div>
                <div className="mt-5 grid gap-5 md:grid-cols-3">
                  <div><h4 className="text-xs font-semibold uppercase text-ink-500">Skills</h4><p className="mt-2 text-sm">{(profile.skills || []).join(", ") || "Not available"}</p></div>
                  <div><h4 className="text-xs font-semibold uppercase text-ink-500">Experience</h4><ul className="mt-2 grid gap-2 text-sm">{(profile.experience || []).map((item, index) => <li key={index}><strong>{item.title || item.company || "Experience"}</strong><span className="block text-xs text-ink-500">{item.company} · {item.duration}</span><span className="block text-xs text-ink-600">{item.description}</span></li>)}</ul></div>
                  <div><h4 className="text-xs font-semibold uppercase text-ink-500">Education</h4><ul className="mt-2 grid gap-2 text-sm">{(profile.education || []).map((item, index) => <li key={index}><strong>{item.degree}</strong><span className="block text-xs text-ink-500">{item.university} · {item.graduation_year}</span></li>)}</ul></div>
                </div>
              </section>;
            })()}
          </>}

          {view === "resume" && <section className="-mx-4 -my-6 sm:-mx-7 sm:-my-8"><ResumeLab /></section>}
        </main>

      {applicationFormOpen && <div className="fixed inset-0 z-50 grid place-items-center bg-ink-950/50 p-4" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) { setApplicationFormOpen(false); setApplicationResumeFile(null); } }}>
        <form onSubmit={createApplication} className="w-full max-w-lg bg-white p-5 shadow-xl">
          <div className="mb-5 flex items-center justify-between"><h2 className="text-lg font-semibold">Add to pipeline</h2><button type="button" aria-label="Close dialog" onClick={() => { setApplicationFormOpen(false); setApplicationResumeFile(null); }}>×</button></div>
          <div className="mb-5 flex gap-2 border-b border-ink-100 pb-3">
            <button type="button" onClick={() => setApplicationEntryMode("existing")} className={applicationEntryMode === "existing" ? buttonPrimary : buttonSecondary}>Select candidate</button>
            <button type="button" onClick={() => setApplicationEntryMode("upload")} className={applicationEntryMode === "upload" ? buttonPrimary : buttonSecondary}>Upload resume</button>
          </div>
          <div className="grid gap-4">
            <SelectField label="Open job" required value={applicationForm.job_id} onChange={(event) => setApplicationForm({ ...applicationForm, job_id: event.target.value })}>
              <option value="">Choose a job</option>
              {jobs.filter((job) => job.status === "open").map((job) => <option key={job.id} value={job.id}>{job.title}</option>)}
            </SelectField>
            {applicationEntryMode === "existing" ? (
              <SelectField label="Candidate" required value={applicationForm.candidate_id} onChange={(event) => setApplicationForm({ ...applicationForm, candidate_id: event.target.value })}>
                <option value="">Choose a candidate</option>
                {candidates.map((candidate) => <option key={candidate.id} value={candidate.id}>{candidate.first_name} {candidate.last_name} · {candidate.email}</option>)}
              </SelectField>
            ) : (
              <label className="grid gap-1.5 text-xs font-semibold text-ink-700">
                Resume (PDF or DOCX)
                <input className={inputStyle + " p-2"} type="file" accept=".pdf,.docx" required onChange={(event) => setApplicationResumeFile(event.target.files?.[0] || null)} />
                <span className="text-[11px] font-normal text-ink-400">{applicationResumeFile ? applicationResumeFile.name : "Upload the candidate resume. Details are extracted automatically and the application is matched to the selected job."}</span>
              </label>
            )}
          </div>
          <div className="mt-6 flex justify-end gap-2"><button type="button" className={buttonSecondary} onClick={() => { setApplicationFormOpen(false); setApplicationResumeFile(null); }}>Cancel</button><button type="submit" className={buttonPrimary}>{applicationEntryMode === "upload" ? "Upload & add application" : "Add application"}</button></div>
        </form>
      </div>
    </div>
  );
}
