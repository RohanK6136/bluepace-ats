import { lazy, Suspense, useEffect, useRef, useState } from "react";
import axios from "axios";
import AtsChatbot from "./AtsChatbot.jsx";
const ResumeLab = lazy(() => import("./App.jsx"));
const CandidatePortal = lazy(() => import("./CandidatePortal.jsx"));
const ScorecardPanel = lazy(() => import("./ScorecardPanel.jsx"));
const ApplicationEnhancements = lazy(() => import("./ApplicationEnhancements.jsx"));
const RecruiterToolsPanel = lazy(() => import("./RecruiterToolsPanel.jsx"));
const InterviewPanel = lazy(() => import("./InterviewPanel.jsx"));
const CandidateMergeCenter = lazy(() => import("./CandidateMergeCenter.jsx"));
const InterviewManagement2 = lazy(() => import("./InterviewManagement2.jsx"));
const OfferManagement = lazy(() => import("./OfferManagement.jsx"));
const CandidateComparisonPanel = lazy(() => import("./CandidateComparisonPanel.jsx"));
const AutomationPanel = lazy(() => import("./AutomationPanel.jsx"));
const AIHiringStudio = lazy(() => import("./AIHiringStudio.jsx"));
const JDApplicantMatch = lazy(() => import("./JDApplicantMatch.jsx"));
const HiringWorkflowPanel = lazy(() => import("./HiringWorkflowPanel.jsx"));

const MAX_DOCUMENT_SIZE_BYTES = 5 * 1024 * 1024;
const MAX_DOCUMENT_SIZE_LABEL = "5 MB";

const configuredApiUrl = import.meta.env.VITE_API_URL?.trim();
const API_URL = (
  configuredApiUrl ||
  (import.meta.env.PROD
    ? "https://bluepace-ats-11.onrender.com"
    : "http://localhost:8000")
).replace(/\/+$/, "");
const REQUEST_TIMEOUT_MS = 90_000;
const AUTH_TIMEOUT_MS = 120_000;
const RETRY_DELAYS_MS = [1_000, 2_000, 4_000];
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
const inputStyle = "w-full rounded-md border border-ink-100 bg-white px-3 py-2.5 text-sm text-ink-900 outline-hidden transition placeholder:text-ink-400 focus:border-gold-500 focus:ring-2 focus:ring-gold-100";

function ThemeToggle({ theme, onToggle }) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className="inline-flex h-10 items-center gap-2 rounded-md border border-ink-100 bg-white px-3 text-sm font-semibold text-ink-700 shadow-xs hover:bg-ink-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
      aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
      title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
    >
      <svg
        aria-hidden="true"
        className="h-4 w-4 shrink-0"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        {theme === "dark" ? (
          <>
            <circle cx="12" cy="12" r="4" />
            <path d="M12 2v2M12 20v2M4.93 4.93l1.42 1.42m11.3 11.3 1.42 1.42M2 12h2m16 0h2M4.93 19.07l1.42-1.42m11.3-11.3 1.42-1.42" />
          </>
        ) : (
          <path d="M20.7 15.3A8.6 8.6 0 0 1 8.7 3.3 8.8 8.8 0 1 0 20.7 15.3Z" />
        )}
      </svg>
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
let apiReadyInFlight = null;

function ensureApiReady() {
  if (apiReadyInFlight) return apiReadyInFlight;

  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), 60_000);

  apiReadyInFlight = fetch(`${API_URL}/healthz`, {
    method: "GET",
    cache: "no-store",
    signal: controller.signal,
  })
    .then((response) => {
      if (!response.ok) throw new Error(`ATS API health check returned HTTP ${response.status}.`);
      return response;
    })
    .finally(() => {
      window.clearTimeout(timeoutId);
      apiReadyInFlight = null;
    });

  return apiReadyInFlight;
}

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
  const isAuthRequest = /^\/auth\/(token|register|logout)$/.test(path);
  const requestTimeout = options.timeout ?? (isAuthRequest ? AUTH_TIMEOUT_MS : REQUEST_TIMEOUT_MS);
  for (let attempt = 0; ; attempt += 1) {
    try {
      return await axios.request({
        baseURL: API_URL,
        method,
        url: path,
        timeout: requestTimeout,
        ...options,
        headers: {
          ...(requestToken ? { Authorization: `Bearer ${requestToken}` } : {}),
          ...options.headers,
        },
      });
    } catch (error) {
      if (isAuthRequest) throw error;
      const canRefresh = Boolean(requestToken)
        && !refreshed
        && error.response?.status === 401
        && !path.startsWith("/auth/token")
        && !path.startsWith("/auth/refresh")
        && !path.startsWith("/auth/logout")
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
  const [user, setUser] = useState(() => {
    try {
      const saved = sessionStorage.getItem("bluepace_user");
      return saved ? JSON.parse(saved) : null;
    } catch {
      return null;
    }
  });
  const [authLoading, setAuthLoading] = useState(false);
  const [theme, setTheme] = useState(() => localStorage.getItem("bluepace_theme") || "light");
  const [accessMode, setAccessMode] = useState(() => (
    new URLSearchParams(window.location.search).get("mode") === "admin" ? "admin" : "public"
  ));
  const [publicJobs, setPublicJobs] = useState([]);
  const [publicLoading, setPublicLoading] = useState(false);
  const [publicApplying, setPublicApplying] = useState(false);
  const [publicApplyJob, setPublicApplyJob] = useState(null);
  const [publicResume, setPublicResume] = useState(null);
  const publicResumeInputRef = useRef(null);
  const [publicForm, setPublicForm] = useState({ full_name: "", email: "", phone: "" });
  const [publicError, setPublicError] = useState("");
  const [publicSuccess, setPublicSuccess] = useState("");
  const [publicFilters, setPublicFilters] = useState({ search: "", department: "", location: "", work_mode: "" });
    const [authForm, setAuthForm] = useState({ email: "", password: "" });
  const [authError, setAuthError] = useState("");
  const [view, setView] = useState("dashboard");
  const [moreOpen, setMoreOpen] = useState(false);
  const [jobs, setJobs] = useState([]);
  const [candidates, setCandidates] = useState([]);
  const [applications, setApplications] = useState([]);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [dashboardData, setDashboardData] = useState(null);
  const [dashboardLoading, setDashboardLoading] = useState(false);
  const [demoPopulationLoading, setDemoPopulationLoading] = useState(false);
  const [candidateActivity, setCandidateActivity] = useState(null);
  const [candidateCollaboration, setCandidateCollaboration] = useState(null);
  const [collabComment, setCollabComment] = useState("");
  const [collabTagName, setCollabTagName] = useState("");
  const [collabTagColor, setCollabTagColor] = useState("#1769d3");
  const [semanticQuery, setSemanticQuery] = useState("");
  const [semanticResults, setSemanticResults] = useState([]);
  const [candidateFilters, setCandidateFilters] = useState({
    search: "", skill: "", source: "", location: "", tags: "", stage_name: "",
    min_experience_years: "", max_experience_years: "", notice_period: "", education: "",
    job_history: "", availability: "", preferred_location: "", work_authorization: "",
    has_applied_job_id: "",
  });
  const [portalToken] = useState(() => new URLSearchParams(window.location.search).get("portal") || "");
  const [portalLink, setPortalLink] = useState("");
  const [portalLinkLoading, setPortalLinkLoading] = useState(false);
  const [jobFormOpen, setJobFormOpen] = useState(false);
  const [jobEntryMode, setJobEntryMode] = useState("manual");
  const [jobDocumentFile, setJobDocumentFile] = useState(null);
  const [jobLinkInput, setJobLinkInput] = useState("");
  const [editingJob, setEditingJob] = useState(null);
  const [jobSourceRefreshing, setJobSourceRefreshing] = useState(false);
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

  const canWrite = user && ["admin", "recruiter"].includes(user.role);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    document.documentElement.style.colorScheme = theme;
    localStorage.setItem("bluepace_theme", theme);
  }, [theme]);

  const toggleTheme = () => setTheme((current) => current === "dark" ? "light" : "dark");

  useEffect(() => {
    if (token) return undefined;
    // Keep the login screen's ATS connection warm. The first request may wake a
    // sleeping Render instance; subsequent checks reuse this connection.
    void ensureApiReady().catch(() => {});
    const intervalId = window.setInterval(() => {
      void ensureApiReady().catch(() => {});
    }, 10 * 60 * 1000);
    return () => window.clearInterval(intervalId);
  }, [token]);

  useEffect(() => {
    if (token || accessMode !== "public") {
      setPublicLoading(false);
      return undefined;
    }

    let active = true;
    setPublicLoading(true);
    setPublicError("");

    // Wait briefly before requesting results while the candidate is typing.
    const requestTimer = window.setTimeout(() => {
      const params = Object.fromEntries(Object.entries(publicFilters).filter(([, value]) => value));
      apiRequest(null, "get", "/public/jobs", { params })
        .then((response) => {
          if (active) setPublicJobs(Array.isArray(response.data) ? response.data : []);
        })
        .catch((requestError) => {
          if (active) setPublicError(errorText(requestError));
        })
        .finally(() => {
          if (active) setPublicLoading(false);
        });
    }, publicFilters.search.trim() ? 300 : 0);

    return () => {
      active = false;
      window.clearTimeout(requestTimer);
    };
  }, [token, accessMode, publicFilters.search, publicFilters.department, publicFilters.location, publicFilters.work_mode]);

  useEffect(() => {
    if (!token) return undefined;
    let active = true;
    async function loadWorkspace() {
      setLoading(true);
      try {
        const [userResponse, jobsResponse] = await Promise.all([
          user
            ? Promise.resolve({ data: user })
            : apiRequest(token, "get", "/auth/me"),
          apiRequest(token, "get", "/jobs", { params: { limit: 100 } }),
        ]);
        if (!active) return;
        const resolvedUser = userResponse.data;
        setUser(resolvedUser);
        sessionStorage.setItem("bluepace_user", JSON.stringify(resolvedUser));
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
    const needsCandidates = new Set(["candidates", "merge-center"]);
    const needsApplications = new Set(["compare", "interviews-2", "offers", "hiring-workflow"]);
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
        if (needsApplications.has(view) && (!applications.length || view === "hiring-workflow")) {
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
    const needsCandidates = new Set(["candidates", "merge-center"]);
    const needsApplications = new Set(["compare", "interviews-2", "offers"]);
    const requests = [];
    requests.push(apiRequest(token, "get", "/jobs", { params: { limit: 100 } }));
    requests.push(
      needsCandidates.has(view)
        ? apiRequest(token, "get", "/candidates", { params: { limit: 100 } })
        : Promise.resolve(null),
    );
    requests.push(
      needsApplications.has(view)
        ? apiRequest(token, "get", "/applications", { params: { limit: 100 } })
        : Promise.resolve(null),
    );
    const [jobsResponse, candidateResponse, applicationResponse] = await Promise.all(requests);
    setJobs(jobsResponse.data);
    if (candidateResponse) setCandidates(candidateResponse.data);
    if (applicationResponse) setApplications(applicationResponse.data);
  }

  async function populateDemoData() {
    if (!token || demoPopulationLoading) return;
    const confirmed = window.confirm(
      "Add synthetic demo records to this ATS organization? Existing records will be preserved. Demo jobs will remain draft, automation examples will stay disabled, and no emails will be sent."
    );
    if (!confirmed) return;

    setDemoPopulationLoading(true);
    setError("");
    setNotice("");
    try {
      const seedResponse = await apiRequest(token, "post", "/demo-data/populate", { data: {} });
      const [jobsResponse, candidatesResponse, applicationsResponse, dashboardResponse] = await Promise.all([
        apiRequest(token, "get", "/jobs", { params: { limit: 100 } }),
        apiRequest(token, "get", "/candidates", { params: { limit: 100 } }),
        apiRequest(token, "get", "/applications", { params: { limit: 100 } }),
        apiRequest(token, "get", "/dashboard"),
      ]);
      setJobs(jobsResponse.data || []);
      setCandidates(candidatesResponse.data || []);
      setApplications(applicationsResponse.data || []);
      setDashboardData(dashboardResponse.data || null);
      setView("dashboard");

      const counts = seedResponse.data?.created || {};
      if (seedResponse.data?.already_populated) {
        setNotice("Demo data is already populated. No duplicate records were added.");
      } else {
        setNotice(
          `Demo data added: ${counts.jobs || 0} jobs, ${counts.candidates || 0} candidates, ${counts.applications || 0} applications, ${counts.interviews || 0} interviews, ${counts.offers || 0} offers, and related workflow examples. No emails were sent; demo jobs remain draft.`
        );
      }
    } catch (requestError) {
      setError(errorText(requestError));
    } finally {
      setDemoPopulationLoading(false);
    }
  }

  async function signIn(event) {
    event.preventDefault();
    setAuthError("");
    setAuthLoading(true);
    try {
      // Do the readiness check before credential verification. If the login page
      // has already warmed the API, this resolves immediately. If Render has
      // spun down the Free instance, this makes the wake-up happen once instead
      // of racing the credential request against the cold start.
      await ensureApiReady();

      const credentials = new URLSearchParams();
      credentials.set("username", authForm.email);
      credentials.set("password", authForm.password);

      let response;
      try {
        response = await apiRequest(null, "post", "/auth/token", {
          data: credentials,
          timeout: AUTH_TIMEOUT_MS,
          headers: { "Content-Type": "application/x-www-form-urlencoded" },
        });
      } catch (firstError) {
        // The API preflight normally removes the cold-start race. Keep one retry
        // for transient gateway failures so a brief Render/network hiccup does
        // not force the recruiter to submit the form again.
        const transientAuthFailure = !firstError.response
          || [502, 503, 504].includes(firstError.response.status)
          || ["ECONNABORTED", "ETIMEDOUT"].includes(firstError.code)
          || firstError.name === "AbortError";
        if (!transientAuthFailure) throw firstError;
        await ensureApiReady();
        response = await apiRequest(null, "post", "/auth/token", {
          data: credentials,
          timeout: AUTH_TIMEOUT_MS,
          headers: { "Content-Type": "application/x-www-form-urlencoded" },
        });
      }

      sessionStorage.setItem("bluepace_token", response.data.access_token);
      if (response.data.user) {
        sessionStorage.setItem("bluepace_user", JSON.stringify(response.data.user));
        setUser(response.data.user);
      }
      setToken(response.data.access_token);
    } catch (authRequestError) {
      setAuthError(errorText(authRequestError));
    } finally {
      setAuthLoading(false);
    }
  }

  function signOut() {
    const currentToken = token;
    // Clear local auth state first. Revocation is best-effort and must never hold
    // the user on the workspace while a sleeping/slow API is responding.
    sessionStorage.removeItem("bluepace_token");
    sessionStorage.removeItem("bluepace_user");
    setToken(null);
    setUser(null);
    setJobs([]);
    setCandidates([]);
    setApplications([]);
    setNotice("");
    setError("");

    if (currentToken) {
      void fetch(`${API_URL}/auth/logout`, {
        method: "POST",
        headers: { Authorization: `Bearer ${currentToken}` },
        keepalive: true,
      }).catch(() => {});
    }
  }



  useEffect(() => {
    if (!token || view !== "dashboard") return undefined;
    let active = true;
    setDashboardLoading(true);
    apiRequest(token, "get", "/dashboard")
      .then(async (response) => {
        if (!active) return;
        setDashboardData(response.data);
        // Older backend deployments do not yet provide total_candidates. Fetch a
        // bounded fallback so the dashboard does not incorrectly report zero.
        if (response.data?.metrics?.total_candidates == null) {
          try {
            const candidateResponse = await apiRequest(token, "get", "/candidates", { params: { limit: 100 } });
            if (active) setCandidates(candidateResponse.data || []);
          } catch (candidateError) {
            if (active) setError(errorText(candidateError));
          }
        }
      })
      .catch((requestError) => { if (active) setError(errorText(requestError)); })
      .finally(() => { if (active) setDashboardLoading(false); });
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
    setJobEntryMode("manual");
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

  async function refreshEditingJobSource() {
    if (!editingJob?.id || !editingJob?.jd_analysis?.source_url) return;
    setJobSourceRefreshing(true);
    setError("");
    try {
      const response = await apiRequest(token, "post", `/jobs/${editingJob.id}/refresh-source`);
      setNotice("Job description and available metadata refreshed from the saved source URL.");
      await refreshWorkspace();
      resetJobForm(response.data);
    } catch (requestError) {
      setError(errorText(requestError));
    } finally {
      setJobSourceRefreshing(false);
    }
  }

  async function saveJob(event) {
    event.preventDefault();
    setError("");
    setNotice("");
    try {
      if (!editingJob && jobEntryMode === "link") {
        if (!jobLinkInput.trim()) {
          setError("Paste a public job URL or an [Title](URL) Markdown job link.");
          return;
        }
        const body = new FormData();
        body.append("url", jobLinkInput.trim());
        body.append("status_value", jobForm.status || "open");
        await apiRequest(token, "post", "/jobs/from-url", { data: body });
        setNotice("Job posting imported. BluePace extracted the description and available job details automatically.");
      } else if (!editingJob && jobEntryMode === "upload") {
        if (!jobDocumentFile) {
          setError("Select a PDF or DOCX job description.");
          return;
        }
        const body = new FormData();
        body.append("file", jobDocumentFile);
        body.append("status_value", jobForm.status || "open");
        await apiRequest(token, "post", "/jobs/from-document", { data: body });
        setNotice("Job document extracted. BluePace created the job and prepared its matching criteria automatically.");
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
          setNotice("Job created successfully.");
        }
      }
      setJobFormOpen(false);
      setJobDocumentFile(null);
      setJobLinkInput("");
      setJobEntryMode("manual");
      await refreshWorkspace();
      if (view === "dashboard") {
        setView("dashboard");
        const refreshedDashboard = await apiRequest(token, "get", "/dashboard");
        setDashboardData(refreshedDashboard.data || null);
      }
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

  async function semanticSearch(event) {
    event?.preventDefault();
    if (!token || !semanticQuery.trim()) return;
    setLoading(true);
    setError("");
    try {
      const response = await apiRequest(token, "get", "/candidates/semantic-search", { params: { q: semanticQuery.trim(), limit: 10 } });
      setSemanticResults(response.data || []);
    } catch (requestError) {
      setError(errorText(requestError));
    } finally {
      setLoading(false);
    }
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

  async function submitPublicApplication(event) {
    event.preventDefault();
    setPublicError("");
    setPublicSuccess("");

    if (!publicApplyJob || !publicResume) {
      setPublicError("Choose a PDF or DOCX resume to continue.");
      return;
    }
    if (!/\\.(pdf|docx)$/i.test(publicResume.name)) {
      setPublicError("Resume must be a PDF or DOCX file.");
      return;
    }
    if (publicResume.size > MAX_DOCUMENT_SIZE_BYTES) {
      setPublicError(`Resume must be ${MAX_DOCUMENT_SIZE_LABEL} or smaller.`);
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

    setPublicApplying(true);
    try {
      const response = await apiRequest(null, "post", `/public/jobs/${publicApplyJob.id}/apply`, {
        data: body,
      });
      setPublicSuccess(response.data?.message || "Application submitted successfully. A confirmation email has been queued to your application email.");
      setPublicResume(null);
      if (publicResumeInputRef.current) publicResumeInputRef.current.value = "";
      setPublicForm({ full_name: "", email: "", phone: "" });
    } catch (requestError) {
      setPublicError(errorText(requestError));
    } finally {
      setPublicApplying(false);
    }
  }

  function handlePublicResumeChange(event) {
    const file = event.currentTarget.files?.[0] || null;
    setPublicError("");

    if (!file) {
      setPublicResume(null);
      return;
    }
    if (!/\\.(pdf|docx)$/i.test(file.name)) {
      setPublicResume(null);
      event.currentTarget.value = "";
      setPublicError("Resume must be a PDF or DOCX file.");
      return;
    }
    if (file.size > MAX_DOCUMENT_SIZE_BYTES) {
      setPublicResume(null);
      event.currentTarget.value = "";
      setPublicError(`Resume must be ${MAX_DOCUMENT_SIZE_LABEL} or smaller. Please choose a smaller file.`);
      return;
    }

    setPublicResume(file);
  }

  function closePublicApplication() {
    setPublicApplyJob(null);
    setPublicResume(null);
    if (publicResumeInputRef.current) publicResumeInputRef.current.value = "";
    setPublicForm({ full_name: "", email: "", phone: "" });
    setPublicError("");
    setPublicSuccess("");
  }

  function switchAccessMode(mode) {
    setAccessMode(mode);
    window.history.replaceState({}, "", mode === "admin" ? "?mode=admin" : window.location.pathname);
    setAuthError("");
  }

  if (portalToken) return <CandidatePortal token={portalToken} theme={theme} onToggleTheme={toggleTheme} />;

  if (!token && accessMode === "public") {
    return (
      <main className="bp-public-shell min-h-screen text-ink-900">
        <header className="bp-public-header">
          <div className="mx-auto flex max-w-7xl items-center justify-between gap-5 px-5 py-4">
            <a href="/" className="bp-wordmark flex items-center gap-3 no-underline" aria-label="BluePace Careers home">
              <span className="bp-logo-mark">BP</span>
              <span>
                <span className="block text-[15px] font-bold tracking-tight">BluePace</span>
                <span className="block text-[10px] font-medium tracking-wide">Careers</span>
              </span>
            </a>
            <nav className="flex items-center gap-6 text-sm font-medium" aria-label="Careers navigation">
              <a className="bp-public-nav-link" href="#jobs">Open roles</a>
              <button type="button" className="bp-public-signin" onClick={() => switchAccessMode("admin")}>Recruiter sign in</button>
            </nav>
          </div>
        </header>

        <section className="bp-careers-hero">
          <div className="bp-careers-hero-inner mx-auto max-w-7xl px-5">
            <p className="bp-careers-eyebrow">CAREERS AT BLUEPACE</p>
            <h1>Find your next opportunity.</h1>
            <p className="bp-careers-intro">Explore current openings and apply directly. Find a role that fits your skills and experience.</p>
            <form
              className="bp-template-search"
              onSubmit={(event) => { event.preventDefault(); document.getElementById("jobs")?.scrollIntoView({ behavior: "smooth" }); }}
            >
              <label className="sr-only" htmlFor="public-role-search">Search open roles</label>
              <input
                id="public-role-search"
                placeholder="Search by job title, skill or department"
                value={publicFilters.search}
                onChange={(event) => setPublicFilters({ ...publicFilters, search: event.target.value })}
              />
              <label className="sr-only" htmlFor="public-work-mode">Work mode</label>
              <select id="public-work-mode" value={publicFilters.work_mode} onChange={(event) => setPublicFilters({ ...publicFilters, work_mode: event.target.value })}>
                <option value="">All work modes</option>
                <option value="remote">Remote</option>
                <option value="hybrid">Hybrid</option>
                <option value="onsite">On-site</option>
              </select>
              <button type="submit">Search roles</button>
            </form>
          </div>
        </section>

        <section id="jobs" className="bp-public-jobs mx-auto max-w-7xl px-5 py-12">
            <div className="bp-public-jobs-heading flex items-end justify-between gap-3">
              <div><p className="bp-section-eyebrow">OPPORTUNITIES</p><h2 className="mt-1 text-2xl font-semibold">Open roles</h2><p className="mt-2 text-sm text-ink-500">Explore our current opportunities.</p></div>
              {publicJobs.length > 0 && <span className="text-sm text-ink-500">{publicJobs.length} position(s)</span>}
            </div>

            {publicLoading && !publicApplyJob && (
              <div className="mt-5 space-y-3" aria-hidden="true">
                {[0, 1, 2].map((i) => (
                  <div key={i} className="bp-skeleton-row">
                    <div className="bp-skeleton" style={{ width: 44, height: 44, borderRadius: 12 }} />
                    <div className="flex-1 space-y-2">
                      <div className="bp-skeleton" style={{ height: 14, width: "38%" }} />
                      <div className="bp-skeleton" style={{ height: 11, width: "62%" }} />
                    </div>
                    <div className="bp-skeleton" style={{ height: 32, width: 104, borderRadius: 9 }} />
                  </div>
                ))}
              </div>
            )}

            {publicError && !publicApplyJob && (
              <div className="mt-5 rounded-xl border border-rose-200 bg-rose-50 p-5 text-sm text-rose-700">
                {publicError}
              </div>
            )}

            {!publicLoading && !publicError && publicJobs.length === 0 && (
              <div className="mt-5 rounded-xl border border-ink-100 bg-white p-10 text-center">
                {Object.values(publicFilters).some((value) => String(value).trim()) ? (
                  <>
                    <p className="font-medium">No roles match your search.</p>
                    <p className="mt-1 text-sm text-ink-500">Try a different job title, skill or work mode.</p>
                    <button
                      type="button"
                      className="mt-4 text-sm font-semibold text-blue-700 hover:underline"
                      onClick={() => setPublicFilters({ search: "", department: "", location: "", work_mode: "" })}
                    >
                      Clear search
                    </button>
                  </>
                ) : (
                  <>
                    <p className="font-medium">No open positions are available right now.</p>
                    <p className="mt-1 text-sm text-ink-500">Please check again later.</p>
                  </>
                )}
              </div>
            )}

            <div className="bp-public-jobs-grid mt-7 grid gap-4 md:grid-cols-2">
              {publicJobs.map((job) => (
                <article key={job.id} className="bp-job-card rounded-xl border border-ink-100 bg-white p-5">
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
                  <p className="mt-4 line-clamp-3 whitespace-pre-line text-sm leading-6 text-ink-600">{job.description}</p>
                  {job.required_skills?.length > 0 && (
                    <div className="mt-4 flex flex-wrap gap-2">
                      {job.required_skills.slice(0, 4).map((skill) => (
                        <span key={skill} className="bp-job-skill rounded-md border border-ink-100 bg-white px-2 py-1 text-[11px] text-ink-600">{skill}</span>
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
                  <p className="bp-section-eyebrow">APPLICATION</p>
                  <h2 className="mt-1 text-xl font-semibold">{publicApplyJob.title}</h2>
                </div>
                <button className="text-xl text-ink-400 hover:text-ink-800" onClick={closePublicApplication} aria-label="Close">×</button>
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
                    ref={publicResumeInputRef}
                    onChange={handlePublicResumeChange}
                    className="rounded-md border border-ink-100 bg-white px-3 py-2.5 text-sm"
                  />
                  <span className="text-[11px] font-normal text-ink-400">PDF or DOCX, up to {MAX_DOCUMENT_SIZE_LABEL}.</span>
                </label>

                {publicError && <p role="alert" className="text-sm text-rose-700">{publicError}</p>}
                {publicSuccess && <p role="status" className="text-sm text-emerald-700">{publicSuccess}</p>}

                <div className="mt-2 flex gap-3">
                  <button type="button" className={`${buttonSecondary} flex-1`} onClick={closePublicApplication}>
                    Cancel
                  </button>
                  <button type="submit" disabled={publicApplying} className={`${buttonPrimary} flex-1`}>
                    {publicApplying ? "Submitting…" : "Submit Application"}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}

        <footer className="bp-public-footer">
          <div className="mx-auto flex max-w-7xl flex-col gap-3 px-5 py-6 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-sm font-semibold">BluePace <span>Careers</span></p>
            <a href="mailto:hello@blupacetech.com" className="text-sm">hello@blupacetech.com</a>
            <p className="text-xs">© BluePace Tech</p>
          </div>
        </footer>
      </main>
    );
  }

  if (!token) {
    return (
      <main className="bp-login-shell flex min-h-screen items-center justify-center bg-[#f3f4f1] px-5 py-12 text-ink-900">
        <section className="w-full max-w-md">
          <div className="mb-8 flex items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <div className="bp-logo-mark grid h-11 w-11 place-items-center rounded-md bg-ink-950 text-sm font-bold text-gold-300">BP</div>
              <div>
                <p className="font-semibold tracking-tight">blupace<span className="text-orange-500">.</span>tech</p>
                
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
          <p className="mt-1 text-sm text-ink-500">Sign in with your organisation-issued recruiting credentials.</p>
          <div className="mt-5 rounded-lg border border-[#e7d6ac] bg-[#fbf6e9] p-4">
            <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-[#806020]">New workspace</p>
            <p className="mt-1 text-sm font-semibold text-ink-950">JD Standardizer & Applicant Match</p>
            <p className="mt-1 text-xs leading-5 text-ink-700">Standardize job descriptions, build reviewable assessment rubrics, and compare resumes against job-related evidence.</p>
          </div>
          <form
            onSubmit={signIn}
            className="mt-7 grid gap-4"
          >
            <Field label="Work email" type="email" autoComplete="email" required value={authForm.email} onChange={(event) => setAuthForm({ ...authForm, email: event.target.value })} />
            <Field label="Password" type="password" autoComplete="current-password" required value={authForm.password} onChange={(event) => setAuthForm({ ...authForm, password: event.target.value })} />
            {authError && <p role="alert" className="text-sm text-rose-700">{authError}</p>}
            <button
              className={`${buttonPrimary} mt-1 w-full py-3`}
              type="submit"
              disabled={authLoading}
              aria-busy={authLoading}
            >
              {authLoading ? "Signing in…" : "Sign in"}
            </button>
          </form>
        </section>
      </main>
    );
  }

  // AI Hiring Studio is a primary workflow, not a hidden advanced tool.
  const navItems = [
    { id: "dashboard", label: "Dashboard" },
    { id: "jobs", label: "Jobs", count: jobs.filter((job) => job.status !== "archived").length },
    { id: "candidates", label: "Candidates", count: candidates.length },
    { id: "hiring-workflow", label: "Hiring Workflow" },
    { id: "interviews-2", label: "Interviews" },
    { id: "ai-studio", label: "AI Hiring Studio" },
    { id: "jd-match", label: "JD & Applicant Match" },
  ];
  const secondaryNavItems = [
    { id: "compare", label: "Compare candidates" },
    { id: "offers", label: "Offers" },
    { id: "resume", label: "Resume Lab" },
    { id: "matching", label: "AI Match" },
    { id: "assistant", label: "AI Assistant" },
    { id: "merge-center", label: "Merge Center" },
    { id: "automation", label: "Automation" },
  ];

  return (
    <div className="bp-admin-shell min-h-screen bg-[#f3f4f1] text-ink-900">
      <a className="bp-skip-link" href="#ats-workspace-content">Skip to main content</a>
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-60 flex-col overflow-y-auto bg-ink-950 text-white lg:flex">
        <div className="flex h-[72px] items-center gap-3 border-b border-white/10 px-5">
          <div className="bp-logo-mark grid h-9 w-9 place-items-center rounded-md bg-gold-500 text-xs font-bold text-ink-950">BP</div>
          <div>
            <p className="text-sm font-semibold tracking-tight">blupace<span className="text-orange-400">.</span>tech</p>
            
          </div>
        </div>
        <nav className="grid gap-0.5 px-3 py-4" aria-label="Workspace">
          <p className="px-3 pb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-ink-400">Workspace</p>
          {navItems.map((item) => (
            <button key={item.id} aria-current={view === item.id ? "page" : undefined} onClick={() => { setView(item.id); setError(""); setMoreOpen(false); }} className={`flex min-h-9 items-center justify-between rounded-md px-3 py-2 text-left text-sm transition ${view === item.id ? "bg-white/10 text-white" : "text-ink-100 hover:bg-white/5 hover:text-white"}`}>
              <span>{item.label}</span>
              {item.count !== undefined && <span className="text-xs text-ink-400">{item.count}</span>}
            </button>
          ))}
          <button type="button" onClick={() => setMoreOpen((open) => !open)} aria-expanded={moreOpen} className="mt-2 flex min-h-9 items-center justify-between rounded-md px-3 py-2 text-left text-sm text-ink-100 hover:bg-white/5 hover:text-white">
            <span>More</span><span aria-hidden="true">{moreOpen ? "−" : "+"}</span>
          </button>
          {moreOpen && <div className="mt-0.5 grid gap-0.5 border-l border-white/10 pl-2">
            {secondaryNavItems.map((item) => (
              <button key={item.id} aria-current={view === item.id ? "page" : undefined} onClick={() => { setView(item.id); setError(""); }} className={`flex min-h-9 items-center justify-between rounded-md px-3 py-2 text-left text-sm transition ${view === item.id ? "bg-white/10 text-white" : "text-ink-300 hover:bg-white/5 hover:text-white"}`}>
                <span>{item.label}</span>
                {item.count !== undefined && <span className="text-xs text-ink-400">{item.count}</span>}
              </button>
            ))}
          </div>}
        </nav>
        <div className="sticky bottom-0 mt-auto border-t border-white/10 bg-ink-950 px-5 py-4">
          <p className="truncate text-sm font-medium">{user?.full_name}</p>
          <p className="mt-0.5 text-xs capitalize text-ink-400">{user?.role?.replaceAll("_", " ")}</p>
          <button onClick={signOut} className="mt-4 text-xs font-medium text-ink-300 hover:text-white">Sign out</button>
        </div>
      </aside>

      <div className="ats-page-shell lg:pl-60">
        <header className="ats-workspace-header sticky top-0 z-20 min-h-[72px] border-b border-ink-100 bg-white/95 backdrop-blur-sm">
          <div className="ats-workspace-header-inner">
            <div>
              <p className="text-xs font-medium text-ink-500">{user?.email}</p>
              <h1 className="text-lg font-semibold">{navItems.find((item) => item.id === view)?.label || secondaryNavItems.find((item) => item.id === view)?.label}</h1>
            </div>
            <div className="ats-workspace-header-actions flex items-center gap-2">
              <button type="button" className={buttonPrimary} onClick={() => { setView("ai-studio"); setMoreOpen(false); setError(""); setNotice(""); }}>
                AI Hiring Studio
              </button>
              {view === "jobs" && canWrite && <button className={buttonPrimary} onClick={() => resetJobForm()}>New job</button>}
              {view === "candidates" && canWrite && <button className={buttonPrimary} onClick={() => setCandidateFormOpen(true)}>Add candidate</button>}
              <ThemeToggle theme={theme} onToggle={toggleTheme} />
              <button className={`${buttonSecondary} lg:hidden`} onClick={signOut}>Sign out</button>
            </div>
            <nav className="ats-mobile-nav flex w-full gap-1 overflow-x-auto pb-0.5 lg:hidden" aria-label="Workspace">
              {navItems.map((item) => <button key={item.id} type="button" aria-current={view === item.id ? "page" : undefined} onClick={() => { setView(item.id); setMoreOpen(false); setError(""); }} className={`whitespace-nowrap rounded-md px-3 py-2 text-sm ${view === item.id ? "bg-ink-950 text-white" : "text-ink-600 hover:bg-ink-50"}`}>{item.label}</button>)}
              <button
                type="button"
                onClick={() => setMoreOpen((open) => !open)}
                aria-expanded={moreOpen}
                className={`whitespace-nowrap rounded-md px-3 py-2 text-sm ${secondaryNavItems.some((item) => item.id === view) ? "bg-ink-950 text-white" : "text-ink-600 hover:bg-ink-50"}`}
              >
                More {moreOpen ? "−" : "+"}
              </button>
            </nav>
            {moreOpen && (
              <div className="ats-mobile-more mt-2 flex gap-1 overflow-x-auto border-t border-ink-100 pt-2 lg:hidden" aria-label="More workspace">
                {secondaryNavItems.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    aria-current={view === item.id ? "page" : undefined}
                    onClick={() => { setView(item.id); setMoreOpen(false); setError(""); }}
                    className={`whitespace-nowrap rounded-md border border-ink-100 bg-white px-3 py-2 text-sm font-medium ${view === item.id ? "border-ink-950 bg-ink-950 text-white" : "text-ink-600 hover:bg-ink-50"}`}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
            )}
          </div>
        </header>

        <Suspense fallback={<div className="mx-auto max-w-[1440px] rounded-xl border border-ink-100 bg-white p-6 text-sm text-ink-500">Loading workspace module…</div>}>
          <main id="ats-workspace-content" className="mx-auto max-w-[1440px] px-4 py-6 sm:px-7 sm:py-8">
          {notice && <div role="status" className="mb-4 flex items-center justify-between border-l-2 border-emerald-600 bg-white px-4 py-3 text-sm text-ink-700"><span>{notice}</span><button aria-label="Dismiss notice" onClick={() => setNotice("")}>×</button></div>}
          {error && <div role="alert" className="mb-4 flex items-center justify-between border-l-2 border-rose-600 bg-white px-4 py-3 text-sm text-rose-800"><span>{error}</span><button aria-label="Dismiss error" onClick={() => setError("")}>×</button></div>}
          {loading && <div className="mb-3 text-xs text-ink-500">Loading workspace…</div>}


          {view === "hiring-workflow" && <HiringWorkflowPanel token={token} applications={applications} jobs={jobs} apiRequest={apiRequest} onNotice={setNotice} onError={(requestError) => setError(errorText(requestError))} onRefresh={refreshWorkspace} />}

          {view === "interviews-2" && <InterviewManagement2 token={token} apiRequest={apiRequest} applications={applications} onNotice={setNotice} onError={(requestError) => setError(errorText(requestError))} />}

          {view === "offers" && <OfferManagement token={token} apiRequest={apiRequest} applications={applications} onNotice={setNotice} onError={(requestError) => setError(errorText(requestError))} />}


          {view === "merge-center" && <CandidateMergeCenter token={token} apiRequest={apiRequest} onNotice={setNotice} onError={(requestError) => setError(errorText(requestError))} />}

          {view === "compare" && <CandidateComparisonPanel token={token} apiRequest={apiRequest} applications={applications} jobs={jobs} onNotice={setNotice} onError={(requestError) => { if (requestError) setError(errorText(requestError)); else setError(""); }} />}

          {view === "dashboard" && <>
            <div className="bp-dashboard-hero mb-7 flex flex-wrap items-end justify-between gap-5">
              <div className="bp-dashboard-copy">
                <p className="bp-eyebrow text-xs font-semibold uppercase tracking-[0.14em]">Talent acquisition</p>
                <h2 className="mt-1 text-2xl font-semibold tracking-tight">Talent acquisition overview</h2>
                <p className="mt-2 max-w-2xl text-sm leading-6 text-ink-600">
                  Monitor active requisitions, candidate activity, application progress and upcoming interviews from one workspace.
                </p>
              </div>
              <div className="bp-dashboard-actions flex gap-2">
                <button type="button" className={buttonPrimary} onClick={() => { setView("ai-studio"); setMoreOpen(false); setError(""); setNotice(""); }}>
                  Open AI Hiring Studio
                </button>
                <button type="button" className={buttonSecondary} onClick={() => { setView("jd-match"); setMoreOpen(false); setError(""); setNotice(""); }}>
                  JD & Applicant Match <span aria-hidden="true">↗</span>
                </button>
                {canWrite && <button type="button" className={buttonPrimary} onClick={() => { setView("jobs"); setMoreOpen(false); resetJobForm(); setError(""); setNotice(""); }}>Create job</button>}
                {canWrite && import.meta.env.DEV && <button type="button" className={buttonSecondary} onClick={populateDemoData} disabled={demoPopulationLoading} title="Add synthetic jobs, candidates, pipeline stages, interviews, offers, talent pools, and workflow examples. Existing data is preserved.">
                  <svg aria-hidden="true" className="h-4 w-4 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                    <ellipse cx="12" cy="5" rx="8" ry="3" />
                    <path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3" />
                  </svg>
                  {demoPopulationLoading ? "Populating…" : "Populate demo data"}
                </button>}
              </div>
            </div>

            {dashboardLoading && (
              <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4" aria-hidden="true">
                {[0, 1, 2, 3].map((i) => (
                  <div key={i} className="bp-skeleton" style={{ height: 108, borderRadius: 12 }} />
                ))}
              </div>
            )}
            {dashboardData && <>
              <section className="bp-metric-strip mb-7" aria-label="Recruiting overview">
                <button type="button" className="bp-metric-card" onClick={() => setView("jobs")}>
                  <span className="bp-metric-label">Active requisitions</span>
                  <strong>{dashboardData.metrics?.open_jobs ?? 0}</strong>
                  <small>Roles currently accepting candidates</small>
                </button>
                <button type="button" className="bp-metric-card" onClick={() => setView("candidates")}>
                  <span className="bp-metric-label">Candidate database</span>
                  <strong>{dashboardData.metrics?.total_candidates ?? (candidates.length >= 100 ? "100+" : candidates.length)}</strong>
                  <small>Profiles available to your team</small>
                </button>
                <div className="bp-metric-card">
                  <span className="bp-metric-label">Applications received</span>
                  <strong>{dashboardData.metrics?.total_applications ?? 0}</strong>
                  <small>Applications recorded in the ATS</small>
                </div>
                <button type="button" className="bp-metric-card" onClick={() => setView("interviews-2")}>
                  <span className="bp-metric-label">Upcoming interviews</span>
                  <strong>{dashboardData.metrics?.upcoming_interviews_count ?? ((dashboardData.upcoming_interviews?.length ?? 0) >= 12 ? "12+" : dashboardData.upcoming_interviews?.length ?? 0)}</strong>
                  <small>Scheduled candidate meetings</small>
                </button>
              </section>

              <section className="bp-dashboard-secondary mt-8 grid gap-8 lg:grid-cols-2">
                <div>
                  <div className="flex items-baseline justify-between gap-3">
                    <div><p className="text-xs font-semibold uppercase tracking-[0.12em] text-ink-500">Attention</p><h3 className="mt-1 text-lg font-semibold">Recent applications</h3></div>
                  </div>
                  <div className="mt-3 divide-y divide-ink-100">
                    {(dashboardData.recent_applications || []).slice(0, 6).map((application) => <button key={application.id} className="flex w-full items-center justify-between gap-4 py-3 text-left hover:bg-ink-50" onClick={() => { setSelectedCandidate(application.candidate_id); setView("candidates"); }}>
                      <div className="min-w-0"><p className="truncate font-medium">{application.candidate_name}</p><p className="truncate text-xs text-ink-500">{application.job_title} · {new Date(application.applied_at).toLocaleDateString()}</p></div>
                      <span className="shrink-0 text-xs font-semibold text-ink-600">{application.stage_name}</span>
                    </button>)}
                    {!dashboardData.recent_applications?.length && <p className="py-5 text-sm text-ink-500">No applications yet.</p>}
                  </div>
                </div>

                <div>
                  <div className="flex items-baseline justify-between gap-3">
                    <div><p className="text-xs font-semibold uppercase tracking-[0.12em] text-ink-500">Schedule</p><h3 className="mt-1 text-lg font-semibold">Upcoming interviews</h3></div>
                    <button className="text-sm font-semibold underline underline-offset-4" onClick={() => setView("interviews-2")}>Manage</button>
                  </div>
                  <div className="mt-3 divide-y divide-ink-100">
                    {(dashboardData.upcoming_interviews || []).slice(0, 5).map((interview) => <button key={interview.id} className="w-full py-3 text-left hover:bg-ink-50" onClick={() => setView("interviews-2")}>
                      <div className="flex items-start justify-between gap-4"><p className="font-medium">{interview.candidate_name}</p><span className="text-xs text-ink-500">{interview.mode === "offline" ? "Offline" : "Online"}</span></div>
                      <p className="mt-1 text-xs text-ink-500">{interview.job_title} · {new Date(interview.starts_at).toLocaleString()} · {interview.duration_minutes} min</p>
                    </button>)}
                    {!dashboardData.upcoming_interviews?.length && <p className="py-5 text-sm text-ink-500">No upcoming interviews.</p>}
                  </div>
                </div>
              </section>

              <details className="bp-operational-details mt-8 border-t border-ink-200 pt-4">
                <summary className="cursor-pointer text-sm font-semibold text-ink-700">Operational details</summary>
                <div className="mt-5 grid gap-8 md:grid-cols-2">
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-[0.12em] text-ink-500">Applications by job</p>
                    <div className="mt-3 grid gap-2">
                      {(dashboardData.job_counts || []).slice(0, 7).map((item) => <div key={item.name} className="flex justify-between gap-3 text-sm"><span className="truncate">{item.name}</span><span className="font-semibold">{item.count}</span></div>)}
                      {!dashboardData.job_counts?.length && <p className="text-sm text-ink-500">No data.</p>}
                    </div>
                  </div>
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-[0.12em] text-ink-500">Application sources</p>
                    <div className="mt-3 grid gap-2">
                      {(dashboardData.source_counts || []).slice(0, 5).map((item) => <div key={item.name} className="flex justify-between gap-3 text-sm"><span className="truncate">{item.name}</span><span className="font-semibold">{item.count}</span></div>)}
                      {!dashboardData.source_counts?.length && <p className="text-sm text-ink-500">No data.</p>}
                    </div>
                  </div>
                </div>
              </details>
            </>}
          </>}

          {view === "jobs" && <>

            {jobFormOpen && <form onSubmit={saveJob} className="mb-6 border-y border-ink-100 bg-white p-4 sm:p-5">
              <div className="mb-4 flex items-center justify-between"><h2 className="font-semibold">{editingJob ? "Edit job" : "New job"}</h2><button type="button" aria-label="Close form" onClick={() => { setJobFormOpen(false); setJobDocumentFile(null); setJobLinkInput(""); }}>×</button></div>
              {!editingJob && <div className="mb-5 flex flex-wrap gap-2 border-b border-ink-100 pb-3">
                <button type="button" onClick={() => setJobEntryMode("manual")} className={jobEntryMode === "manual" ? buttonPrimary : buttonSecondary}>Enter manually</button>
                <button type="button" onClick={() => setJobEntryMode("link")} className={jobEntryMode === "link" ? buttonPrimary : buttonSecondary}>Import from job URL</button>
                <button type="button" onClick={() => setJobEntryMode("upload")} className={jobEntryMode === "upload" ? buttonPrimary : buttonSecondary}>Upload JD file</button>
              </div>}
              {jobEntryMode === "link" && !editingJob ? (
                <div className="grid gap-4">
                  <div className="rounded-xl border border-gold-200 bg-[#fbf7ef] p-4 text-sm leading-6 text-ink-700">
                    <p className="font-semibold">Automatic job intake</p>
                    <p className="mt-1">Paste a public job-posting URL or an <code>[Job title](URL)</code> link. BluePace retrieves the source page and automatically extracts the complete readable description, title, location, employment type, work mode, skills, experience and other available requirements. No description typing or field-by-field setup is needed.</p>
                    <p className="mt-2 text-xs">If a field is not available on the source page, it may remain unknown. The imported description is preserved for recruiter review.</p>
                  </div>
                  <label className="grid gap-1.5 text-xs font-semibold text-ink-700">Public job posting URL
                    <input className={inputStyle} required value={jobLinkInput} placeholder="https://careers.example.com/jobs/123" onChange={(event) => setJobLinkInput(event.target.value)} />
                    <span className="text-[11px] font-normal text-ink-400">Supports public HTML job pages, including many job-board links. Sign-in-only pages may not be accessible.</span>
                  </label>
                </div>
              ) : jobEntryMode === "upload" && !editingJob ? (
                <div className="grid gap-4">
                  <div className="rounded-xl border border-gold-200 bg-[#fbf7ef] p-4 text-sm leading-6 text-ink-700">
                    <p className="font-semibold">Automatic document extraction</p>
                    <p className="mt-1">Upload the original JD as a PDF or DOCX. BluePace extracts its complete readable text and automatically identifies the title, location, employment type, work mode, required skills, experience and education requirements where available.</p>
                    <p className="mt-2 text-xs">Maximum file size: 5 MB. You do not need to retype the description or metadata.</p>
                  </div>
                  <label className="grid gap-1.5 text-xs font-semibold text-ink-700">Job description file
                    <input className={inputStyle + " p-2"} type="file" accept=".pdf,.docx" required onChange={(event) => { const selected = event.target.files?.[0] || null; if (selected && selected.size > MAX_DOCUMENT_SIZE_BYTES) { setJobDocumentFile(null); setError(`Job document must be ${MAX_DOCUMENT_SIZE_LABEL} or smaller.`); event.target.value = ""; return; } setJobDocumentFile(selected); setError(""); }} />
                    <span className="text-[11px] font-normal text-ink-400">{jobDocumentFile ? jobDocumentFile.name : "PDF or DOCX, up to 5 MB."}</span>
                  </label>
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
                  <Field label="Minimum experience (years)" type="number" min="0" max="60" step="0.5" value={jobForm.minimum_experience_years} onChange={(event) => setJobForm({ ...jobForm, minimum_experience_years: event.target.value })} />
                  <label className="flex min-h-10 items-center gap-2 text-sm font-medium text-ink-700"><input type="checkbox" checked={jobForm.fresher_allowed} onChange={(event) => setJobForm({ ...jobForm, fresher_allowed: event.target.checked })} />Open to freshers</label>
                  {(editingJob?.jd_analysis?.source_url || editingJob?.jd_analysis?.source_file) ? (
                    <div className="grid gap-1.5 text-xs font-semibold text-ink-700 sm:col-span-2">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span>Imported job description · read-only</span>
                        {editingJob?.jd_analysis?.source_url && (
                          <button type="button" onClick={refreshEditingJobSource} disabled={jobSourceRefreshing} className="rounded-md border border-ink-200 bg-white px-3 py-1.5 text-xs font-semibold disabled:opacity-50">
                            {jobSourceRefreshing ? "Refreshing source…" : "Refresh from source"}
                          </button>
                        )}
                      </div>
                      <div className="max-h-64 overflow-auto whitespace-pre-wrap rounded-md border border-ink-100 bg-[#fafaf8] p-3 text-xs font-normal leading-5 text-ink-700">
                        {jobForm.description || "No source description is available for this job."}
                      </div>
                      <span className="text-[11px] font-normal text-ink-400">
                        This description was imported from the original source.
                        {editingJob?.jd_analysis?.source_url ? " Use Refresh from source to sync the latest public posting." : " Import an updated PDF/DOCX to replace this content."}
                      </span>
                      {editingJob?.jd_analysis?.source_url && <a className="break-all text-[11px] font-medium text-blue-700 hover:underline" href={editingJob.jd_analysis.source_url} target="_blank" rel="noreferrer">Open original job posting</a>}
                    </div>
                  ) : (
                    <label className="grid gap-1.5 text-xs font-semibold text-ink-700 sm:col-span-2">
                      Job description <span className="font-normal text-ink-500">(required)</span>
                      <textarea
                        className={inputStyle + " min-h-40 resize-y"}
                        rows={8}
                        required
                        value={jobForm.description}
                        placeholder="Describe the role, key responsibilities, required skills, experience and qualifications."
                        onChange={(event) => setJobForm({ ...jobForm, description: event.target.value })}
                      />
                      <span className="text-[11px] font-normal text-ink-400">Enter the job description here. BluePace will build matching criteria from the role details.</span>
                    </label>
                  )}
                </div>
              )}
              <div className="mt-4 flex gap-2"><button className={buttonPrimary} type="submit">{editingJob ? "Save changes" : jobEntryMode === "manual" ? "Create job" : jobEntryMode === "upload" ? "Extract & create job" : "Import & create job"}</button><button className={buttonSecondary} type="button" onClick={() => { setJobFormOpen(false); setJobDocumentFile(null); setJobLinkInput(""); }}>Cancel</button></div>
            </form>}
            <div className="mb-5"><p className="text-sm text-ink-500">{jobs.length} total jobs</p><h2 className="mt-1 text-xl font-semibold">Job openings</h2></div>
            <div className="ats-jobs-table overflow-x-auto rounded-xl border border-ink-100 bg-white shadow-xs"><div className="min-w-[980px]">
              <div className="ats-jobs-grid grid grid-cols-[minmax(360px,2.4fr)_minmax(150px,0.9fr)_110px_minmax(220px,1.2fr)] gap-5 border-b border-ink-100 bg-[#fafaf8] px-5 py-3 text-[11px] font-semibold uppercase tracking-wide text-ink-500"><span>Role</span><span>Location</span><span>Created</span><span>Status</span></div>
              {jobs.map((job) => <div key={job.id} className="ats-jobs-grid grid grid-cols-[minmax(360px,2.4fr)_minmax(150px,0.9fr)_110px_minmax(220px,1.2fr)] gap-5 border-b border-ink-50 px-5 py-5 last:border-0">
                <div>{job.jd_analysis?.source_url ? <a className="font-semibold underline decoration-ink-200 underline-offset-4 hover:decoration-ink-700" href={job.jd_analysis.source_url} target="_blank" rel="noreferrer">{job.title}</a> : <button className="font-semibold hover:underline" onClick={() => resetJobForm(job)}>{job.title}</button>}<p className="mt-0.5 text-xs text-ink-500">{job.department || "Unassigned department"} · {job.employment_type || "Employment type not set"} · {workModeLabel(job.work_mode)}</p><p className="mt-1 text-xs text-ink-500">{job.minimum_experience_years === null ? "Experience unspecified" : `${job.minimum_experience_years}+ years`}{job.fresher_allowed ? " · Freshers welcome" : ""}{job.required_skills?.length ? ` · ${job.required_skills.join(", ")}` : ""}</p>
                {job.jd_analysis && <details className="mt-2 text-xs text-ink-600"><summary className="cursor-pointer font-semibold text-ink-700">View requirements</summary><div className="mt-2 rounded-lg bg-ink-50 p-3">
                  <div className="flex flex-wrap gap-x-4 gap-y-1">
                    <span><b>Seniority:</b> {job.jd_analysis.seniority || "Unspecified"}</span>
                    <span><b>Experience:</b> {job.jd_analysis.minimum_experience_years != null ? String(job.jd_analysis.minimum_experience_years) + "+" + (job.jd_analysis.maximum_experience_years ? "–" + job.jd_analysis.maximum_experience_years : "") + " years" : "Unspecified"}</span>
                    <span><b>Education:</b> {job.jd_analysis.education || "Unspecified"}</span>
                    <span><b>Mode:</b> {workModeLabel(job.jd_analysis.work_mode || job.work_mode)}</span>
                  </div>
                  <div className="mt-2"><b>Required:</b> {(job.jd_analysis.required_skills || []).join(", ") || "None"} · <b>Preferred:</b> {(job.jd_analysis.preferred_skills || []).join(", ") || "None"}</div>
                  {job.jd_analysis.responsibilities?.length > 0 && <div className="mt-2"><b>Responsibilities:</b> {job.jd_analysis.responsibilities.slice(0, 3).join(" · ")}</div>}
                  {job.jd_analysis.interview_topics?.length > 0 && <div className="mt-2"><b>Interview topics:</b> {job.jd_analysis.interview_topics.join(", ")}</div>}
                </div></details>}
                {job.jd_analysis?.source_url && <p className="mt-1 text-[11px] text-ink-400">Imported from job link</p>}</div>
                <div className="self-start wrap-break-word pt-0.5 text-sm text-ink-600">{job.location || "Remote / unspecified"}</div>
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
              <div className="flex flex-wrap items-center gap-x-8 gap-y-3 text-sm">
                <div><p className="text-[11px] font-semibold uppercase text-ink-500">Seniority</p><p className="mt-1 capitalize">{matchAnalysis.seniority || "Unspecified"}</p></div>
                <div><p className="text-[11px] font-semibold uppercase text-ink-500">Experience</p><p className="mt-1">{matchAnalysis.minimum_experience_years ? `${matchAnalysis.minimum_experience_years}+ years` : "Unspecified"}</p></div>
                <div><p className="text-[11px] font-semibold uppercase text-ink-500">Work mode</p><p className="mt-1 capitalize">{matchAnalysis.work_mode || "Unspecified"}</p></div>
                <div><p className="text-[11px] font-semibold uppercase text-ink-500">Required skills</p><p className="mt-1">{(matchAnalysis.required_skills || []).length}</p></div>
                <details className="basis-full border-t border-ink-50 pt-3">
                  <summary className="cursor-pointer text-xs font-semibold text-ink-700">View JD intelligence</summary>
                  <div className="mt-3 grid gap-3 text-sm sm:grid-cols-2">
                    <div><p className="text-[11px] font-semibold uppercase text-ink-500">Location</p><p className="mt-1">{matchAnalysis.location || "Unspecified"}</p></div>
                    <div><p className="text-[11px] font-semibold uppercase text-ink-500">Education</p><p className="mt-1">{matchAnalysis.education || "No degree requirement extracted"}</p></div>
                    <div><p className="text-[11px] font-semibold uppercase text-ink-500">Required</p><p className="mt-1">{(matchAnalysis.required_skills || []).join(", ") || "None extracted"}</p></div>
                    <div><p className="text-[11px] font-semibold uppercase text-ink-500">Preferred</p><p className="mt-1">{(matchAnalysis.preferred_skills || []).join(", ") || "None extracted"}</p></div>
                    <div><p className="text-[11px] font-semibold uppercase text-ink-500">Responsibilities</p><ul className="mt-1 grid gap-1">{(matchAnalysis.responsibilities || []).slice(0, 5).map((item, index) => <li key={index}>• {item}</li>)}</ul></div>
                    <div><p className="text-[11px] font-semibold uppercase text-ink-500">Interview topics</p><p className="mt-1">{(matchAnalysis.interview_topics || []).join(", ") || "No topics extracted"}</p></div>
                    <div className="sm:col-span-2"><p className="text-[11px] font-semibold uppercase text-ink-500">Skill normalization</p><div className="mt-1 flex flex-wrap gap-1.5">{Object.entries(matchAnalysis.skill_normalization || {}).map(([raw, normalized]) => <span key={raw} className="rounded-full bg-ink-50 px-2 py-1 text-[11px]">{raw} → {normalized}</span>)}</div></div>
                  </div>
                </details>
              </div>
            </section>}
            {matches.length > 0 && <div className="mb-3 flex items-center justify-between text-xs text-ink-500">
              <span>{matches.length} ranked candidate profiles</span>
              <details><summary className="cursor-pointer font-semibold text-ink-500">How matching works</summary><span className="ml-2">Skills and experience rules plus semantic matching when embeddings are available.</span></details>
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
                      <td className="min-w-32 px-3 py-4"><p className="text-lg font-semibold tabular-nums">{match.effective_score}<span className="text-xs font-normal text-ink-500"> / 100</span></p>{match.recruiter_override !== null && <p className="text-[11px] text-gold-600">Model: {match.model_score}</p>}<div className="mt-1 h-1.5 w-24 bg-ink-100"><div className="h-full bg-gold-500" style={{ width: `${match.effective_score}%` }} /></div><details className="mt-2"><summary className="cursor-pointer text-[10px] font-semibold text-ink-500">Scoring details</summary><p className="mt-2 text-[10px] text-ink-500">{Object.entries(MATCH_WEIGHTS).map(([key, weight]) => `${key.replaceAll("_", " ")} ${match.score_breakdown[key] ?? 0}·${weight}%`).join(" · ")}</p></details><p className="mt-1 text-[10px] text-ink-400">Decision-support signal; recruiter review remains required.</p></td>
                      <td className="max-w-48 px-3 py-4 text-xs text-emerald-800">{match.matched_skills.join(", ") || "No direct skill matches"}</td>
                      <td className="max-w-48 px-3 py-4 text-xs text-rose-800">{match.skill_gaps.join(", ") || "No required skill gaps"}</td>
                      <td className="max-w-64 px-3 py-4">
  <p className="text-xs leading-5 text-ink-700">{match.match_explanation?.summary || match.explanations?.[0] || "Match evidence is available for recruiter review."}</p>
  {!!(match.match_explanation?.strengths || []).length && (
    <div className="mt-2 grid gap-1.5">
      {match.match_explanation.strengths.slice(0, 2).map((item, itemIndex) => <p key={itemIndex} className="text-[11px] leading-5 text-emerald-800">+ {item}</p>)}
    </div>
  )}
  {!!(match.match_explanation?.review_flags || []).length && (
    <div className="mt-2 grid gap-1.5">
      {match.match_explanation.review_flags.slice(0, 2).map((item, itemIndex) => <p key={itemIndex} className="text-[11px] leading-5 text-amber-800">Review: {item}</p>)}
    </div>
  )}
  {!!(match.match_explanation?.evidence || []).length && (
    <details className="mt-2">
      <summary className="cursor-pointer text-[11px] font-semibold text-blue-700">View evidence</summary>
      <div className="mt-2 grid gap-1.5 text-[11px] text-ink-500">
        {match.match_explanation.evidence.slice(0, 4).map((item, itemIndex) => <div key={item.type + "-" + itemIndex}><span className="font-semibold text-ink-700">{item.title}</span>{item.details ? " · " + item.details : ""}</div>)}
      </div>
    </details>
  )}
</td>
<td className="min-w-64 px-3 py-4">
  <details>
    <summary className="cursor-pointer text-[11px] font-semibold text-ink-600">View CV summary</summary>
    <ul className="mt-2 grid gap-1 text-xs text-ink-600">{(match.cv_summary || []).slice(0, 4).map((item, itemIndex) => <li key={itemIndex}>• {item}</li>)}</ul>
  </details>
</td>
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
                  <input className={`${inputStyle} p-2`} type="file" accept=".pdf,.docx" onChange={(event) => { const selected = event.target.files?.[0] || null; if (selected && selected.size > MAX_DOCUMENT_SIZE_BYTES) { setResumeFile(null); setError(`Resume must be ${MAX_DOCUMENT_SIZE_LABEL} or smaller.`); event.target.value = ""; return; } setResumeFile(selected); setError(""); }} />
                  <span className="text-[11px] font-normal text-ink-400">{candidateEntryMode === "resume" ? "Required in upload mode." : "Optional in manual mode."}</span>
                </label>
              </div>
              <div className="mt-4 flex gap-2"><button className={buttonPrimary} type="submit">Add candidate</button><button className={buttonSecondary} type="button" onClick={() => setCandidateFormOpen(false)}>Cancel</button></div>
            </form>}
            <form onSubmit={semanticSearch} className="mb-4 border-b border-ink-100 pb-4">
              <div className="flex flex-wrap items-end gap-2">
                <div className="min-w-[260px] flex-1">
                  <label className="grid gap-1.5 text-xs font-semibold text-ink-700">Semantic search
                    <input className={inputStyle} placeholder="e.g. Python backend engineer with FastAPI and AWS" value={semanticQuery} onChange={(event) => setSemanticQuery(event.target.value)} />
                  </label>
                </div>
                <button className={buttonSecondary} type="submit">Find similar profiles</button>
                {semanticResults.length > 0 && <button className={buttonSecondary} type="button" onClick={() => setSemanticResults([])}>Clear</button>}
              </div>
              {semanticResults.length > 0 && <div className="mt-3 grid gap-1.5">
                {semanticResults.map((result) => <div key={result.candidate_id} className="flex flex-wrap items-center justify-between gap-2 border-b border-ink-50 py-2 text-xs">
                  <div><button type="button" className="font-semibold text-ink-900 hover:underline" onClick={() => setSelectedCandidate(result.candidate_id)}>{result.name}</button><span className="ml-2 text-ink-500">{result.location || "Location not evidenced"}</span></div>
                  <span className="text-ink-500">{result.similarity}% similarity · {result.retrieval_mode === "embedding" ? "semantic" : "text fallback"}</span>
                </div>)}
              </div>}
            </form>
            <form onSubmit={searchCandidates} className="mb-5 border-b border-ink-100 pb-5">
              <div className="flex flex-wrap items-end justify-between gap-3">
                <div><p className="text-xs font-medium text-ink-500">Candidate directory</p><h2 className="mt-1 text-2xl font-semibold tracking-tight">Candidates</h2><p className="mt-1 text-sm text-ink-500">Search structured resume evidence and open a profile when you need more detail.</p></div>
                <span className="text-xs text-ink-500">{candidates.length} profiles</span>
              </div>
              <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                 <Field label="Search" placeholder="Candidate, skill, or role" value={candidateFilters.search} onChange={(event) => setCandidateFilters({ ...candidateFilters, search: event.target.value })} />
                 <Field label="Skills" placeholder="Python, SQL, React" value={candidateFilters.skill} onChange={(event) => setCandidateFilters({ ...candidateFilters, skill: event.target.value })} />
                 <label className="grid gap-1.5 text-xs font-semibold text-ink-700">Stage<select className={inputStyle} value={candidateFilters.stage_name} onChange={(event) => setCandidateFilters({ ...candidateFilters, stage_name: event.target.value })}><option value="">Any stage</option>{["Applied","Screening","Interview","Offer","Hired","Rejected","withdrawn"].map((stage) => <option key={stage}>{stage}</option>)}</select></label>
               </div>
               <details className="mt-3">
                 <summary className="cursor-pointer text-xs font-semibold text-ink-700">More filters</summary>
                 <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                   <Field label="Location" placeholder="Hyderabad" value={candidateFilters.location} onChange={(event) => setCandidateFilters({ ...candidateFilters, location: event.target.value })} />
                   <Field label="Preferred location" placeholder="Bengaluru" value={candidateFilters.preferred_location} onChange={(event) => setCandidateFilters({ ...candidateFilters, preferred_location: event.target.value })} />
                   <Field label="Min experience" type="number" min="0" max="60" placeholder="Years" value={candidateFilters.min_experience_years} onChange={(event) => setCandidateFilters({ ...candidateFilters, min_experience_years: event.target.value })} />
                   <Field label="Max experience" type="number" min="0" max="60" placeholder="Years" value={candidateFilters.max_experience_years} onChange={(event) => setCandidateFilters({ ...candidateFilters, max_experience_years: event.target.value })} />
                   <Field label="Notice period" placeholder="30 days" value={candidateFilters.notice_period} onChange={(event) => setCandidateFilters({ ...candidateFilters, notice_period: event.target.value })} />
                   <Field label="Availability" placeholder="Immediate / 2026-10-15" value={candidateFilters.availability} onChange={(event) => setCandidateFilters({ ...candidateFilters, availability: event.target.value })} />
                   <Field label="Education" placeholder="B.Tech / Computer Science" value={candidateFilters.education} onChange={(event) => setCandidateFilters({ ...candidateFilters, education: event.target.value })} />
                   <Field label="Job history" placeholder="Infosys / Backend Engineer" value={candidateFilters.job_history} onChange={(event) => setCandidateFilters({ ...candidateFilters, job_history: event.target.value })} />
                   <Field label="Tags" placeholder="Immediate, React" value={candidateFilters.tags} onChange={(event) => setCandidateFilters({ ...candidateFilters, tags: event.target.value })} />
                   <label className="grid gap-1.5 text-xs font-semibold text-ink-700">Source<select className={inputStyle} value={candidateFilters.source} onChange={(event) => setCandidateFilters({ ...candidateFilters, source: event.target.value })}><option value="">All sources</option>{[...new Set(candidates.map((candidate) => candidate.source).filter(Boolean))].map((source) => <option key={source}>{source}</option>)}</select></label>
                   <label className="grid gap-1.5 text-xs font-semibold text-ink-700">Has applied to job<select className={inputStyle} value={candidateFilters.has_applied_job_id} onChange={(event) => setCandidateFilters({ ...candidateFilters, has_applied_job_id: event.target.value })}><option value="">Any job</option>{jobs.map((job) => <option key={job.id} value={job.id}>{job.title}</option>)}</select></label>
                   <Field label="Work authorization" placeholder="Authorized / visa" value={candidateFilters.work_authorization} onChange={(event) => setCandidateFilters({ ...candidateFilters, work_authorization: event.target.value })} />
                 </div>
               </details>
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
              <table className="w-full min-w-[760px] border-collapse text-left text-sm">
                <thead className="border-b border-ink-100 text-[11px] uppercase tracking-wide text-ink-500"><tr><th className="px-4 py-3">Candidate</th><th className="px-4 py-3">Current signal</th><th className="px-4 py-3">Skills</th><th className="px-4 py-3">Resume</th><th className="px-4 py-3">Open</th></tr></thead>
                <tbody className="divide-y divide-ink-50">
                  {candidates.map((candidate) => {
                    const profile = candidate.resume_data || {};
                    const signals = [
                      profile.years_of_experience != null ? `${profile.years_of_experience} yrs experience` : null,
                      profile.current_location || null,
                      profile.resume_quality?.missing_fields?.length ? `${profile.resume_quality.missing_fields.length} review signal${profile.resume_quality.missing_fields.length === 1 ? "" : "s"}` : null,
                    ].filter(Boolean);
                    return <tr key={candidate.id} className="hover:bg-[#fcfcfa]">
                      <td className="px-4 py-3 align-top"><button className="font-semibold text-ink-900 hover:underline" onClick={() => setSelectedCandidate(candidate.id)}>{candidate.first_name} {candidate.last_name}</button><p className="mt-1 text-xs text-ink-500">{candidate.email}{candidate.phone ? ` · ${candidate.phone}` : ""}</p></td>
                      <td className="px-4 py-3 align-top text-xs text-ink-600">{signals.length ? signals.join(" · ") : "Profile needs review"}</td>
                      <td className="max-w-72 px-4 py-3 align-top text-xs text-ink-600">{(profile.skills || []).slice(0, 6).join(", ") || "Not parsed"}</td>
                      <td className="px-4 py-3 align-top text-xs">{candidate.resume_storage_key ? <span className="font-medium text-emerald-700">Parsed</span> : <span className="text-ink-400">No resume</span>}</td>
                      <td className="px-4 py-3 align-top"><button type="button" className="text-sm font-semibold underline underline-offset-4" onClick={() => setSelectedCandidate(candidate.id)}>Open profile</button></td>
                    </tr>;
                  })}
                </tbody>
              </table>
              {!candidates.length && <EmptyState title="No candidates yet" detail="Add a profile and upload a resume to parse it." />}
            </div>
            {selectedCandidate && (() => {
              const candidate = candidates.find((item) => item.id === selectedCandidate);
              if (!candidate) return null;
              const profile = candidate.resume_data || {};
              return <section className="mt-5 border-y border-ink-100 bg-white p-4 sm:p-5">
                <div className="flex items-start justify-between gap-4 border-b border-ink-100 pb-5">
                  <div>
                    <p className="text-xs font-medium text-ink-500">Candidate evidence</p>
                    <h3 className="mt-1 text-2xl font-semibold tracking-tight">{candidate.first_name} {candidate.last_name}</h3>
                    <p className="mt-1 text-sm text-ink-500">{candidate.email}{candidate.phone && " · " + candidate.phone}{candidate.source ? " · " + candidate.source : ""}</p>
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
                    ].map(([label, value]) => <div key={label} className="rounded-lg border border-ink-100 bg-white p-3"><p className="text-[11px] font-semibold uppercase text-ink-500">{label}</p><p className="mt-1 wrap-break-word text-sm">{value}</p></div>)}
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
                    <>
                      <div className="mt-5 rounded-xl border border-ink-100 bg-white p-4 shadow-xs">
                        <div className="flex flex-wrap items-start justify-between gap-4">
                          <div className="min-w-0 flex-1">
                            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-blue-700">Candidate fit summary</p>
                            <div className="mt-1 flex flex-wrap items-center gap-2">
                              <h5 className="text-lg font-semibold text-ink-900">{fitAnalysis.fit || fitAnalysis.alignment}</h5>
                              {fitAnalysis.decision_support_only && <span className="rounded-full bg-slate-50 px-2 py-1 text-[11px] font-medium text-slate-600">Decision support</span>}
                            </div>
                            <p className="mt-2 max-w-4xl text-sm leading-6 text-ink-600">{fitAnalysis.summary || "Role-fit evidence generated from the candidate resume and selected job description."}</p>
                            <div className="mt-3 rounded-lg border border-ink-100 bg-[#fafaf8] p-3">
                              <p className="text-[11px] font-semibold uppercase tracking-wide text-ink-500">Review signal</p>
                              <p className="mt-1 text-sm font-semibold text-ink-900">{fitAnalysis.final_recommendation || fitAnalysis.recommendation || "Recruiter review required"}</p>
                              <p className="mt-1 text-[11px] leading-5 text-ink-500">Use the evidence below to guide recruiter review. This is not an automated hiring decision.</p>
                            </div>
                          </div>
                          <div className="shrink-0 rounded-xl border border-blue-100 bg-blue-50 px-5 py-3 text-center">
                            <p className="text-[11px] font-semibold uppercase tracking-wide text-blue-700">Match score</p>
                            <p className="mt-1 text-3xl font-bold text-ink-900">{fitAnalysis.match_score}%</p>
                          </div>
                        </div>
                        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                          <div className="rounded-lg bg-[#fafaf8] p-3"><p className="text-[11px] uppercase tracking-wide text-ink-500">Required skills</p><p className="mt-1 text-sm font-semibold text-ink-900">{fitAnalysis.mandatory_skills_match_score ?? fitAnalysis.match_score}%</p></div>
                          <div className="rounded-lg bg-[#fafaf8] p-3"><p className="text-[11px] uppercase tracking-wide text-ink-500">Coding skills</p><p className="mt-1 text-sm font-semibold text-ink-900">{fitAnalysis.coding_skills_score ?? "—"}%</p></div>
                          <div className="rounded-lg bg-[#fafaf8] p-3"><p className="text-[11px] uppercase tracking-wide text-ink-500">Experience</p><p className="mt-1 text-sm font-semibold text-ink-900">{fitAnalysis.experience_years ?? fitAnalysis.experience_years_estimate ?? "—"} years</p></div>
                          <div className="rounded-lg bg-[#fafaf8] p-3"><p className="text-[11px] uppercase tracking-wide text-ink-500">Experience fit</p><p className="mt-1 text-sm font-semibold text-ink-900">{fitAnalysis.experience_score ?? "—"}%</p></div>
                        </div>
                        <div className="mt-4 grid gap-3 lg:grid-cols-2">
                          <div>
                            <p className="text-xs font-semibold uppercase tracking-wide text-ink-500">Strengths</p>
                            <div className="mt-2 grid gap-2">{(fitAnalysis.strengths || []).map((item, index) => <div key={index} className="rounded-lg border border-emerald-100 bg-emerald-50/60 p-3 text-xs leading-5 text-emerald-900">{item}</div>)}{!(fitAnalysis.strengths || []).length && <p className="text-sm text-ink-500">No strong strengths were identified.</p>}</div>
                          </div>
                          <div>
                            <p className="text-xs font-semibold uppercase tracking-wide text-ink-500">Gaps / missing requirements</p>
                            <div className="mt-2 flex flex-wrap gap-2">{(fitAnalysis.missing_skills || fitAnalysis.skill_gaps || []).map((item) => <span key={item} className="rounded-full bg-rose-50 px-2.5 py-1 text-[11px] font-semibold text-rose-800">{item}</span>)}{!(fitAnalysis.missing_skills || fitAnalysis.skill_gaps || []).length && <p className="text-sm text-emerald-700">No skill gaps identified.</p>}</div>
                          </div>
                        </div>
                      </div>
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
                    </>
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
                />
                <RecruiterToolsPanel
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
            <div className="border-b border-ink-200 pb-5">
              <p className="text-xs font-medium text-ink-500">Decision support</p>
              <h2 className="mt-1 text-2xl font-semibold tracking-tight">AI Assistant</h2>
              <p className="mt-1 max-w-3xl text-sm text-ink-500">Ask about one application. Answers use the job, parsed resume, match evidence, and submitted interview scorecards.</p>
              <div className="mt-5 grid gap-3">
                <SelectField label="Application" value={assistantApplicationId} onChange={(event) => { setAssistantApplicationId(event.target.value); setAssistantResult(null); }}>
                  <option value="">Choose an application</option>
                  {applications.map((item) => <option key={item.id} value={item.id}>{item.candidate_name || "Candidate"} — {item.job_title || "Role"}</option>)}
                </SelectField>
                <div className="flex flex-wrap gap-2">
                  {["Summarize against the JD.","Show missing required skills.","Create interview questions."].map((item) => <button key={item} type="button" onClick={() => setAssistantQuestion(item)} className="rounded-full border border-ink-100 bg-white px-3 py-1.5 text-xs font-semibold text-ink-700 hover:bg-ink-50">{item}</button>)}
                </div>
                <textarea className={inputStyle + " min-h-24"} value={assistantQuestion} onChange={(event) => setAssistantQuestion(event.target.value)} placeholder="Ask a question about this application…" />
                <button type="button" disabled={!assistantApplicationId || assistantLoading} onClick={askRecruiterAssistant} className={buttonPrimary}>{assistantLoading ? "Analyzing evidence…" : "Ask assistant"}</button>
              </div>
            </div>
            {assistantResult && <div className="grid gap-4">
              <div className="border-b border-ink-200 pb-5">
                <p className="text-xs font-medium uppercase tracking-wide text-ink-500">{assistantResult.intent?.replaceAll("_", " ")}</p>
                <h3 className="mt-1 text-lg font-semibold">Response</h3>
                <p className="mt-3 text-sm leading-6 text-ink-700">{assistantResult.summary}</p>
                <p className="mt-2 text-xs text-ink-500">Evidence coverage {assistantResult.data_coverage ?? 0}% · Confidence {assistantResult.confidence || "medium"}</p>
              </div>
              <details className="border-y border-ink-100 py-3">
                <summary className="cursor-pointer text-sm font-semibold text-ink-800">View recruiting details</summary>
                <div className="mt-4 grid gap-5">
                  <div>
                    <p className="text-sm font-semibold">Required skills</p>
                    <div className="mt-2 flex flex-wrap gap-2">{(assistantResult.matched_required_skills || []).map((skill) => <span key={skill} className="rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-800">{skill} · evidenced</span>)}{(assistantResult.missing_required_skills || []).map((skill) => <span key={skill} className="rounded-full bg-rose-50 px-2.5 py-1 text-xs font-semibold text-rose-800">{skill} · not evidenced</span>)}</div>
                  </div>
                  <div>
                    <p className="text-sm font-semibold">Requirement explanation</p>
                    <p className="mt-2 text-sm leading-6 text-ink-600">{assistantResult.requirement_explanation}</p>
                  </div>
                  <div>
                    <p className="text-sm font-semibold">Interview questions</p>
                    <ol className="mt-2 grid gap-2 text-sm text-ink-700">{(assistantResult.interview_questions || []).map((item, index) => <li key={index} className="border-b border-ink-100 py-2">{index + 1}. {item}</li>)}</ol>
                  </div>
                  <div>
                    <p className="text-sm font-semibold">Interview feedback</p>
                    <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-ink-600">{assistantResult.interview_feedback_summary}</p>
                  </div>
                  <div>
                    <p className="text-sm font-semibold">Screening email draft</p>
                    <pre className="mt-2 whitespace-pre-wrap font-sans text-sm leading-6 text-ink-600">{assistantResult.screening_email}</pre>
                  </div>
                </div>
              </details>
              <details className="border-y border-ink-100 py-3">
                <summary className="cursor-pointer text-sm font-semibold text-ink-800">View evidence & guardrails</summary>
                <div className="mt-4 flex flex-wrap gap-2">{(assistantResult.sources || []).map((source) => <span key={source.id} className="rounded-full border border-ink-100 bg-ink-50 px-3 py-1.5 text-xs font-semibold text-ink-700">{source.id} · {source.label}</span>)}</div>
                {assistantResult.retrieved_evidence?.length > 0 && <div className="mt-4"><p className="text-xs font-semibold uppercase tracking-wide text-ink-500">Retrieved evidence</p><div className="mt-2 grid gap-2">{assistantResult.retrieved_evidence.slice(0, 8).map((item, index) => <div key={`${item.source_id}-${item.field}-${index}`} className="rounded-lg border border-ink-100 bg-ink-50 p-3"><p className="text-xs font-semibold text-ink-700">{item.source_id} · {item.field}</p><p className="mt-1 text-xs leading-5 text-ink-600">{item.text}</p></div>)}</div></div>}
                <div className="mt-4 grid gap-1 text-xs text-ink-600">{(assistantResult.guardrails || []).map((item, index) => <p key={index}>• {item}</p>)}</div>
              </details>
            </div>}
          </section>}
          {view === "automation" && <AutomationPanel token={token} apiRequest={apiRequest} onNotice={setNotice} onError={(requestError) => setError(errorText(requestError))} />}
          {view === "ai-studio" && <AIHiringStudio token={token} apiRequest={apiRequest} jobs={jobs} onSaved={refreshWorkspace} />}
          {view === "jd-match" && <JDApplicantMatch token={token} apiRequest={apiRequest} /> }
          {view === "resume" && <section className="-mx-4 -my-6 sm:-mx-7 sm:-my-8"><ResumeLab theme={theme} onToggleTheme={toggleTheme} token={token} /></section>}
          </main>
        </Suspense>
      </div>

      {token && (
        <AtsChatbot
          token={token}
          apiRequest={apiRequest}
          onError={(requestError) => setError(errorText(requestError))}
        />
      )}

    </div>
  );
}
