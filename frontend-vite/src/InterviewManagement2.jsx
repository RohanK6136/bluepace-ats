import { useEffect, useState } from "react";

const input = "w-full rounded-md border border-ink-100 bg-white px-3 py-2 text-sm";
const primary = "rounded-md bg-[#1769d3] px-3 py-2 text-sm font-semibold text-white disabled:opacity-50";
const secondary = "rounded-md border border-ink-100 bg-white px-3 py-2 text-sm font-semibold text-ink-800";

function findSharedSlots(slots, interviewerIds, durationMinutes) {
  if (!interviewerIds.length) return [];
  const now = Date.now();
  let windows = slots
    .filter((slot) => Number(slot.user_id) === interviewerIds[0] && slot.status === "available")
    .map((slot) => ({ start: Date.parse(slot.starts_at), end: Date.parse(slot.ends_at) }))
    .filter((window) => Number.isFinite(window.start) && Number.isFinite(window.end) && window.end > now);
  for (const userId of interviewerIds.slice(1)) {
    windows = windows.flatMap((window) => slots
      .filter((slot) => Number(slot.user_id) === userId && slot.status === "available")
      .map((slot) => ({ start: Math.max(window.start, Date.parse(slot.starts_at)), end: Math.min(window.end, Date.parse(slot.ends_at)) }))
      .filter((window) => window.end > window.start));
  }
  const duration = Number(durationMinutes) * 60_000;
  const unique = new Map();
  windows.filter((window) => window.start >= now && window.end - window.start >= duration)
    .sort((a, b) => a.start - b.start)
    .forEach((window) => unique.set(`${window.start}:${window.end}`, window));
  return [...unique.values()].slice(0, 6);
}

function localDateTimeValue(timestamp) {
  const date = new Date(timestamp);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
}

export default function InterviewManagement2({ token, apiRequest, applications = [], initialApplicationId = "", initialInterviewRoundNumber = null, initialRescheduleQuestionId = null, onNotice, onError, onOpenFeedback, onRescheduled }) {
  const [availability, setAvailability] = useState([]);
  const [feedbackQueue, setFeedbackQueue] = useState([]);
  const [applicationId, setApplicationId] = useState(applications[0]?.id ? String(applications[0].id) : "");
  const [rounds, setRounds] = useState([]);
  const [reschedulingInterviewId, setReschedulingInterviewId] = useState(null);
  const [portalReplyOnReschedule, setPortalReplyOnReschedule] = useState(true);
  const [users, setUsers] = useState([]);
  const [form, setForm] = useState({ starts_at:"", duration_minutes:60, mode:"online", meeting_url:"", location:"", round_name:"Technical Interview", round_type:"technical", round_number:1, feedback_deadline:"", interviewer_ids:[] });
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const preferred = applications.some((application) => String(application.id) === String(initialApplicationId))
      ? String(initialApplicationId)
      : applications[0]?.id ? String(applications[0].id) : "";
    setApplicationId(preferred);
  }, [applications, initialApplicationId]);
  useEffect(() => {
    Promise.allSettled([
      apiRequest(token, "get", "/interviewers/availability"),
      apiRequest(token, "get", "/recruiting-users"),
    ]).then(([a,u]) => {
      if (a.status === "fulfilled") setAvailability(a.value.data || []);
      if (u.status === "fulfilled") setUsers(u.value.data || []);
      const failed = [a,u].find((result) => result.status === "rejected");
      if (failed) onError(failed.reason);
    });
  }, [token]);

  useEffect(() => {
    let active = true;
    apiRequest(token, "get", "/interviewer-dashboard")
      .then((response) => { if (active) setFeedbackQueue((response.data?.interviews || []).filter((row) => row.status === "completed" && !row.scorecard_submitted)); })
      .catch((error) => { if (active) onError(error); });
    return () => { active = false; };
  }, [apiRequest, token]);

  async function loadRounds() {
    if (!applicationId) return;
    setLoading(true);
    try { const r = await apiRequest(token, "get", "/applications/"+applicationId+"/interviews"); setRounds(r.data || []); }
    catch(e) { onError(e); } finally { setLoading(false); }
  }
  useEffect(() => { loadRounds(); }, [applicationId]);

  useEffect(() => {
    if (!initialInterviewRoundNumber) return;
    const target = rounds.find((round) => Number(round.round_number) === Number(initialInterviewRoundNumber) && round.status !== "cancelled");
    if (!target) return;
    setReschedulingInterviewId(target.id);
    setPortalReplyOnReschedule(true);
    setForm((current) => ({ ...current, starts_at: "", duration_minutes: target.duration_minutes || 60, mode: target.mode || "online", meeting_url: target.meeting_url || "", location: target.location || "", round_name: target.round_name || "Interview", round_type: target.round_type || "technical", round_number: target.round_number || 1, feedback_deadline: target.feedback_deadline ? localDateTimeValue(Date.parse(target.feedback_deadline)) : "", interviewer_ids: [] }));
  }, [rounds, initialInterviewRoundNumber]);

  async function schedule() {
    if (!applicationId || !form.starts_at || (!reschedulingInterviewId && !form.interviewer_ids.length)) return onError({message:"Select an application, time, and at least one interviewer."});
    try {
      const payload = {
        ...form, starts_at:new Date(form.starts_at).toISOString(),
        feedback_deadline: form.feedback_deadline ? new Date(form.feedback_deadline).toISOString() : null,
        duration_minutes:Number(form.duration_minutes), round_number:Number(form.round_number),
      };
      if (reschedulingInterviewId) {
        const response = await apiRequest(token, "patch", "/interviews/"+reschedulingInterviewId+"/reschedule", {data:payload});
        let portalReplyPosted = false;
        if (initialRescheduleQuestionId && portalReplyOnReschedule) {
          const saved = response.data || {};
          const details = [
            `Your ${saved.round_name || "interview"} has been rescheduled to ${saved.starts_at ? new Date(saved.starts_at).toLocaleString() : new Date(payload.starts_at).toLocaleString()}.`,
            saved.mode === "online" && saved.meeting_url ? `Meeting link: ${saved.meeting_url}` : null,
            saved.mode === "offline" && saved.location ? `Location: ${saved.location}` : null,
            "Please contact the recruiting team through your portal if you have questions.",
          ].filter(Boolean).join("\n\n");
          try {
            await apiRequest(token, "patch", `/candidate-portal/questions/${initialRescheduleQuestionId}`, { data: { answer: details, status: "answered" } });
            portalReplyPosted = true;
          } catch {
            onError({ message: "Interview rescheduled, but the candidate portal reply could not be saved. Please answer the request manually." });
          }
        }
        if (portalReplyPosted) {
          onNotice("Interview rescheduled, and the candidate portal was updated. No email was sent.");
        } else if (!initialRescheduleQuestionId || !portalReplyOnReschedule) {
          onNotice("Interview rescheduled. The existing panel assignment was retained.");
        }
        onNotice("Interview rescheduled. The existing panel assignment was retained.");
        setReschedulingInterviewId(null);
        onRescheduled?.();
      } else {
        await apiRequest(token, "post", "/applications/"+applicationId+"/interviews", {data:payload});
        onNotice("Interview round scheduled with the full panel.");
      }
      setForm({...form, starts_at:"", feedback_deadline:""}); await loadRounds();
    } catch(e) { onError(e); }
  }

  function cancelRescheduling() {
    setReschedulingInterviewId(null);
    setForm((current) => ({ ...current, starts_at:"", feedback_deadline:"", round_name:"Technical Interview", round_type:"technical", round_number:1, interviewer_ids:[] }));
    onRescheduled?.();
  }

  async function cancel(id) {
    const reason=window.prompt("Cancellation reason:");
    if (!reason) return;
    try { await apiRequest(token,"post","/interviews/"+id+"/cancel",{params:{reason}}); onNotice("Interview cancelled."); await loadRounds(); }
    catch(e){onError(e);}
  }

  const selected = applications.find(a=>a.id===Number(applicationId));
  const suggestedSlots = findSharedSlots(availability, form.interviewer_ids, form.duration_minutes);

  return <section className="space-y-5">
    <div><p className="text-sm text-ink-500">Scheduling & feedback</p><h2 className="mt-1 text-2xl font-semibold">Interviews</h2></div>
    <section className="rounded-xl border border-amber-200 bg-amber-50/60 p-4 sm:p-5" aria-labelledby="feedback-queue-title">
      <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-xs font-semibold uppercase tracking-wide text-amber-800">Interviewer follow-through</p><h3 id="feedback-queue-title" className="mt-1 font-semibold text-ink-950">Outstanding interview feedback</h3><p className="mt-1 text-xs leading-5 text-ink-600">Completed interviews assigned to you that still need a submitted scorecard.</p></div><span className="rounded-full bg-white px-3 py-1 text-sm font-semibold tabular-nums text-amber-900">{feedbackQueue.length} pending</span></div>
      {feedbackQueue.length > 0 ? <div className="mt-3 grid gap-2">{feedbackQueue.map((row) => {
        const late = row.feedback_deadline && Date.parse(row.feedback_deadline) < Date.now();
        return <div key={row.interview_id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-amber-100 bg-white p-3"><div><p className="text-sm font-semibold text-ink-900">{row.candidate_name} · {row.job_title}</p><p className="mt-1 text-xs text-ink-500">{row.round_name || "Interview"}{row.feedback_deadline ? ` · Due ${new Date(row.feedback_deadline).toLocaleString()}` : " · No deadline set"}</p>{late && <p className="mt-1 text-xs font-semibold text-rose-700">Feedback deadline has passed</p>}</div><button type="button" className={secondary} onClick={() => onOpenFeedback?.(row.application_id)}>Open scorecard</button></div>;
      })}</div> : <p className="mt-3 rounded-lg border border-amber-100 bg-white p-3 text-sm text-emerald-800">No completed interviews are waiting on your feedback.</p>}
    </section>
    <div className="grid gap-5 xl:grid-cols-[1.1fr_.9fr]">
      <div className="rounded-xl border border-ink-100 bg-white p-5">
        <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="font-semibold">{reschedulingInterviewId ? "Reschedule interview" : "Schedule panel interview"}</h3>{reschedulingInterviewId && <button type="button" className={secondary} onClick={cancelRescheduling}>Cancel edit</button>}</div>{reschedulingInterviewId && <p className="mt-2 text-xs text-amber-900">This updates the existing interview round. Its current interviewer assignments remain in place.</p>{initialRescheduleQuestionId && <label className="mt-2 flex items-start gap-2 text-xs text-ink-700"><input type="checkbox" checked={portalReplyOnReschedule} onChange={(event) => setPortalReplyOnReschedule(event.target.checked)} /><span>Post the updated schedule as a reply in the candidate portal. No email will be sent.</span></label>}
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <label className="text-xs font-semibold">Application<select className={input} value={applicationId} onChange={e=>setApplicationId(e.target.value)}><option value="">Select application</option>{applications.map(a=><option key={a.id} value={a.id}>#{a.id} · {a.job_title} · {a.candidate?.first_name} {a.candidate?.last_name}</option>)}</select></label>
          <label className="text-xs font-semibold">Round type<select className={input} value={form.round_type} onChange={e=>setForm({...form,round_type:e.target.value})}><option value="technical">Technical</option><option value="hr">HR</option><option value="manager">Manager</option><option value="custom">Custom</option></select></label>
          <label className="text-xs font-semibold">Round name<input className={input} value={form.round_name} onChange={e=>setForm({...form,round_name:e.target.value})}/></label>
          <label className="text-xs font-semibold">Round number<input className={input} type="number" min="1" value={form.round_number} onChange={e=>setForm({...form,round_number:e.target.value})}/></label>
          <label className="text-xs font-semibold">Start time<input className={input} type="datetime-local" value={form.starts_at} onChange={e=>setForm({...form,starts_at:e.target.value})}/></label>
          <label className="text-xs font-semibold">Duration<input className={input} type="number" min="15" max="480" value={form.duration_minutes} onChange={e=>setForm({...form,duration_minutes:e.target.value})}/></label>
          <label className="text-xs font-semibold">Mode<select className={input} value={form.mode} onChange={e=>setForm({...form,mode:e.target.value})}><option value="online">Online</option><option value="offline">Offline</option></select></label>
          {form.mode==="online"?<label className="text-xs font-semibold">Meeting URL<input className={input} placeholder="https://..." value={form.meeting_url} onChange={e=>setForm({...form,meeting_url:e.target.value})}/></label>:<label className="text-xs font-semibold">Location<input className={input} value={form.location} onChange={e=>setForm({...form,location:e.target.value})}/></label>}
          <label className="text-xs font-semibold">Feedback deadline<input className={input} type="datetime-local" value={form.feedback_deadline} onChange={e=>setForm({...form,feedback_deadline:e.target.value})}/></label>
          {!reschedulingInterviewId && <label className="text-xs font-semibold sm:col-span-2">Interviewers<select multiple className={input+" min-h-28"} value={form.interviewer_ids.map(String)} onChange={e=>setForm({...form,interviewer_ids:Array.from(e.target.selectedOptions).map(o=>Number(o.value))})}>{users.map(u=><option key={u.id} value={u.id}>{u.full_name} · {u.role}</option>)}</select></label>}
          {form.interviewer_ids.length > 0 && <div className="rounded-lg border border-blue-100 bg-blue-50/50 p-3 sm:col-span-2"><p className="text-xs font-semibold text-blue-900">Shared panel availability</p><p className="mt-1 text-xs text-ink-600">Suggestions fit the selected duration and intersect published availability for every selected interviewer.</p>{suggestedSlots.length ? <div className="mt-2 grid gap-2">{suggestedSlots.map((slot) => <div key={`${slot.start}-${slot.end}`} className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-blue-100 bg-white px-3 py-2"><span className="text-xs font-medium text-ink-800">{new Date(slot.start).toLocaleString()} · {Math.floor((slot.end - slot.start) / 60_000)} min window</span><button type="button" className={secondary} onClick={() => setForm({...form, starts_at:localDateTimeValue(slot.start)})}>Use this time</button></div>)}</div> : <p className="mt-2 text-xs text-amber-800">No shared future slot is published for this panel and duration. Ask interviewers to publish overlapping availability or choose a time manually.</p>}</div>}
        </div>
        <button className={primary+" mt-4"} onClick={schedule}>{reschedulingInterviewId ? "Save new interview time" : "Schedule interview"}</button>
      </div>
      <div className="rounded-xl border border-ink-100 bg-white p-5">
        <h3 className="font-semibold">Interviewer availability</h3>
        <p className="mt-1 text-xs text-ink-500">Published organization interviewer availability.</p>
        <div className="mt-4 space-y-2">{availability.map(slot=><div key={slot.id} className="rounded-lg bg-ink-50 p-3 text-sm"><div className="font-semibold">{new Date(slot.starts_at).toLocaleString()} — {new Date(slot.ends_at).toLocaleTimeString()}</div><div className="text-xs text-ink-500">{users.find((user) => user.id === slot.user_id)?.full_name || `Interviewer #${slot.user_id}`} · {slot.status}{slot.note?" · "+slot.note:""}</div></div>)}{!availability.length&&<p className="text-sm text-ink-500">No availability slots published.</p>}</div>
      </div>
    </div>
    <div className="rounded-xl border border-ink-100 bg-white p-5">
      <div className="flex flex-wrap items-center justify-between gap-3"><div><h3 className="font-semibold">{selected ? "Interview rounds · "+selected.candidate?.first_name+" "+selected.candidate?.last_name : "Interview rounds"}</h3><p className="text-xs text-ink-500">Review and manage scheduled interview rounds.</p></div><button className={secondary} onClick={loadRounds} disabled={loading}>{loading?"Loading…":"Refresh"}</button></div>
      <div className="mt-4 divide-y divide-ink-50">{rounds.map(r=><div key={r.id} className="flex flex-wrap items-center justify-between gap-3 py-4"><div><p className="font-semibold">Round {r.round_number} · {r.round_name} <span className="ml-2 rounded-full bg-blue-50 px-2 py-1 text-xs text-blue-800">{r.round_type}</span></p><p className="text-sm text-ink-500">{new Date(r.starts_at).toLocaleString()} · {r.status}{r.feedback_deadline?" · feedback by "+new Date(r.feedback_deadline).toLocaleString():""}</p>{r.cancellation_reason&&<p className="text-xs text-red-600">Cancelled: {r.cancellation_reason}</p>}</div>{r.status==="scheduled"&&<div className="flex gap-2"><a className={secondary} href={(import.meta.env.VITE_API_URL||"https://bluepace-ats-11.onrender.com")+"/interviews/"+r.id+"/ics"}>Calendar</a><button className={secondary} onClick={()=>cancel(r.id)}>Cancel</button></div>}</div>)}{!rounds.length&&<p className="py-8 text-center text-sm text-ink-500">No rounds for this application.</p>}</div>
    </div>
  </section>;
}
