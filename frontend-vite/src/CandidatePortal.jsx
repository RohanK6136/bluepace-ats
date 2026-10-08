import { useEffect, useState } from "react";
import axios from "axios";
import PublicHelpCenter from "./PublicHelpCenter.jsx";
import { MAX_DOCUMENT_SIZE_BYTES, MAX_DOCUMENT_SIZE_LABEL } from "./constants/documentLimits.js";

const API_URL = (
  import.meta.env.VITE_API_URL?.trim() ||
  (import.meta.env.PROD ? "https://bluepace-ats-11.onrender.com" : "http://localhost:8000")
).replace(/\/+$/, "");

export default function CandidatePortal({ token, theme = "light", onToggleTheme = () => {} }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [withdrawReason, setWithdrawReason] = useState("");
  const [message, setMessage] = useState("");
  const [documents, setDocuments] = useState([]);
  const [documentFile, setDocumentFile] = useState(null);
  const [profileForm, setProfileForm] = useState({ email: "", phone: "" });
  const [profileEditing, setProfileEditing] = useState(false);
  const [savingProfile, setSavingProfile] = useState(false);
  const [documentLoading, setDocumentLoading] = useState(false);
  const [documentRequests, setDocumentRequests] = useState([]);
  const [questions, setQuestions] = useState([]);
  const [questionForm, setQuestionForm] = useState({ subject: "", question: "" });
  const [questionLoading, setQuestionLoading] = useState(false);
  const [selectedRequestId, setSelectedRequestId] = useState(null);

  async function load() {
    const encoded = encodeURIComponent(token);
    const [response, documentResponse, requestResponse, questionResponse] = await Promise.all([
      axios.get(API_URL + "/public/application/" + encoded + "/details", { timeout: 30000 }),
      axios.get(API_URL + "/public/application/" + encoded + "/documents", { timeout: 30000 }).catch(() => ({ data: [] })),
      axios.get(API_URL + "/public/application/" + encoded + "/document-requests", { timeout: 30000 }).catch(() => ({ data: [] })),
      axios.get(API_URL + "/public/application/" + encoded + "/questions", { timeout: 30000 }).catch(() => ({ data: [] })),
    ]);
    setData(response.data);
    setDocuments(documentResponse.data || []);
    setDocumentRequests(requestResponse.data || []);
    setQuestions(questionResponse.data || []);
    setProfileForm((current) => ({
      email: response.data?.candidate_email || current.email || "",
      phone: response.data?.candidate_phone || current.phone || "",
    }));
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

  async function saveProfile() {
    setSavingProfile(true);
    setMessage("");
    try {
      const response = await axios.patch(API_URL + "/public/application/" + encodeURIComponent(token) + "/profile", profileForm, { timeout: 30000 });
      setProfileForm({ email: response.data.email || "", phone: response.data.phone || "" });
      setProfileEditing(false);
      setMessage("Your contact details were updated.");
      await load();
    } catch (requestError) {
      setError(requestError.response?.data?.detail || "We could not update your contact details.");
    } finally { setSavingProfile(false); }
  }

  async function uploadDocument() {
    if (!documentFile) return;
    if (documentFile.size > MAX_DOCUMENT_SIZE_BYTES) {
      setError(`Document must be ${MAX_DOCUMENT_SIZE_LABEL} or smaller.`);
      return;
    }
    setDocumentLoading(true);
    try {
      const form = new FormData();
      form.append("file", documentFile);
      const requestQuery = selectedRequestId ? "?request_id=" + encodeURIComponent(selectedRequestId) : "";
      await axios.post(API_URL + "/public/application/" + encodeURIComponent(token) + "/documents" + requestQuery, form, { timeout: 30000 });
      setDocumentFile(null);
      setSelectedRequestId(null);
      setMessage("Document uploaded successfully.");
      await load();
    } catch (requestError) {
      setError(requestError.response?.data?.detail || "We could not upload this document.");
    } finally { setDocumentLoading(false); }
  }

  async function submitQuestion() {
    if (!questionForm.subject.trim() || !questionForm.question.trim() || questionLoading) return;
    setQuestionLoading(true);
    setMessage("");
    try {
      await axios.post(
        API_URL + "/public/application/" + encodeURIComponent(token) + "/questions",
        questionForm,
        { timeout: 30000 }
      );
      setQuestionForm({ subject: "", question: "" });
      setMessage("Your question has been sent to the recruiting team.");
      await load();
    } catch (requestError) {
      setError(requestError.response?.data?.detail || "We could not send your question.");
    } finally {
      setQuestionLoading(false);
    }
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
        <div className="mb-7 flex items-center justify-between gap-3">
          <a href="https://www.blupacetech.com/" target="_blank" rel="noreferrer" className="bp-wordmark flex items-center gap-3 no-underline">
            <span className="bp-logo-mark bp-logo-mark-light">B</span>
            <span><span className="block text-[15px] font-semibold tracking-tight text-ink-950">blupace</span><span className="block text-[9px] font-semibold uppercase tracking-[0.24em] text-ink-400">tech</span></span>
          </a>
          <div className="flex items-center gap-2">
            <span className="hidden rounded-full border border-blue-100 bg-blue-50 px-3 py-1.5 text-[11px] font-semibold text-blue-700 sm:inline-flex">Candidate portal</span>
          <button
            type="button"
            onClick={onToggleTheme}
            className="inline-flex h-10 items-center gap-2 rounded-md border border-ink-100 bg-white px-3 text-sm font-semibold text-ink-700 shadow-sm hover:bg-ink-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
            aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
            title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
          >
            <span aria-hidden="true">{theme === "dark" ? "☀️" : "🌙"}</span>
            <span className="hidden sm:inline">{theme === "dark" ? "Light" : "Dark"}</span>
          </button>
          </div>
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
          </div>

          <div className="mt-7 border-t border-ink-100 pt-6">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div><p className="text-xs font-semibold uppercase tracking-[0.14em] text-blue-700">Contact details</p><p className="mt-1 text-sm text-ink-500">Keep your email and phone current for recruiting updates.</p></div>
              <button className="text-sm font-semibold underline" onClick={() => setProfileEditing((value) => !value)}>{profileEditing ? "Cancel" : "Edit"}</button>
            </div>
            {profileEditing ? (
              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                <input className={inputStyle} type="email" value={profileForm.email} onChange={(e) => setProfileForm({...profileForm,email:e.target.value})} placeholder="Email" />
                <input className={inputStyle} value={profileForm.phone} onChange={(e) => setProfileForm({...profileForm,phone:e.target.value})} placeholder="Phone" />
                <button className="sm:col-span-2 w-fit rounded-md bg-[#1769d3] px-4 py-2 text-sm font-semibold text-white" disabled={savingProfile} onClick={saveProfile}>{savingProfile ? "Saving…" : "Save details"}</button>
              </div>
            ) : (
              <div className="mt-3 grid gap-3 sm:grid-cols-2"><div className="rounded-lg bg-[#fafaf8] p-3 text-sm">{profileForm.email || "Email not available"}</div><div className="rounded-lg bg-[#fafaf8] p-3 text-sm">{profileForm.phone || "Phone not available"}</div></div>
            )}
          </div>

          <div className="mt-7 border-t border-ink-100 pt-6">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div><p className="text-xs font-semibold uppercase tracking-[0.14em] text-blue-700">Documents</p><p className="mt-1 text-sm text-ink-500">Upload supporting documents requested by recruiting.</p></div>
              <label className="rounded-md border border-ink-100 bg-white px-3 py-2 text-xs font-semibold cursor-pointer">Choose file<input className="hidden" type="file" accept=".pdf,.docx,.png,.jpg,.jpeg" onChange={(e) => { const selected = e.target.files?.[0] || null; if (selected && selected.size > MAX_DOCUMENT_SIZE_BYTES) { setDocumentFile(null); setError(`Document must be ${MAX_DOCUMENT_SIZE_LABEL} or smaller.`); e.target.value = ""; return; } setDocumentFile(selected); setError(""); }} /></label>
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-2">{selectedRequestId && <span className="rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-800">Uploading for requested document #{selectedRequestId}</span>}{documentFile && <><span className="rounded-md bg-blue-50 px-3 py-2 text-xs text-blue-800">{documentFile.name}</span><button className="rounded-md bg-[#1769d3] px-3 py-2 text-xs font-semibold text-white" disabled={documentLoading} onClick={uploadDocument}>{documentLoading ? "Uploading…" : "Upload"}</button></>}</div>
            {documentRequests.length > 0 && (
            <div className="mt-4 rounded-xl border border-blue-100 bg-blue-50/50 p-4">
              <p className="text-sm font-semibold">Requested documents</p>
              <div className="mt-3 grid gap-2">
                {documentRequests.map((request) => (
                  <div key={request.id} className="rounded-lg border border-ink-100 bg-white p-3">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <p className="text-sm font-semibold">{request.name}{request.required ? <span className="ml-2 text-xs text-rose-600">Required</span> : null}</p>
                        {request.description && <p className="mt-1 text-xs text-ink-500">{request.description}</p>}
                        {request.due_at && <p className="mt-1 text-xs text-ink-500">Due {new Date(request.due_at).toLocaleDateString()}</p>}
                      </div>
                      <span className="rounded-full bg-ink-50 px-2.5 py-1 text-[11px] font-semibold capitalize">{request.status}</span>
                    </div>
                    {request.status !== "fulfilled" && (
                      <div className="mt-3 flex flex-wrap gap-2">
                        <button className="rounded-md border border-ink-100 px-3 py-2 text-xs font-semibold" onClick={() => setSelectedRequestId(request.id)}>Upload for this request</button>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
          <div className="mt-4 grid gap-2">{documents.map((doc) => <div key={doc.id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-ink-100 p-3 text-sm"><div><p className="font-semibold">{doc.name}</p><p className="text-xs text-ink-500">{Math.max(1, Math.round(doc.size_bytes / 1024))} KB</p></div><a className="text-xs font-semibold underline" href={API_URL + doc.download_url}>Download</a></div>)}{!documents.length && <p className="text-sm text-ink-500">No additional documents uploaded.</p>}</div>
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
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-blue-700">Application history</p>
            <div className="mt-4 space-y-3">
              {(data.history || []).map((item) => (
                <div key={item.id} className="flex gap-3 rounded-lg border border-ink-100 p-3">
                  <div className="mt-1 h-2.5 w-2.5 shrink-0 rounded-full bg-blue-600" />
                  <div>
                    <p className="text-sm font-semibold">{item.title}</p>
                    <p className="mt-1 text-xs text-ink-500">{new Date(item.created_at).toLocaleString()}</p>
                    {item.details?.stage_name && <p className="mt-1 text-xs text-ink-600">Stage: {item.details.stage_name}</p>}
                  </div>
                </div>
              ))}
              {!data.history?.length && <p className="text-sm text-ink-500">No application history is available yet.</p>}
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

          <div className="mt-7 border-t border-ink-100 pt-6">
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-blue-700">Candidate questions</p>
            <p className="mt-1 text-sm text-ink-500">Ask the recruiting team about your application, interview, documents or offer.</p>
            <div className="mt-3 grid gap-3">
              <input className={inputStyle} value={questionForm.subject} onChange={(e) => setQuestionForm({...questionForm, subject: e.target.value})} placeholder="Subject" />
              <textarea className={inputStyle + " min-h-24"} value={questionForm.question} onChange={(e) => setQuestionForm({...questionForm, question: e.target.value})} placeholder="Your question" />
              <button className="w-fit rounded-md bg-[#1769d3] px-4 py-2 text-sm font-semibold text-white disabled:opacity-50" disabled={questionLoading || !questionForm.subject.trim() || !questionForm.question.trim()} onClick={submitQuestion}>{questionLoading ? "Sending…" : "Send question"}</button>
            </div>
            <div className="mt-5 space-y-3">
              {questions.map((item) => (
                <div key={item.id} className="rounded-xl border border-ink-100 p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3"><p className="font-semibold">{item.subject}</p><span className="rounded-full bg-ink-50 px-2.5 py-1 text-[11px] font-semibold capitalize">{item.status}</span></div>
                  <p className="mt-2 text-sm text-ink-700 whitespace-pre-wrap">{item.question}</p>
                  {item.answer && <div className="mt-3 rounded-lg bg-emerald-50 p-3"><p className="text-xs font-semibold text-emerald-800">Recruiting team</p><p className="mt-1 text-sm text-emerald-950 whitespace-pre-wrap">{item.answer}</p></div>}
                </div>
              ))}
              {!questions.length && <p className="text-sm text-ink-500">No questions yet.</p>}
            </div>
          </div>

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
        <PublicHelpCenter portal />
      </section>
    </main>
  );
}

const inputStyle = "w-full rounded-md border border-amber-200 bg-white px-3 py-2.5 text-sm text-ink-900 outline-none focus:border-amber-400 focus:ring-2 focus:ring-amber-100";
