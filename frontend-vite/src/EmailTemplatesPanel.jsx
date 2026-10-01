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

const EMPTY_TEMPLATE = { subject: "", body: "" };

export default function EmailTemplatesPanel({ token, apiRequest, onNotice, onError }) {
  const [templates, setTemplates] = useState({});
  const [active, setActive] = useState("Applied");
  const [draft, setDraft] = useState(EMPTY_TEMPLATE);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [preview, setPreview] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [testRecipient, setTestRecipient] = useState("");
  const [testSending, setTestSending] = useState(false);
  const [savedAt, setSavedAt] = useState("");

  async function loadTemplates() {
    setLoading(true);
    try {
      const response = await apiRequest(token, "get", "/email-templates");
      setTemplates(response.data || {});
    } catch (error) {
      onError(error);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadTemplates();
  }, [token]);

  useEffect(() => {
    setDraft(templates[active] || EMPTY_TEMPLATE);
    setPreview(null);
  }, [active, templates]);

  async function save() {
    if (!draft.subject.trim() || !draft.body.trim()) {
      onError(new Error("Subject and body are required."));
      return;
    }
    setSaving(true);
    try {
      const response = await apiRequest(token, "patch", "/email-templates", {
        data: { templates: { [active]: { subject: draft.subject.trim(), body: draft.body } } },
      });
      const nextTemplates = response.data || {};
      setTemplates(nextTemplates);
      setDraft(nextTemplates[active] || EMPTY_TEMPLATE);
      setSavedAt(new Date().toLocaleTimeString());
      onNotice("Email template saved successfully. New lifecycle emails will use this template.");
    } catch (error) {
      onError(error);
    } finally {
      setSaving(false);
    }
  }

  async function previewTemplate() {
    setPreviewLoading(true);
    try {
      const response = await apiRequest(token, "get", "/email-templates/preview", {
        params: { template_name: active },
      });
      setPreview(response.data);
    } catch (error) {
      onError(error);
    } finally {
      setPreviewLoading(false);
    }
  }

  async function sendTest() {
    const recipient = testRecipient.trim();
    if (!recipient) {
      onError(new Error("Enter a test recipient email address."));
      return;
    }
    setTestSending(true);
    try {
      const response = await apiRequest(token, "post", "/email-templates/test", {
        data: { template_name: active, recipient },
      });
      onNotice(response.data?.status === "queued"
        ? `Test email queued for ${response.data.recipient}. Check Email Center for delivery status.`
        : "Test email request completed.");
    } catch (error) {
      onError(error);
    } finally {
      setTestSending(false);
    }
  }

  return (
    <section>
      <div className="mb-5">
        <p className="text-sm text-ink-500">Edit, preview, and test every candidate notification template.</p>
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
                  type="button"
                  key={name}
                  className={"rounded-md px-3 py-2 text-left text-sm font-medium " + (active === name ? "bg-blue-50 text-blue-800" : "text-ink-700 hover:bg-ink-50")}
                  onClick={() => setActive(name)}
                >
                  <span>{name}</span>
                  {templates[name]?.subject && <span className="mt-0.5 block text-[10px] text-emerald-600">Configured</span>}
                </button>
              ))}
            </div>
          </aside>

          <div className="grid gap-5">
            <section className="rounded-xl border border-ink-100 bg-white p-5">
              <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.14em] text-blue-700">{active}</p>
                  <h3 className="mt-1 font-semibold">Message editor</h3>
                  {savedAt && <p className="mt-1 text-xs text-emerald-600">Saved at {savedAt}</p>}
                </div>
                <button type="button" className={buttonSecondary} onClick={() => setDraft(templates[active] || EMPTY_TEMPLATE)}>Reload saved version</button>
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
                  <p className="font-semibold">Supported placeholders</p>
                  <p className="mt-1 font-mono break-words">{'{{candidate_name}}'}, {'{{job_title}}'}, {'{{interview_date}}'}, {'{{interview_time}}'}, {'{{interview_duration}}'}, {'{{interview_mode}}'}, {'{{meeting_link}}'}, {'{{interview_location}}'}, {'{{candidate_portal_url}}'}, {'{{company_name}}'}</p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <button type="button" className={buttonPrimary} disabled={saving || !draft.subject?.trim() || !draft.body?.trim()} onClick={save}>{saving ? "Saving…" : "Save template"}</button>
                  <button type="button" className={buttonSecondary} disabled={previewLoading} onClick={previewTemplate}>{previewLoading ? "Loading preview…" : "Preview rendered email"}</button>
                </div>
              </div>
            </section>

            {preview && (
              <section className="rounded-xl border border-ink-100 bg-white p-5">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div><p className="text-xs font-semibold uppercase tracking-[0.14em] text-blue-700">Live preview</p><h3 className="mt-1 font-semibold">{preview.subject}</h3></div>
                  <span className="rounded-full bg-ink-50 px-2.5 py-1 text-[11px] font-semibold text-ink-700">{preview.is_custom ? "Saved custom template" : "Default template"}</span>
                </div>
                <pre className="mt-4 whitespace-pre-wrap rounded-xl border border-ink-100 bg-[#fafaf8] p-4 text-sm leading-6 text-ink-700">{preview.body}</pre>
              </section>
            )}

            <section className="rounded-xl border border-ink-100 bg-white p-5">
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-blue-700">Delivery check</p>
              <h3 className="mt-1 font-semibold">Send a test email</h3>
              <p className="mt-1 text-sm text-ink-500">This tests the selected template and your SMTP configuration. Delivery status appears in Email Center.</p>
              <div className="mt-4 flex flex-col gap-2 sm:flex-row">
                <input className={inputStyle} type="email" value={testRecipient} placeholder="recruiter@example.com" onChange={(event) => setTestRecipient(event.target.value)} />
                <button type="button" className={buttonPrimary} disabled={testSending || !testRecipient.trim()} onClick={sendTest}>{testSending ? "Queueing…" : "Send test"}</button>
              </div>
            </section>
          </div>
        </div>
      )}
    </section>
  );
}
