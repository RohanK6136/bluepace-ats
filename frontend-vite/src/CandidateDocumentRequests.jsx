import { useEffect, useMemo, useState } from "react";

const input = "w-full rounded-md border border-ink-200 bg-white px-3 py-2 text-sm text-ink-800";
const button = "inline-flex items-center justify-center rounded-md border border-ink-200 bg-white px-3 py-2 text-xs font-semibold text-ink-700 hover:bg-ink-50 disabled:cursor-not-allowed disabled:opacity-50";

export default function CandidateDocumentRequests({ token, apiRequest, applications = [], onNotice, onError }) {
  const [requests, setRequests] = useState([]);
  const [applicationId, setApplicationId] = useState(applications[0]?.id ? String(applications[0].id) : "");
  const [form, setForm] = useState({ name: "", description: "", required: true, due_at: "" });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [portalLink, setPortalLink] = useState("");
  const [linkLoading, setLinkLoading] = useState(false);
  const applicationKey = useMemo(() => applications.map((item) => item.id).join(","), [applications]);

  useEffect(() => {
    let active = true;
    const rows = applications.filter((item) => item?.id);
    if (!rows.length) {
      setRequests([]);
      setApplicationId("");
      setLoading(false);
      return () => { active = false; };
    }
    setApplicationId((current) => rows.some((item) => String(item.id) === current) ? current : String(rows[0].id));
    setLoading(true);
    Promise.all(rows.map(async (application) => {
      const response = await apiRequest(token, "get", `/applications/${application.id}/candidate-portal/document-requests`);
      return (response.data || []).map((request) => ({ ...request, application_id: application.id, job_title: application.job_title }));
    })).then((results) => { if (active) setRequests(results.flat()); })
      .catch((error) => { if (active) onError?.(error); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [apiRequest, applicationKey, token]);

  async function createRequest(event) {
    event.preventDefault();
    const chosen = applications.find((item) => item.id === Number(applicationId));
    if (!chosen || !form.name.trim()) return;
    setSaving(true);
    try {
      const response = await apiRequest(token, "post", `/applications/${chosen.id}/candidate-portal/document-requests`, { data: {
        name: form.name.trim(),
        description: form.description.trim() || null,
        required: form.required,
        due_at: form.due_at ? new Date(form.due_at).toISOString() : null,
      }});
      setRequests((current) => [{ ...response.data, application_id: chosen.id, job_title: chosen.job_title }, ...current]);
      setForm({ name: "", description: "", required: true, due_at: "" });
      onNotice?.("Document request added to the candidate portal. No email was sent.");
    } catch (error) { onError?.(error); }
    finally { setSaving(false); }
  }

  async function generatePortalLink() {
    if (!applicationId) return;
    setLinkLoading(true);
    try {
      const response = await apiRequest(token, "get", `/applications/${applicationId}/portal-link`);
      setPortalLink(response.data?.url || "");
    } catch (error) { onError?.(error); }
    finally { setLinkLoading(false); }
  }

  async function copyPortalLink() {
    try { await navigator.clipboard.writeText(portalLink); onNotice?.("Candidate portal link copied."); }
    catch { onNotice?.(portalLink); }
  }

  const pendingCount = requests.filter((request) => request.status !== "fulfilled").length;

  return <section className="mt-5 rounded-xl border border-blue-100 bg-blue-50/30 p-4 sm:p-5" aria-labelledby="candidate-documents-heading">
    <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-xs font-semibold uppercase tracking-wide text-blue-700">Candidate portal</p><h4 id="candidate-documents-heading" className="mt-1 font-semibold text-ink-950">Document requests</h4><p className="mt-1 text-xs leading-5 text-ink-600">Request files and track portal uploads by application. Requests do not send email automatically.</p></div><span className="rounded-full bg-white px-3 py-1 text-xs font-semibold text-amber-900">{pendingCount} outstanding</span></div>
    <form onSubmit={createRequest} className="mt-4 grid gap-3 rounded-lg border border-ink-100 bg-white p-3 sm:grid-cols-2">
      <label className="grid gap-1 text-xs font-semibold text-ink-700 sm:col-span-2">Application<select className={input} value={applicationId} onChange={(event) => { setApplicationId(event.target.value); setPortalLink(""); }} required><option value="">Choose an application</option>{applications.map((application) => <option key={application.id} value={application.id}>{application.job_title || "Open role"} · {application.stage_name}</option>)}</select></label>
      <label className="grid gap-1 text-xs font-semibold text-ink-700">Document name<input className={input} maxLength={200} value={form.name} onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))} placeholder="e.g. Proof of address" required /></label>
      <label className="grid gap-1 text-xs font-semibold text-ink-700">Due date (optional)<input className={input} type="date" value={form.due_at} onChange={(event) => setForm((current) => ({ ...current, due_at: event.target.value }))} /></label>
      <label className="grid gap-1 text-xs font-semibold text-ink-700 sm:col-span-2">Instructions (optional)<textarea className={`${input} min-h-16`} maxLength={2000} value={form.description} onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))} placeholder="Tell the candidate what to upload or how to prepare it." /></label>
      <label className="flex items-center gap-2 text-xs font-medium text-ink-700"><input type="checkbox" checked={form.required} onChange={(event) => setForm((current) => ({ ...current, required: event.target.checked }))} />Required to proceed</label>
      <div className="flex flex-wrap justify-end gap-2"><button type="button" className={button} onClick={generatePortalLink} disabled={!applicationId || linkLoading}>{linkLoading ? "Generating link…" : "Generate portal link"}</button><button type="submit" className={button} disabled={saving || !applicationId || !form.name.trim()}>{saving ? "Adding…" : "Add request"}</button></div>
      {portalLink && <div className="flex flex-wrap items-center gap-2 sm:col-span-2"><a className="max-w-full break-all text-xs font-medium text-blue-800 underline" href={portalLink} target="_blank" rel="noreferrer">Open candidate portal</a><button type="button" className={button} onClick={copyPortalLink}>Copy link</button></div>}
    </form>
    {loading ? <p className="mt-3 rounded-lg border border-ink-100 bg-white p-3 text-sm text-ink-500">Loading document requests…</p>
      : requests.length ? <div className="mt-3 grid gap-2">{requests.map((request) => {
        const overdue = request.status !== "fulfilled" && request.due_at && Date.parse(request.due_at) < Date.now();
        return <article key={request.id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-ink-100 bg-white p-3"><div><p className="text-sm font-semibold text-ink-900">{request.name}{request.required && <span className="ml-2 text-[10px] font-semibold uppercase text-rose-700">Required</span>}</p><p className="mt-1 text-xs text-ink-500">{request.job_title || `Application #${request.application_id}`}{request.due_at ? ` · Due ${new Date(request.due_at).toLocaleDateString()}` : " · No due date"}{overdue ? " · Overdue" : ""}</p>{request.description && <p className="mt-1 text-xs text-ink-600">{request.description}</p>}</div><span className={`rounded-full px-2.5 py-1 text-[10px] font-semibold ${request.status === "fulfilled" ? "bg-emerald-50 text-emerald-800" : overdue ? "bg-rose-50 text-rose-800" : "bg-amber-50 text-amber-900"}`}>{request.status}</span></article>;
      })}</div> : <p className="mt-3 rounded-lg border border-ink-100 bg-white p-3 text-sm text-ink-500">No documents have been requested for this candidate.</p>}
  </section>;
}

