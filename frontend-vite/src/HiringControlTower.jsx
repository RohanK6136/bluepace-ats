import { useCallback, useEffect, useMemo, useState } from "react";
import { getWorkflowStage, isTerminalApplication } from "./hiringWorkflowUtils.mjs";

const button = "inline-flex items-center justify-center rounded-md border border-ink-200 bg-white px-3 py-2 text-xs font-semibold text-ink-700 transition hover:bg-ink-50 disabled:cursor-not-allowed disabled:opacity-50";
const thresholds = [3, 5, 7, 14];

function ageInDays(value, now) {
  if (!value) return null;
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return null;
  return Math.max(0, Math.floor((now - timestamp) / 86_400_000));
}

function displayDate(value) {
  if (!value) return "Time not recorded";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Time not recorded" : date.toLocaleString(undefined, { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
}

function candidateName(application) {
  const candidate = application.candidate || {};
  return [candidate.first_name, candidate.last_name].filter(Boolean).join(" ") || "Unnamed candidate";
}

function Signal({ item, onAction }) {
  const urgency = item.urgency === "urgent"
    ? "border-rose-200 bg-rose-50 text-rose-800"
    : item.urgency === "watch"
      ? "border-amber-200 bg-amber-50 text-amber-900"
      : "border-ink-100 bg-white text-ink-800";
  return (
    <article className="grid gap-3 rounded-lg border border-ink-100 bg-white p-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <span className={`rounded-full border px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${urgency}`}>{item.label}</span>
          <span className="text-xs text-ink-500">{item.context}</span>
        </div>
        <h3 className="mt-2 truncate text-sm font-semibold text-ink-950">{item.title}</h3>
        <p className="mt-1 text-xs leading-5 text-ink-600">{item.reason}</p>
      </div>
      <button type="button" className={button} onClick={onAction}>{item.action}</button>
    </article>
  );
}

function Metric({ label, value, detail, tone = "ink" }) {
  const valueTone = tone === "rose" ? "text-rose-700" : tone === "amber" ? "text-amber-700" : "text-ink-950";
  return <div className="rounded-lg border border-ink-100 bg-white p-4"><p className="text-[10px] font-semibold uppercase tracking-wide text-ink-500">{label}</p><p className={`mt-1 text-2xl font-semibold tabular-nums ${valueTone}`}>{value}</p><p className="mt-1 text-xs text-ink-500">{detail}</p></div>;
}

export default function HiringControlTower({ token, apiRequest, onOpenWorkflow, onOpenInterviews, onOpenJobs }) {
  const [applications, setApplications] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [upcomingInterviews, setUpcomingInterviews] = useState([]);
  const [threshold, setThreshold] = useState(5);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [lastUpdated, setLastUpdated] = useState(null);

  const refresh = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setError("");
    try {
      const [applicationResponse, jobResponse, dashboardResponse] = await Promise.all([
        apiRequest(token, "get", "/applications", { params: { limit: 100 } }),
        apiRequest(token, "get", "/jobs", { params: { limit: 100 } }),
        apiRequest(token, "get", "/dashboard"),
      ]);
      setApplications(Array.isArray(applicationResponse.data) ? applicationResponse.data : []);
      setJobs(Array.isArray(jobResponse.data) ? jobResponse.data : []);
      setUpcomingInterviews(Array.isArray(dashboardResponse.data?.upcoming_interviews) ? dashboardResponse.data.upcoming_interviews : []);
      setLastUpdated(new Date());
    } catch (requestError) {
      const message = requestError?.response?.data?.detail || requestError?.message || "Could not load recruiting activity.";
      setError(String(message));
    } finally {
      setLoading(false);
    }
  }, [apiRequest, token]);

  useEffect(() => { refresh(); }, [refresh]);

  const queue = useMemo(() => {
    const now = Date.now();
    const activeApplications = applications.filter((application) => !isTerminalApplication(application));
    const items = [];

    for (const application of activeApplications) {
      const lastActivity = application.updated_at || application.applied_at;
      const age = ageInDays(lastActivity, now);
      if (age === null || age < threshold) continue;
      const stage = getWorkflowStage(application);
      const stageLabel = stage === "Applied" ? "Initial review" : stage;
      items.push({
        id: `stalled-${application.id}`,
        label: age >= threshold * 2 ? "Needs attention" : "Stalled",
        urgency: age >= threshold * 2 ? "urgent" : "watch",
        context: `${age} days without an update · ${stageLabel}`,
        title: `${candidateName(application)} · ${application.job_title || "Open role"}`,
        reason: `The application has not changed since ${displayDate(lastActivity)}. Consider updating the candidate, recording the next step, or closing the loop.`,
        action: "Review pipeline",
        onAction: () => onOpenWorkflow?.(),
      });
    }

    const applicantsByJob = new Map();
    for (const application of activeApplications) {
      const id = String(application.job_id);
      applicantsByJob.set(id, (applicantsByJob.get(id) || 0) + 1);
    }
    // The API page is bounded. Avoid claiming a role has no applicants if we may
    // have only loaded the first page of a larger pipeline.
    if (applications.length < 100) {
      for (const job of jobs) {
        if (job.status !== "open" || job.archived) continue;
        if ((applicantsByJob.get(String(job.id)) || 0) !== 0) continue;
        items.push({
          id: `empty-role-${job.id}`,
          label: "No applicants",
          urgency: "watch",
          context: "Open requisition",
          title: job.title || "Untitled role",
          reason: "This role is accepting applications but has no active applicants in the current pipeline. Review reach, requirements, or sourcing coverage.",
          action: "Review jobs",
          onAction: () => onOpenJobs?.(),
        });
      }
    }

    for (const interview of upcomingInterviews) {
      const start = Date.parse(interview.starts_at || "");
      const hoursUntil = (start - now) / 3_600_000;
      if (!Number.isFinite(start) || hoursUntil <= 0 || hoursUntil > 24) continue;
      const missingSetup = interview.mode === "online"
        ? !String(interview.meeting_url || "").trim()
        : interview.mode === "offline" && !String(interview.location || "").trim();
      if (!missingSetup) continue;
      const missing = interview.mode === "online" ? "video meeting link" : "interview location";
      items.push({
        id: `interview-setup-${interview.id}`,
        label: "Interview setup",
        urgency: hoursUntil <= 4 ? "urgent" : "watch",
        context: `Starts ${displayDate(interview.starts_at)}`,
        title: `${interview.candidate_name || "Candidate"} · ${interview.job_title || "Interview"}`,
        reason: `This interview is in the next 24 hours and is missing a ${missing}. Add the logistics before the candidate joins.`,
        action: "Open interviews",
        onAction: () => onOpenInterviews?.(),
      });
    }

    return items.sort((a, b) => ({ urgent: 0, watch: 1, normal: 2 }[a.urgency] - ({ urgent: 0, watch: 1, normal: 2 }[b.urgency])));
  }, [applications, jobs, onOpenInterviews, onOpenJobs, onOpenWorkflow, threshold, upcomingInterviews]);

  const urgentCount = queue.filter((item) => item.urgency === "urgent").length;
  const staleCount = queue.filter((item) => item.id.startsWith("stalled-")).length;
  const setupCount = queue.filter((item) => item.id.startsWith("interview-setup-")).length;

  return (
    <section className="grid gap-5">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-500">Recruiting operations</p>
          <h2 className="mt-1 text-xl font-semibold tracking-tight text-ink-950">Hiring Control Tower</h2>
          <p className="mt-1 max-w-2xl text-sm leading-6 text-ink-600">A prioritized queue of workflow gaps—not a candidate ranking. Every signal shows what triggered it and leaves the next decision with your team.</p>
        </div>
        <div className="flex items-center gap-2">
          {lastUpdated && <span className="text-[11px] text-ink-500">Updated {lastUpdated.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}</span>}
          <button type="button" className={button} onClick={refresh} disabled={loading}>{loading ? "Refreshing…" : "Refresh"}</button>
        </div>
      </header>

      <div className="grid gap-3 sm:grid-cols-3">
        <Metric label="Needs attention" value={urgentCount} detail="Time-sensitive workflow gaps" tone="rose" />
        <Metric label="Stalled applications" value={staleCount} detail={`No update for ${threshold}+ days`} tone="amber" />
        <Metric label="Interview setup gaps" value={setupCount} detail="Upcoming interviews missing logistics" />
      </div>

      <section className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-ink-100 bg-[#fafaf8] px-4 py-3">
        <div><h3 className="text-sm font-semibold text-ink-900">Tune the stalled-candidate signal</h3><p className="mt-1 text-xs text-ink-500">An application is flagged after this many days without an ATS update.</p></div>
        <label className="flex items-center gap-2 text-xs font-semibold text-ink-700">Flag after
          <select aria-label="Days without an update before an application is flagged" value={threshold} onChange={(event) => setThreshold(Number(event.target.value))} className="rounded-md border border-ink-200 bg-white px-2.5 py-2 text-xs">
            {thresholds.map((days) => <option key={days} value={days}>{days} days</option>)}
          </select>
        </label>
      </section>

      {error && <div role="alert" className="rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">{error}</div>}
      {loading && !lastUpdated && <div className="rounded-lg border border-ink-100 bg-white p-5 text-sm text-ink-500">Gathering open applications, requisitions, and upcoming interviews…</div>}
      {!loading && !error && queue.length === 0 && <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-5"><h3 className="text-sm font-semibold text-emerald-950">Your workflow is clear</h3><p className="mt-1 text-sm leading-6 text-emerald-900">No stalled applications, empty open requisitions, or imminent interviews missing logistics were found in the data checked.</p></div>}
      {queue.length > 0 && <div className="grid gap-3">{queue.map((item) => <Signal key={item.id} item={item} onAction={item.onAction} />)}</div>}
      <p className="text-[11px] leading-5 text-ink-500">Signals use ATS update times and scheduled interview details. They do not assess candidate quality or make hiring decisions. The queue loads up to 100 applications.</p>
    </section>
  );
}

