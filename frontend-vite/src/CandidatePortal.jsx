import { useEffect, useState } from "react";
import axios from "axios";

const API_URL = (
  import.meta.env.VITE_API_URL?.trim() ||
  (import.meta.env.PROD ? "https://bluepace-ats-11.onrender.com" : "http://localhost:8000")
).replace(/\/+$/, "");

export default function CandidatePortal({ token }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [withdrawReason, setWithdrawReason] = useState("");
  const [message, setMessage] = useState("");

  async function load() {
    const response = await axios.get(API_URL + "/public/application/" + encodeURIComponent(token) + "/details", { timeout: 30000 });
    setData(response.data);
  }

  useEffect(() => {
    let active = true;
    load()
      .catch((requestError) => {
        if (active) setError(requestError.response?.data?.detail || "This candidate portal link is invalid or expired.");
      })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [token]);

  async function respondToOffer(status) {
    if (actionLoading) return;
    const label = status === "accepted" ? "accept" : "decline";
    if (!window.confirm("Confirm that you want to " + label + " this offer?")) return;
    setActionLoading(true);
    setMessage("");
    try {
      const response = await axios.post(API_URL + "/public/application/" + encodeURIComponent(token) + "/offer-response", { status }, { timeout: 30000 });
      setMessage(response.data?.message || "Your offer response has been recorded.");
      await load();
    } catch (requestError) {
      setError(requestError.response?.data?.detail || "We could not update your offer response.");
    } finally { setActionLoading(false); }
  }

  async function withdrawApplication() {
    if (actionLoading) return;
    if (!window.confirm("Withdraw this application? This action cannot be undone from the portal.")) return;
    setActionLoading(true);
    setMessage("");
    try {
      const response = await axios.post(API_URL + "/public/application/" + encodeURIComponent(token) + "/withdraw", { reason: withdrawReason.trim() || null }, { timeout: 30000 });
      setMessage(response.data?.message || "Your application has been withdrawn.");
      await load();
    } catch (requestError) {
      setError(requestError.response?.data?.detail || "We could not withdraw your application.");
    } finally { setActionLoading(false); }
  }

  if (loading) return <main className="grid min-h-screen place-items-center bg-[#f5f8fb] text-ink-900"><p className="text-sm text-ink-500">Loading application portal…</p></main>;
  if (error && !data) return <main className="grid min-h-screen place-items-center bg-[#f5f8fb] px-5 text-ink-900"><section className="w-full max-w-xl rounded-2xl border border-ink-100 bg-white p-8 text-center shadow-sm"><h1 className="text-xl font-semibold">Application portal</h1><p className="mt-3 text-sm text-rose-700">{error}</p></section></main>;
  if (!data) return null;

  return (
    <main className="min-h-screen bg-[#f5f8fb] px-5 py-10 text-ink-900">
      <section className="mx-auto w-full max-w-4xl">
        <div className="mb-6 flex items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-md bg-ink-950 text-xs font-bold text-white">BP</div>
          <div><p className="font-semibold">Blupace Tech</p><p className="text-xs text-ink-500">Candidate application portal</p></div>
        </div>

        {message && <div className="mb-4 rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800">{message}</div>}
        {error && <div className="mb-4 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">{error}</div>}

        <section className="rounded-2xl border border-ink-100 bg-white p-6 shadow-sm sm:p-8">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div><p className="text-xs font-semibold uppercase tracking-[0.16em] text-blue-700">Application #{data.application_id}</p><h1 className="mt-2 text-2xl font-semibold">{data.job_title}</h1><p className="mt-1 text-sm text-ink-500">{data.candidate_name}</p></div>
            <span className="rounded-full bg-blue-50 px-3 py-1.5 text-xs font-semibold text-blue-800">{data.stage_name}</span>
          </div>

          <div className="mt-7 grid gap-4 sm:grid-cols-3">
            <div className="rounded-xl border border-ink-100 bg-[#fafaf8] p-4"><p className="text-xs uppercase text-ink-500">Status</p><p className="mt-1 font-semibold capitalize">{data.status}</p></div>
            <div className="rounded-xl border border-ink-100 bg-[#fafaf8] p-4"><p className="text-xs uppercase text-ink-500">Applied</p><p className="mt-1 font-semibold">{new Date(data.applied_at).toLocaleDateString()}</p></div>
            <div className="rounded-xl border border-ink-100 bg-[#fafaf8] p-4"><p className="text-xs uppercase text-ink-500">Reference</p><p className="mt-1 font-semibold">BP-{String(data.application_id).padStart(6, "0")}</p></div>
          </div>

          <div className="mt-7 border-t border-ink-100 pt-6">
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-blue-700">Application timeline</p>
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              {(data.timeline || []).map((item, index) => (
                <div key={index} className="rounded-xl border border-ink-100 p-4">
                  <p className="text-sm font-semibold">{item.title}</p>
                  <p className="mt-1 text-xs text-ink-500">{item.created_at ? new Date(item.created_at).toLocaleString() : ""}</p>
                </div>
              ))}
              {!data.timeline?.length && <p className="text-sm text-ink-500">No timeline events are available yet.</p>}
            </div>
          </div>

          <div className="mt-7 border-t border-ink-100 pt-6">
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-blue-700">Interview schedule</p>
            <div className="mt-3 grid gap-3">
              {(data.interviews || []).map((interview) => {
                const calendarHref = API_URL + interview.calendar_url;
                return (
                  <div key={interview.id} className="rounded-xl border border-ink-100 p-4">
                    <div className="flex flex-wrap items-center justify-between gap-3"><div><p className="font-semibold">Round {interview.round_number} · {interview.round_name}</p><p className="mt-1 text-sm text-ink-600">{new Date(interview.starts_at).toLocaleString()} · {interview.duration_minutes} minutes</p></div><span className="rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-800">{interview.status}</span></div>
                    <p className="mt-2 text-sm text-ink-600">{interview.mode === "online" ? "Online" : "Offline / On-site"}{interview.location ? " · " + interview.location : ""}</p>
                    <div className="mt-3 flex flex-wrap gap-3">
                      {interview.meeting_url && <a className="text-sm font-semibold underline" href={interview.meeting_url} target="_blank" rel="noreferrer">Join interview</a>}
                      {interview.status !== "cancelled" && <a className="text-sm font-semibold underline" href={calendarHref}>Add to calendar</a>}
                    </div>
                  </div>
                );
              })}
              {!data.interviews?.length && <p className="text-sm text-ink-500">No interview is scheduled yet. We will update this page when the stage changes.</p>}
            </div>
          </div>

          {data.offer && (
            <div className="mt-7 border-t border-ink-100 pt-6">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div><p className="text-xs font-semibold uppercase tracking-[0.14em] text-blue-700">Offer</p><h2 className="mt-1 text-lg font-semibold">{data.offer.position_title}</h2></div>
                <span className="rounded-full bg-gold-50 px-3 py-1.5 text-xs font-semibold text-gold-700">{data.offer.status}</span>
              </div>
              <div className="mt-4 grid gap-3 sm:grid-cols-3">
                {data.offer.annual_ctc && <div className="rounded-lg bg-[#fafaf8] p-3"><p className="text-xs text-ink-500">Annual CTC</p><p className="mt-1 font-semibold">{data.offer.annual_ctc} {data.offer.currency}</p></div>}
                {data.offer.joining_date && <div className="rounded-lg bg-[#fafaf8] p-3"><p className="text-xs text-ink-500">Joining date</p><p className="mt-1 font-semibold">{new Date(data.offer.joining_date).toLocaleDateString()}</p></div>}
                <div className="rounded-lg bg-[#fafaf8] p-3"><p className="text-xs text-ink-500">Status</p><p className="mt-1 font-semibold capitalize">{data.offer.status}</p></div>
              </div>
              {data.offer.offer_letter_url && <a className="mt-3 inline-block text-sm font-semibold underline" href={data.offer.offer_letter_url} target="_blank" rel="noreferrer">View offer letter</a>}
              {data.offer.status === "sent" || data.offer.status === "viewed" ? (
                <div className="mt-5 flex flex-wrap gap-2">
                  <button className="inline-flex items-center rounded-md bg-emerald-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50" disabled={actionLoading} onClick={() => respondToOffer("accepted")}>Accept offer</button>
                  <button className="inline-flex items-center rounded-md border border-rose-200 bg-white px-4 py-2 text-sm font-semibold text-rose-700 disabled:opacity-50" disabled={actionLoading} onClick={() => respondToOffer("declined")}>Decline offer</button>
                </div>
              ) : null}
            </div>
          )}

          {data.status !== "hired" && data.status !== "rejected" && data.status !== "withdrawn" && (
            <div className="mt-7 border-t border-ink-100 pt-6">
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-blue-700">Application actions</p>
              <div className="mt-3 rounded-xl border border-amber-100 bg-amber-50 p-4">
                <p className="text-sm text-amber-900">You may withdraw this application using the secure portal link.</p>
                <textarea className={inputStyle} value={withdrawReason} onChange={(event) => setWithdrawReason(event.target.value)} placeholder="Optional reason" />
                <button className="mt-3 inline-flex items-center rounded-md border border-rose-200 bg-white px-4 py-2 text-sm font-semibold text-rose-700" disabled={actionLoading} onClick={withdrawApplication}>Withdraw application</button>
              </div>
            </div>
          )}

          <div className="mt-7 rounded-xl border border-blue-100 bg-blue-50 p-4 text-sm leading-6 text-blue-900">
            Keep this secure link for future status updates. You do not need to create a separate account.
          </div>
        </section>
      </section>
    </main>
  );
}

const inputStyle = "w-full rounded-md border border-amber-200 bg-white px-3 py-2.5 text-sm text-ink-900 outline-none focus:border-amber-400 focus:ring-2 focus:ring-amber-100";
