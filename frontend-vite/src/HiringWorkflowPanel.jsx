import { useEffect, useMemo, useState } from "react";
import {
  BOARD_STAGES,
  filterWorkflowApplications,
  getNextWorkflowStage,
  getWorkflowStage,
  isTerminalApplication,
  summarizeWorkflow,
  buildWorkflowStagePayload,
} from "./hiringWorkflowUtils.mjs";

const input = "w-full rounded-md border border-ink-200 bg-white px-3 py-2.5 text-sm text-ink-900 outline-none focus:border-amber-500 focus:ring-2 focus:ring-amber-100";
const primary = "inline-flex items-center justify-center rounded-md bg-[#c49a4a] px-3 py-2 text-xs font-semibold text-[#10131c] transition hover:bg-[#d4b06a] disabled:cursor-not-allowed disabled:opacity-50";
const secondary = "inline-flex items-center justify-center rounded-md border border-ink-200 bg-white px-3 py-2 text-xs font-semibold text-ink-700 transition hover:bg-ink-50 disabled:cursor-not-allowed disabled:opacity-50";

function candidateName(application) {
  const candidate = application.candidate || {};
  return [candidate.first_name, candidate.last_name].filter(Boolean).join(" ") || "Unnamed candidate";
}

function dateLabel(value) {
  if (!value) return "Date unavailable";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Date unavailable" : date.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

function Metric({ label, value, detail }) {
  return (
    <div className="rounded-lg border border-ink-100 bg-white p-3">
      <p className="text-[10px] font-semibold uppercase tracking-wide text-ink-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums text-ink-950">{value}</p>
      {detail && <p className="mt-1 text-xs text-ink-500">{detail}</p>}
    </div>
  );
}

export default function HiringWorkflowPanel({ token, applications = [], jobs = [], canWrite = false, apiRequest, onNotice, onError, onRefresh }) {
  const [rows, setRows] = useState(applications);
  const [search, setSearch] = useState("");
  const [jobId, setJobId] = useState("all");
  const [stageFilter, setStageFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [savingId, setSavingId] = useState(null);
  const [interviewApplication, setInterviewApplication] = useState(null);
  const [interviewForm, setInterviewForm] = useState({
    starts_at: "",
    duration_minutes: "60",
    mode: "online",
    location: "",
    meeting_url: "",
  });
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => { setRows(applications); }, [applications]);

  const filtered = useMemo(
    () => filterWorkflowApplications(rows, { search, jobId, stage: stageFilter, status: statusFilter }),
    [rows, search, jobId, stageFilter, statusFilter],
  );
  const summary = useMemo(() => summarizeWorkflow(filtered), [filtered]);

  async function refresh() {
    if (!onRefresh || refreshing) return;
    setRefreshing(true);
    try {
      await onRefresh();
      onNotice?.("Hiring workflow refreshed.");
    } catch (error) {
      onError?.(error);
    } finally {
      setRefreshing(false);
    }
  }

  function openInterview(application) {
    setInterviewApplication(application);
    setInterviewForm({ starts_at: "", duration_minutes: "60", mode: "online", location: "", meeting_url: "" });
  }

  async function moveApplication(application, targetStage, details = {}) {
    if (!canWrite || savingId !== null) return;
    if (targetStage === "Hired" && !window.confirm("Mark " + candidateName(application) + " as hired? This closes the application.")) return;
    if (targetStage === "Rejected" && !window.confirm("Reject " + candidateName(application) + " for " + application.job_title + "?")) return;

    let payload;
    try {
      payload = buildWorkflowStagePayload(targetStage, details);
    } catch (validationError) {
      onError?.(validationError);
      return;
    }

    setSavingId(application.id);
    try {
      const response = await apiRequest(token, "post", "/applications/" + application.id + "/stage", { data: payload });
      const updated = response.data && typeof response.data === "object" ? response.data : {};
      setRows((current) => current.map((row) => row.id === application.id
        ? { ...row, ...updated, stage_name: updated.stage_name || targetStage, status: updated.status || (targetStage === "Hired" ? "hired" : targetStage === "Rejected" ? "rejected" : "active") }
        : row));
      setInterviewApplication(null);
      onNotice?.(candidateName(application) + " moved to " + targetStage + ".");
      try { await onRefresh?.(); } catch { /* Keep the successful local transition visible if refresh fails. */ }
    } catch (error) {
      onError?.(error);
    } finally {
      setSavingId(null);
    }
  }

  async function submitInterview(event) {
    event.preventDefault();
    if (!interviewApplication) return;
    await moveApplication(interviewApplication, "Interview", interviewForm);
  }

  const openJobs = jobs.filter((job) => job.status !== "archived");
  const stageTone = {
    Applied: "border-slate-200 bg-slate-50 text-slate-700",
    Screening: "border-blue-200 bg-blue-50 text-blue-800",
    Interview: "border-violet-200 bg-violet-50 text-violet-800",
    Offer: "border-amber-200 bg-amber-50 text-amber-800",
    Hired: "border-emerald-200 bg-emerald-50 text-emerald-800",
    Rejected: "border-rose-200 bg-rose-50 text-rose-800",
    Withdrawn: "border-slate-200 bg-slate-100 text-slate-600",
  };

  return (
    <section className="grid gap-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-500">Recruitment operations</p>
          <h2 className="mt-1 text-xl font-semibold tracking-tight text-ink-950">Hiring Workflow</h2>
          <p className="mt-1 max-w-2xl text-sm leading-6 text-ink-600">Track every application from first review to outcome. Stage changes are recorded by the ATS, and moving a candidate to Interview requires scheduling details.</p>
        </div>
        <button type="button" className={secondary} disabled={refreshing || savingId !== null} onClick={refresh}>
          {refreshing ? "Refreshing…" : "Refresh"}
        </button>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <Metric label="Applications" value={summary.total} detail="Matching the current filters" />
        <Metric label="In progress" value={summary.active} detail="Not yet closed" />
        <Metric label="Interview" value={summary.interviews} />
        <Metric label="Offers" value={summary.offers} />
        <Metric label="Hired" value={summary.hired} />
      </div>

      <div className="grid gap-3 rounded-xl border border-ink-100 bg-white p-4 sm:grid-cols-2 xl:grid-cols-4">
        <label className="grid gap-1.5 text-xs font-semibold text-ink-700">
          Search candidates or jobs
          <input className={input} value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Name, email, job title…" />
        </label>
        <label className="grid gap-1.5 text-xs font-semibold text-ink-700">
          Job
          <select className={input} value={jobId} onChange={(event) => setJobId(event.target.value)}>
            <option value="all">All jobs</option>
            {openJobs.map((job) => <option key={job.id} value={String(job.id)}>{job.title}</option>)}
          </select>
        </label>
        <label className="grid gap-1.5 text-xs font-semibold text-ink-700">
          Stage
          <select className={input} value={stageFilter} onChange={(event) => setStageFilter(event.target.value)}>
            <option value="all">All stages</option>
            {BOARD_STAGES.map((stage) => <option key={stage} value={stage}>{stage}</option>)}
          </select>
        </label>
        <label className="grid gap-1.5 text-xs font-semibold text-ink-700">
          Application status
          <select className={input} value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
            <option value="all">Active and closed</option>
            <option value="active">In progress only</option>
            <option value="closed">Closed outcomes only</option>
          </select>
        </label>
      </div>

      {!filtered.length ? (
        <div className="rounded-xl border border-dashed border-ink-200 bg-white px-5 py-12 text-center">
          <p className="text-sm font-semibold text-ink-800">No applications match these filters</p>
          <p className="mt-1 text-sm text-ink-500">Try another job or stage, or clear the search to see the full pipeline.</p>
          <button type="button" className={secondary + " mt-3"} onClick={() => { setSearch(""); setJobId("all"); setStageFilter("all"); setStatusFilter("all"); }}>Clear filters</button>
        </div>
      ) : (
        <div className="overflow-x-auto pb-2">
          <div className="grid min-w-max grid-flow-col auto-cols-[280px] gap-3">
            {BOARD_STAGES.map((stage) => {
              const stageRows = filtered.filter((application) => getWorkflowStage(application) === stage);
              return (
                <section key={stage} className="flex min-h-64 flex-col rounded-xl border border-ink-100 bg-[#f8f8f6] p-3">
                  <div className="mb-3 flex items-center justify-between gap-2 border-b border-ink-100 pb-3">
                    <div className="flex items-center gap-2">
                      <span className={"rounded-md border px-2 py-1 text-[11px] font-semibold " + (stageTone[stage] || stageTone.Applied)}>{stage}</span>
                    </div>
                    <span className="rounded-full bg-white px-2 py-0.5 text-xs font-semibold tabular-nums text-ink-600">{stageRows.length}</span>
                  </div>
                  <div className="grid content-start gap-3">
                    {stageRows.map((application) => {
                      const terminal = isTerminalApplication(application);
                      const nextStage = getNextWorkflowStage(stage);
                      const isSaving = savingId === application.id;
                      return (
                        <article key={application.id} className="rounded-lg border border-ink-100 bg-white p-3 shadow-sm">
                          <div className="flex items-start justify-between gap-2">
                            <div className="min-w-0">
                              <h3 className="break-words text-sm font-semibold text-ink-950">{candidateName(application)}</h3>
                              <p className="mt-1 break-words text-xs leading-5 text-ink-600">{application.job_title || "Job title unavailable"}</p>
                            </div>
                            <span className="shrink-0 rounded-md bg-ink-50 px-2 py-1 text-[10px] font-semibold text-ink-600">#{application.id}</span>
                          </div>
                          <div className="mt-3 space-y-1 border-t border-ink-100 pt-3 text-xs text-ink-500">
                            <p className="break-words">{application.candidate?.email || "No email provided"}</p>
                            <p>Applied {dateLabel(application.applied_at)}</p>
                            {application.candidate?.source && <p>Source: {application.candidate.source}</p>}
                            <p className="font-medium text-ink-700">Status: {String(application.status || "active").replaceAll("_", " ")}</p>
                          </div>
                          {!terminal && canWrite && (
                            <div className="mt-3 grid gap-2">
                              {nextStage === "Interview" ? (
                                <button type="button" className={primary} disabled={savingId !== null} onClick={() => openInterview(application)}>Schedule interview</button>
                              ) : nextStage ? (
                                <button type="button" className={primary} disabled={savingId !== null} onClick={() => moveApplication(application, nextStage)}>{nextStage === "Hired" ? "Mark hired" : "Move to " + nextStage}</button>
                              ) : null}
                              <button type="button" className={secondary + " text-rose-700"} disabled={savingId !== null} onClick={() => moveApplication(application, "Rejected")}>Reject application</button>
                            </div>
                          )}
                          {terminal && <p className="mt-3 rounded-md bg-ink-50 px-2.5 py-2 text-[11px] text-ink-500">This application is closed.</p>}
                          {!terminal && !canWrite && <p className="mt-3 rounded-md bg-ink-50 px-2.5 py-2 text-[11px] text-ink-500">Read-only view. A recruiter or admin can update this stage.</p>}
                          {isSaving && <p className="mt-2 text-[11px] text-ink-500" role="status">Saving stage change…</p>}
                        </article>
                      );
                    })}
                    {!stageRows.length && <p className="rounded-md border border-dashed border-ink-200 bg-white/60 px-3 py-6 text-center text-xs text-ink-400">No applications</p>}
                  </div>
                </section>
              );
            })}
          </div>
        </div>
      )}

      {interviewApplication && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && savingId === null) setInterviewApplication(null); }}>
          <section role="dialog" aria-modal="true" aria-labelledby="workflow-interview-title" className="max-h-[90vh] w-full max-w-xl overflow-y-auto rounded-xl bg-white p-5 shadow-xl">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h3 id="workflow-interview-title" className="text-lg font-semibold text-ink-950">Schedule interview</h3>
                <p className="mt-1 text-sm text-ink-500">{candidateName(interviewApplication)} · {interviewApplication.job_title}</p>
              </div>
              <button type="button" className={secondary} disabled={savingId !== null} onClick={() => setInterviewApplication(null)}>Close</button>
            </div>
            <form className="mt-4 grid gap-3 sm:grid-cols-2" onSubmit={submitInterview}>
              <label className="grid gap-1.5 text-xs font-semibold text-ink-700 sm:col-span-2">
                Date and time
                <input className={input} type="datetime-local" required value={interviewForm.starts_at} onChange={(event) => setInterviewForm((form) => ({ ...form, starts_at: event.target.value }))} />
              </label>
              <label className="grid gap-1.5 text-xs font-semibold text-ink-700">
                Duration (minutes)
                <input className={input} type="number" min="15" max="480" step="15" required value={interviewForm.duration_minutes} onChange={(event) => setInterviewForm((form) => ({ ...form, duration_minutes: event.target.value }))} />
              </label>
              <label className="grid gap-1.5 text-xs font-semibold text-ink-700">
                Interview mode
                <select className={input} value={interviewForm.mode} onChange={(event) => setInterviewForm((form) => ({ ...form, mode: event.target.value }))}>
                  <option value="online">Online</option>
                  <option value="offline">In person</option>
                </select>
              </label>
              {interviewForm.mode === "online" ? (
                <label className="grid gap-1.5 text-xs font-semibold text-ink-700 sm:col-span-2">
                  Meeting link
                  <input className={input} type="url" required placeholder="https://…" value={interviewForm.meeting_url} onChange={(event) => setInterviewForm((form) => ({ ...form, meeting_url: event.target.value }))} />
                </label>
              ) : (
                <label className="grid gap-1.5 text-xs font-semibold text-ink-700 sm:col-span-2">
                  Location
                  <input className={input} required maxLength={500} placeholder="Office / meeting room" value={interviewForm.location} onChange={(event) => setInterviewForm((form) => ({ ...form, location: event.target.value }))} />
                </label>
              )}
              <div className="flex justify-end gap-2 border-t border-ink-100 pt-3 sm:col-span-2">
                <button type="button" className={secondary} disabled={savingId !== null} onClick={() => setInterviewApplication(null)}>Cancel</button>
                <button type="submit" className={primary} disabled={savingId !== null}>{savingId === interviewApplication.id ? "Scheduling…" : "Schedule and move to Interview"}</button>
              </div>
            </form>
          </section>
        </div>
      )}
    </section>
  );
}
