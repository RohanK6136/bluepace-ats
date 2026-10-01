import { useEffect, useState } from "react";

const input = "w-full rounded-md border border-ink-100 bg-white px-3 py-2.5 text-sm text-ink-900 outline-none focus:border-gold-500 focus:ring-2 focus:ring-gold-100";
const primary = "inline-flex items-center justify-center rounded-md bg-[#c49a4a] px-4 py-2 text-sm font-semibold text-[#10131c] disabled:opacity-50";
const secondary = "inline-flex items-center justify-center rounded-md border border-ink-100 bg-white px-3 py-2 text-sm font-semibold text-ink-800 disabled:opacity-50";

const STAGES = ["", "Applied", "Screening", "Interview", "Offer", "Hired", "Rejected"];

export default function AutomationPanel({ token, apiRequest, onNotice, onError }) {
  const empty = { name: "", trigger_stage: "", subject: "", body: "", enabled: true };
  const [rules, setRules] = useState([]);
  const [form, setForm] = useState(empty);
  const [editingId, setEditingId] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  async function load() {
    setLoading(true);
    try {
      const response = await apiRequest(token, "get", "/automation-rules");
      setRules(response.data || []);
    } catch (error) { onError(error); }
    finally { setLoading(false); }
  }

  useEffect(() => { load(); }, [token]);

  function startEdit(rule) {
    setEditingId(rule.id);
    setForm({
      name: rule.name || "",
      trigger_stage: rule.trigger_stage || "",
      subject: rule.subject || "",
      body: rule.body || "",
      enabled: rule.enabled !== false,
    });
  }

  function reset() {
    setEditingId(null);
    setForm(empty);
  }

  async function save(event) {
    event.preventDefault();
    if (!form.name.trim() || !form.subject.trim() || !form.body.trim()) return;
    setSaving(true);
    try {
      const payload = {
        name: form.name.trim(),
        trigger_stage: form.trigger_stage || null,
        subject: form.subject.trim(),
        body: form.body,
        enabled: form.enabled,
      };
      if (editingId) {
        await apiRequest(token, "patch", "/automation-rules/" + editingId, { data: payload });
        onNotice("Automation rule updated");
      } else {
        await apiRequest(token, "post", "/automation-rules", { data: payload });
        onNotice("Automation rule created");
      }
      reset();
      await load();
    } catch (error) { onError(error); }
    finally { setSaving(false); }
  }

  async function toggle(rule) {
    try {
      const response = await apiRequest(token, "patch", "/automation-rules/" + rule.id, { data: { enabled: !rule.enabled } });
      setRules((rows) => rows.map((row) => row.id === rule.id ? response.data : row));
      onNotice(rule.enabled ? "Automation disabled" : "Automation enabled");
    } catch (error) { onError(error); }
  }

  async function remove(rule) {
    if (!window.confirm("Delete this automation rule?")) return;
    try {
      await apiRequest(token, "delete", "/automation-rules/" + rule.id);
      setRules((rows) => rows.filter((row) => row.id !== rule.id));
      if (editingId === rule.id) reset();
      onNotice("Automation rule deleted");
    } catch (error) { onError(error); }
  }

  return (
    <section>
      <div className="mb-5">
        <p className="text-sm text-ink-500">Configure triggered candidate communications without changing the core recruiting pipeline.</p>
        <h2 className="mt-1 text-xl font-semibold">Workflow automation</h2>
      </div>
      <div className="grid gap-5 lg:grid-cols-[420px,1fr]">
        <form onSubmit={save} className="rounded-xl border border-ink-100 bg-white p-5">
          <div className="flex items-center justify-between">
            <div><p className="text-xs font-semibold uppercase tracking-[0.14em] text-blue-700">{editingId ? "Edit rule" : "New rule"}</p><h3 className="mt-1 font-semibold">Stage-triggered email</h3></div>
            {editingId && <button type="button" className={secondary} onClick={reset}>New</button>}
          </div>
          <div className="mt-4 grid gap-3">
            <label className="grid gap-1 text-xs font-semibold">Rule name<input className={input} value={form.name} onChange={(e) => setForm({...form, name:e.target.value})} placeholder="Screening follow-up" /></label>
            <label className="grid gap-1 text-xs font-semibold">When stage changes to<select className={input} value={form.trigger_stage} onChange={(e) => setForm({...form, trigger_stage:e.target.value})}>{STAGES.map((stage) => <option key={stage} value={stage}>{stage || "Any pipeline stage"}</option>)}</select></label>
            <label className="grid gap-1 text-xs font-semibold">Subject<input className={input} value={form.subject} onChange={(e) => setForm({...form, subject:e.target.value})} placeholder="Update for {{job_title}}" /></label>
            <label className="grid gap-1 text-xs font-semibold">Email body<textarea className={input + " min-h-44"} value={form.body} onChange={(e) => setForm({...form, body:e.target.value})} placeholder={"Hello {{candidate_name}},\n\nYour application for {{job_title}} is now in {{stage_name}}."} /></label>
            <label className="flex items-center gap-2 text-sm font-semibold"><input type="checkbox" checked={form.enabled} onChange={(e) => setForm({...form, enabled:e.target.checked})} /> Enabled</label>
            <p className="text-[11px] leading-5 text-ink-500">Placeholders: {{candidate_name}}, {{candidate_email}}, {{job_title}}, {{stage_name}}</p>
          </div>
          <div className="mt-5 flex gap-2"><button className={primary} disabled={saving}>{saving ? "Saving…" : editingId ? "Save changes" : "Create automation"}</button><button type="button" className={secondary} onClick={reset}>Reset</button></div>
        </form>

        <section className="rounded-xl border border-ink-100 bg-white">
          <div className="border-b border-ink-100 px-5 py-4"><p className="text-xs font-semibold uppercase tracking-[0.14em] text-blue-700">Active rules</p><p className="mt-1 text-sm text-ink-500">{rules.filter((rule) => rule.enabled).length} enabled · {rules.length} total</p></div>
          {loading ? <div className="p-5 text-sm text-ink-500">Loading automations…</div> : (
            <div className="divide-y divide-ink-50">
              {rules.map((rule) => (
                <div key={rule.id} className="p-5">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div><p className="font-semibold">{rule.name}</p><p className="mt-1 text-xs text-ink-500">Trigger: {rule.trigger_stage || "Any stage"} · Action: email</p></div>
                    <span className={rule.enabled ? "rounded-full bg-emerald-50 px-2.5 py-1 text-[11px] font-semibold text-emerald-800" : "rounded-full bg-ink-50 px-2.5 py-1 text-[11px] font-semibold text-ink-500"}>{rule.enabled ? "Enabled" : "Disabled"}</span>
                  </div>
                  <p className="mt-3 text-sm font-medium">{rule.subject}</p>
                  <p className="mt-2 line-clamp-3 whitespace-pre-wrap text-xs leading-5 text-ink-600">{rule.body}</p>
                  <div className="mt-4 flex flex-wrap gap-2"><button className={secondary} onClick={() => startEdit(rule)}>Edit</button><button className={secondary} onClick={() => toggle(rule)}>{rule.enabled ? "Disable" : "Enable"}</button><button className={secondary} onClick={() => remove(rule)}>Delete</button></div>
                </div>
              ))}
              {!rules.length && <div className="p-12 text-center text-sm text-ink-500">No workflow rules yet.</div>}
            </div>
          )}
        </section>
      </div>
    </section>
  );
}
