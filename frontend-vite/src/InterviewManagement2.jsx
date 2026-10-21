import { useEffect, useState } from "react";

const input = "w-full rounded-md border border-ink-100 bg-white px-3 py-2 text-sm";
const primary = "rounded-md bg-[#1769d3] px-3 py-2 text-sm font-semibold text-white disabled:opacity-50";
const secondary = "rounded-md border border-ink-100 bg-white px-3 py-2 text-sm font-semibold text-ink-800";

export default function InterviewManagement2({ token, apiRequest, applications = [], onNotice, onError }) {
  const [availability, setAvailability] = useState([]);
  const [applicationId, setApplicationId] = useState(applications[0]?.id ? String(applications[0].id) : "");
  const [rounds, setRounds] = useState([]);
  const [users, setUsers] = useState([]);
  const [form, setForm] = useState({ starts_at:"", duration_minutes:60, mode:"online", meeting_url:"", location:"", round_name:"Technical Interview", round_type:"technical", round_number:1, feedback_deadline:"", interviewer_ids:[] });
  const [loading, setLoading] = useState(false);

  useEffect(() => { setApplicationId(applications[0]?.id ? String(applications[0].id) : ""); }, [applications]);
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

  async function loadRounds() {
    if (!applicationId) return;
    setLoading(true);
    try { const r = await apiRequest(token, "get", "/applications/"+applicationId+"/interviews"); setRounds(r.data || []); }
    catch(e) { onError(e); } finally { setLoading(false); }
  }
  useEffect(() => { loadRounds(); }, [applicationId]);

  async function schedule() {
    if (!applicationId || !form.starts_at || !form.interviewer_ids.length) return onError({message:"Select an application, time, and at least one interviewer."});
    try {
      await apiRequest(token, "post", "/applications/"+applicationId+"/interviews", {data:{
        ...form, starts_at:new Date(form.starts_at).toISOString(),
        feedback_deadline: form.feedback_deadline ? new Date(form.feedback_deadline).toISOString() : null,
        duration_minutes:Number(form.duration_minutes), round_number:Number(form.round_number),
      }});
      onNotice("Interview round scheduled with the full panel."); setForm({...form, starts_at:"", feedback_deadline:""}); await loadRounds();
    } catch(e) { onError(e); }
  }

  async function cancel(id) {
    const reason=window.prompt("Cancellation reason:");
    if (!reason) return;
    try { await apiRequest(token,"post","/interviews/"+id+"/cancel",{params:{reason}}); onNotice("Interview cancelled."); await loadRounds(); }
    catch(e){onError(e);}
  }

  const selected = applications.find(a=>a.id===Number(applicationId));

  return <section className="space-y-5">
    <div><p className="text-sm text-ink-500">Scheduling & feedback</p><h2 className="mt-1 text-2xl font-semibold">Interviews</h2></div>
    <div className="grid gap-5 xl:grid-cols-[1.1fr_.9fr]">
      <div className="rounded-xl border border-ink-100 bg-white p-5">
        <h3 className="font-semibold">Schedule panel interview</h3>
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
          <label className="text-xs font-semibold sm:col-span-2">Interviewers<select multiple className={input+" min-h-28"} value={form.interviewer_ids.map(String)} onChange={e=>setForm({...form,interviewer_ids:Array.from(e.target.selectedOptions).map(o=>Number(o.value))})}>{users.map(u=><option key={u.id} value={u.id}>{u.full_name} · {u.role}</option>)}</select></label>
        </div>
        <button className={primary+" mt-4"} onClick={schedule}>Schedule interview</button>
      </div>
      <div className="rounded-xl border border-ink-100 bg-white p-5">
        <h3 className="font-semibold">Interviewer availability</h3>
        <p className="mt-1 text-xs text-ink-500">Your published availability slots.</p>
        <div className="mt-4 space-y-2">{availability.map(slot=><div key={slot.id} className="rounded-lg bg-ink-50 p-3 text-sm"><div className="font-semibold">{new Date(slot.starts_at).toLocaleString()} — {new Date(slot.ends_at).toLocaleTimeString()}</div><div className="text-xs text-ink-500">{slot.status}{slot.note?" · "+slot.note:""}</div></div>)}{!availability.length&&<p className="text-sm text-ink-500">No availability slots published.</p>}</div>
      </div>
    </div>
    <div className="rounded-xl border border-ink-100 bg-white p-5">
      <div className="flex flex-wrap items-center justify-between gap-3"><div><h3 className="font-semibold">{selected ? "Interview rounds · "+selected.candidate?.first_name+" "+selected.candidate?.last_name : "Interview rounds"}</h3><p className="text-xs text-ink-500">Review and manage scheduled interview rounds.</p></div><button className={secondary} onClick={loadRounds} disabled={loading}>{loading?"Loading…":"Refresh"}</button></div>
      <div className="mt-4 divide-y divide-ink-50">{rounds.map(r=><div key={r.id} className="flex flex-wrap items-center justify-between gap-3 py-4"><div><p className="font-semibold">Round {r.round_number} · {r.round_name} <span className="ml-2 rounded-full bg-blue-50 px-2 py-1 text-xs text-blue-800">{r.round_type}</span></p><p className="text-sm text-ink-500">{new Date(r.starts_at).toLocaleString()} · {r.status}{r.feedback_deadline?" · feedback by "+new Date(r.feedback_deadline).toLocaleString():""}</p>{r.cancellation_reason&&<p className="text-xs text-red-600">Cancelled: {r.cancellation_reason}</p>}</div>{r.status==="scheduled"&&<div className="flex gap-2"><a className={secondary} href={(import.meta.env.VITE_API_URL||"https://bluepace-ats-11.onrender.com")+"/interviews/"+r.id+"/ics"}>Calendar</a><button className={secondary} onClick={()=>cancel(r.id)}>Cancel</button></div>}</div>)}{!rounds.length&&<p className="py-8 text-center text-sm text-ink-500">No rounds for this application.</p>}</div>
    </div>
  </section>;
}
