import { useEffect, useState } from "react";

const stages = ["draft", "internal_review", "approved", "sent", "viewed", "accepted", "declined", "expired"];
const label = (value) => String(value || "").replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase());

export default function OfferManagement({ token, apiRequest, applications = [], onNotice, onError }) {
  const [offers, setOffers] = useState([]);
  const [selected, setSelected] = useState(null);
  const [loading, setLoading] = useState(false);
  const [form, setForm] = useState({ application_id: "", position_title: "", annual_ctc: "", currency: "INR", joining_date: "", probation_period: "6 months", benefits: "", ctc_breakdown: "{}", notes: "", expires_at: "" });

  async function loadOffers() {
    setLoading(true);
    try { const response = await apiRequest(token, "get", "/offer-management/offers"); setOffers(response.data || []); }
    catch (error) { onError?.(error); }
    finally { setLoading(false); }
  }
  useEffect(() => { loadOffers(); }, []);

  async function createOffer(event) {
    event.preventDefault();
    try {
      const app = applications.find((item) => item.id === Number(form.application_id));
      const response = await apiRequest(token, "post", "/offer-management/offers", { data: {
        application_id: Number(form.application_id), position_title: form.position_title || app?.job_title || "",
        annual_ctc: form.annual_ctc || null, currency: form.currency,
        joining_date: form.joining_date ? new Date(form.joining_date).toISOString() : null,
        probation_period: form.probation_period || null,
        benefits: form.benefits.split(",").map((v) => v.trim()).filter(Boolean),
        ctc_breakdown: JSON.parse(form.ctc_breakdown || "{}"), notes: form.notes || null,
        expires_at: form.expires_at ? new Date(form.expires_at).toISOString() : null
      }});
      setSelected(response.data); onNotice?.("Offer created as Draft"); await loadOffers();
    } catch (error) { onError?.(error); }
  }

  async function action(path, data) {
    try { const response = await apiRequest(token, "post", path, { data: data || {} }); setSelected(response.data); onNotice?.("Offer updated"); await loadOffers(); }
    catch (error) { onError?.(error); }
  }

  async function openLetter(offer) {
    try {
      const response = await apiRequest(token, "get", "/offer-management/offers/" + offer.id + "/letter", { responseType: "blob" });
      const url = URL.createObjectURL(new Blob([response.data], { type: "text/html" }));
      window.open(url, "_blank", "noopener,noreferrer");
    } catch (error) { onError?.(error); }
  }

  async function saveRevision(event) {
    event.preventDefault();
    if (!selected) return;
    try {
      const response = await apiRequest(token, "patch", "/offer-management/offers/" + selected.id, { data: {
        annual_ctc: form.annual_ctc || null, currency: form.currency,
        joining_date: form.joining_date ? new Date(form.joining_date).toISOString() : null,
        probation_period: form.probation_period || null,
        benefits: form.benefits.split(",").map((v) => v.trim()).filter(Boolean),
        ctc_breakdown: JSON.parse(form.ctc_breakdown || "{}"), notes: form.notes || null, reason: "Recruiter revision"
      }});
      setSelected(response.data); await loadOffers(); onNotice?.("Offer revision saved");
    } catch (error) { onError?.(error); }
  }

  function selectOffer(offer) {
    setSelected(offer);
    setForm((current) => ({ ...current, annual_ctc: offer.annual_ctc || "", currency: offer.currency || "INR",
      joining_date: offer.joining_date ? String(offer.joining_date).slice(0, 16) : "",
      probation_period: offer.probation_period || "", benefits: (offer.benefits || []).join(", "),
      ctc_breakdown: JSON.stringify(offer.ctc_breakdown || {}, null, 2), notes: offer.notes || "",
      expires_at: offer.expires_at ? String(offer.expires_at).slice(0, 16) : "" }));
  }

  const editable = selected && ["draft", "internal_review"].includes(selected.status);

  return <section>
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div><p className="text-sm text-ink-500">Offer lifecycle</p><h2 className="mt-1 text-xl font-semibold">Offers</h2></div>
      <button className="inline-flex items-center justify-center rounded-md border border-ink-100 bg-white px-3 py-2 text-sm font-semibold" onClick={loadOffers}>Refresh</button>
    </div>
    <details className="mb-5 border-y border-ink-100 py-3">
      <summary className="cursor-pointer text-sm font-semibold text-ink-800">View offer lifecycle</summary>
      <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-8">
        {stages.map((stage) => <div key={stage} className="rounded-lg bg-ink-50 p-2"><p className="text-[10px] font-semibold uppercase text-ink-500">{label(stage)}</p><p className="mt-1 text-lg font-bold">{offers.filter((o) => o.status === stage).length}</p></div>)}
      </div>
    </details>
    <div className="grid gap-5 xl:grid-cols-[1fr_1.35fr]">
      <section className="rounded-xl border border-ink-100 bg-white p-4">
        <div className="flex items-center justify-between"><h3 className="font-semibold">Offers</h3><span className="text-xs text-ink-500">{offers.length} total</span></div>
        <div className="mt-4 grid gap-2">
          {offers.map((offer) => <button key={offer.id} onClick={() => selectOffer(offer)} className={"rounded-lg border p-3 text-left " + (selected?.id === offer.id ? "border-gold-400 bg-[#fbf7ef]" : "border-ink-100")}>
            <div className="flex items-start justify-between gap-2"><div><p className="font-semibold">{offer.position_title}</p><p className="text-xs text-ink-500">Application #{offer.application_id} · Rev {offer.revision}</p></div><span className="rounded-full bg-ink-50 px-2 py-1 text-[10px] font-semibold">{label(offer.status)}</span></div>
            <p className="mt-2 text-sm">{offer.annual_ctc || "CTC not set"} {offer.currency}</p>
          </button>)}
          {!offers.length && !loading && <p className="py-8 text-sm text-ink-500">No offers yet. Create the first offer on the right.</p>}
        </div>
      </section>

      <section className="rounded-xl border border-ink-100 bg-white p-4">
        {!selected ? <form onSubmit={createOffer} className="grid gap-4">
          <div><h3 className="font-semibold">Create offer</h3><p className="mt-1 text-xs text-ink-500">New offers begin in Draft.</p></div>
          <label className="grid gap-1.5 text-xs font-semibold">Application<select className="rounded-md border border-ink-100 px-3 py-2.5 text-sm" required value={form.application_id} onChange={(e) => { const app = applications.find((item) => item.id === Number(e.target.value)); setForm({ ...form, application_id: e.target.value, position_title: app?.job_title || "" }); }}>
            <option value="">Choose an application</option>{applications.map((app) => <option key={app.id} value={app.id}>{app.candidate.first_name} {app.candidate.last_name} · {app.job_title}</option>)}
          </select></label>
          <label className="grid gap-1.5 text-xs font-semibold">Position title<input className="rounded-md border border-ink-100 px-3 py-2.5 text-sm" required value={form.position_title} onChange={(e) => setForm({ ...form, position_title: e.target.value })}/></label>
          <div className="grid gap-3 sm:grid-cols-2">
            <input aria-label="Annual CTC" className="rounded-md border border-ink-100 px-3 py-2.5 text-sm" placeholder="Annual CTC" value={form.annual_ctc} onChange={(e) => setForm({ ...form, annual_ctc: e.target.value })}/>
            <input aria-label="Currency" className="rounded-md border border-ink-100 px-3 py-2.5 text-sm" value={form.currency} onChange={(e) => setForm({ ...form, currency: e.target.value })}/>
            <input aria-label="Joining date" type="datetime-local" className="rounded-md border border-ink-100 px-3 py-2.5 text-sm" value={form.joining_date} onChange={(e) => setForm({ ...form, joining_date: e.target.value })}/>
            <input aria-label="Probation" className="rounded-md border border-ink-100 px-3 py-2.5 text-sm" placeholder="Probation" value={form.probation_period} onChange={(e) => setForm({ ...form, probation_period: e.target.value })}/>
          </div>
          <input aria-label="Benefits" className="rounded-md border border-ink-100 px-3 py-2.5 text-sm" placeholder="Benefits separated by commas" value={form.benefits} onChange={(e) => setForm({ ...form, benefits: e.target.value })}/>
          <textarea aria-label="CTC breakdown" className="min-h-28 rounded-md border border-ink-100 px-3 py-2.5 font-mono text-xs" value={form.ctc_breakdown} onChange={(e) => setForm({ ...form, ctc_breakdown: e.target.value })}/>
          <textarea aria-label="Notes" className="min-h-24 rounded-md border border-ink-100 px-3 py-2.5 text-sm" placeholder="Offer notes" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })}/>
          <input aria-label="Offer expiry" type="datetime-local" className="rounded-md border border-ink-100 px-3 py-2.5 text-sm" value={form.expires_at} onChange={(e) => setForm({ ...form, expires_at: e.target.value })}/>
          <button className="inline-flex justify-center rounded-md bg-[#c49a4a] px-4 py-2 text-sm font-semibold" type="submit">Create Draft Offer</button>
        </form> : <div>
          <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-xs uppercase tracking-[0.14em] text-blue-700">Revision {selected.revision}</p><h3 className="mt-1 text-lg font-semibold">{selected.position_title}</h3><p className="text-xs text-ink-500">Application #{selected.application_id}</p></div><span className="rounded-full bg-ink-50 px-3 py-1 text-xs font-semibold">{label(selected.status)}</span></div>
          <div className="mt-4 grid gap-2 rounded-xl border border-ink-100 bg-[#fafaf8] p-3 sm:grid-cols-4">{stages.map((stage, index) => <div key={stage} className={"text-xs " + (stages.indexOf(selected.status) >= index ? "font-semibold text-ink-900" : "text-ink-400")}><span className="mr-1">{stages.indexOf(selected.status) >= index ? "●" : "○"}</span>{label(stage)}</div>)}</div>
          <form onSubmit={editable ? saveRevision : (e) => e.preventDefault()} className="mt-5 grid gap-3">
            <div className="grid gap-3 sm:grid-cols-2"><input aria-label="Annual CTC" className="rounded-md border border-ink-100 px-3 py-2.5 text-sm" placeholder="Annual CTC" value={form.annual_ctc} disabled={!editable} onChange={(e) => setForm({ ...form, annual_ctc: e.target.value })}/><input aria-label="Joining date" type="datetime-local" className="rounded-md border border-ink-100 px-3 py-2.5 text-sm" value={form.joining_date} disabled={!editable} onChange={(e) => setForm({ ...form, joining_date: e.target.value })}/><input aria-label="Probation" className="rounded-md border border-ink-100 px-3 py-2.5 text-sm" value={form.probation_period} disabled={!editable} onChange={(e) => setForm({ ...form, probation_period: e.target.value })}/><input aria-label="Benefits" className="rounded-md border border-ink-100 px-3 py-2.5 text-sm" value={form.benefits} disabled={!editable} onChange={(e) => setForm({ ...form, benefits: e.target.value })}/></div>
            <textarea aria-label="CTC breakdown" className="min-h-28 rounded-md border border-ink-100 px-3 py-2.5 font-mono text-xs" disabled={!editable} value={form.ctc_breakdown} onChange={(e) => setForm({ ...form, ctc_breakdown: e.target.value })}/>
            {editable && <button className="inline-flex justify-center rounded-md border border-ink-100 px-4 py-2 text-sm font-semibold">Save revision</button>}
          </form>
          <div className="mt-4 flex flex-wrap gap-2">
            {selected.status === "draft" && <button className="rounded-md bg-ink-950 px-3 py-2 text-xs font-semibold text-white" onClick={() => action("/offer-management/offers/" + selected.id + "/submit-review")}>Submit for Internal Review</button>}
            {selected.status === "internal_review" && <button className="rounded-md bg-emerald-700 px-3 py-2 text-xs font-semibold text-white" onClick={() => action("/offer-management/offers/" + selected.id + "/approve")}>Approve Offer</button>}
            {selected.status === "approved" && <button className="rounded-md bg-blue-700 px-3 py-2 text-xs font-semibold text-white" onClick={() => action("/offer-management/offers/" + selected.id + "/send")}>Send Offer</button>}
            {["sent","viewed"].includes(selected.status) && <button className="rounded-md border border-ink-100 px-3 py-2 text-xs font-semibold" onClick={() => openLetter(selected)}>Generate Offer Letter</button>}
            {["sent","viewed"].includes(selected.status) && <button className="rounded-md border border-rose-200 px-3 py-2 text-xs font-semibold text-rose-700" onClick={() => action("/offer-management/offers/" + selected.id + "/expire")}>Expire</button>}
            {["approved","sent","viewed"].includes(selected.status) && <button className="rounded-md border border-ink-100 px-3 py-2 text-xs font-semibold" onClick={() => action("/offer-management/offers/" + selected.id + "/revise", { reason: "Recruiter requested revision" })}>Create Revision</button>}
          </div>
          <div className="mt-5 grid gap-4 border-t border-ink-100 pt-4 lg:grid-cols-3">
            <div><p className="text-xs font-semibold uppercase text-ink-500">Revision history</p><div className="mt-2 grid gap-2 text-xs">{(selected.revisions || []).map((r) => <div key={r.id} className="rounded border border-ink-100 p-2">Rev {r.revision} · {r.reason || "Updated"}<br/>{new Date(r.created_at).toLocaleString()}</div>)}</div></div>
            <div><p className="text-xs font-semibold uppercase text-ink-500">Approvals</p><div className="mt-2 grid gap-2 text-xs">{(selected.approvals || []).map((a) => <div key={a.id} className="rounded border border-ink-100 p-2">{a.status} · user #{a.approver_id}<br/>{new Date(a.created_at).toLocaleString()}</div>)}</div></div>
            <div><p className="text-xs font-semibold uppercase text-ink-500">Electronic acceptance</p><div className="mt-2 grid gap-2 text-xs">{(selected.acceptance_records || []).map((a) => <div key={a.id} className="rounded border border-ink-100 p-2">{label(a.action)} · {new Date(a.accepted_at).toLocaleString()}<br/>{a.acknowledgement}</div>)}{!selected.acceptance_records?.length && <p className="text-ink-400">No response recorded.</p>}</div></div>
          </div>
        </div>}
      </section>
    </div>
  </section>;
}
