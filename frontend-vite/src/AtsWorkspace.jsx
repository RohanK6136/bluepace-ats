import { lazy, Suspense, useEffect, useState } from "react";
import axios from "axios";
import AtsChatbot from "./AtsChatbot.jsx";
import PublicHelpCenter from "./PublicHelpCenter.jsx";
const ResumeLab = lazy(() => import("./App.jsx"));
const CandidatePortal = lazy(() => import("./CandidatePortal.jsx"));
const EmailTemplatesPanel = lazy(() => import("./EmailTemplatesPanel.jsx"));
const ScorecardPanel = lazy(() => import("./ScorecardPanel.jsx"));
const TalentPoolsPanel = lazy(() => import("./TalentPoolsPanel.jsx"));
const AnalyticsPanel = lazy(() => import("./AnalyticsPanel.jsx"));
const ApplicationEnhancements = lazy(() => import("./ApplicationEnhancements.jsx"));
const RecruiterToolsPanel = lazy(() => import("./RecruiterToolsPanel.jsx"));
const InterviewPanel = lazy(() => import("./InterviewPanel.jsx"));
const AutomationPanel = lazy(() => import("./AutomationPanel.jsx"));
const CommandCenterPanel = lazy(() => import("./CommandCenterPanel.jsx"));
const CandidateMergeCenter = lazy(() => import("./CandidateMergeCenter.jsx"));
const InterviewManagement2 = lazy(() => import("./InterviewManagement2.jsx"));
const OfferManagement = lazy(() => import("./OfferManagement.jsx"));

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
const MATCH_WEIGHTS = {
  required_skill_coverage: 25,
  preferred_skill_coverage: 10,
  experience_alignment: 15,
  education_alignment: 10,
  location_alignment: 8,
  work_mode_alignment: 7,
  project_evidence: 10,
  semantic_similarity: 15,
};
const buttonPrimary = "inline-flex items-center justify-center gap-2 rounded-md bg-[#c49a4a] px-4 py-2 text-sm font-semibold text-[#10131c] transition hover:bg-[#d4b06a] disabled:cursor-not-allowed disabled:opacity-50";
const buttonSecondary = "inline-flex items-center justify-center gap-2 rounded-md border border-ink-100 bg-white px-3 py-2 text-sm font-semibold text-ink-800 transition hover:bg-ink-50 disabled:cursor-not-allowed disabled:opacity-50";
const inputStyle = "w-full rounded-md border border-ink-100 bg-white px-3 py-2.5 text-sm text-ink-900 outline-none transition placeholder:text-ink-400 focus:border-gold-500 focus:ring-2 focus:ring-gold-100";

function ThemeToggle({ theme, onToggle }) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className="inline-flex h-10 items-center gap-2 rounded-md border border-ink-100 bg-white px-3 text-sm font-semibold text-ink-700 shadow-sm hover:bg-ink-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
      aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
      title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
    >
      <span aria-hidden="true">{theme === "dark" ? "☀️" : "🌙"}</span>
      <span className="hidden sm:inline">{theme === "dark" ? "Light" : "Dark"}</span>
    </button>
  );
}

function wait(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function shouldRetry(error) {
  if (["ECONNABORTED", "ETIMEDOUT"].includes(error.code)) return false;
  if (!error.response) return true;
  return [502, 503, 504].includes(error.response.status);
}

let tokenRefreshInFlight = null;

async function refreshAccessToken(currentToken) {
  if (!currentToken) throw new Error("No access token available.");
  if (!tokenRefreshInFlight) {
    tokenRefreshInFlight = axios.post(
      `${API_URL}/auth/refresh`,
      null,
      {
        timeout: 15_000,
        headers: { Authorization: `Bearer ${currentToken}` },
      },
    )
      .then((response) => {
        const refreshedToken = response.data?.access_token;
        if (!refreshedToken) throw new Error("The ATS API did not return a refreshed access token.");
        sessionStorage.setItem("bluepace_token", refreshedToken);
        return refreshedToken;
      })
      .finally(() => {
        tokenRefreshInFlight = null;
      });
  }
  return tokenRefreshInFlight;
}

async function apiRequest(token, method, path, options = {}) {
  let requestToken = token || sessionStorage.getItem("bluepace_token") || "";
  let refreshed = false;
  for (let attempt = 0; ; attempt += 1) {
    try {
      return await axios.request({
        baseURL: API_URL,
        method,
        url: path,
        timeout: REQUEST_TIMEOUT_MS,
        ...options,
        headers: {
          ...(requestToken ? { Authorization: `Bearer ${requestToken}` } : {}),
          ...options.headers,
        },
      });
    } catch (error) {
      const canRefresh = Boolean(requestToken)
        && !refreshed
        && error.response?.status === 401
        && !path.startsWith("/auth/token")
        && !path.startsWith("/auth/refresh")
        && Boolean(sessionStorage.getItem("bluepace_token"));
      if (canRefresh) {
        try {
          requestToken = await refreshAccessToken(requestToken);
          refreshed = true;
          continue;
        } catch (refreshError) {
          sessionStorage.removeItem("bluepace_token");
          throw refreshError;
        }
      }
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

function workModeLabel(mode) {
  return mode === "remote" ? "Remote" : mode === "hybrid" ? "Hybrid" : "On-site";
}

function interviewModeLabel(mode) {
  return mode === "offline" ? "Offline / On-site" : "Online";
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
  const [theme, setTheme] = useState(() => localStorage.getItem("bluepace_theme") || "light");
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
  const [publicFilters, setPublicFilters] = useState({ search: "", department: "", location: "", work_mode: "" });
  const [authMode, setAuthMode] = useState("login");
  const [authForm, setAuthForm] = useState({ organization_name: "", full_name: "", email: "", password: "" });
  const [authError, setAuthError] = useState("");
  const [view, setView] = useState("dashboard");
  const [jobs, setJobs] = useState([]);
  const [candidates, setCandidates] = useState([]);
  const [applications, setApplications] = useState([]);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [dashboardData, setDashboardData] = useState(null);
  const [dashboardLoading, setDashboardLoading] = useState(false);
  const [candidateActivity, setCandidateActivity] = useState(null);
  const [candidateCollaboration, setCandidateCollaboration] = useState(null);
  const [collabComment, setCollabComment] = useState("");
  const [collabTagName, setCollabTagName] = useState("");
  const [collabTagColor, setCollabTagColor] = useState("#1769d3");
  const [emails, setEmails] = useState([]);
  const [emailsLoading, setEmailsLoading] = useState(false);
  const [candidateFilters, setCandidateFilters] = useState({
    search: "", skill: "", source: "", location: "", tags: "", stage_name: "",
    min_experience_years: "", max_experience_years: "", notice_period: "", education: "",
    job_history: "", availability: "", preferred_location: "", work_authorization: "",
    has_applied_job_id: "",
  });
  const [portalToken] = useState(() => new URLSearchParams(window.location.search).get("portal") || "");
  const [portalLink, setPortalLink] = useState("");
  const [portalLinkLoading, setPortalLinkLoading] = useState(false);
  const [filters, setFilters] = useState({ search: "", skill: "", stage_name: "", source: "", applied_after: "", applied_before: "" });
  const [jobFormOpen, setJobFormOpen] = useState(false);
  const [jobEntryMode, setJobEntryMode] = useState("manual");
  const [jobDocumentFile, setJobDocumentFile] = useState(null);
  const [jobLinkInput, setJobLinkInput] = useState("");
  const [editingJob, setEditingJob] = useState(null);
  const [jobForm, setJobForm] = useState({
    title: "",
    description: "",
    department: "",
    location: "",
    employment_type: "Full-time",
    work_mode: "onsite",
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
  const [fitAnalysis, setFitAnalysis] = useState(null);
  const [fitJobId, setFitJobId] = useState("");
  const [fitLoading, setFitLoading] = useState(false);
  const [assistantApplicationId, setAssistantApplicationId] = useState("");
  const [assistantQuestion, setAssistantQuestion] = useState("Summarize this candidate against the JD.");
  const [assistantResult, setAssistantResult] = useState(null);
  const [assistantLoading, setAssistantLoading] = useState(false);
  const [interviewDialogApplication, setInterviewDialogApplication] = useState(null);
  const [interviewForm, setInterviewForm] = useState({ starts_at: "", duration_minutes: "60", mode: "online", location: "", meeting_url: "" });

  const canWrite = user && ["admin", "recruiter"].includes(user.role);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    document.documentElement.style.colorScheme = theme;
    localStorage.setItem("bluepace_theme", theme);
  }, [theme]);

  const toggleTheme = () => setTheme((current) => current === "dark" ? "light" : "dark");

  useEffect(() => {
    if (token || accessMode !== "public") return undefined;
    let active = true;
    const params = Object.fromEntries(Object.entries(publicFilters).filter(([, value]) => value));
    apiRequest(null, "get", "/public/jobs", { params })
      .then((response) => { if (active) setPublicJobs(Array.isArray(response.data) ? response.data : []); })
      .catch((requestError) => { if (active) setPublicError(errorText(requestError)); });
    return () => { active = false; };
  }, [token, accessMode, publicFilters.search, publicFilters.department, publicFilters.location, publicFilters.work_mode]);

  useEffect(() => {
    if (!token) return undefined;
    let active = true;
    async function loadWorkspace() {
      setLoading(true);
      try {
        const [userResponse, jobsResponse] = await Promise.all([
          apiRequest(token, "get", "/auth/me"),
          apiRequest(token, "get", "/jobs", { params: { limit: 100 } }),
        ]);
        if (!active) return;
        setUser(userResponse.data);
        setJobs(jobsResponse.data);
        setMatchJobId((current) => current || String(jobsResponse.data.find((job) => job.status === "open")?.id || jobsResponse.data[0]?.id || ""));
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

  useEffect(() => {
    if (!token) return undefined;
    const needsCandidates = new Set(["candidates", "matches", "merge", "tools", "talent", "portal"]);
    const needsApplications = new Set(["pipeline", "matches", "interviews", "offers", "tools", "automation"]);
    if (!needsCandidates.has(view) && !needsApplications.has(view)) return undefined;
    let active = true;
    async function loadViewData() {
      try {
        const requests = [];
        if (needsCandidates.has(view) && !candidates.length) {
          requests.push(apiRequest(token, "get", "/candidates", { params: { limit: 100 } }));
        } else {
          requests.push(Promise.resolve(null));
        }
        if (needsApplications.has(view) && !applications.length) {
          requests.push(apiRequest(token, "get", "/applications", { params: { limit: 100 } }));
        } else {
          requests.push(Promise.resolve(null));
        }
        const [candidateResponse, applicationResponse] = await Promise.all(requests);
        if (!active) return;
        if (candidateResponse) setCandidates(candidateResponse.data);
        if (applicationResponse) setApplications(applicationResponse.data);
      } catch (loadError) {
        if (active) setError(errorText(loadError));
      }
    }
    loadViewData();
    return () => { active = false; };
  }, [token, view]);

  async function refreshWorkspace() {
    if (!token) return;
    const needsCandidates = new Set(["candidates", "matches", "merge", "tools", "talent", "portal"]);
    const needsApplications = new Set(["pipeline", "matches", "interviews", "offers", "tools", "automation"]);
    const requests = [];
    requests.push(apiRequest(token, "get", "/jobs", { params: { limit: 100 } }));
    requests.push(
      needsCandidates.has(view)
        ? apiRequest(token, "get", "/candidates", { params: { limit: 100 } })
        : Promise.resolve(null),
    );
    requests.push(
      needsApplications.has(view)
        ? apiRequest(token, "get", "/applications", {
            params: {
              ...Object.fromEntries(Object.entries(filters).filter(([, value]) => value)),
              limit: 100,
            },
          })
        : Promise.resolve(null),
    );
    const [jobsResponse, candidateResponse, applicationResponse] = await Promise.all(requests);
    setJobs(jobsResponse.data);
    if (candidateResponse) setCandidates(candidateResponse.data);
    if (applicationResponse) setApplications(applicationResponse.data);
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

  async function signOut() {
    const currentToken = token;
    try {
      if (currentToken) await apiRequest(currentToken, "post", "/auth/logout");
    } catch (_) {
      // Always clear local state even when the server session is already expired.
    } finally {
      sessionStorage.removeItem("bluepace_token");
      setToken(null);
      setUser(null);
      setJobs([]);
      setCandidates([]);
      setApplications([]);
      setNotice("");
      setError("");
    }
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


  useEffect(() => {
    if (!token || view !== "dashboard") return undefined;
    let active = true;
    setDashboardLoading(true);
    apiRequest(token, "get", "/dashboard")
      .then((response) => { if (active) setDashboardData(response.data); })
      .catch((requestError) => { if (active) setError(errorText(requestError)); })
      .finally(() => { if (active) setDashboardLoading(false); });
    return () => { active = false; };
  }, [token, view]);

  useEffect(() => {
    if (!token || view !== "emails") return undefined;
    let active = true;
    setEmailsLoading(true);
    setError("");
    apiRequest(token, "get", "/emails", { params: { limit: 200 } })
      .then((response) => { if (active) setEmails(Array.isArray(response.data) ? response.data : []); })
      .catch((requestError) => {
        if (!active) return;
        if (requestError.response?.status === 401) {
          sessionStorage.removeItem("bluepace_token");
          setToken(null);
          setUser(null);
          setEmails([]);
          setError("Your session has expired. Please sign in again to open Email Center.");
          return;
        }
        setError(errorText(requestError));
      })
      .finally(() => { if (active) setEmailsLoading(false); });
    return () => { active = false; };
  }, [token, view]);

  useEffect(() => {
    if (!token || !selectedCandidate) {
      setCandidateCollaboration(null);
      return undefined;
    }
    let active = true;
    apiRequest(token, "get", "/candidates/" + selectedCandidate + "/collaboration")
      .then((response) => { if (active) setCandidateCollaboration(response.data); })
      .catch(() => { if (active) setCandidateCollaboration(null); });
    return () => { active = false; };
  }, [token, selectedCandidate]);

  async function refreshCandidateCollaboration() {
    if (!token || !selectedCandidate) return;
    const response = await apiRequest(token, "get", "/candidates/" + selectedCandidate + "/collaboration");
    setCandidateCollaboration(response.data);
  }

  async function updateCandidateCollaboration(patch) {
    try {
      const response = await apiRequest(token, "patch", "/candidates/" + selectedCandidate + "/collaboration", { data: patch });
      setCandidateCollaboration(response.data);
      setCandidates((current) => current.map((item) => item.id === selectedCandidate ? { ...item, ...response.data } : item));
    } catch (requestError) {
      setError(errorText(requestError));
    }
  }

  async function addCollaborationTag(event) {
    event.preventDefault();
    if (!collabTagName.trim()) return;
    try {
      await apiRequest(token, "post", "/candidates/" + selectedCandidate + "/collaboration/tags", { data: { name: collabTagName.trim(), color: collabTagColor } });
      setCollabTagName("");
      await refreshCandidateCollaboration();
      await refreshWorkspace();
    } catch (requestError) { setError(errorText(requestError)); }
  }

  async function removeCollaborationTag(tagId) {
    try {
      await apiRequest(token, "delete", "/candidates/" + selectedCandidate + "/collaboration/tags/" + tagId);
      await refreshCandidateCollaboration();
      await refreshWorkspace();
    } catch (requestError) { setError(errorText(requestError)); }
  }

  async function addCollaborationComment(event) {
    event.preventDefault();
    if (!collabComment.trim()) return;
    try {
      await apiRequest(token, "post", "/candidates/" + selectedCandidate + "/collaboration/comments", { data: { body: collabComment.trim() } });
      setCollabComment("");
      await refreshCandidateCollaboration();
      setNotice("Internal comment added");
    } catch (requestError) { setError(errorText(requestError)); }
  }

  async function toggleCandidateFollow() {
    try {
      if (candidateCollaboration?.following) {
        await apiRequest(token, "delete", "/candidates/" + selectedCandidate + "/collaboration/follow");
      } else {
        await apiRequest(token, "post", "/candidates/" + selectedCandidate + "/collaboration/follow");
      }
      await refreshCandidateCollaboration();
    } catch (requestError) { setError(errorText(requestError)); }
  }

  useEffect(() => {
    if (!token || !selectedCandidate) {
      setCandidateActivity(null);
      return undefined;
    }
    let active = true;
    apiRequest(token, "get", "/candidates/" + selectedCandidate + "/activity")
      .then((response) => { if (active) setCandidateActivity(response.data); })
      .catch(() => { if (active) setCandidateActivity(null); });
    return () => { active = false; };
  }, [token, selectedCandidate]);

  async function generatePortalLink(applicationId) {
    if (!applicationId) return;
    setPortalLinkLoading(true);
    setError("");
    try {
      const response = await apiRequest(token, "get", "/applications/" + applicationId + "/portal-link");
      setPortalLink(response.data?.url || "");
    } catch (requestError) {
      setError(errorText(requestError));
    } finally {
      setPortalLinkLoading(false);
    }
  }

  function resetJobForm(job = null) {
    setEditingJob(job);
    setJobEntryMode(job ? "manual" : "manual");
    setJobDocumentFile(null);
    setJobLinkInput(job?.jd_analysis?.source_url || "");
    setJobForm(job ? {
      title: job.title,
      description: job.description,
      department: job.department || "",
      location: job.location || "",
      employment_type: job.employment_type || "Full-time",
      work_mode: job.work_mode || "onsite",
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
      work_mode: "onsite",
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
      if (!editingJob && jobEntryMode === "link") {
        if (!jobLinkInput.trim()) {
          setError("Paste a public job URL or an [Title](URL) Markdown job link.");
          return;
        }
        const body = new FormData();
        body.append("url", jobLinkInput.trim());
        if (jobForm.title.trim()) body.append("title", jobForm.title.trim());
        if (jobForm.location.trim()) body.append("location", jobForm.location.trim());
        body.append("work_mode", jobForm.work_mode);
        body.append("status_value", jobForm.status);
        if (jobForm.minimum_experience_years !== "") body.append("minimum_experience_years", String(Number(jobForm.minimum_experience_years)));
        body.append("fresher_allowed", String(Boolean(jobForm.fresher_allowed)));
        await apiRequest(token, "post", "/jobs/from-url", { data: body });
        setNotice("Job link imported, requirements extracted, and matching criteria prepared");
      } else if (!editingJob && jobEntryMode === "upload") {
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
        body.append("work_mode", jobForm.work_mode);
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
      setJobLinkInput("");
      setJobEntryMode("manual");
      await refreshWorkspace();
    } catch (requestError) {
      setError(errorText(requestError));
    }
  }

  async function analyzeJob(job) {
    try {
      const response = await apiRequest(token, "post", "/jobs/" + job.id + "/analyze");
      setJobs((current) => current.map((item) => item.id === job.id ? { ...item, jd_analysis: response.data.jd_analysis } : item));
      setNotice("JD intelligence refreshed");
    } catch (requestError) { setError(errorText(requestError)); }
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

  function openInterviewDialog(application) {
    const start = new Date(Date.now() + 60 * 60 * 1000);
    const local = new Date(start.getTime() - start.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
    setInterviewDialogApplication(application);
    const defaultMode = application.job_work_mode === "onsite" ? "offline" : "online";
    setInterviewForm({ starts_at: local, duration_minutes: "60", mode: defaultMode, location: "", meeting_url: "" });
    setError("");
  }

  async function scheduleInterviewAndChangeStage(event) {
    event.preventDefault();
    if (!interviewDialogApplication || !interviewForm.starts_at) return;
    try {
      const startsAt = new Date(interviewForm.starts_at);
      if (Number.isNaN(startsAt.getTime())) {
        setError("Enter a valid interview date and time.");
        return;
      }
      await apiRequest(token, "post", `/applications/${interviewDialogApplication.id}/stage`, {
        data: {
          stage_name: "Interview",
          interview_starts_at: startsAt.toISOString(),
          interview_duration_minutes: Number(interviewForm.duration_minutes || 60),
          interview_mode: interviewForm.mode,
          interview_location: interviewForm.mode === "offline" ? interviewForm.location.trim() : null,
          interview_meeting_url: interviewForm.mode === "online" ? interviewForm.meeting_url.trim() : null,
        },
      });
      setInterviewDialogApplication(null);
      setNotice(`Interview scheduled and invitation sent to ${interviewDialogApplication.candidate.email}`);
      await refreshWorkspace();
    } catch (requestError) {
      setError(errorText(requestError));
    }
  }

  async function changeStage(applicationId, stageName) {
    const application = applications.find((item) => item.id === applicationId);
    const enrichedApplication = application ? { ...application, job_work_mode: jobs.find((job) => job.id === application.job_id)?.work_mode || "onsite" } : null;
    if (stageName === "Interview" && enrichedApplication) {
      openInterviewDialog(enrichedApplication);
      return;
    }
    try {
      await apiRequest(token, "post", `/applications/${applicationId}/stage`, { data: { stage_name: stageName } });
      const emailStage = stageName === "Offer" ? "Offer email sent" : stageName === "Hired" ? "Selection email sent" : stageName === "Rejected" ? "Rejection email sent" : `Application moved to ${stageName}`;
      setNotice(emailStage);
      await refreshWorkspace();
    } catch (requestError) {
      setError(errorText(requestError));
      await refreshWorkspace();
    }
  }

  async function loadFitAnalysis() {
    if (!selectedCandidate || !fitJobId) return;
    const application = applications.find(
      (item) => item.candidate_id === selectedCandidate && item.job_id === Number(fitJobId)
    );
    if (!application) {
      setError("This candidate is not currently attached to the selected job.");
      return;
    }
    setFitLoading(true);
    setFitAnalysis(null);
    setError("");
    try {
      const response = await apiRequest(token, "get", `/applications/${application.id}/fit-analysis`);
      setFitAnalysis(response.data);
    } catch (requestError) {
      setError(errorText(requestError));
    } finally {
      setFitLoading(false);
    }
  }

  async function askRecruiterAssistant() {
    if (!assistantApplicationId || !assistantQuestion.trim()) return;
    setAssistantLoading(true);
    setAssistantResult(null);
    setError("");
    try {
      const response = await apiRequest(token, "post", `/candidate-tools/applications/${assistantApplicationId}/assistant`, {
        data: { question: assistantQuestion.trim() },
      });
      setAssistantResult(response.data);
      setNotice("Assistant response generated from ATS evidence");
    } catch (requestError) {
      setError(errorText(requestError));
    } finally {
      setAssistantLoading(false);
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

  async function searchCandidates(event) {
    event?.preventDefault();
    if (!token) return;
    setLoading(true);
    setError("");
    try {
      const params = Object.fromEntries(Object.entries(candidateFilters).filter(([, value]) => value));
      const response = await apiRequest(token, "get", "/candidates", { params: { ...params, limit: 100 } });
      setCandidates(response.data);
      setSelectedCandidate(null);
    } catch (requestError) {
      setError(errorText(requestError));
    } finally {
      setLoading(false);
    }
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
      setPublicSuccess(response.data?.message || "Application submitted successfully. A confirmation email has been queued to your application email.");
      setPublicResume(null);
      setPublicForm({ full_name: "", email: "", phone: "" });
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

  if (portalToken) return <CandidatePortal token={portalToken} theme={theme} onToggleTheme={toggleTheme} />;

  if (!token && accessMode === "public") {
    return (
      <main className="min-h-screen bg-[#f3f4f1] text-ink-900">
        <header className="bp-public-header border-b border-white/10 bg-ink-950 px-5 py-4 text-white">
          <div className="mx-auto flex max-w-7xl items-center justify-between gap-5">
            <a href="https://www.blupacetech.com/" target="_blank" rel="noreferrer" className="bp-wordmark flex items-center gap-3 text-white no-underline">
              <span className="bp-logo-mark">B</span>
              <span>
                <span className="block text-[15px] font-semibold tracking-tight">blupace</span>
                <span className="block text-[9px] font-semibold uppercase tracking-[0.24em] text-white/55">tech</span>
              </span>
            </a>
            <div className="flex items-center gap-2">
              <span className="hidden text-xs text-white/60 sm:inline">Talent &amp; Workforce</span>
              <a href="https://www.blupacetech.com/" target="_blank" rel="noreferrer" className="hidden rounded-md px-3 py-2 text-xs font-semibold text-white/80 hover:bg-white/10 hover:text-white sm:inline-flex">
                Company site
              </a>
              <ThemeToggle theme={theme} onToggle={toggleTheme} />
              <button className="border-white/20 bg-white/10 text-white hover:bg-white/15" onClick={() => switchAccessMode("admin")}>
                Admin / Recruiter Login
              </button>
            </div>
          </div>
        </header>

        <section className="bp-public-hero relative overflow-hidden border-b border-ink-100">
          <div className="mx-auto grid max-w-7xl gap-10 px-5 py-14 sm:py-16 lg:grid-cols-[1.35fr_0.65fr] lg:items-end lg:py-20">
            <div className="max-w-3xl">
              <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.22em] text-blue-700">
                <span className="h-1.5 w-1.5 rounded-full bg-orange-500"></span>
                Careers at Blupace Tech
              </p>
              <h1 className="mt-5 text-4xl font-semibold tracking-[-0.035em] text-ink-950 sm:text-5xl lg:text-6xl">
                Enterprise talent, built to move at your pace.
              </h1>
              <p className="mt-5 max-w-2xl text-base leading-7 text-ink-600 sm:text-lg">
                Explore technology opportunities across software, AI, data, cloud, cybersecurity, infrastructure and workplace services.
              </p>
              <div className="mt-8 flex flex-wrap items-center gap-3">
                <a href="#jobs" className={buttonPrimary + " no-underline"}>Explore open roles</a>
                <a href="https://www.blupacetech.com/recruitment-staff-augmentation" target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 rounded-md border border-ink-100 bg-white px-4 py-2 text-sm font-semibold text-ink-800 no-underline shadow-sm hover:bg-ink-50">
                  About Talent &amp; Workforce
                </a>
              </div>
            </div>
            <div className="grid grid-cols-3 gap-3 lg:pb-1">
              <div className="bp-stat-card"><span>20+</span><small>Years</small></div>
              <div className="bp-stat-card"><span>10+</span><small>Countries</small></div>
              <div className="bp-stat-card"><span>3</span><small>Specialist businesses</small></div>
            </div>
          </div>
        </section>

        <section className="mx-auto max-w-7xl px-5 pb-4 pt-10">
          <div className="bp-career-intro rounded-2xl border border-blue-100 bg-blue-50/60 p-5 sm:flex sm:items-center sm:justify-between sm:gap-6">
            <div>
              <p className="text-sm font-semibold text-ink-900">A candidate experience designed around clarity.</p>
              <p className="mt-1 text-sm leading-6 text-ink-600">Apply without creating an account, keep your email current, and use your secure candidate portal for updates.</p>
            </div>
            <span className="mt-3 inline-flex w-fit rounded-full border border-blue-100 bg-white px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-blue-700 sm:mt-0">Secure application flow</span>
          </div>
        </section>

        <section id="jobs" className="mx-auto max-w-7xl px-5 py-8">
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
                        {[job.department, job.location, job.employment_type, workModeLabel(job.work_mode)].filter(Boolean).join(" · ")}
                      </p>
                    </div>
                    {job.fresher_allowed && (
                      <span className="rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-700">Fresher friendly</span>
                    )}
                  </div>
                  <p className="mt-4 line-clamp-4 whitespace-pre-line text-sm leading-6 text-ink-600">{job.description}</p>
              <p className="mt-3 text-xs font-semibold uppercase tracking-[0.14em] text-ink-500">Work mode: <span className="normal-case tracking-normal text-ink-700">{workModeLabel(job.work_mode)}</span></p>
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

        <PublicHelpCenter />

        <footer className="bp-public-footer mt-16 border-t border-ink-100 bg-ink-950 px-5 py-10 text-white">
          <div className="mx-auto grid max-w-7xl gap-8 sm:grid-cols-2 lg:grid-cols-3">
            <div>
              <p className="text-lg font-semibold">blupace<span className="text-orange-400">.</span>tech</p>
              <p className="mt-2 max-w-sm text-sm leading-6 text-white/60">Enterprise technology, global capability centres, and talent &amp; workforce solutions.</p>
            </div>
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-white/40">Careers</p>
              <a className="mt-3 block text-sm text-white/75 hover:text-white" href="#jobs">Open positions</a>
              <a className="mt-2 block text-sm text-white/75 hover:text-white" href="https://www.blupacetech.com/recruitment-staff-augmentation" target="_blank" rel="noreferrer">Talent &amp; Workforce</a>
            </div>
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-white/40">Connect</p>
              <a className="mt-3 block text-sm text-white/75 hover:text-white" href="mailto:hello@blupacetech.com">hello@blupacetech.com</a>
              <a className="mt-2 block text-sm text-white/75 hover:text-white" href="https://www.blupacetech.com/" target="_blank" rel="noreferrer">blupacetech.com</a>
            </div>
          </div>
          <div className="mx-auto mt-8 max-w-7xl border-t border-white/10 pt-5 text-[11px] text-white/40">© Blupace Tech · Careers &amp; Talent</div>
        </footer>
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
                <p className="font-semibold tracking-tight">blupace<span className="text-orange-500">.</span>tech</p>
                <p className="text-xs text-ink-500">Talent &amp; Workforce · Recruiting</p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <ThemeToggle theme={theme} onToggle={toggleTheme} />
              <button className={buttonSecondary} onClick={() => switchAccessMode("public")}>
                Public Portal
              </button>
            </div>
          </div>
          <h1 className="text-2xl font-semibold">Sign in</h1>
          <p className="mt-1 text-sm text-ink-500">Use the shared recruiting account provided by your administrator.</p>
          <form onSubmit={signIn} className="mt-7 grid gap-4">
            <Field label="Work email" type="email" autoComplete="email" required value={authForm.email} onChange={(event) => setAuthForm({ ...authForm, email: event.target.value })} />
            <Field label="Password" type="password" autoComplete={authMode === "login" ? "current-password" : "new-password"} minLength={12} required value={authForm.password} onChange={(event) => setAuthForm({ ...authForm, password: event.target.value })} />
            {authError && <p role="alert" className="text-sm text-rose-700">{authError}</p>}
            <button className={`${buttonPrimary} mt-1 w-full py-3`} type="submit">
              Sign in
            </button>
          </form>
        </section>
      </main>
    );
  }

  const navItems = [
    { id: "dashboard", label: "Dashboard" },
    { id: "command", label: "Command Center" },
    { id: "pipeline", label: "Applications", count: applications.length },
    { id: "jobs", label: "Jobs", count: jobs.filter((job) => job.status !== "archived").length },
    { id: "candidates", label: "Candidates", count: candidates.length },
    { id: "merge-center", label: "Merge Center" },
    { id: "interviews-2", label: "Interview Management" },
    { id: "offers", label: "Offer Management" },
    { id: "matching", label: "AI Match" },
    { id: "assistant", label: "AI Recruiter Assistant" },
    { id: "emails", label: "Email Center" },
    { id: "templates", label: "Email Templates" },
    { id: "talent", label: "Talent Pools" },
    { id: "analytics", label: "Analytics" },
    { id: "resume", label: "Resume Lab" },
  ];

  return (
    <div className="min-h-screen bg-[#f3f4f1] text-ink-900">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-60 flex-col overflow-y-auto bg-ink-950 text-white lg:flex">
        <div className="flex h-[72px] items-center gap-3 border-b border-white/10 px-5">
          <div className="grid h-9 w-9 place-items-center rounded-md bg-gold-500 text-xs font-bold text-ink-950">BP</div>
          <div>
            <p className="text-sm font-semibold tracking-tight">blupace<span className="text-orange-400">.</span>tech</p>
            <p className="text-[11px] text-ink-400">Talent &amp; Workforce · Recruiting</p>
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
        <div className="sticky bottom-0 mt-auto border-t border-white/10 bg-ink-950 px-5 py-4">
          <p className="truncate text-sm font-medium">{user?.full_name}</p>
          <p className="mt-0.5 text-xs capitalize text-ink-400">{user?.role?.replaceAll("_", " ")}</p>
          <button onClick={signOut} className="mt-4 text-xs font-medium text-ink-300 hover:text-white">Sign out</button>
        </div>
      </aside>

      <div className="lg:pl-60">
        <header className="ats-workspace-header sticky top-0 z-20 flex min-h-[72px] flex-wrap items-center justify-between gap-3 border-b border-ink-100 bg-white/95 px-4 py-3 backdrop-blur sm:px-7">
          <div>
            <p className="text-xs font-medium text-ink-500">{user?.email}</p>
            <h1 className="text-lg font-semibold">{navItems.find((item) => item.id === view)?.label}</h1>
          </div>
          <div className="flex items-center gap-2">
            {view === "pipeline" && canWrite && <button className={buttonPrimary} onClick={() => { setApplicationFormOpen(true); setError(""); }}>Add application</button>}
            {view === "jobs" && canWrite && <button className={buttonPrimary} onClick={() => resetJobForm()}>New job</button>}
            {view === "candidates" && canWrite && <button className={buttonPrimary} onClick={() => setCandidateFormOpen(true)}>Add candidate</button>}
            <ThemeToggle theme={theme} onToggle={toggleTheme} />
            <button className={`${buttonSecondary} lg:hidden`} onClick={signOut}>Sign out</button>
          </div>
          <nav className="ats-mobile-nav flex w-full gap-1 overflow-x-auto pb-0.5 lg:hidden" aria-label="Workspace">
            {navItems.map((item) => <button key={item.id} onClick={() => setView(item.id)} className={`whitespace-nowrap rounded-md px-3 py-2 text-sm ${view === item.id ? "bg-ink-950 text-white" : "text-ink-600 hover:bg-ink-50"}`}>{item.label}</button>)}
          </nav>
        </header>

        <Suspense fallback={<div className="mx-auto max-w-[1440px] rounded-xl border border-ink-100 bg-white p-6 text-sm text-ink-500">Loading workspace module…</div>}>
          <main className="mx-auto max-w-[1440px] px-4 py-6 sm:px-7 sm:py-8">
          {notice && <div role="status" className="mb-4 flex items-center justify-between border-l-2 border-emerald-600 bg-white px-4 py-3 text-sm text-ink-700"><span>{notice}</span><button aria-label="Dismiss notice" onClick={() => setNotice("")}>×</button></div>}
          {error && <div role="alert" className="mb-4 flex items-center justify-between border-l-2 border-rose-600 bg-white px-4 py-3 text-sm text-rose-800"><span>{error}</span><button aria-label="Dismiss error" onClick={() => setError("")}>×</button></div>}
          {loading && <div className="mb-3 text-xs text-ink-500">Loading workspace…</div>}


          {view === "command" && <CommandCenterPanel
            token={token}
            apiRequest={apiRequest}
            onNotice={setNotice}
            onError={(requestError) => setError(errorText(requestError))}
          />}

          {view === "interviews-2" && <InterviewManagement2 token={token} apiRequest={apiRequest} applications={applications} onNotice={setNotice} onError={(requestError) => setError(errorText(requestError))} />}

          {view === "offers" && <OfferManagement token={token} apiRequest={apiRequest} applications={applications} onNotice={setNotice} onError={(requestError) => setError(errorText(requestError))} />}


          {view === "merge-center" && <CandidateMergeCenter token={token} apiRequest={apiRequest} onNotice={setNotice} onError={(requestError) => setError(errorText(requestError))} />}

          {view === "dashboard" && <>
            <div className="mb-6"><p className="text-sm text-ink-500">Recruitment overview</p><h2 className="mt-1 text-2xl font-semibold">Recruiter dashboard</h2></div>
            {dashboardLoading && <div className="mb-5 rounded-xl border border-ink-100 bg-white p-5 text-sm text-ink-500">Loading dashboard…</div>}
            {dashboardData && <>
              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-6">
                {[
                  ["Open jobs", dashboardData.metrics.open_jobs],
                  ["Applicants", dashboardData.metrics.total_applications],
                  ["Screening", dashboardData.metrics.screening],
                  ["Interviews", dashboardData.metrics.interviews],
                  ["Offers", dashboardData.metrics.offers],
                  ["Hired", dashboardData.metrics.hired],
                ].map(([label, value]) => <div key={label} className="rounded-xl border border-ink-100 bg-white p-4"><p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-500">{label}</p><p className="mt-2 text-3xl font-bold text-ink-900">{value}</p></div>)}
              </div>

              <div className="mt-5 grid gap-5 xl:grid-cols-3">
                <section className="rounded-xl border border-ink-100 bg-white p-5">
                  <div className="flex items-center justify-between gap-3"><div><p className="text-xs font-semibold uppercase tracking-[0.14em] text-blue-700">Pipeline</p><h3 className="mt-1 font-semibold">Applications by stage</h3></div><button className={buttonSecondary} onClick={() => setView("pipeline")}>Open pipeline</button></div>
                  <div className="mt-5 grid gap-3">
                    {STAGES.map((stage) => {
                      const value = dashboardData.stage_counts?.[stage] || 0;
                      const total = Math.max(dashboardData.metrics.total_applications, 1);
                      return <div key={stage}><div className="mb-1 flex justify-between text-xs"><span>{stage}</span><span className="font-semibold">{value}</span></div><div className="h-2 overflow-hidden rounded-full bg-ink-50"><div className="h-full rounded-full bg-[#1769d3]" style={{ width: String(Math.min(100, (value / total) * 100)) + "%" }} /></div></div>;
                    })}
                  </div>
                </section>

                <section className="rounded-xl border border-ink-100 bg-white p-5">
                  <div className="flex items-center justify-between gap-3"><div><p className="text-xs font-semibold uppercase tracking-[0.14em] text-blue-700">Hiring demand</p><h3 className="mt-1 font-semibold">Applications by job</h3></div><button className={buttonSecondary} onClick={() => setView("jobs")}>Jobs</button></div>
                  <div className="mt-5 grid gap-3">
                    {(dashboardData.job_counts || []).slice(0, 7).map((item) => <div key={item.name} className="flex items-center justify-between gap-3 border-b border-ink-50 pb-2 text-sm last:border-0"><span className="truncate">{item.name}</span><span className="rounded-full bg-blue-50 px-2 py-1 text-xs font-semibold text-blue-800">{item.count}</span></div>)}
                    {!dashboardData.job_counts?.length && <p className="text-sm text-ink-500">No application data yet.</p>}
                  </div>
                </section>

                <section className="rounded-xl border border-ink-100 bg-white p-5">
                  <div className="flex items-center justify-between gap-3"><div><p className="text-xs font-semibold uppercase tracking-[0.14em] text-blue-700">Communication</p><h3 className="mt-1 font-semibold">Email delivery</h3></div><button className={buttonSecondary} onClick={() => setView("emails")}>Email center</button></div>
                  <div className="mt-5 grid grid-cols-3 gap-3">
                    <div className="rounded-xl bg-emerald-50 p-3 text-emerald-800"><p className="text-[11px] uppercase">Sent</p><p className="mt-1 text-2xl font-bold">{dashboardData.email_counts?.sent || 0}</p></div>
                    <div className="rounded-xl bg-amber-50 p-3 text-amber-800"><p className="text-[11px] uppercase">Pending</p><p className="mt-1 text-2xl font-bold">{dashboardData.email_counts?.pending || 0}</p></div>
                    <div className="rounded-xl bg-rose-50 p-3 text-rose-800"><p className="text-[11px] uppercase">Failed</p><p className="mt-1 text-2xl font-bold">{dashboardData.email_counts?.failed || 0}</p></div>
                  </div>
                </section>
              </div>

              <div className="mt-5 grid gap-5 xl:grid-cols-2">
                <section className="rounded-xl border border-ink-100 bg-white p-5">
                  <div><p className="text-xs font-semibold uppercase tracking-[0.14em] text-blue-700">Recruitment analytics</p><h3 className="mt-1 font-semibold">Funnel visibility</h3></div>
                  <div className="mt-4 grid gap-2">
                    {STAGES.map((stage, index) => {
                      const value = dashboardData.stage_counts?.[stage] || 0;
                      const previous = index === 0 ? dashboardData.metrics.total_applications : (dashboardData.stage_counts?.[STAGES[index - 1]] || 0);
                      const rate = previous > 0 ? Math.round((value / previous) * 100) : 0;
                      return <div key={stage} className="flex items-center justify-between gap-4 border-b border-ink-50 py-2 text-sm last:border-0"><span>{stage}</span><span className="text-xs text-ink-500">{value} · {rate}% vs prior stage</span></div>;
                    })}
                  </div>
                </section>
                <section className="rounded-xl border border-ink-100 bg-white p-5">
                  <div className="flex items-center justify-between gap-3"><div><p className="text-xs font-semibold uppercase tracking-[0.14em] text-blue-700">Source tracking</p><h3 className="mt-1 font-semibold">Applications by source</h3></div><span className="text-xs text-ink-400">Top sources</span></div>
                  <div className="mt-4 grid gap-3">
                    {(dashboardData.source_counts || []).slice(0, 8).map((item) => {
                      const total = Math.max(dashboardData.metrics.total_applications, 1);
                      return <div key={item.name} className="grid gap-1"><div className="flex justify-between text-sm"><span>{item.name}</span><span className="font-semibold">{item.count}</span></div><div className="h-2 rounded-full bg-ink-50"><div className="h-full rounded-full bg-[#1769d3]" style={{ width: String(Math.min(100, (item.count / total) * 100)) + "%" }} /></div></div>;
                    })}
                    {!dashboardData.source_counts?.length && <p className="text-sm text-ink-500">No source data yet.</p>}
                  </div>
                </section>
              </div>

              <div className="mt-5 grid gap-5 xl:grid-cols-2">
                <section className="rounded-xl border border-ink-100 bg-white p-5">
                  <div className="flex items-center justify-between gap-3"><div><p className="text-xs font-semibold uppercase tracking-[0.14em] text-blue-700">Calendar</p><h3 className="mt-1 font-semibold">Upcoming interviews</h3></div><button className={buttonSecondary} onClick={() => setView("pipeline")}>Manage</button></div>
                  <div className="mt-4 grid gap-3">
                    {(dashboardData.upcoming_interviews || []).slice(0, 6).map((interview) => <div key={interview.id} className="rounded-lg border border-ink-100 p-3"><div className="flex items-start justify-between gap-3"><div><p className="font-semibold">{interview.candidate_name}</p><p className="text-xs text-ink-500">{interview.job_title}</p></div><span className="rounded-full bg-blue-50 px-2 py-1 text-[11px] font-semibold text-blue-800">{interview.mode === "offline" ? "Offline" : "Online"}</span></div><p className="mt-2 text-sm">{new Date(interview.starts_at).toLocaleString()} · {interview.duration_minutes} min</p><p className="mt-1 text-xs text-ink-500">{interview.mode === "offline" ? interview.location : interview.meeting_url}</p></div>)}
                    {!dashboardData.upcoming_interviews?.length && <p className="text-sm text-ink-500">No upcoming scheduled interviews.</p>}
                  </div>
                </section>

                <section className="rounded-xl border border-ink-100 bg-white p-5">
                  <div><p className="text-xs font-semibold uppercase tracking-[0.14em] text-blue-700">Recent</p><h3 className="mt-1 font-semibold">Latest applications</h3></div>
                  <div className="mt-4 divide-y divide-ink-50">
                    {(dashboardData.recent_applications || []).map((application) => <button key={application.id} className="flex w-full items-center justify-between gap-3 py-3 text-left hover:bg-ink-50" onClick={() => { setSelectedCandidate(application.candidate_id); setView("candidates"); }}><div><p className="font-medium">{application.candidate_name}</p><p className="text-xs text-ink-500">{application.job_title} · {new Date(application.applied_at).toLocaleDateString()}</p></div><span className="rounded-full bg-ink-50 px-2 py-1 text-[11px] font-semibold text-ink-700">{application.stage_name}</span></button>)}
                    {!dashboardData.recent_applications?.length && <p className="py-5 text-sm text-ink-500">No applications yet.</p>}
                  </div>
                </section>
              </div>
            </>}
          </>}

          {view === "analytics" && <AnalyticsPanel
            token={token}
            apiRequest={apiRequest}
            onError={(requestError) => setError(errorText(requestError))}
          />}

          {view === "talent" && <TalentPoolsPanel
            token={token}
            candidates={candidates}
            apiRequest={apiRequest}
            onNotice={setNotice}
            onError={(requestError) => setError(errorText(requestError))}
          />}

          {view === "templates" && <EmailTemplatesPanel
            token={token}
            apiRequest={apiRequest}
            onNotice={setNotice}
            onError={(requestError) => setError(errorText(requestError))}
          />}

                    {view === "pipeline" && <>
            <div className="mb-6 flex flex-col gap-4 border-b border-ink-100 pb-5 lg:flex-row lg:items-center lg:justify-between">
              <div className="min-w-0">
                <p className="text-sm text-ink-500">{applications.length} applications in this view</p>
                <h2 className="mt-1 text-xl font-semibold tracking-tight">Applications</h2>
                <p className="mt-1 max-w-2xl text-sm leading-6 text-ink-500">Review candidates, filter the pipeline, and move applications through each hiring stage.</p>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <button className={buttonSecondary} onClick={exportCsv}>Export CSV</button>
              </div>
            </div>

            <form onSubmit={loadFilteredApplications} className="mb-5 rounded-xl border border-ink-100 bg-white p-4 shadow-sm">
              <div className="mb-3 flex items-center justify-between gap-3">
                <div>
                  <p className="text-sm font-semibold text-ink-900">Filters</p>
                  <p className="text-xs text-ink-500">Narrow the application list using the fields below.</p>
                </div>
                <button
                  type="button"
                  className="text-xs font-semibold text-ink-500 underline underline-offset-4 hover:text-ink-900"
                  onClick={() => {
                    setFilters({ search: "", skill: "", stage_name: "", source: "", applied_after: "", applied_before: "" });
                  }}
                >
                  Clear
                </button>
              </div>
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-7 xl:items-end">
                <Field label="Search" placeholder="Candidate or job" value={filters.search} onChange={(event) => setFilter("search", event.target.value)} />
                <Field label="Skill" placeholder="Python" value={filters.skill} onChange={(event) => setFilter("skill", event.target.value)} />
                <SelectField label="Stage" value={filters.stage_name} onChange={(event) => setFilter("stage_name", event.target.value)}>
                  <option value="">All stages</option>
                  {STAGES.map((stage) => <option key={stage}>{stage}</option>)}
                </SelectField>
                <Field label="Source" placeholder="Referral" value={filters.source} onChange={(event) => setFilter("source", event.target.value)} />
                <Field label="Applied after" type="date" value={filters.applied_after} onChange={(event) => setFilter("applied_after", event.target.value)} />
                <Field label="Applied before" type="date" value={filters.applied_before} onChange={(event) => setFilter("applied_before", event.target.value)} />
                <div className="flex items-end">
                  <button type="submit" className={buttonPrimary + " w-full h-[42px]"}>Apply</button>
                </div>
              </div>
            </form>

            {canWrite && selectedApplications.length > 0 && (
              <div className="mb-4 flex flex-col gap-3 rounded-xl border border-gold-300 bg-[#fbf7ef] p-3 sm:flex-row sm:flex-wrap sm:items-end">
                <div className="mr-auto">
                  <span className="text-sm font-semibold text-ink-900">{selectedApplications.length} selected</span>
                  <p className="mt-0.5 text-xs text-ink-500">Apply a bulk stage action to the selected applications.</p>
                </div>
                <div className="w-full sm:w-44">
                  <SelectField label="Move to" value={bulkStage} onChange={(event) => setBulkStage(event.target.value)}>
                    {STAGES.map((stage) => <option key={stage}>{stage}</option>)}
                  </SelectField>
                </div>
                <button className={buttonPrimary} onClick={() => moveSelected()}>Move stage</button>
                <button className="rounded-md border border-rose-200 bg-white px-3 py-2 text-sm font-semibold text-rose-700 hover:bg-rose-50" onClick={() => moveSelected("Rejected")}>Reject selected</button>
              </div>
            )}

            <div className="ats-applications-table overflow-hidden rounded-xl border border-ink-100 bg-white shadow-sm">
              <div className="overflow-x-auto overscroll-x-contain">
                <table className="w-full min-w-[1100px] table-fixed border-collapse text-left text-sm">
                  <colgroup>
                    <col className="w-[4%]" />
                    <col className="w-[22%]" />
                    <col className="w-[18%]" />
                    <col className="w-[10%]" />
                    <col className="w-[26%]" />
                    <col className="w-[9%]" />
                    <col className="w-[11%]" />
                  </colgroup>
                  <thead className="border-b border-ink-100 bg-[#fafaf8] text-[11px] font-semibold uppercase tracking-wide text-ink-500">
                    <tr>
                      <th className="px-3 py-3 text-center align-middle"><span className="sr-only">Select</span></th>
                      <th className="px-3 py-3 align-middle">Candidate</th>
                      <th className="px-3 py-3 align-middle">Job</th>
                      <th className="px-3 py-3 align-middle">Source</th>
                      <th className="px-3 py-3 align-middle">Skills</th>
                      <th className="px-3 py-3 text-center align-middle">Applied</th>
                      <th className="px-3 py-3 align-middle">Stage</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-ink-50">
                    {applications.map((application) => (
                      <tr key={application.id} className="hover:bg-[#fcfcfa]">
                        <td className="px-3 py-4 text-center align-middle">
                          <input
                            aria-label={`Select ${application.candidate.first_name}`}
                            type="checkbox"
                            checked={selectedApplications.includes(application.id)}
                            onChange={() => toggleApplication(application.id)}
                            disabled={!canWrite}
                            className="h-4 w-4"
                          />
                        </td>
                        <td className="px-3 py-4 align-middle">
                          <button className="block max-w-full truncate text-left font-semibold text-ink-900 hover:text-ink-600" title={`${application.candidate.first_name} ${application.candidate.last_name}`} onClick={() => { setSelectedCandidate(application.candidate_id); setView("candidates"); }}>
                            {application.candidate.first_name} {application.candidate.last_name}
                          </button>
                          <div className="mt-1 max-w-full truncate text-xs text-ink-500" title={application.candidate.email}>{application.candidate.email}</div>
                        </td>
                        <td className="px-3 py-4 align-middle">
                          <div className="truncate font-medium text-ink-900" title={application.job_title}>{application.job_title}</div>
                        </td>
                        <td className="px-3 py-4 align-middle text-ink-600">
                          <span className="inline-flex max-w-full truncate rounded-full bg-ink-50 px-2.5 py-1 text-xs font-medium" title={application.candidate.source || "Not specified"}>
                            {application.candidate.source || "Not specified"}
                          </span>
                        </td>
                        <td className="px-3 py-4 align-middle text-xs leading-5 text-ink-600">
                          <div className="line-clamp-2" title={(application.candidate.resume_data?.skills || []).join(", ")}>
                            {(application.candidate.resume_data?.skills || []).slice(0, 5).join(", ") || "No skills extracted"}
                          </div>
                        </td>
                        <td className="px-3 py-4 align-middle whitespace-nowrap text-center text-xs text-ink-500">
                          {new Date(application.applied_at).toLocaleDateString()}
                        </td>
                        <td className="px-3 py-4 align-middle">
                          <select
                            aria-label={`Stage for ${application.candidate.first_name}`}
                            className="w-full min-w-32 rounded-md border border-ink-100 bg-white px-2.5 py-2 text-xs font-medium text-ink-800 outline-none focus:border-ink-300 focus:ring-2 focus:ring-ink-100"
                            value={application.stage_name || "Applied"}
                            disabled={!canWrite}
                            onChange={(event) => changeStage(application.id, event.target.value)}
                          >
                            {STAGES.map((stage) => <option key={stage}>{stage}</option>)}
                          </select>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {!applications.length && <EmptyState title="No applications found" detail="Create an application or adjust your filters." />}
            </div>
          </>}

          {view === "jobs" && <>

            {jobFormOpen && <form onSubmit={saveJob} className="mb-6 border-y border-ink-100 bg-white p-4 sm:p-5">
              <div className="mb-4 flex items-center justify-between"><h2 className="font-semibold">{editingJob ? "Edit job" : "New job"}</h2><button type="button" aria-label="Close form" onClick={() => { setJobFormOpen(false); setJobDocumentFile(null); setJobLinkInput(""); }}>×</button></div>
              {!editingJob && <div className="mb-5 flex flex-wrap gap-2 border-b border-ink-100 pb-3">
                <button type="button" onClick={() => setJobEntryMode("manual")} className={jobEntryMode === "manual" ? buttonPrimary : buttonSecondary}>Manual entry</button>
                <button type="button" onClick={() => setJobEntryMode("upload")} className={jobEntryMode === "upload" ? buttonPrimary : buttonSecondary}>Upload JD</button>
                <button type="button" onClick={() => setJobEntryMode("link")} className={jobEntryMode === "link" ? buttonPrimary : buttonSecondary}>Import job link</button>
              </div>}
              {jobEntryMode === "link" && !editingJob ? (
                <div className="grid gap-4">
                  <div className="rounded-xl border border-gold-200 bg-[#fbf7ef] p-4 text-sm text-ink-700">Paste a job link exactly like <code>[AI Infrastructure Engineer, pAGI](https://jobs.ashbyhq.com/openai/...)</code> or the public URL alone. The ATS imports the page, extracts requirements and prepares it for resume matching.</div>
                  <label className="grid gap-1.5 text-xs font-semibold text-ink-700">Job link
                    <input className={inputStyle} required value={jobLinkInput} placeholder="[AI Infrastructure Engineer, pAGI](https://jobs.ashbyhq.com/openai/...)" onChange={(event) => setJobLinkInput(event.target.value)} />
                    <span className="text-[11px] font-normal text-ink-400">Supports Ashby-style links and standard public job pages.</span>
                  </label>
                  <div className="grid gap-3 sm:grid-cols-3">
                    <Field label="Title override (optional)" placeholder="AI Infrastructure Engineer, pAGI" value={jobForm.title} onChange={(event) => setJobForm({ ...jobForm, title: event.target.value })} />
                    <Field label="Location override (optional)" value={jobForm.location} onChange={(event) => setJobForm({ ...jobForm, location: event.target.value })} />
                    <SelectField label="Work mode" value={jobForm.work_mode} onChange={(event) => setJobForm({ ...jobForm, work_mode: event.target.value })}>
                      <option value="remote">Remote</option><option value="hybrid">Hybrid</option><option value="onsite">On-site / Offline</option>
                    </SelectField>
                    <SelectField label="Status" value={jobForm.status} onChange={(event) => setJobForm({ ...jobForm, status: event.target.value })}>{["draft", "open", "paused", "closed"].map((value) => <option key={value} value={value}>{value}</option>)}</SelectField>
                  </div>
                </div>
              ) : jobEntryMode === "upload" && !editingJob ? (
                <div className="grid gap-4">
                  <div className="rounded-xl border border-gold-200 bg-[#fbf7ef] p-4 text-sm text-ink-700">Upload the job description as PDF or DOCX. BluePace extracts the text, required skills, experience, location and education requirements automatically, then uses the same matching engine for applicants.</div>
                  <label className="grid gap-1.5 text-xs font-semibold text-ink-700">Job description document
                    <input className={inputStyle + " p-2"} type="file" accept=".pdf,.docx" required onChange={(event) => setJobDocumentFile(event.target.files?.[0] || null)} />
                    <span className="text-[11px] font-normal text-ink-400">{jobDocumentFile ? jobDocumentFile.name : "PDF or DOCX, up to 10MB."}</span>
                  </label>
                  <div className="grid gap-3 sm:grid-cols-3">
                    <Field label="Job title override (optional)" value={jobForm.title} onChange={(event) => setJobForm({ ...jobForm, title: event.target.value })} />
                    <Field label="Department override (optional)" value={jobForm.department} onChange={(event) => setJobForm({ ...jobForm, department: event.target.value })} />
                    <Field label="Location override (optional)" value={jobForm.location} onChange={(event) => setJobForm({ ...jobForm, location: event.target.value })} />
                    <SelectField label="Employment type" value={jobForm.employment_type} onChange={(event) => setJobForm({ ...jobForm, employment_type: event.target.value })}>{["Full-time", "Part-time", "Contract", "Temporary", "Internship"].map((type) => <option key={type}>{type}</option>)}</SelectField>
                    <SelectField label="Work mode" value={jobForm.work_mode} onChange={(event) => setJobForm({ ...jobForm, work_mode: event.target.value })}><option value="remote">Remote</option><option value="hybrid">Hybrid</option><option value="onsite">On-site / Offline</option></SelectField>
                    <SelectField label="Status" value={jobForm.status} onChange={(event) => setJobForm({ ...jobForm, status: event.target.value })}>{["draft", "open", "paused", "closed"].map((value) => <option key={value} value={value}>{value}</option>)}</SelectField>
                    <Field label="Minimum experience override" type="number" min="0" max="60" placeholder="Auto-detect" value={jobForm.minimum_experience_years} onChange={(event) => setJobForm({ ...jobForm, minimum_experience_years: event.target.value })} />
                  </div>
                  <label className="flex min-h-10 items-center gap-2 text-sm font-medium text-ink-700"><input type="checkbox" checked={jobForm.fresher_allowed} onChange={(event) => setJobForm({ ...jobForm, fresher_allowed: event.target.checked })} />Open to freshers (override)</label>
                </div>
              ) : (
                <div className="grid gap-3 sm:grid-cols-2">
                  <Field label="Job title" required value={jobForm.title} onChange={(event) => setJobForm({ ...jobForm, title: event.target.value })} />
                  <Field label="Department" value={jobForm.department} onChange={(event) => setJobForm({ ...jobForm, department: event.target.value })} />
                  <Field label="Location" value={jobForm.location} onChange={(event) => setJobForm({ ...jobForm, location: event.target.value })} />
                  <SelectField label="Employment type" value={jobForm.employment_type} onChange={(event) => setJobForm({ ...jobForm, employment_type: event.target.value })}>{["Full-time", "Part-time", "Contract", "Temporary", "Internship"].map((type) => <option key={type}>{type}</option>)}</SelectField>
                  <SelectField label="Work mode" value={jobForm.work_mode} onChange={(event) => setJobForm({ ...jobForm, work_mode: event.target.value })}><option value="remote">Remote</option><option value="hybrid">Hybrid</option><option value="onsite">On-site / Offline</option></SelectField>
                  <SelectField label="Status" value={jobForm.status} onChange={(event) => setJobForm({ ...jobForm, status: event.target.value })}>{["draft", "open", "paused", "closed"].map((value) => <option key={value} value={value}>{value}</option>)}</SelectField>
                  <Field label="Required skills" placeholder="Python, PostgreSQL, AWS" value={jobForm.required_skills} onChange={(event) => setJobForm({ ...jobForm, required_skills: event.target.value })} />
                  <Field label="Minimum experience (years)" type="number" min="0" max="60" value={jobForm.minimum_experience_years} onChange={(event) => setJobForm({ ...jobForm, minimum_experience_years: event.target.value })} />
                  <label className="flex min-h-10 items-center gap-2 text-sm font-medium text-ink-700"><input type="checkbox" checked={jobForm.fresher_allowed} onChange={(event) => setJobForm({ ...jobForm, fresher_allowed: event.target.checked })} />Open to freshers</label>
                  <label className="grid gap-1.5 text-xs font-semibold text-ink-700 sm:col-span-2">Description<textarea className={inputStyle + " min-h-28 resize-y"} required value={jobForm.description} onChange={(event) => setJobForm({ ...jobForm, description: event.target.value })} /></label>
                </div>
              )}
              <div className="mt-4 flex gap-2"><button className={buttonPrimary} type="submit">{editingJob ? "Save changes" : jobEntryMode === "upload" ? "Upload & create job" : jobEntryMode === "link" ? "Import & create job" : "Create job"}</button><button className={buttonSecondary} type="button" onClick={() => { setJobFormOpen(false); setJobDocumentFile(null); setJobLinkInput(""); }}>Cancel</button></div>
            </form>}
            <div className="mb-5"><p className="text-sm text-ink-500">{jobs.length} total jobs</p><h2 className="mt-1 text-xl font-semibold">Job openings</h2></div>
            <div className="ats-jobs-table overflow-x-auto rounded-xl border border-ink-100 bg-white shadow-sm"><div className="min-w-[980px]">
              <div className="ats-jobs-grid grid grid-cols-[minmax(360px,2.4fr)_minmax(150px,0.9fr)_110px_minmax(220px,1.2fr)] gap-5 border-b border-ink-100 bg-[#fafaf8] px-5 py-3 text-[11px] font-semibold uppercase tracking-wide text-ink-500"><span>Role</span><span>Location</span><span>Created</span><span>Status</span></div>
              {jobs.map((job) => <div key={job.id} className="ats-jobs-grid grid grid-cols-[minmax(360px,2.4fr)_minmax(150px,0.9fr)_110px_minmax(220px,1.2fr)] gap-5 border-b border-ink-50 px-5 py-5 last:border-0">
                <div>{job.jd_analysis?.source_url ? <a className="font-semibold underline decoration-ink-200 underline-offset-4 hover:decoration-ink-700" href={job.jd_analysis.source_url} target="_blank" rel="noreferrer">{job.title}</a> : <button className="font-semibold hover:underline" onClick={() => resetJobForm(job)}>{job.title}</button>}<p className="mt-0.5 text-xs text-ink-500">{job.department || "Unassigned department"} · {job.employment_type || "Employment type not set"} · {workModeLabel(job.work_mode)}</p><p className="mt-1 text-xs text-ink-500">{job.minimum_experience_years === null ? "Experience unspecified" : `${job.minimum_experience_years}+ years`}{job.fresher_allowed ? " · Freshers welcome" : ""}{job.required_skills?.length ? ` · ${job.required_skills.join(", ")}` : ""}</p>
                {job.jd_analysis && <div className="mt-2 rounded-lg bg-ink-50 p-3 text-xs text-ink-600">
                  <div className="flex flex-wrap gap-x-4 gap-y-1">
                    <span><b>Seniority:</b> {job.jd_analysis.seniority || "Unspecified"}</span>
                    <span><b>Experience:</b> {job.jd_analysis.minimum_experience_years != null ? String(job.jd_analysis.minimum_experience_years) + "+" + (job.jd_analysis.maximum_experience_years ? "–" + job.jd_analysis.maximum_experience_years : "") + " years" : "Unspecified"}</span>
                    <span><b>Education:</b> {job.jd_analysis.education || "Unspecified"}</span>
                    <span><b>Mode:</b> {workModeLabel(job.jd_analysis.work_mode || job.work_mode)}</span>
                  </div>
                  <div className="mt-2"><b>Required:</b> {(job.jd_analysis.required_skills || []).join(", ") || "None"} · <b>Preferred:</b> {(job.jd_analysis.preferred_skills || []).join(", ") || "None"}</div>
                  {job.jd_analysis.responsibilities?.length > 0 && <div className="mt-2"><b>Responsibilities:</b> {job.jd_analysis.responsibilities.slice(0, 3).join(" · ")}</div>}
                  {job.jd_analysis.interview_topics?.length > 0 && <div className="mt-2"><b>Interview topics:</b> {job.jd_analysis.interview_topics.join(", ")}</div>}
                </div>}
                {job.jd_analysis?.source_url && <p className="mt-1 text-[11px] text-ink-400">Imported from job link</p>}</div>
                <div className="self-start break-words pt-0.5 text-sm text-ink-600">{job.location || "Remote / unspecified"}</div>
                <span className="self-start whitespace-nowrap pt-0.5 text-xs text-ink-500">{new Date(job.created_at).toLocaleDateString()}</span>
                <div className="flex min-w-0 flex-col items-start gap-2 self-start"><span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${job.status === "open" ? "bg-emerald-50 text-emerald-800" : job.status === "archived" ? "bg-ink-100 text-ink-500" : "bg-gold-50 text-ink-700"}`}>{job.status}</span><div className="flex flex-wrap items-center gap-x-4 gap-y-2"><button className="text-xs font-medium text-blue-700 underline underline-offset-2" onClick={() => analyzeJob(job)}>Refresh JD intelligence</button>{canWrite && job.status !== "archived" && <button className="text-xs font-medium text-ink-500 underline underline-offset-2" onClick={() => archiveJob(job)}>Archive</button>}</div></div>
              </div>)}
              {!jobs.length && <EmptyState title="No jobs yet" detail="Create a job to begin building your pipeline." />}
              </div>
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
                <div><p className="text-[11px] font-semibold uppercase text-ink-500">Work mode</p><p className="mt-1 capitalize">{matchAnalysis.work_mode || "Unspecified"}</p></div>
                <div><p className="text-[11px] font-semibold uppercase text-ink-500">Responsibilities</p><ul className="mt-1 grid gap-1 text-sm">{(matchAnalysis.responsibilities || []).slice(0, 5).map((item, index) => <li key={index}>• {item}</li>)}</ul></div>
                <div><p className="text-[11px] font-semibold uppercase text-ink-500">Interview topics</p><p className="mt-1 text-sm">{(matchAnalysis.interview_topics || []).join(", ") || "No topics extracted"}</p></div>
                <div><p className="text-[11px] font-semibold uppercase text-ink-500">Skill normalization</p><div className="mt-1 flex flex-wrap gap-1.5">{Object.entries(matchAnalysis.skill_normalization || {}).map(([raw, normalized]) => <span key={raw} className="rounded-full bg-ink-50 px-2 py-1 text-[11px]">{raw} → {normalized}</span>)}</div></div>
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
                      <td className="min-w-32 px-3 py-4"><p className="text-lg font-semibold tabular-nums">{match.effective_score}<span className="text-xs font-normal text-ink-500"> / 100</span></p>{match.recruiter_override !== null && <p className="text-[11px] text-gold-600">Model: {match.model_score}</p>}<div className="mt-1 h-1.5 w-24 bg-ink-100"><div className="h-full bg-gold-500" style={{ width: `${match.effective_score}%` }} /></div><p className="mt-2 text-[10px] text-ink-500">{Object.entries(MATCH_WEIGHTS).map(([key, weight]) => `${key.replaceAll("_", " ")} ${match.score_breakdown[key] ?? 0}·${weight}%`).join(" · ")}</p><p className="mt-1 text-[10px] text-ink-400">Decision-support signal; recruiter review remains required.</p></td>
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
            <form onSubmit={searchCandidates} className="mb-5 rounded-xl border border-ink-100 bg-white p-4">
              <div className="flex items-start justify-between gap-3">
                <div><p className="text-xs font-semibold uppercase tracking-[0.14em] text-blue-700">Advanced candidate search</p><p className="mt-1 text-sm text-ink-500">Combine structured filters with Boolean search across the candidate profile and resume.</p></div>
                <span className="rounded-full bg-ink-50 px-2.5 py-1 text-[11px] font-semibold text-ink-600">Recruiter search</span>
              </div>
              <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                <Field label="Boolean search" placeholder="Python AND SQL NOT Java" value={candidateFilters.search} onChange={(event) => setCandidateFilters({ ...candidateFilters, search: event.target.value })} />
                <Field label="Skills (all required)" placeholder="Python, SQL, React" value={candidateFilters.skill} onChange={(event) => setCandidateFilters({ ...candidateFilters, skill: event.target.value })} />
                <Field label="Location" placeholder="Hyderabad" value={candidateFilters.location} onChange={(event) => setCandidateFilters({ ...candidateFilters, location: event.target.value })} />
                <Field label="Preferred location" placeholder="Bengaluru" value={candidateFilters.preferred_location} onChange={(event) => setCandidateFilters({ ...candidateFilters, preferred_location: event.target.value })} />
                <Field label="Min experience" type="number" min="0" max="60" placeholder="Years" value={candidateFilters.min_experience_years} onChange={(event) => setCandidateFilters({ ...candidateFilters, min_experience_years: event.target.value })} />
                <Field label="Max experience" type="number" min="0" max="60" placeholder="Years" value={candidateFilters.max_experience_years} onChange={(event) => setCandidateFilters({ ...candidateFilters, max_experience_years: event.target.value })} />
                <Field label="Notice period" placeholder="30 days" value={candidateFilters.notice_period} onChange={(event) => setCandidateFilters({ ...candidateFilters, notice_period: event.target.value })} />
                <Field label="Availability" placeholder="Immediate / 2026-10-15" value={candidateFilters.availability} onChange={(event) => setCandidateFilters({ ...candidateFilters, availability: event.target.value })} />
                <Field label="Education" placeholder="B.Tech / Computer Science" value={candidateFilters.education} onChange={(event) => setCandidateFilters({ ...candidateFilters, education: event.target.value })} />
                <Field label="Job history" placeholder="Infosys / Backend Engineer" value={candidateFilters.job_history} onChange={(event) => setCandidateFilters({ ...candidateFilters, job_history: event.target.value })} />
                <Field label="Tags (all required)" placeholder="Immediate, React" value={candidateFilters.tags} onChange={(event) => setCandidateFilters({ ...candidateFilters, tags: event.target.value })} />
                <label className="grid gap-1.5 text-xs font-semibold text-ink-700">Stage<select className={inputStyle} value={candidateFilters.stage_name} onChange={(event) => setCandidateFilters({ ...candidateFilters, stage_name: event.target.value })}><option value="">Any stage</option>{["Applied","Screening","Interview","Offer","Hired","Rejected","withdrawn"].map((stage) => <option key={stage}>{stage}</option>)}</select></label>
                <label className="grid gap-1.5 text-xs font-semibold text-ink-700">Source<select className={inputStyle} value={candidateFilters.source} onChange={(event) => setCandidateFilters({ ...candidateFilters, source: event.target.value })}><option value="">All sources</option>{[...new Set(candidates.map((candidate) => candidate.source).filter(Boolean))].map((source) => <option key={source}>{source}</option>)}</select></label>
                <label className="grid gap-1.5 text-xs font-semibold text-ink-700">Has applied to job<select className={inputStyle} value={candidateFilters.has_applied_job_id} onChange={(event) => setCandidateFilters({ ...candidateFilters, has_applied_job_id: event.target.value })}><option value="">Any job</option>{jobs.map((job) => <option key={job.id} value={job.id}>{job.title}</option>)}</select></label>
                <Field label="Work authorization" placeholder="Authorized / visa" value={candidateFilters.work_authorization} onChange={(event) => setCandidateFilters({ ...candidateFilters, work_authorization: event.target.value })} />
              </div>
              <div className="mt-4 flex flex-wrap items-center gap-2">
                <button className={buttonPrimary} type="submit">Search candidates</button>
                <button className={buttonSecondary} type="button" onClick={() => {
                  const cleared = { search: "", skill: "", source: "", location: "", tags: "", stage_name: "", min_experience_years: "", max_experience_years: "", notice_period: "", education: "", job_history: "", availability: "", preferred_location: "", work_authorization: "", has_applied_job_id: "" };
                  setCandidateFilters(cleared);
                  apiRequest(token, "get", "/candidates", { params: { limit: 100 } }).then((response) => setCandidates(response.data)).catch((requestError) => setError(errorText(requestError)));
                }}>Clear</button>
                <span className="text-[11px] text-ink-500">Boolean: AND · OR · NOT · parentheses · quoted phrases</span>
              </div>
            </form>

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
                <div className="flex items-start justify-between">
                  <div>
                    <p className="text-xs uppercase text-ink-500">Candidate profile</p>
                    <h3 className="mt-1 text-lg font-semibold">{candidate.first_name} {candidate.last_name}</h3>
                    <p className="text-sm text-ink-500">{candidate.email}{candidate.phone && " · " + candidate.phone}</p>
                    {candidateActivity?.applications?.[0] && <div className="mt-3 flex flex-wrap gap-2">
                      <button type="button" className={buttonSecondary} disabled={portalLinkLoading} onClick={() => generatePortalLink(candidateActivity.applications[0].id)}>{portalLinkLoading ? "Generating…" : "Candidate portal link"}</button>
                      {portalLink && <button type="button" className={buttonSecondary} onClick={() => navigator.clipboard?.writeText(portalLink).then(() => setNotice("Candidate portal link copied")).catch(() => setNotice(portalLink))}>Copy portal link</button>}
                    </div>}
                  </div>
                  <button aria-label="Close profile" onClick={() => { setSelectedCandidate(null); setFitAnalysis(null); setCandidateActivity(null); setPortalLink(""); }}>×</button>
                </div>

                <div className="mt-5 rounded-xl border border-ink-100 bg-[#fcfcfa] p-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div><p className="text-xs font-semibold uppercase tracking-[0.16em] text-blue-700">Recruiter collaboration</p><p className="mt-1 text-sm text-ink-500">Tags, ownership, review state, follows and internal discussion.</p></div>
                    <div className="flex flex-wrap gap-2">
                      <button type="button" className={buttonSecondary} onClick={toggleCandidateFollow}>{candidateCollaboration?.following ? "Following" : "Follow"}</button>
                      <button type="button" className={candidateCollaboration?.starred ? buttonPrimary : buttonSecondary} onClick={() => updateCandidateCollaboration({ starred: !candidateCollaboration?.starred })}>{candidateCollaboration?.starred ? "★ Starred" : "☆ Star"}</button>
                      <button type="button" className={candidateCollaboration?.needs_review ? buttonPrimary : buttonSecondary} onClick={() => updateCandidateCollaboration({ needs_review: !candidateCollaboration?.needs_review })}>{candidateCollaboration?.needs_review ? "Needs review ✓" : "Needs review"}</button>
                      <button type="button" className={candidateCollaboration?.priority === "high" ? buttonPrimary : buttonSecondary} onClick={() => updateCandidateCollaboration({ priority: candidateCollaboration?.priority === "high" ? "normal" : "high" })}>{candidateCollaboration?.priority === "high" ? "High priority ✓" : "High priority"}</button>
                    </div>
                  </div>
                  <div className="mt-4 grid gap-4 lg:grid-cols-2">
                    <div>
                      <label className="grid gap-1.5 text-xs font-semibold text-ink-700">Candidate owner
                        <select className={inputStyle} value={candidateCollaboration?.owner_id || ""} onChange={(event) => updateCandidateCollaboration({ owner_id: event.target.value ? Number(event.target.value) : null })}>
                          <option value="">Unassigned</option>
                          {(candidateCollaboration?.followers || []).map((member) => <option key={member.user_id} value={member.user_id}>{member.user_name}</option>)}
                        </select>
                      </label>
                      <form onSubmit={addCollaborationTag} className="mt-4 flex gap-2">
                        <input className={inputStyle} placeholder="Add tag, e.g. React expert" value={collabTagName} onChange={(event) => setCollabTagName(event.target.value)} />
                        <input aria-label="Tag color" title="Tag color" type="color" className="h-10 w-12 rounded-md border border-ink-100 bg-white p-1" value={collabTagColor} onChange={(event) => setCollabTagColor(event.target.value)} />
                        <button className={buttonSecondary} type="submit">Add</button>
                      </form>
                      <div className="mt-3 flex flex-wrap gap-2">
                        {(candidateCollaboration?.tags || []).map((tag) => <span key={tag.id} className="inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-semibold text-white" style={{ backgroundColor: tag.color }}><span>{tag.name}</span><button type="button" className="opacity-80 hover:opacity-100" onClick={() => removeCollaborationTag(tag.id)} aria-label={"Remove " + tag.name}>×</button></span>)}
                        {!candidateCollaboration?.tags?.length && <span className="text-xs text-ink-400">No tags yet.</span>}
                      </div>
                    </div>
                    <div>
                      <form onSubmit={addCollaborationComment}>
                        <label className="grid gap-1.5 text-xs font-semibold text-ink-700">Internal comment
                          <textarea className={inputStyle + " min-h-24 resize-y"} placeholder="Add a private note. Mention teammates with @Aishwarya." value={collabComment} onChange={(event) => setCollabComment(event.target.value)} />
                        </label>
                        <div className="mt-2 flex justify-end"><button className={buttonSecondary} type="submit" disabled={!collabComment.trim()}>Add comment</button></div>
                      </form>
                      <div className="mt-3 max-h-48 space-y-2 overflow-auto">
                        {(candidateCollaboration?.comments || []).map((comment) => <div key={comment.id} className="rounded-lg border border-ink-100 bg-white p-3"><div className="flex justify-between gap-3"><span className="text-xs font-semibold">{comment.author_name}</span><span className="text-[11px] text-ink-400">{new Date(comment.created_at).toLocaleString()}</span></div><p className="mt-1 whitespace-pre-wrap text-sm text-ink-700">{comment.body}</p>{comment.mentions?.length ? <p className="mt-1 text-[11px] text-blue-700">Mentioned: {comment.mentions.map((mention) => "@" + mention.user_name).join(", ")}</p> : null}</div>)}
                        {!candidateCollaboration?.comments?.length && <p className="text-xs text-ink-400">No internal comments yet.</p>}
                      </div>
                    </div>
                  </div>
                </div>

                <div className="mt-5 grid gap-5 md:grid-cols-3">
                  <div>
                    <h4 className="text-xs font-semibold uppercase text-ink-500">Skills</h4>
                    <p className="mt-2 text-sm">{(profile.skills || []).join(", ") || "Not available"}</p>
                  </div>
                  <div>
                    <h4 className="text-xs font-semibold uppercase text-ink-500">Experience</h4>
                    <ul className="mt-2 grid gap-2 text-sm">
                      {(profile.experience || []).map((item, index) => <li key={index}><strong>{item.title || item.company || "Experience"}</strong><span className="block text-xs text-ink-500">{item.company} · {item.duration}</span><span className="block text-xs text-ink-600">{item.description}</span></li>)}
                    </ul>
                  </div>
                  <div>
                    <h4 className="text-xs font-semibold uppercase text-ink-500">Education</h4>
                    <ul className="mt-2 grid gap-2 text-sm">
                      {(profile.education || []).map((item, index) => <li key={index}><strong>{item.degree}</strong><span className="block text-xs text-ink-500">{item.university} · {item.graduation_year}</span></li>)}
                    </ul>
                  </div>
                </div>

                <div className="mt-5 rounded-xl border border-blue-100 bg-blue-50/40 p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div><p className="text-xs font-semibold uppercase tracking-[0.16em] text-blue-700">Resume intelligence</p><p className="mt-1 text-sm text-ink-500">Structured resume evidence for recruiter review. Missing or suspicious fields are signals to verify, not definitive facts.</p></div>
                    <span className="rounded-full bg-white px-2.5 py-1 text-[11px] font-semibold text-blue-800">Evidence-based</span>
                  </div>
                  <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                    {[
                      ["Years of experience", profile.years_of_experience ?? "Not found"],
                      ["Current location", profile.current_location || "Not found"],
                      ["Preferred location", profile.preferred_location || "Not found"],
                      ["Notice period", profile.notice_period || "Not found"],
                      ["Work authorization", profile.work_authorization || "Not found"],
                      ["LinkedIn", profile.linkedin || "Not found"],
                      ["GitHub", profile.github || "Not found"],
                      ["Highest education", profile.highest_education || "Not found"],
                    ].map(([label, value]) => <div key={label} className="rounded-lg border border-ink-100 bg-white p-3"><p className="text-[11px] font-semibold uppercase text-ink-500">{label}</p><p className="mt-1 break-words text-sm">{value}</p></div>)}
                  </div>
                  <div className="mt-4 grid gap-4 lg:grid-cols-3">
                    <div className="rounded-lg border border-ink-100 bg-white p-3"><p className="text-[11px] font-semibold uppercase text-ink-500">Companies</p><p className="mt-2 text-sm">{(profile.companies || []).join(", ") || "Not found"}</p></div>
                    <div className="rounded-lg border border-ink-100 bg-white p-3"><p className="text-[11px] font-semibold uppercase text-ink-500">Job titles</p><p className="mt-2 text-sm">{(profile.job_titles || []).join(", ") || "Not found"}</p></div>
                    <div className="rounded-lg border border-ink-100 bg-white p-3"><p className="text-[11px] font-semibold uppercase text-ink-500">Certifications</p><p className="mt-2 text-sm">{(profile.certifications || []).join(", ") || "Not found"}</p></div>
                  </div>
                  <div className="mt-4 rounded-lg border border-ink-100 bg-white p-3">
                    <div className="flex items-center justify-between gap-3">
                      <p className="text-[11px] font-semibold uppercase text-ink-500">Extraction confidence & evidence</p>
                      <span className="text-[11px] text-ink-500">Confidence describes extraction certainty, not candidate quality.</span>
                    </div>
                    <div className="mt-3 grid gap-2 sm:grid-cols-2">
                      {Object.entries(profile.extraction_confidence || {}).slice(0, 12).map(([field, score]) => {
                        const evidence = (profile.extraction_evidence || []).find((item) => item.field === field);
                        return <div key={field} className="rounded-md border border-ink-100 bg-[#fafaf8] p-2">
                          <div className="flex items-center justify-between gap-2 text-xs">
                            <span className="font-medium">{field.replaceAll("_", " ")}</span>
                            <span>{Math.round(Number(score) * 100)}%</span>
                          </div>
                          {evidence?.source_lines?.length ? <p className="mt-1 text-[11px] text-ink-500">{evidence.source_lines[0]}</p> : null}
                        </div>;
                      })}
                    </div>
                    {!Object.keys(profile.extraction_confidence || {}).length && <p className="mt-2 text-xs text-ink-400">Evidence details unavailable for this resume.</p>}
                  </div>
                  <div className="mt-4 grid gap-4 lg:grid-cols-2">
                    <div className="rounded-lg border border-ink-100 bg-white p-3"><p className="text-[11px] font-semibold uppercase text-ink-500">Projects</p><ul className="mt-2 grid gap-1 text-sm">{(profile.projects || profile.university_projects || []).slice(0, 12).map((project, index) => <li key={index}>{typeof project === "object" ? (project.name || project.title || project.description || JSON.stringify(project)) : project}</li>)}{!(profile.projects || profile.university_projects || []).length && <li className="text-ink-400">Not found</li>}</ul></div>
                    <div className="rounded-lg border border-ink-100 bg-white p-3"><p className="text-[11px] font-semibold uppercase text-ink-500">Resume review signals</p>
                      <p className="mt-2 text-xs text-ink-500">These flags indicate fields that may need recruiter verification.</p>
                      <div className="mt-2 flex flex-wrap gap-2">
                        {(profile.resume_quality?.missing_fields || []).map((field) => <span key={"missing-"+field} className="rounded-full bg-amber-50 px-2 py-1 text-[11px] font-medium text-amber-800">Missing: {field}</span>)}
                        {(profile.resume_quality?.optional_missing_fields || []).map((field) => <span key={"optional-missing-"+field} className="rounded-full bg-slate-50 px-2 py-1 text-[11px] font-medium text-slate-600">Not found: {field}</span>)}
                      </div>
                      <div className="mt-2 grid gap-2">{(profile.resume_quality?.suspicious_fields || []).map((flag, index) => <div key={index} className="rounded-md border border-amber-100 bg-amber-50/50 p-2 text-xs"><span className="font-semibold">{flag.field}</span>: {flag.reason}{flag.evidence ? <span className="block mt-1 text-ink-500">Evidence: {flag.evidence}</span> : null}</div>)}</div>
                      {!profile.resume_quality?.missing_fields?.length && !profile.resume_quality?.suspicious_fields?.length && <p className="mt-2 text-sm text-emerald-700">No review signals detected by the parser.</p>}
                    </div>
                  </div>
                </div>

                <div className="mt-6 border-t border-ink-100 pt-5">
                  <div className="flex items-start justify-between gap-3">
                    <div><p className="text-xs font-semibold uppercase tracking-[0.18em] text-blue-700">Candidate 360°</p><h4 className="mt-1 font-semibold">Application history & communication</h4></div>
                    {candidateActivity?.candidate && <span className="text-xs text-ink-500">{candidateActivity.applications?.length || 0} application(s)</span>}
                  </div>
                  <div className="mt-4 grid gap-4 lg:grid-cols-2">
                    <div className="rounded-xl border border-ink-100 bg-[#fafaf8] p-4">
                      <p className="text-xs font-semibold uppercase text-ink-500">Applied roles</p>
                      <div className="mt-3 grid gap-2">
                        {(candidateActivity?.applications || []).map((item) => <div key={item.id} className="flex items-center justify-between gap-3 rounded-lg border border-ink-100 bg-white p-3"><div><p className="text-sm font-semibold">{item.job_title}</p><p className="text-xs text-ink-500">{new Date(item.applied_at).toLocaleDateString()}</p></div><span className="rounded-full bg-blue-50 px-2 py-1 text-[11px] font-semibold text-blue-800">{item.stage_name}</span></div>)}
                        {!candidateActivity?.applications?.length && <p className="text-sm text-ink-500">No applications found.</p>}
                      </div>
                    </div>
                    <div className="rounded-xl border border-ink-100 bg-[#fafaf8] p-4">
                      <p className="text-xs font-semibold uppercase text-ink-500">Activity timeline</p>
                      <div className="mt-3 max-h-80 overflow-auto pr-1">
                        <div className="grid gap-3">
                          {(candidateActivity?.events || []).map((event, index) => <div key={index} className="rounded-lg border border-ink-100 bg-white p-3"><div className="flex items-center justify-between gap-2"><span className="text-xs font-semibold uppercase tracking-wide text-blue-700">{event.type}</span><span className="text-[11px] text-ink-400">{event.created_at ? new Date(event.created_at).toLocaleString() : ""}</span></div><p className="mt-1 text-sm font-medium">{event.title}</p>{event.details?.status && <p className="mt-1 text-xs text-ink-500">Status: {event.details.status}</p>}{event.details?.meeting_url && <a className="mt-1 block text-xs underline" href={event.details.meeting_url} target="_blank" rel="noreferrer">Open meeting link</a>}{event.details?.location && <p className="mt-1 text-xs text-ink-500">{event.details.location}</p>}</div>)}
                          {!candidateActivity?.events?.length && <p className="text-sm text-ink-500">No activity recorded yet.</p>}
                        </div>
                      </div>
                    </div>
                  </div>
                </div>

                <div className="mt-6 border-t border-ink-100 pt-5">
                  <div className="flex flex-wrap items-end justify-between gap-3">
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-blue-700">Role fit</p>
                      <h4 className="mt-1 font-semibold">Experience & project evidence</h4>
                    </div>
                    <div className="flex flex-wrap items-end gap-2">
                      <SelectField label="Job" value={fitJobId} onChange={(event) => { setFitJobId(event.target.value); setFitAnalysis(null); }}>
                        <option value="">Choose an applied job</option>
                        {applications.filter((item) => item.candidate_id === candidate.id).map((item) => <option key={item.id} value={item.job_id}>{item.job_title}</option>)}
                      </SelectField>
                      <button type="button" className={buttonPrimary} disabled={!fitJobId || fitLoading} onClick={loadFitAnalysis}>{fitLoading ? "Checking…" : "Check role fit"}</button>
                    </div>
                  </div>
                  {fitAnalysis && (
                    <div className="mt-5 grid gap-4 lg:grid-cols-3">
                      <div className="rounded-xl border border-blue-100 bg-blue-50 p-4 lg:col-span-1">
                        <p className="text-xs font-semibold uppercase text-blue-700">Screening evidence</p>
                        <p className="mt-2 text-2xl font-bold text-ink-900">{fitAnalysis.match_score}%</p>
                        <p className="mt-1 text-sm font-semibold text-blue-800">{fitAnalysis.alignment}</p>
                        <p className="mt-3 text-xs text-ink-600">{fitAnalysis.explanations?.join(" ")}</p>
                      </div>
                      <div className="rounded-xl border border-ink-100 p-4">
                        <p className="text-xs font-semibold uppercase text-ink-500">Relevant experience</p>
                        <div className="mt-2 grid gap-2 text-sm">{fitAnalysis.experience?.length ? fitAnalysis.experience.map((item, index) => <div key={index}><p className="font-semibold">{item.title}</p><p className="text-xs text-ink-500">{item.details || "Experience evidence extracted from resume."}</p></div>) : <p className="text-sm text-ink-500">No parsed experience evidence.</p>}</div>
                      </div>
                      <div className="rounded-xl border border-ink-100 p-4">
                        <p className="text-xs font-semibold uppercase text-ink-500">Projects relevant to this role</p>
                        <ul className="mt-2 grid gap-2 text-sm">{fitAnalysis.projects?.length ? fitAnalysis.projects.map((project, index) => <li key={index}>• {project}</li>) : <li className="text-ink-500">No parsed project evidence.</li>}</ul>
                      </div>
                      <div className="rounded-xl border border-ink-100 p-4 lg:col-span-2">
                        <p className="text-xs font-semibold uppercase text-ink-500">Matched vs. missing skills</p>
                        <div className="mt-3 flex flex-wrap gap-2">
                          {(fitAnalysis.matched_skills || []).map((skill) => <span key={skill} className="rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-800">{skill}</span>)}
                          {(fitAnalysis.skill_gaps || []).map((skill) => <span key={"gap-" + skill} className="rounded-full bg-rose-50 px-2.5 py-1 text-xs font-semibold text-rose-800">{skill}</span>)}
                        </div>
                      </div>
                      <div className="rounded-xl border border-ink-100 p-4">
                        <p className="text-xs font-semibold uppercase text-ink-500">Recruiter note</p>
                        <p className="mt-2 text-xs leading-5 text-ink-600">{fitAnalysis.note}</p>
                      </div>
                    </div>
                  )}
                </div>
                <ScorecardPanel
                  token={token}
                  applicationId={applications.find((item) => item.candidate_id === candidate.id && (fitJobId ? item.job_id === Number(fitJobId) : item.stage_name === "Interview"))?.id || applications.find((item) => item.candidate_id === candidate.id)?.id}
                  candidateName={candidate.first_name + " " + candidate.last_name}
                  apiRequest={apiRequest}
                  onNotice={setNotice}
                  onError={(requestError) => setError(errorText(requestError))}
                />
                <ApplicationEnhancements
                  token={token}
                  applications={applications}
                  candidateId={candidate.id}
                  apiRequest={apiRequest}
                  onNotice={setNotice}
                  onError={(requestError) => setError(errorText(requestError))}
                />\n                <RecruiterToolsPanel
                  token={token}
                  candidates={candidates}
                  applications={applications}
                  candidateId={candidate.id}
                  compact
                  canWrite={canWrite}
                  apiRequest={apiRequest}
                  onNotice={setNotice}
                  onError={(requestError) => setError(errorText(requestError))}
                />
                <InterviewPanel
                  token={token}
                  applications={applications.filter((item) => item.candidate_id === candidate.id)}
                  apiRequest={apiRequest}
                  onNotice={setNotice}
                  onError={(requestError) => setError(errorText(requestError))}
                />
              </section>;
            })()}
          </>}


          {view === "assistant" && <section className="grid gap-5">
            <div className="rounded-2xl border border-ink-100 bg-white p-5 shadow-sm">
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gold-700">AI recruiter copilot</p>
              <h2 className="mt-1 text-xl font-semibold">Evidence-first assistant</h2>
              <p className="mt-1 text-sm text-ink-500">Ask about a candidate, JD requirements, interviews, or communications. Answers are grounded in the stored JD, parsed resume, and submitted scorecards. The assistant does not move candidates or make hiring decisions.</p>
              <div className="mt-5 grid gap-3">
                <SelectField label="Candidate application" value={assistantApplicationId} onChange={(event) => { setAssistantApplicationId(event.target.value); setAssistantResult(null); }}>
                  <option value="">Choose an application</option>
                  {applications.map((item) => <option key={item.id} value={item.id}>{item.candidate_name || "Candidate"} — {item.job_title || "Role"}</option>)}
                </SelectField>
                <div className="flex flex-wrap gap-2">
                  {["Summarize this candidate against the JD.","Show missing required skills.","Create interview questions based on this resume and role.","Summarize all interview feedback.","Draft a screening email.","Explain why the resume does not satisfy this requirement."].map((item) => <button key={item} type="button" onClick={() => setAssistantQuestion(item)} className="rounded-full border border-ink-100 bg-white px-3 py-1.5 text-xs font-semibold text-ink-700 hover:bg-ink-50">{item}</button>)}
                </div>
                <textarea className={inputStyle + " min-h-24"} value={assistantQuestion} onChange={(event) => setAssistantQuestion(event.target.value)} />
                <button type="button" disabled={!assistantApplicationId || assistantLoading} onClick={askRecruiterAssistant} className={buttonPrimary}>{assistantLoading ? "Analyzing evidence…" : "Ask assistant"}</button>
              </div>
            </div>
            {assistantResult && <div className="grid gap-4">
              <div className="rounded-2xl border border-blue-100 bg-white p-5">
                <p className="text-xs font-semibold uppercase text-blue-700">{assistantResult.intent?.replaceAll("_", " ")}</p>
                <h3 className="mt-1 font-semibold">Assistant response</h3>
                <p className="mt-3 text-sm leading-6 text-ink-700">{assistantResult.summary}</p>
              </div>
              <div className="grid gap-4 lg:grid-cols-2">
                <div className="rounded-xl border border-ink-100 bg-white p-4"><h4 className="font-semibold">Required skills: evidence</h4><div className="mt-3 flex flex-wrap gap-2">{(assistantResult.matched_required_skills || []).map((skill) => <span key={skill} className="rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-800">{skill} · evidenced</span>)}{(assistantResult.missing_required_skills || []).map((skill) => <span key={skill} className="rounded-full bg-rose-50 px-2.5 py-1 text-xs font-semibold text-rose-800">{skill} · not evidenced</span>)}</div></div>
                <div className="rounded-xl border border-ink-100 bg-white p-4"><h4 className="font-semibold">Requirement explanation</h4><p className="mt-2 text-sm leading-6 text-ink-600">{assistantResult.requirement_explanation}</p></div>
              </div>
              <div className="rounded-xl border border-ink-100 bg-white p-4"><h4 className="font-semibold">Interview questions</h4><ol className="mt-3 grid gap-2 text-sm text-ink-700">{(assistantResult.interview_questions || []).map((item, index) => <li key={index} className="rounded-lg bg-ink-50 p-3">{index + 1}. {item}</li>)}</ol></div>
              <div className="grid gap-4 lg:grid-cols-2"><div className="rounded-xl border border-ink-100 bg-white p-4"><h4 className="font-semibold">Interview feedback</h4><p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-ink-600">{assistantResult.interview_feedback_summary}</p></div><div className="rounded-xl border border-ink-100 bg-white p-4"><h4 className="font-semibold">Screening email draft</h4><pre className="mt-3 whitespace-pre-wrap font-sans text-sm leading-6 text-ink-600">{assistantResult.screening_email}</pre></div></div>
              <div className="rounded-xl border border-gold-200 bg-[#fbf7ef] p-4"><h4 className="font-semibold">Evidence & sources</h4><div className="mt-3 flex flex-wrap gap-2">{(assistantResult.sources || []).map((source) => <span key={source.id} className="rounded-full border border-gold-200 bg-white px-3 py-1.5 text-xs font-semibold text-ink-700">{source.id} · {source.label}</span>)}</div><div className="mt-3 grid gap-1 text-xs text-ink-600">{(assistantResult.guardrails || []).map((item, index) => <p key={index}>• {item}</p>)}</div></div>
            </div>}
          </section>}

          {view === "emails" && <>
            <div className="mb-5 flex items-end justify-between gap-3"><div><p className="text-sm text-ink-500">Candidate communication audit</p><h2 className="mt-1 text-xl font-semibold">Email center</h2></div><button className={buttonSecondary} onClick={() => setView("dashboard")}>Back to dashboard</button></div>
            {emailsLoading && <div className="mb-4 rounded-xl border border-ink-100 bg-white p-5 text-sm text-ink-500">Loading email history…</div>}
            <div className="overflow-x-auto border-y border-ink-100 bg-white">
              <table className="w-full min-w-[850px] border-collapse text-left text-sm">
                <thead className="border-b border-ink-100 bg-[#fafaf8] text-[11px] uppercase text-ink-500"><tr><th className="px-4 py-3">Candidate</th><th className="px-4 py-3">Event</th><th className="px-4 py-3">Recipient</th><th className="px-4 py-3">Status</th><th className="px-4 py-3">Sent</th><th className="px-4 py-3">Error</th></tr></thead>
                <tbody className="divide-y divide-ink-50">
                  {emails.map((email) => <tr key={email.id} className="hover:bg-[#fcfcfa]"><td className="px-4 py-3"><button className="font-semibold hover:underline" onClick={() => { if (email.application_id) { const application = applications.find((item) => item.id === email.application_id); if (application) { setSelectedCandidate(application.candidate_id); setView("candidates"); } } }}>{email.candidate_name}</button><p className="text-xs text-ink-500">{email.job_title || "—"}</p></td><td className="px-4 py-3 text-xs">{email.subject}</td><td className="px-4 py-3 text-xs text-ink-600">{email.recipient}</td><td className="px-4 py-3 text-xs font-semibold">{email.status}</td><td className="px-4 py-3 text-xs text-ink-500">{email.sent_at ? new Date(email.sent_at).toLocaleString() : "—"}</td><td className="max-w-72 px-4 py-3 text-xs text-rose-700">{email.error_message || "—"}</td></tr>)}
                </tbody>
              </table>
              {!emails.length && <EmptyState title="No email events yet" detail="Application and pipeline notifications will appear here." />}
            </div>
          </>}
          {view === "tools" && <RecruiterToolsPanel token={token} candidates={candidates} applications={applications} canWrite={canWrite} apiRequest={apiRequest} onNotice={setNotice} onError={(requestError) => setError(errorText(requestError))} />}
          {view === "automation" && <AutomationPanel token={token} apiRequest={apiRequest} onNotice={setNotice} onError={(requestError) => setError(errorText(requestError))} />}\n          {view === "resume" && <section className="-mx-4 -my-6 sm:-mx-7 sm:-my-8"><ResumeLab theme={theme} onToggleTheme={toggleTheme} /></section>}
          </main>
        </Suspense>
      </div>

      {interviewDialogApplication && <div className="fixed inset-0 z-50 grid place-items-center bg-ink-950/50 p-4" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setInterviewDialogApplication(null); }}>
        <form onSubmit={scheduleInterviewAndChangeStage} className="w-full max-w-lg bg-white p-5 shadow-xl">
          <div className="mb-5 flex items-start justify-between gap-3">
            <div><p className="text-xs font-semibold uppercase tracking-[0.16em] text-blue-700">Interview scheduling</p><h2 className="mt-1 text-lg font-semibold">{interviewDialogApplication.candidate.first_name} {interviewDialogApplication.candidate.last_name}</h2><p className="text-sm text-ink-500">{interviewDialogApplication.job_title} · {interviewDialogApplication.candidate.email}</p></div>
            <button type="button" aria-label="Close dialog" onClick={() => setInterviewDialogApplication(null)}>×</button>
          </div>
          <div className="grid gap-4">
            <Field label="Interview date & time" type="datetime-local" required value={interviewForm.starts_at} onChange={(event) => setInterviewForm({ ...interviewForm, starts_at: event.target.value })} />
            <SelectField label="Interview mode" value={interviewForm.mode} onChange={(event) => setInterviewForm({ ...interviewForm, mode: event.target.value, location: "", meeting_url: "" })}>
              <option value="online">Online</option>
              <option value="offline">Offline / On-site</option>
            </SelectField>
            <Field label="Duration (minutes)" type="number" min="15" max="480" value={interviewForm.duration_minutes} onChange={(event) => setInterviewForm({ ...interviewForm, duration_minutes: event.target.value })} />
            {interviewForm.mode === "online" ? (
              <Field label="Meeting link" required placeholder="https://teams.microsoft.com/..." value={interviewForm.meeting_url} onChange={(event) => setInterviewForm({ ...interviewForm, meeting_url: event.target.value })} />
            ) : (
              <Field label="Interview location / address" required placeholder="Blupace Tech office, Hyderabad..." value={interviewForm.location} onChange={(event) => setInterviewForm({ ...interviewForm, location: event.target.value })} />
            )}
            <div className="rounded-xl border border-blue-100 bg-blue-50 p-4 text-sm text-blue-900">
              The candidate will be moved to <strong>Interview</strong> and an email will be sent to <strong>{interviewDialogApplication.candidate.email}</strong>. It will include the date, time, duration and {interviewModeLabel(interviewForm.mode).toLowerCase()} details.
            </div>
          </div>
          <div className="mt-6 flex justify-end gap-2"><button type="button" className={buttonSecondary} onClick={() => setInterviewDialogApplication(null)}>Cancel</button><button type="submit" className={buttonPrimary}>Schedule & send email</button></div>
        </form>
      </div>}

      <AtsChatbot
        token={token}
        apiRequest={apiRequest}
        onError={(requestError) => setError(errorText(requestError))}
      />

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
      </div>}
    </div>
  );
}
