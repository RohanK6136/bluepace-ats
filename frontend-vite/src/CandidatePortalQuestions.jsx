import { useEffect, useMemo, useState } from "react";

const field = "w-full rounded-md border border-ink-200 bg-white px-3 py-2 text-sm text-ink-800";
const button = "inline-flex items-center justify-center rounded-md border border-ink-200 bg-white px-3 py-2 text-xs font-semibold text-ink-700 hover:bg-ink-50 disabled:cursor-not-allowed disabled:opacity-50";

export default function CandidatePortalQuestions({ token, apiRequest, applications = [], onNotice, onError }) {
  const [questions, setQuestions] = useState([]);
  const [drafts, setDrafts] = useState({});
  const [loading, setLoading] = useState(true);
  const [savingId, setSavingId] = useState(null);
  const applicationKey = useMemo(() => applications.map((item) => item.id).join(","), [applications]);

  useEffect(() => {
    let active = true;
    const rows = applications.filter((item) => item?.id);
    if (!rows.length) {
      setQuestions([]);
      setDrafts({});
      setLoading(false);
      return () => { active = false; };
    }
    setLoading(true);
    Promise.all(rows.map(async (application) => {
      const response = await apiRequest(token, "get", `/applications/${application.id}/candidate-portal/questions`);
      return (response.data || []).map((question) => ({ ...question, application_id: application.id, job_title: application.job_title }));
    })).then((results) => {
      if (!active) return;
      const allQuestions = results.flat().sort((a, b) => {
        const openDiff = Number(a.status !== "open") - Number(b.status !== "open");
        return openDiff || new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
      });
      setQuestions(allQuestions);
      setDrafts(Object.fromEntries(allQuestions.map((question) => [question.id, question.answer || ""])));
    }).catch((error) => { if (active) onError?.(error); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [apiRequest, applicationKey, token]);

  async function saveAnswer(question) {
    const answer = String(drafts[question.id] || "").trim();
    if (!answer) return onError?.({ message: "Write a reply before publishing it to the candidate portal." });
    setSavingId(question.id);
    try {
      const response = await apiRequest(token, "patch", `/candidate-portal/questions/${question.id}`, { data: { answer, status: "answered" } });
      setQuestions((current) => current.map((item) => item.id === question.id ? { ...item, answer, status: response.data?.status || "answered", answered_at: response.data?.answered_at || new Date().toISOString() } : item));
      onNotice?.("Reply published to the candidate portal. No email was sent.");
    } catch (error) { onError?.(error); }
    finally { setSavingId(null); }
  }

  const openCount = questions.filter((question) => question.status === "open").length;

  return <section className="mt-5 rounded-xl border border-blue-100 bg-blue-50/30 p-4 sm:p-5" aria-labelledby="candidate-questions-heading">
    <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-xs font-semibold uppercase tracking-wide text-blue-700">Candidate portal</p><h4 id="candidate-questions-heading" className="mt-1 font-semibold text-ink-950">Candidate questions</h4><p className="mt-1 text-xs leading-5 text-ink-600">Replies you publish here appear in the candidate’s secure portal. They are not emailed.</p></div><span className="rounded-full bg-white px-3 py-1 text-xs font-semibold text-amber-900">{openCount} open</span></div>
    {loading ? <p className="mt-4 rounded-lg border border-ink-100 bg-white p-3 text-sm text-ink-500">Loading portal questions…</p>
      : questions.length ? <div className="mt-4 grid gap-3">{questions.map((question) => <article key={question.id} className="rounded-lg border border-ink-100 bg-white p-4">
        <div className="flex flex-wrap items-start justify-between gap-2"><div><p className="text-sm font-semibold text-ink-900">{question.subject}</p><p className="mt-1 text-[11px] text-ink-500">{question.job_title || `Application #${question.application_id}`} · {question.created_at ? new Date(question.created_at).toLocaleString() : "Date unavailable"}</p></div><span className={`rounded-full px-2 py-1 text-[10px] font-semibold ${question.status === "open" ? "bg-amber-50 text-amber-900" : "bg-emerald-50 text-emerald-800"}`}>{question.status}</span></div>
        <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-ink-700">{question.question}</p>
        {question.status === "open" || question.answer ? <div className="mt-3 grid gap-2"><label className="text-xs font-semibold text-ink-700">Reply to candidate<textarea className={`${field} mt-1.5 min-h-24`} maxLength={5000} value={drafts[question.id] ?? question.answer ?? ""} onChange={(event) => setDrafts((current) => ({ ...current, [question.id]: event.target.value }))} placeholder="Write a clear, job-related answer…" /></label><div className="flex flex-wrap items-center justify-between gap-2"><span className="text-[11px] text-ink-400">{(drafts[question.id] || "").length}/5000 characters</span><button type="button" className={button} disabled={savingId === question.id || !String(drafts[question.id] || "").trim()} onClick={() => saveAnswer(question)}>{savingId === question.id ? "Publishing…" : question.status === "open" ? "Publish reply" : "Update reply"}</button></div></div> : <p className="mt-3 rounded-md bg-emerald-50 p-3 text-sm text-emerald-900">{question.answer || "This question is closed."}</p>}
      </article>)}</div>
      : <p className="mt-4 rounded-lg border border-ink-100 bg-white p-3 text-sm text-ink-500">No questions have been sent through this candidate’s portal.</p>}
  </section>;
}

