import { useEffect, useState } from "react";

const input = "w-full rounded-md border border-ink-100 bg-white px-3 py-2.5 text-sm text-ink-900 outline-none focus:border-gold-500 focus:ring-2 focus:ring-gold-100";
const primary = "inline-flex items-center justify-center rounded-md bg-[#c49a4a] px-4 py-2 text-sm font-semibold text-[#10131c] disabled:opacity-50";
const secondary = "inline-flex items-center justify-center rounded-md border border-ink-100 bg-white px-3 py-2 text-sm font-semibold text-ink-800 disabled:opacity-50";
const STAGES = ["", "Applied", "Screening", "Interview", "Offer", "Hired", "Rejected"];

export default function AutomationPanel({ token, apiRequest, onNotice, onError }) {
  const empty = { name: "", trigger_event: "stage_changed", trigger_stage: "", action_type: "send_email", action_value: "", subject: "", body: "", enabled: true };
  const [rules, setRules] = useState([]);
  const [users, setUsers] = useState([]);
  const [form, setForm] = useState(empty);
  const [editingId, setEditingId] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [starterInterviewer, setStarterInterviewer] = useState("");

  async function load() {
    setLoading(true);
    try {
      const [rulesResponse, usersResponse] = await Promise.all([
        apiRequest(token, "get", "/automation-rules"),
        apiRequest(token, "get", "/recruiting-users"),
      ]);
      setRules(rulesResponse.data || []);
      setUsers(usersResponse.data || []);
    } catch (error) { onError(error); }
    finally { setLoading(false); }
  }

  useEffect(() => { load(); }, [token]);

  function startEdit(rule) {
    setEditingId(rule.id);
    setForm({
      name: rule.name || "",
      trigger_event: rule.trigger_event || "stage_changed",
      trigger_stage: rule.trigger_stage || "",
      action_type: rule.action_type || "send_email",
      action_value: rule.action_value || "",
      subject: rule.subject || "",
      body: rule.body || "",
      enabled: rule.enabled !== false,
    });
  }

  function reset() {
    setEditingId(null);
    setForm({ ...empty });
  }

  async function save(event) {
    event.preventDefault();
    if (!form.name.trim()) return;
    if (form.action_type === "send_email" && (!form.subject.trim() || !form.body.trim())) return;
    if (form.action_type !== "send_email" && !form.action_value.trim()) return;
    setSaving(true);
    try {
      const payload = {
        name: form.name.trim(),
        trigger_event: form.trigger_event,
        trigger_stage: form.trigger_event === "stage_changed" ? (form.trigger_stage || null) : null,
        action_type: form.action_type,
        action_value: form.action_value.trim() || null,
        subject: form.action_type === "send_email" ? form.subject.trim() : "",
        body: form.action_type === "send_email" ? form.body : "",
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
        <p className="text-sm text-ink-500">Automate communications and controlled workflow actions while leaving final hiring decisions with recruiters.</p>
        <h2 className="mt-1 text-xl font-semibold">Workflow automation</h2>
      </div>
      <section className="mb-5 rounded-xl border border-blue-100 bg-blue-50 p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div><p className="text-xs font-semibold uppercase tracking-[0.14em] text-blue-700">Quick-start recipes</p><h3 className="mt-1 font-semibold">Build the recruiting flow in a few clicks</h3><p className="mt-1 text-sm text-blue-900/75">These create editable rules in this workspace. Review them before enabling production communications.</p></div>
          <div className="flex flex-wrap items-center gap-2">
            <select className="rounded-md border border-blue-200 bg-white px-3 py-2 text-sm font-medium text-blue-900" value={starterInterviewer} onChange={(event) => setStarterInterviewer(event.target.value)}>
              <option value="">No automatic interviewer assignment</option>
              {users.filter((user) => user.role === "interviewer").map((user) => <option key={user.id} value={user.id}>Assign {user.full_name}</option>)}
            </select>
            <button type="button" className="rounded-md bg-white px-3 py-2 text-sm font-semibold text-blue-800" onClick={async () => {
            const starterRules = [
              { name: "Screening candidate update", trigger_event: "stage_changed", trigger_stage: "Screening", action_type: "send_email", action_value: null, subject: "Application update — {{job_title}}", body: "Hello {{candidate_name}},\n\nYour application for {{job_title}} has moved to our screening stage. We will contact you with the next update.\n\nTrack your application: {{candidate_portal_url}}\n\nRegards,\nBlupace Tech Talent Team", enabled: true },
              ...(starterInterviewer ? [{ name: "Screening interviewer assignment", trigger_event: "stage_changed", trigger_stage: "Screening", action_type: "assign_interviewer", action_value: starterInterviewer, subject: "", body: "", enabled: true }] : []),
              { name: "Scorecards complete → Offer review", trigger_event: "scorecards_complete", trigger_stage: null, action_type: "move_stage", action_value: "Offer", subject: "", body: "", enabled: true }
            ];
            try {
              for (const rule of starterRules) await apiRequest(token, "post", "/automation-rules", { data: rule });
              onNotice("Starter workflow created: Screening email" + (starterInterviewer ? " + interviewer assignment" : "") + " + scorecards-complete → Offer");
              await load();
            } catch (error) { onError(error); }
          }}>Create starter workflow</button>
        </div>
      </section>      <div className="grid gap-5 lg:grid-cols-[430px,1fr]">
        <form onSubmit={save} className="rounded-xl border border-ink-100 bg-white p-5">
          <div className="flex items-center justify-between"><div><p className="text-xs font-semibold uppercase tracking-[0.14em] text-blue-700">{editingId ? "Edit rule" : "New rule"}</p><h3 className="mt-1 font-semibold">Automation builder</h3></div>{editingId && <button type="button" className={secondary} onClick={reset}>New</button>}</div>
          <div className="mt-4 grid gap-3">
            <label className="grid gap-1 text-xs font-semibold">Rule name<input className={input} value={form.name} onChange={(e) => setForm({...form, name:e.target.value})} placeholder="Screening workflow" /></label>
            <label className="grid gap-1 text-xs font-semibold">Trigger<select className={input} value={form.trigger_event} onChange={(e) => setForm({...form, trigger_event:e.target.value})}><option value="stage_changed">Application stage changed</option><option value="scorecards_complete">All interview scorecards submitted</option></select></label>
            {form.trigger_event === "stage_changed" && <label className="grid gap-1 text-xs font-semibold">Stage<select className={input} value={form.trigger_stage} onChange={(e) => setForm({...form, trigger_stage:e.target.value})}>{STAGES.map((stage) => <option key={stage} value={stage}>{stage || "Any stage"}</option>)}</select></label>}
            <label className="grid gap-1 text-xs font-semibold">Action<select className={input} value={form.action_type} onChange={(e) => setForm({...form, action_type:e.target.value, action_value:""})}><option value="send_email">Send candidate email</option><option value="assign_owner">Assign candidate owner</option><option value="assign_interviewer">Assign interviewer</option><option value="mark_review">Mark candidate needs review</option><option value="move_stage">Move application to stage</option></select></label>
            {form.action_type === "assign_owner" && <label className="grid gap-1 text-xs font-semibold">Owner<select className={input} value={form.action_value} onChange={(e) => setForm({...form, action_value:e.target.value})}><option value="">Select recruiter…</option>{users.map((user) => <option key={user.id} value={user.id}>{user.full_name} · {user.role}</option>)}</select></label>}
            {form.action_type === "assign_interviewer" && <label className="grid gap-1 text-xs font-semibold">Interviewer<select className={input} value={form.action_value} onChange={(e) => setForm({...form, action_value:e.target.value})}><option value="">Select interviewer…</option>{users.filter((user) => user.role === "interviewer").map((user) => <option key={user.id} value={user.id}>{user.full_name} · {user.role}</option>)}</select></label>}
            {form.action_type === "move_stage" && <label className="grid gap-1 text-xs font-semibold">Target stage<select className={input} value={form.action_value} onChange={(e) => setForm({...form, action_value:e.target.value})}>{STAGES.filter((stage) => Boolean(stage) && stage !== "Interview").map((stage) => <option key={stage}>{stage}</option>)}</select></label>}
            {form.action_type === "mark_review" && <input type="hidden" value="true" readOnly />}
            {form.action_type === "send_email" && <>
              <label className="grid gap-1 text-xs font-semibold">Subject<input className={input} value={form.subject} onChange={(e) => setForm({...form, subject:e.target.value})} placeholder="Update for {{job_title}}" /></label>
              <label className="grid gap-1 text-xs font-semibold">Email body<textarea className={input + " min-h-44"} value={form.body} onChange={(e) => setForm({...form, body:e.target.value})} placeholder={"Hello {{candidate_name}},\n\nYour application for {{job_title}} is now in {{stage_name}}."} /></label>
              <p className="text-[11px] leading-5 text-ink-500">Placeholders: {{candidate_name}}, {{candidate_email}}, {{job_title}}, {{stage_name}}</p>
            </>}
            {form.action_type !== "send_email" && <p className="text-[11px] leading-5 text-ink-500">{form.action_type === "assign_owner" ? "The candidate is assigned to the selected recruiting user." : form.action_type === "assign_interviewer" ? "The selected interviewer is attached to future interview rounds for this application." : form.action_type === "mark_review" ? "The candidate is flagged for recruiter review." : "The application is moved only to the selected pipeline stage."}</p>}
            <label className="flex items-center gap-2 text-sm font-semibold"><input type="checkbox" checked={form.enabled} onChange={(e) => setForm({...form, enabled:e.target.checked})} /> Enabled</label>
          </div>
          <div className="mt-5 flex gap-2"><button className={primary} disabled={saving}>{saving ? "Saving…" : editingId ? "Save changes" : "Create automation"}</button><button type="button" className={secondary} onClick={reset}>Reset</button></div>
        </form>

        <section className="rounded-xl border border-ink-100 bg-white">
          <div className="border-b border-ink-100 px-5 py-4"><p className="text-xs font-semibold uppercase tracking-[0.14em] text-blue-700">Rules</p><p className="mt-1 text-sm text-ink-500">{rules.filter((rule) => rule.enabled).length} enabled · {rules.length} total</p></div>
          {loading ? <div className="p-5 text-sm text-ink-500">Loading automations…</div> : <div className="divide-y divide-ink-50">
            {rules.map((rule) => <div key={rule.id} className="p-5"><div className="flex flex-wrap items-start justify-between gap-3"><div><p className="font-semibold">{rule.name}</p><p className="mt-1 text-xs text-ink-500">Trigger: {rule.trigger_event === "scorecards_complete" ? "All scorecards submitted" : rule.trigger_stage || "Any stage"} · Action: {rule.action_type.replaceAll("_"," ")}</p></div><span className={rule.enabled ? "rounded-full bg-emerald-50 px-2.5 py-1 text-[11px] font-semibold text-emerald-800" : "rounded-full bg-ink-50 px-2.5 py-1 text-[11px] font-semibold text-ink-500"}>{rule.enabled ? "Enabled" : "Disabled"}</span></div>{rule.subject && <p className="mt-3 text-sm font-medium">{rule.subject}</p>}{rule.action_value && <p className="mt-2 text-xs text-ink-500">Value: {users.find((u) => String(u.id) === String(rule.action_value))?.full_name || rule.action_value}</p>}<div className="mt-4 flex flex-wrap gap-2"><button className={secondary} onClick={() => startEdit(rule)}>Edit</button><button className={secondary} onClick={() => toggle(rule)}>{rule.enabled ? "Disable" : "Enable"}</button><button className={secondary} onClick={() => remove(rule)}>Delete</button></div></div>)}
            {!rules.length && <div className="p-12 text-center text-sm text-ink-500">No workflow rules yet.</div>}
          </div>}
        </section>
      </div>
    </section>
  );
}
