import { useEffect, useState } from "react";

const STAGE_NAMES = [
  "Applied",
  "Screening",
  "Interview",
  "Offer",
  "Hired",
  "Rejected",
  "Interview Reminder 24h",
  "Interview Reminder 1h",
];

const inputStyle = "w-full rounded-md border border-ink-100 bg-white px-3 py-2.5 text-sm text-ink-900 outline-none transition placeholder:text-ink-400 focus:border-blue-500 focus:ring-2 focus:ring-blue-100";
const buttonPrimary = "inline-flex items-center justify-center gap-2 rounded-md bg-[#1769d3] px-4 py-2 text-sm font-semibold text-white transition hover:bg-[#0b4ea2] disabled:cursor-not-allowed disabled:opacity-50";
const buttonSecondary = "inline-flex items-center justify-center gap-2 rounded-md border border-ink-100 bg-white px-3 py-2 text-sm font-semibold text-ink-800 transition hover:bg-ink-50 disabled:cursor-not-allowed disabled:opacity-50";

export default function EmailTemplatesPanel({ token, apiRequest, onNotice, onError }) {
  const [templates, setTemplates] = useState({});
  const [active, setActive] = useState("Applied");
  const [draft, setDraft] = useState({ subject: "", body: "" });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    apiRequest(token, "get", "/email-templates")
      .then((response) => {
        if (!mounted) return;
        setTemplates(response.data || {});
      })
      .catch((error) => {
        if (mounted) onError(error);
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });
    return () => { mounted = false; };
  }, [token, apiRequest, onError]);

  useEffect(() => {
    setDraft(templates[active] || { subject: "", body: "" });
  }, [active, templates]);

  async function save() {
    setSaving(true);
    try {
      const response = await apiRequest(token, "patch", "/email-templates", {
        data: { templates: { [active]: draft } },
      });
      setTemplates(response.data || {});
      onNotice("Email template saved");
    } catch (error) {
      onError(error);
    } finally {
      setSaving(false);
    }
  }

  return (
    <section>
      <div className="mb-5">
        <p className="text-sm text-ink-500">Control the messages candidates receive throughout the hiring process.</p>
        <h2 className="mt-1 text-xl font-semibold">Email templates</h2>
      </div>
      {loading ? (
        <div className="rounded-xl border border-ink-100 bg-white p-6 text-sm text-ink-500">Loading templates…</div>
      ) : (
        <div className="grid gap-5 lg:grid-cols-[260px_1fr]">
          <aside className="rounded-xl border border-ink-100 bg-white p-3">
            <p className="px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-500">Templates</p>
            <div className="grid gap-1">
              {STAGE_NAMES.map((name) => (
                <button
                  key={name}
                  className={"rounded-md px-3 py-2 text-left text-sm font-medium " + (active === name ? "bg-blue-50 text-blue-800" : "text-ink-700 hover:bg-ink-50")}
                  onClick={() => setActive(name)}
                >
                  {name}
                </button>
              ))}
            </div>
          </aside>
          <section className="rounded-xl border border-ink-100 bg-white p-5">
            <div className="mb-5 flex items-start justify-between gap-3">
              <div><p className="text-xs font-semibold uppercase tracking-[0.14em] text-blue-700">{active}</p><h3 className="mt-1 font-semibold">Message editor</h3></div>
              <button className={buttonSecondary} onClick={() => setDraft(templates[active] || { subject: "", body: "" })}>Reset</button>
            </div>
            <div className="grid gap-4">
              <label className="grid gap-1.5 text-xs font-semibold text-ink-700">
                Subject
                <input className={inputStyle} value={draft.subject || ""} onChange={(event) => setDraft({ ...draft, subject: event.target.value })} />
              </label>
              <label className="grid gap-1.5 text-xs font-semibold text-ink-700">
                Body
                <textarea className={inputStyle + " min-h-72 resize-y"} value={draft.body || ""} onChange={(event) => setDraft({ ...draft, body: event.target.value })} />
              </label>
              <div className="rounded-lg border border-blue-100 bg-blue-50 p-4 text-xs leading-5 text-blue-900">
                Supported placeholders: {{candidate_name}}, {{job_title}}, {{interview_date}}, {{interview_time}}, {{interview_duration}}, {{interview_mode}}, {{meeting_link}}, {{interview_location}}, {{candidate_portal_url}}, {{company_name}}
              </div>
              <div><button className={buttonPrimary} disabled={saving || !draft.subject || !draft.body} onClick={save}>{saving ? "Saving…" : "Save template"}</button></div>
            </div>
          </section>
        </div>
      )}
    </section>
  );
}
