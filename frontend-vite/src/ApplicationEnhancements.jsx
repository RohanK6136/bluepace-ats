import { useEffect, useState } from "react";

const input = "w-full rounded-md border border-ink-100 bg-white px-3 py-2 text-sm";
const primary = "rounded-md bg-[#c49a4a] px-3 py-2 text-sm font-semibold text-[#10131c]";
const secondary = "rounded-md border border-ink-100 bg-white px-3 py-2 text-sm font-semibold text-ink-800";

export default function ApplicationEnhancements({ token, applications, candidateId, apiRequest, onNotice, onError }) {
  const candidateApplications = applications.filter((item) => item.candidate_id === candidateId);
  const [applicationId, setApplicationId] = useState(candidateApplications[0]?.id ? String(candidateApplications[0].id) : "");
  const [comparison, setComparison] = useState(null);
  const [notes, setNotes] = useState([]);
  const [note, setNote] = useState("");
  const [offer, setOffer] = useState(null);
  const [offerForm, setOfferForm] = useState({ position_title: "", annual_ctc: "", currency: "INR", joining_date: "", offer_letter_url: "", notes: "", probation_period: "", expires_at: "", ctc_breakdown: "", benefits: "" });
  const [interviews, setInterviews] = useState([]);
  const [interviewForm, setInterviewForm] = useState({ starts_at: "", duration_minutes: "60", mode: "online", location: "", meeting_url: "", round_name: "Technical interview", feedback_deadline: "" });

  useEffect(() => {
    const first = candidateApplications[0]?.id ? String(candidateApplications[0].id) : "";
    setApplicationId(first);
  }, [candidateId, applications.length]);

  async function load() {
    if (!applicationId) return;
    try {
      const [comparisonResponse, notesResponse, interviewsResponse, offerResponse] = await Promise.all([
        apiRequest(token, "get", "/applications/" + applicationId + "/comparison"),
        apiRequest(token, "get", "/applications/" + applicationId + "/notes"),
        apiRequest(token, "get", "/applications/" + applicationId + "/interviews"),
        apiRequest(token, "get", "/applications/" + applicationId + "/offer").catch(() => ({ data: null })),
      ]);
      setComparison(comparisonResponse.data);
      setNotes(notesResponse.data || []);
      setInterviews(interviewsResponse.data || []);
      setOffer(offerResponse.data || null);
      if (offerResponse.data) setOfferForm({ position_title: offerResponse.data.position_title || "", annual_ctc: offerResponse.data.annual_ctc || "", currency: offerResponse.data.currency || "INR", joining_date: offerResponse.data.joining_date ? new Date(offerResponse.data.joining_date).toISOString().slice(0,16) : "", offer_letter_url: offerResponse.data.offer_letter_url || "", notes: offerResponse.data.notes || "", probation_period: offerResponse.data.probation_period || "", expires_at: offerResponse.data.expires_at ? new Date(offerResponse.data.expires_at).toISOString().slice(0,16) : "", ctc_breakdown: Object.entries(offerResponse.data.ctc_breakdown || {}).map(([key,value]) => key + ": " + value).join("\n"), benefits: (offerResponse.data.benefits || []).join("\n") });
    } catch (error) { onError(error); }
  }

  useEffect(() => { load(); }, [applicationId]);

  async function addNote(event) {
    event.preventDefault();
    if (!note.trim()) return;
    try {
      await apiRequest(token, "post", "/applications/" + applicationId + "/notes", { data: { body: note.trim() } });
      setNote(""); await load(); onNotice("Recruiter note added");
    } catch (error) { onError(error); }
  }

  async function saveOffer(event) {
    event.preventDefault();
    try {
      const payload = { ...offerForm, joining_date: offerForm.joining_date ? new Date(offerForm.joining_date).toISOString() : null, expires_at: offerForm.expires_at ? new Date(offerForm.expires_at).toISOString() : null, ctc_breakdown: Object.fromEntries(offerForm.ctc_breakdown.split("\n").map((line) => line.split(":").map((part) => part.trim())).filter((parts) => parts.length >= 2 && parts[0])), benefits: offerForm.benefits.split(/\n|,/).map((item) => item.trim()).filter(Boolean) };
      const response = await apiRequest(token, "post", "/applications/" + applicationId + "/offer", { data: payload });
      setOffer(response.data); onNotice("Offer saved");
    } catch (error) { onError(error); }
  }

  async function transitionOffer(status) {
    if (!applicationId) return;
    try {
      const response = await apiRequest(token, "post", "/applications/" + applicationId + "/offer/transition", { data: { status } });
      setOffer((value) => ({ ...value, status: response.data.status }));
      onNotice("Offer moved to " + status.replaceAll("_", " "));
    } catch (error) { onError(error); }
  }

  async function sendOffer() {
    try {
      await apiRequest(token, "post", "/applications/" + applicationId + "/offer/send");
      setOffer((value) => ({ ...value, status: "sent" }));
      onNotice("Offer sent to the candidate");
    } catch (error) { onError(error); }
  }

  async function scheduleRound(event) {
    event.preventDefault();
    try {
      const payload = { ...interviewForm, duration_minutes: Number(interviewForm.duration_minutes), starts_at: new Date(interviewForm.starts_at).toISOString(), feedback_deadline: interviewForm.feedback_deadline ? new Date(interviewForm.feedback_deadline).toISOString() : null };
      const response = await apiRequest(token, "post", "/applications/" + applicationId + "/interviews", { data: payload });
      setInterviews((items) => [...items, response.data].sort((a,b) => a.round_number - b.round_number));
      onNotice("Interview round scheduled");
    } catch (error) { onError(error); }
  }

  async function updateInterviewStatus(id, status) {
    try { await apiRequest(token, "patch", "/interviews/" + id + "/status", { data: { status } }); setInterviews((items) => items.map((item) => item.id === id ? { ...item, status } : item)); onNotice("Interview updated"); }
    catch (error) { onError(error); }
  }

  const selected = candidateApplications.find((item) => item.id === Number(applicationId));
  if (!candidateApplications.length) return null;

  return (
    <section className="mt-6 border-t border-ink-100 pt-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div><p className="text-xs font-semibold uppercase tracking-[0.18em] text-blue-700">ATS 2.0 tools</p><h4 className="mt-1 font-semibold">Application workspace</h4></div>
        <select className={input} value={applicationId} onChange={(e) => setApplicationId(e.target.value)}>{candidateApplications.map((item) => <option key={item.id} value={item.id}>{item.job_title} · #{item.id}</option>)}</select>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <section className="rounded-xl border border-ink-100 p-4">
          <p className="text-xs font-semibold uppercase text-blue-700">JD vs Resume</p>
          {comparison && <><p className="mt-2 text-2xl font-bold">{comparison.score}/100</p><div className="mt-3 flex flex-wrap gap-2">{comparison.matched_skills?.map((s) => <span key={s} className="rounded-full bg-emerald-50 px-2 py-1 text-xs text-emerald-800">{s}</span>)}{comparison.missing_skills?.map((s) => <span key={"m"+s} className="rounded-full bg-rose-50 px-2 py-1 text-xs text-rose-800">{s}</span>)}</div><p className="mt-3 text-xs text-ink-600">Experience: {comparison.experience_estimated} years {comparison.experience_required != null ? " / " + comparison.experience_required + "+ required" : ""}</p><p className="mt-2 text-xs text-ink-600">Education: {comparison.education_requirement}</p>{comparison.education_evidence?.length > 0 && <p className="mt-1 text-xs text-ink-500">Evidence: {comparison.education_evidence.join(" · ")}</p>}<p className="mt-2 text-xs text-ink-600">Projects: {(comparison.project_evidence || []).slice(0,4).join(" · ") || "None parsed"}</p>{comparison.gaps?.length > 0 && <p className="mt-2 text-xs text-rose-700">Gaps: {comparison.gaps.join(" · ")}</p>}</>}
        </section>

        <section className="rounded-xl border border-ink-100 p-4">
          <p className="text-xs font-semibold uppercase text-blue-700">Recruiter notes</p>
          <form onSubmit={addNote} className="mt-3 flex gap-2"><input className={input} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Add an internal note…" /><button className={primary} type="submit">Add</button></form>
          <div className="mt-3 max-h-48 overflow-auto grid gap-2">{notes.map((item) => <div key={item.id} className="rounded-lg bg-[#fafaf8] p-3"><p className="text-xs font-semibold">{item.author_name}</p><p className="mt-1 text-sm">{item.body}</p><p className="mt-1 text-[11px] text-ink-400">{new Date(item.created_at).toLocaleString()}</p></div>)}{!notes.length && <p className="text-sm text-ink-500">No notes yet.</p>}</div>
        </section>

        <section className="rounded-xl border border-ink-100 p-4 lg:col-span-2">
          <div className="flex flex-wrap items-center justify-between gap-3"><div><p className="text-xs font-semibold uppercase text-blue-700">Interview rounds</p><h5 className="mt-1 font-semibold">Schedule and track multiple rounds</h5></div></div>
          <form onSubmit={scheduleRound} className="mt-4 grid gap-3 sm:grid-cols-3">
            <label className="grid gap-1 text-xs font-semibold">Round name<input className={input} value={interviewForm.round_name} onChange={(e) => setInterviewForm({...interviewForm, round_name:e.target.value})} /></label>
            <label className="grid gap-1 text-xs font-semibold">Date & time<input className={input} required type="datetime-local" value={interviewForm.starts_at} onChange={(e) => setInterviewForm({...interviewForm, starts_at:e.target.value})} /></label>
            <label className="grid gap-1 text-xs font-semibold">Duration<input className={input} type="number" min="15" value={interviewForm.duration_minutes} onChange={(e) => setInterviewForm({...interviewForm, duration_minutes:e.target.value})} /></label>
            <label className="grid gap-1 text-xs font-semibold">Feedback deadline<input className={input} type="datetime-local" value={interviewForm.feedback_deadline} onChange={(e) => setInterviewForm({...interviewForm, feedback_deadline:e.target.value})} /></label>
            <label className="grid gap-1 text-xs font-semibold">Mode<select className={input} value={interviewForm.mode} onChange={(e) => setInterviewForm({...interviewForm, mode:e.target.value, location:"", meeting_url:""})}><option value="online">Online</option><option value="offline">Offline</option></select></label>
            {interviewForm.mode === "online" ? <label className="grid gap-1 text-xs font-semibold">Meeting URL<input required className={input} value={interviewForm.meeting_url} onChange={(e) => setInterviewForm({...interviewForm, meeting_url:e.target.value})} placeholder="https://teams..." /></label> : <label className="grid gap-1 text-xs font-semibold">Location<input required className={input} value={interviewForm.location} onChange={(e) => setInterviewForm({...interviewForm, location:e.target.value})} /></label>}
            <div className="flex items-end"><button className={primary} type="submit">Schedule round</button></div>
          </form>
          <div className="mt-4 overflow-x-auto border-y border-ink-100"><table className="w-full min-w-[850px] text-left text-sm"><thead className="bg-[#fafaf8] text-[11px] uppercase text-ink-500"><tr><th className="px-3 py-3">Round</th><th className="px-3 py-3">When</th><th className="px-3 py-3">Mode</th><th className="px-3 py-3">Status</th><th className="px-3 py-3"></th></tr></thead><tbody className="divide-y divide-ink-50">{interviews.map((item) => <tr key={item.id}><td className="px-3 py-3"><p className="font-semibold">Round {item.round_number} · {item.round_name}</p></td><td className="px-3 py-3">{new Date(item.starts_at).toLocaleString()}</td><td className="px-3 py-3 text-xs">{item.mode === "offline" ? item.location : item.meeting_url}</td><td className="px-3 py-3 text-xs font-semibold">{item.status}</td><td className="px-3 py-3 text-right"><div className="flex gap-2 justify-end">{item.status === "scheduled" && <><button className={secondary} type="button" onClick={() => updateInterviewStatus(item.id, "completed")}>Complete</button><button className={secondary} type="button" onClick={() => updateInterviewStatus(item.id, "cancelled")}>Cancel</button></>}</div></td></tr>)}</tbody></table></div>
        </section>

        <section className="rounded-xl border border-ink-100 p-4 lg:col-span-2">
          <p className="text-xs font-semibold uppercase text-blue-700">Offer management</p>
          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            <label className="grid gap-1 text-xs font-semibold">Position title<input className={input} value={offerForm.position_title || selected.job_title} onChange={(e) => setOfferForm({...offerForm, position_title:e.target.value})} /></label>
            <label className="grid gap-1 text-xs font-semibold">Annual CTC<input className={input} value={offerForm.annual_ctc} onChange={(e) => setOfferForm({...offerForm, annual_ctc:e.target.value})} placeholder="1200000" /></label>
            <label className="grid gap-1 text-xs font-semibold">Currency<input className={input} value={offerForm.currency} onChange={(e) => setOfferForm({...offerForm, currency:e.target.value})} /></label>
            <label className="grid gap-1 text-xs font-semibold">Joining date<input className={input} type="datetime-local" value={offerForm.joining_date} onChange={(e) => setOfferForm({...offerForm, joining_date:e.target.value})} /></label>
            <label className="grid gap-1 text-xs font-semibold">Offer expiry<input className={input} type="datetime-local" value={offerForm.expires_at} onChange={(e) => setOfferForm({...offerForm, expires_at:e.target.value})} /></label>
            <label className="grid gap-1 text-xs font-semibold">Probation<input className={input} value={offerForm.probation_period} onChange={(e) => setOfferForm({...offerForm, probation_period:e.target.value})} placeholder="6 months" /></label>
            <label className="grid gap-1 text-xs font-semibold sm:col-span-2">CTC breakdown<textarea className={input + " min-h-20"} value={offerForm.ctc_breakdown} onChange={(e) => setOfferForm({...offerForm, ctc_breakdown:e.target.value})} placeholder={"Basic: 600000\nHRA: 240000\nBonus: 120000"} /></label>
            <label className="grid gap-1 text-xs font-semibold">Benefits<textarea className={input + " min-h-20"} value={offerForm.benefits} onChange={(e) => setOfferForm({...offerForm, benefits:e.target.value})} placeholder={"Health insurance\nPF\nPaid leave"} /></label>
            <label className="grid gap-1 text-xs font-semibold sm:col-span-3">Offer notes<textarea className={input + " min-h-20"} value={offerForm.notes} onChange={(e) => setOfferForm({...offerForm, notes:e.target.value})} /></label>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <button className={primary} onClick={saveOffer}>Save offer</button>
            {offer && <>
              <span className="rounded-full bg-blue-50 px-2.5 py-1 text-xs font-semibold text-blue-800">Status: {offer.status}</span>
              {offer.status === "draft" && <button type="button" className={secondary} onClick={() => transitionOffer("internal_review")}>Submit for review</button>}
              {offer.status === "internal_review" && <button type="button" className={secondary} onClick={() => transitionOffer("approved")}>Approve offer</button>}
              {offer.status === "approved" && <button type="button" className={primary} onClick={sendOffer}>Send to candidate</button>}
              {(offer.status === "sent" || offer.status === "viewed") && <a className={secondary} target="_blank" rel="noreferrer" href={(import.meta.env.VITE_API_URL || "https://bluepace-ats-11.onrender.com") + "/applications/" + applicationId + "/offer/letter"}>Open offer letter</a>}
              {["sent","viewed"].includes(offer.status) && offer.expires_at && <span className="text-xs text-ink-500">Expires {new Date(offer.expires_at).toLocaleString()}</span>}
            </>}
          </div>
        </section>
      </div>
    </section>
  );
}
