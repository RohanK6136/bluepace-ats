import { useEffect, useState } from "react";
import axios from "axios";
import ResumeLab from "./App.jsx";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";
const STAGES = ["Applied", "Screening", "Interview", "Offer", "Hired", "Rejected"];
const buttonPrimary = "inline-flex items-center justify-center gap-2 rounded-md bg-[#c49a4a] px-4 py-2 text-sm font-semibold text-[#10131c] transition hover:bg-[#d4b06a] disabled:cursor-not-allowed disabled:opacity-50";
const buttonSecondary = "inline-flex items-center justify-center gap-2 rounded-md border border-ink-100 bg-white px-3 py-2 text-sm font-semibold text-ink-800 transition hover:bg-ink-50 disabled:cursor-not-allowed disabled:opacity-50";
const inputStyle = "w-full rounded-md border border-ink-100 bg-white px-3 py-2.5 text-sm text-ink-900 outline-none transition placeholder:text-ink-400 focus:border-gold-500 focus:ring-2 focus:ring-gold-100";

function apiRequest(token, method, path, options = {}) {
  return axios.request({
    baseURL: API_URL,
    method,
    url: path,
    ...options,
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  });
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
  const [editingJob, setEditingJob] = useState(null);
  const [jobForm, setJobForm] = useState({ title: "", description: "", department: "", location: "", employment_type: "Full-time", status: "open" });
  const [candidateFormOpen, setCandidateFormOpen] = useState(false);
  const [candidateForm, setCandidateForm] = useState({ first_name: "", last_name: "", email: "", phone: "", source: "Direct" });
  const [resumeFile, setResumeFile] = useState(null);
  const [selectedCandidate, setSelectedCandidate] = useState(null);
  const [applicationFormOpen, setApplicationFormOpen] = useState(false);
  const [applicationForm, setApplicationForm] = useState({ job_id: "", candidate_id: "" });
  const [selectedApplications, setSelectedApplications] = useState([]);
  const [bulkStage, setBulkStage] = useState("Screening");

  const canWrite = user && ["admin", "recruiter"].includes(user.role);

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
        await axios.post(`${API_URL}/auth/register`, authForm);
      }
      const credentials = new URLSearchParams();
      credentials.set("username", authForm.email);
      credentials.set("password", authForm.password);
      const response = await axios.post(`${API_URL}/auth/token`, credentials, {
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
    setJobForm(job ? {
      title: job.title,
      description: job.description,
      department: job.department || "",
      location: job.location || "",
      employment_type: job.employment_type || "Full-time",
      status: job.status,
    } : { title: "", description: "", department: "", location: "", employment_type: "Full-time", status: "open" });
    setJobFormOpen(true);
  }

  async function saveJob(event) {
    event.preventDefault();
    setError("");
    try {
      if (editingJob) {
        await apiRequest(token, "patch", `/jobs/${editingJob.id}`, { data: jobForm });
        setNotice("Job updated");
      } else {
        await apiRequest(token, "post", "/jobs", { data: jobForm });
        setNotice("Job created");
      }
      setJobFormOpen(false);
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
      const response = await apiRequest(token, "post", "/candidates", { data: candidateForm });
      if (resumeFile) {
        const body = new FormData();
        body.append("file", resumeFile);
        await apiRequest(token, "post", `/candidates/${response.data.id}/resume`, { data: body });
      }
      setCandidateForm({ first_name: "", last_name: "", email: "", phone: "", source: "Direct" });
      setResumeFile(null);
      setCandidateFormOpen(false);
      setNotice(resumeFile ? "Candidate added and resume parsed" : "Candidate added");
      await refreshWorkspace();
    } catch (requestError) {
      setError(errorText(requestError));
    }
  }

  async function createApplication(event) {
    event.preventDefault();
    try {
      await apiRequest(token, "post", "/applications", {
        data: { job_id: Number(applicationForm.job_id), candidate_id: Number(applicationForm.candidate_id) },
      });
      setApplicationFormOpen(false);
      setNotice("Application added to Applied");
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

  function toggleApplication(id) {
    setSelectedApplications((current) => current.includes(id)
      ? current.filter((selectedId) => selectedId !== id)
      : [...current, id]);
  }

  function setFilter(field, value) {
    setFilters((current) => ({ ...current, [field]: value }));
  }

  if (!token) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-[#f3f4f1] px-5 py-12 text-ink-900">
        <section className="w-full max-w-md">
          <div className="mb-8 flex items-center gap-3">
            <div className="grid h-11 w-11 place-items-center rounded-md bg-ink-950 text-sm font-bold text-gold-300">BP</div>
            <div>
              <p className="font-semibold">BluePace</p>
              <p className="text-xs text-ink-500">Recruiting workspace</p>
            </div>
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
              <div className="mb-4 flex items-center justify-between"><h2 className="font-semibold">{editingJob ? "Edit job" : "New job"}</h2><button type="button" aria-label="Close form" onClick={() => setJobFormOpen(false)}>×</button></div>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Job title" required value={jobForm.title} onChange={(event) => setJobForm({ ...jobForm, title: event.target.value })} />
                <Field label="Department" value={jobForm.department} onChange={(event) => setJobForm({ ...jobForm, department: event.target.value })} />
                <Field label="Location" value={jobForm.location} onChange={(event) => setJobForm({ ...jobForm, location: event.target.value })} />
                <SelectField label="Employment type" value={jobForm.employment_type} onChange={(event) => setJobForm({ ...jobForm, employment_type: event.target.value })}>{["Full-time", "Part-time", "Contract", "Temporary", "Internship"].map((type) => <option key={type}>{type}</option>)}</SelectField>
                <SelectField label="Status" value={jobForm.status} onChange={(event) => setJobForm({ ...jobForm, status: event.target.value })}>{["draft", "open", "paused", "closed"].map((value) => <option key={value} value={value}>{value}</option>)}</SelectField>
                <label className="grid gap-1.5 text-xs font-semibold text-ink-700 sm:col-span-2">Description<textarea className={`${inputStyle} min-h-28 resize-y`} required value={jobForm.description} onChange={(event) => setJobForm({ ...jobForm, description: event.target.value })} /></label>
              </div>
              <div className="mt-4 flex gap-2"><button className={buttonPrimary} type="submit">{editingJob ? "Save changes" : "Create job"}</button><button className={buttonSecondary} type="button" onClick={() => setJobFormOpen(false)}>Cancel</button></div>
            </form>}
            <div className="mb-5"><p className="text-sm text-ink-500">{jobs.length} total jobs</p><h2 className="mt-1 text-xl font-semibold">Job openings</h2></div>
            <div className="border-y border-ink-100 bg-white">
              <div className="grid grid-cols-[minmax(180px,2fr)_1fr_1fr_100px] gap-3 border-b border-ink-100 bg-[#fafaf8] px-4 py-3 text-[11px] font-semibold uppercase text-ink-500"><span>Role</span><span>Location</span><span>Created</span><span>Status</span></div>
              {jobs.map((job) => <div key={job.id} className="grid grid-cols-1 gap-2 border-b border-ink-50 px-4 py-4 last:border-0 sm:grid-cols-[minmax(180px,2fr)_1fr_1fr_100px] sm:items-center sm:gap-3">
                <div><button className="font-semibold hover:underline" onClick={() => resetJobForm(job)}>{job.title}</button><p className="mt-0.5 text-xs text-ink-500">{job.department || "Unassigned department"} · {job.employment_type || "Employment type not set"}</p></div>
                <span className="text-sm text-ink-600">{job.location || "Remote / unspecified"}</span>
                <span className="text-xs text-ink-500">{new Date(job.created_at).toLocaleDateString()}</span>
                <div className="flex items-center justify-between gap-2"><span className={`rounded-full px-2 py-1 text-[11px] font-semibold ${job.status === "open" ? "bg-emerald-50 text-emerald-800" : job.status === "archived" ? "bg-ink-100 text-ink-500" : "bg-gold-50 text-ink-700"}`}>{job.status}</span>{canWrite && job.status !== "archived" && <button className="text-xs font-medium text-ink-500 underline underline-offset-2" onClick={() => archiveJob(job)}>Archive</button>}</div>
              </div>)}
              {!jobs.length && <EmptyState title="No jobs yet" detail="Create a job to begin building your pipeline." />}
            </div>
          </>}

          {view === "candidates" && <>
            {candidateFormOpen && <form onSubmit={saveCandidate} className="mb-6 border-y border-ink-100 bg-white p-4 sm:p-5">
              <div className="mb-4 flex items-center justify-between"><h2 className="font-semibold">New candidate</h2><button type="button" aria-label="Close form" onClick={() => setCandidateFormOpen(false)}>×</button></div>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                <Field label="First name" required value={candidateForm.first_name} onChange={(event) => setCandidateForm({ ...candidateForm, first_name: event.target.value })} />
                <Field label="Last name" required value={candidateForm.last_name} onChange={(event) => setCandidateForm({ ...candidateForm, last_name: event.target.value })} />
                <Field label="Email" type="email" required value={candidateForm.email} onChange={(event) => setCandidateForm({ ...candidateForm, email: event.target.value })} />
                <Field label="Phone" value={candidateForm.phone} onChange={(event) => setCandidateForm({ ...candidateForm, phone: event.target.value })} />
                <Field label="Source" value={candidateForm.source} onChange={(event) => setCandidateForm({ ...candidateForm, source: event.target.value })} />
                <label className="grid gap-1.5 text-xs font-semibold text-ink-700">Resume (PDF or DOCX)<input className={`${inputStyle} p-2`} type="file" accept=".pdf,.docx" onChange={(event) => setResumeFile(event.target.files?.[0] || null)} /></label>
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
      </div>

      {applicationFormOpen && <div className="fixed inset-0 z-50 grid place-items-center bg-ink-950/50 p-4" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setApplicationFormOpen(false); }}>
        <form onSubmit={createApplication} className="w-full max-w-lg bg-white p-5 shadow-xl">
          <div className="mb-5 flex items-center justify-between"><h2 className="text-lg font-semibold">Add to pipeline</h2><button type="button" aria-label="Close dialog" onClick={() => setApplicationFormOpen(false)}>×</button></div>
          <div className="grid gap-4">
            <SelectField label="Open job" required value={applicationForm.job_id} onChange={(event) => setApplicationForm({ ...applicationForm, job_id: event.target.value })}><option value="">Choose a job</option>{jobs.filter((job) => job.status === "open").map((job) => <option key={job.id} value={job.id}>{job.title}</option>)}</SelectField>
            <SelectField label="Candidate" required value={applicationForm.candidate_id} onChange={(event) => setApplicationForm({ ...applicationForm, candidate_id: event.target.value })}><option value="">Choose a candidate</option>{candidates.map((candidate) => <option key={candidate.id} value={candidate.id}>{candidate.first_name} {candidate.last_name} · {candidate.email}</option>)}</SelectField>
          </div>
          <div className="mt-6 flex justify-end gap-2"><button type="button" className={buttonSecondary} onClick={() => setApplicationFormOpen(false)}>Cancel</button><button type="submit" className={buttonPrimary}>Add application</button></div>
        </form>
      </div>}
    </div>
  );
}