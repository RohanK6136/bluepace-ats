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

  useEffect(() => {
    let active = true;
    axios.get(API_URL + "/public/application/" + encodeURIComponent(token), { timeout: 30000 })
      .then((response) => { if (active) setData(response.data); })
      .catch((requestError) => {
        if (!active) return;
        setError(requestError.response?.data?.detail || "This candidate portal link is invalid or expired.");
      })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [token]);

  if (loading) return <main className="grid min-h-screen place-items-center bg-[#f5f8fb] text-ink-900"><p className="text-sm text-ink-500">Loading application status…</p></main>;
  if (error) return <main className="grid min-h-screen place-items-center bg-[#f5f8fb] px-5 text-ink-900"><section className="w-full max-w-xl rounded-2xl border border-ink-100 bg-white p-8 text-center shadow-sm"><h1 className="text-xl font-semibold">Application portal</h1><p className="mt-3 text-sm text-rose-700">{error}</p></section></main>;

  return (
    <main className="min-h-screen bg-[#f5f8fb] px-5 py-10 text-ink-900">
      <section className="mx-auto w-full max-w-3xl">
        <div className="mb-6 flex items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-md bg-ink-950 text-xs font-bold text-white">BP</div>
          <div><p className="font-semibold">Blupace Tech</p><p className="text-xs text-ink-500">Candidate application portal</p></div>
        </div>
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
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-blue-700">Interview schedule</p>
            <div className="mt-3 grid gap-3">
              {(data.interviews || []).map((interview) => (
                <div key={interview.id} className="rounded-xl border border-ink-100 p-4">
                  <div className="flex flex-wrap items-center justify-between gap-3"><p className="font-semibold">{new Date(interview.starts_at).toLocaleString()}</p><span className="rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-800">{interview.status}</span></div>
                  <p className="mt-2 text-sm text-ink-600">{interview.duration_minutes} minutes · {interview.mode === "online" ? "Online" : "Offline / On-site"}</p>
                  {interview.meeting_url && <a className="mt-2 block text-sm underline" href={interview.meeting_url} target="_blank" rel="noreferrer">Join interview</a>}
                  {interview.location && <p className="mt-2 text-sm text-ink-600">{interview.location}</p>}
                </div>
              ))}
              {!data.interviews?.length && <p className="text-sm text-ink-500">No interview is scheduled yet. We will update this page when the stage changes.</p>}
            </div>
          </div>

          <div className="mt-7 rounded-xl border border-blue-100 bg-blue-50 p-4 text-sm leading-6 text-blue-900">
            Keep this secure link for future status updates. You do not need to create a separate account.
          </div>
        </section>
      </section>
    </main>
  );
}
