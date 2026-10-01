import { useEffect, useState } from "react";

const secondary = "inline-flex items-center justify-center rounded-md border border-ink-100 bg-white px-3 py-2 text-sm font-semibold text-ink-800 disabled:opacity-50";
const primary = "inline-flex items-center justify-center rounded-md bg-[#c49a4a] px-4 py-2 text-sm font-semibold text-[#10131c]";
const card = "rounded-xl border border-ink-100 bg-white p-4";

export default function CommandCenterPanel({ token, apiRequest, onNotice, onError }) {
  const [data, setData] = useState(null);
  const [analytics, setAnalytics] = useState(null);
  const [interviewer, setInterviewer] = useState(null);
  const [calendar, setCalendar] = useState(null);
  const [loading, setLoading] = useState(true);
  const [reportLoading, setReportLoading] = useState("");

  async function load() {
    setLoading(true);
    try {
      const [dashboardResult, analyticsResult] = await Promise.allSettled([
        apiRequest(token, "get", "/dashboard"),
        apiRequest(token, "get", "/analytics"),
      ]);
      if (dashboardResult.status === "rejected") throw dashboardResult.reason;
      if (analyticsResult.status === "rejected") throw analyticsResult.reason;
      setData(dashboardResult.value.data);
      setAnalytics(analyticsResult.value.data);

      // Optional integrations must never take down the Command Center.
      const dashboard = dashboardResult.value.data || {};
      setInterviewer({
        pending_scorecards: dashboard.pending_scorecards ?? 0,
        interviews: (dashboard.upcoming_interviews || []).map((item) => ({
          interview_id: item.id,
          candidate_name: item.candidate_name,
          job_title: item.job_title,
          round_name: item.mode || "Interview",
          starts_at: item.starts_at,
          scorecard_submitted: false,
          status: item.status || "scheduled",
        })),
      });
      setCalendar({
        message: "Calendar invitations are available through the interview scheduling workflow.",
        google: { configured: false },
        microsoft: { configured: false },
        ics_available: true,
      });
    } catch (error) {
      setData(null);
      setAnalytics(null);
      onError(error);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, [token]);

  async function download(kind) {
    onError(new Error("Recruitment report export is not available in this deployment yet."));
  }

  if (loading) return <section className={card + " text-sm text-ink-500"}>Loading recruitment command center…</section>;
  if (!data) return null;

  const metrics = data.metrics || {};
  const scorecardPending = data.pending_scorecards ?? interviewer?.pending_scorecards ?? 0;

  return (
    <section>
      <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div><p className="text-sm text-ink-500">Jobs → candidates → interviews → feedback → offers → hiring.</p><h2 className="mt-1 text-2xl font-semibold">Recruitment command center</h2></div>
        <div className="flex gap-2"><button className={secondary} onClick={() => download("xlsx")}>Excel report</button><button className={secondary} onClick={() => download("pdf")}>PDF report</button></div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-7">
        {[
          ["Open jobs", metrics.open_jobs],
          ["Applications", metrics.total_applications],
          ["Screening", metrics.screening],
          ["Interviews", metrics.interviews],
          ["Pending scorecards", scorecardPending],
          ["Offers", metrics.offers],
          ["Hired", metrics.hired],
        ].map(([label, value]) => <div key={label} className={card}><p className="text-[10px] font-semibold uppercase tracking-[0.13em] text-ink-500">{label}</p><p className="mt-2 text-2xl font-bold">{value ?? 0}</p></div>)}
      </div>

      <div className="mt-5 grid gap-5 lg:grid-cols-3">
        <section className={card}>
          <p className="text-xs font-semibold uppercase tracking-[0.14em] text-blue-700">Time metrics</p>
          <div className="mt-4 grid gap-3">
            <div><p className="text-xs text-ink-500">Average days per application</p><p className="mt-1 text-xl font-semibold">{analytics?.avg_days_in_application ?? 0}</p></div>
            <div><p className="text-xs text-ink-500">Average days to hire</p><p className="mt-1 text-xl font-semibold">{analytics?.avg_days_to_hire ?? 0}</p></div>
            <div><p className="text-xs text-ink-500">Top source</p><p className="mt-1 text-sm font-semibold">{analytics?.sources?.[0]?.name || "No source data"}</p></div>
          </div>
        </section>

        <section className={card + " lg:col-span-2"}>
          <div className="flex items-center justify-between"><div><p className="text-xs font-semibold uppercase tracking-[0.14em] text-blue-700">Upcoming workload</p><h3 className="mt-1 font-semibold">Interviews and feedback</h3></div><span className="text-xs text-ink-500">{interviewer?.interviews?.length || 0} visible</span></div>
          <div className="mt-4 grid gap-2">
            {(interviewer?.interviews || []).slice(0,6).map((item) => <div key={item.interview_id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-[#fafaf8] p-3 text-sm"><div><p className="font-semibold">{item.candidate_name} · {item.job_title}</p><p className="mt-1 text-xs text-ink-500">{item.round_name} · {new Date(item.starts_at).toLocaleString()}</p></div><span className={item.scorecard_submitted ? "rounded-full bg-emerald-50 px-2 py-1 text-[11px] font-semibold text-emerald-800" : "rounded-full bg-amber-50 px-2 py-1 text-[11px] font-semibold text-amber-800"}>{item.scorecard_submitted ? "Feedback submitted" : item.status === "completed" ? "Feedback pending" : item.status}</span></div>)}
            {!interviewer?.interviews?.length && <p className="text-sm text-ink-500">No interview workload is assigned to this account.</p>}
          </div>
        </section>
      </div>

      <div className="mt-5 grid gap-5 lg:grid-cols-2">
        <section className={card}>
          <p className="text-xs font-semibold uppercase tracking-[0.14em] text-blue-700">Application funnel</p>
          <div className="mt-4 grid gap-2">{Object.entries(data.stage_counts || {}).map(([stage, count]) => <div key={stage} className="flex items-center justify-between border-b border-ink-50 py-2 text-sm last:border-0"><span>{stage}</span><span className="font-semibold">{count}</span></div>)}</div>
        </section>

        <section className={card}>
          <p className="text-xs font-semibold uppercase tracking-[0.14em] text-blue-700">Calendar integrations</p>
          <p className="mt-2 text-sm text-ink-500">{calendar?.message}</p>
          <div className="mt-4 grid gap-2 sm:grid-cols-3">
            <div className="rounded-lg border border-ink-100 p-3"><p className="text-xs font-semibold">Google Calendar</p><p className="mt-1 text-xs">{calendar?.google?.configured ? "OAuth configured" : "ICS fallback"}</p></div>
            <div className="rounded-lg border border-ink-100 p-3"><p className="text-xs font-semibold">Microsoft 365</p><p className="mt-1 text-xs">{calendar?.microsoft?.configured ? "OAuth configured" : "ICS fallback"}</p></div>
            <div className="rounded-lg border border-ink-100 p-3"><p className="text-xs font-semibold">Universal calendar</p><p className="mt-1 text-xs">{calendar?.ics_available ? "ICS available" : "Unavailable"}</p></div>
          </div>
          <p className="mt-3 text-[11px] text-ink-500">Provider credentials are intentionally kept in server environment variables, not recruiter browser storage.</p>
        </section>
      </div>

      <section className={card + " mt-5"}>
        <div className="flex flex-wrap items-center justify-between gap-3"><div><p className="text-xs font-semibold uppercase tracking-[0.14em] text-blue-700">Aging and source signals</p><h3 className="mt-1 font-semibold">Operational visibility</h3></div><button className={primary} onClick={load}>Refresh data</button></div>
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <div><p className="text-xs font-semibold text-ink-600">Sources</p><div className="mt-2 grid gap-2">{(analytics?.sources || []).slice(0,8).map((item) => <div key={item.name} className="flex justify-between text-sm"><span>{item.name}</span><span className="font-semibold">{item.count}</span></div>)}</div></div>
          <div><p className="text-xs font-semibold text-ink-600">Recent applications</p><div className="mt-2 grid gap-2">{(data.recent_applications || []).slice(0,6).map((item) => <div key={item.id} className="flex justify-between gap-3 text-sm"><span className="truncate">{item.candidate_name} · {item.job_title}</span><span className="text-xs text-ink-500">{item.stage_name}</span></div>)}</div></div>
        </div>
      </section>
    </section>
  );
}
