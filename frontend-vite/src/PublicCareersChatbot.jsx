import { useMemo, useState } from "react";

const quickQuestions = [
  "How do I apply for a job?",
  "Which file types can I upload?",
  "How can I check my application status?",
  "I need help finding a role",
];

function answerQuestion(input, jobs) {
  const q = input.toLowerCase();
  if (/\b(hello|hi|hey|good morning|good afternoon)\b/.test(q)) {
    return "Hello! I’m the BluePace Careers assistant. I can help you find open roles, submit an application, prepare your resume upload, and understand the candidate portal.";
  }
  if (/\b(job|jobs|opening|openings|vacanc|role|position|available)\b/.test(q) && /\b(list|show|open|available|find|search|which|current|latest)\b/.test(q)) {
    if (!jobs.length) return "There are no open roles listed at the moment. Please check the Open roles section again later.";
    return "Here are the open roles currently shown on this page:\n" + jobs.slice(0, 8).map((job) => "• " + job.title + (job.location ? " — " + job.location : "")).join("\n") + (jobs.length > 8 ? "\nOpen the Open roles section to see the rest." : "") + "\n\nChoose “Apply for this position” on a role card to apply.";
  }
  if (/\b(apply|application form|submit|how to apply)\b/.test(q)) {
    return "To apply: 1) Browse Open roles and choose a suitable position. 2) Select “Apply for this position”. 3) Enter your full name and email, add your phone if you wish, and upload your resume as a PDF or DOCX (up to 5 MB). 4) Select “Submit Application”. Check that your contact details and file are correct before submitting.";
  }
  if (/\b(pdf|docx|word|file type|format|resume|cv|upload|size limit)\b/.test(q)) {
    return "The application form accepts a resume in PDF or DOCX format, up to 5 MB. Please use a text-readable document and check that your name, contact details, skills, experience, and education are easy to read.";
  }
  if (/\b(status|track|tracking|progress|shortlist|screening|interview|offer|rejected|hired|candidate portal)\b/.test(q)) {
    return "For application-specific updates, use the candidate portal link provided to you by the recruiting team, if you have one. If you can’t access it or need clarification, contact the recruiting team through the contact details on the careers page. I can’t look up private application records from this public chat.";
  }
  if (/\b(withdraw|cancel application|remove my application)\b/.test(q)) {
    return "If you have a candidate portal link, open it to review the options available for your application. If you can’t access the portal, contact the recruiting team and include the role title and the email address you applied with. Don’t share passwords or sensitive identity documents in chat.";
  }
  if (/\b(password|login|sign in|portal link|expired|invalid link)\b/.test(q)) {
    return "The candidate portal is accessed through the private link supplied for your application. If the link has expired or won’t open, contact the recruiting team and ask them to help you access the portal. Never share your password or private access link publicly.";
  }
  if (/\b(contact|human|person|recruiter|support|help|email|phone)\b/.test(q)) {
    return "I can answer common careers and application questions. For a personal application issue, use the contact details shown in the careers page footer or contact the recruiting team directly. This assistant does not send emails or create support tickets.";
  }
  if (/\b(privacy|data|personal information|resume data|secure)\b/.test(q)) {
    return "Only enter information required by the application form and upload the resume you intend to submit. Avoid sharing passwords, government ID numbers, banking details, or other sensitive information in this chat. For questions about how your application data is handled, contact BluePace Tech through its official website.";
  }
  return "I can help with finding open roles, applying, resume file requirements, candidate portal access, and application-status questions. Try one of the suggested questions below. For personal application records, please contact the recruiting team.";
}

export default function PublicCareersChatbot({ jobs = [] }) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [messages, setMessages] = useState([
    { role: "assistant", text: "Hi! I’m the BluePace Careers assistant. Ask me about open roles, applications, resume uploads, or candidate portal access." },
  ]);
  const visibleJobs = useMemo(() => Array.isArray(jobs) ? jobs : [], [jobs]);

  function send(value = draft) {
    const question = value.trim();
    if (!question || busy) return;
    setDraft("");
    setMessages((current) => [...current, { role: "user", text: question }]);
    setBusy(true);
    // A local FAQ assistant keeps public help available without exposing candidate data or depending on an AI key.
    const reply = answerQuestion(question, visibleJobs);
    setMessages((current) => [...current, { role: "assistant", text: reply }]);
    setBusy(false);
  }

  return (
    <>
      {open && (
        <section
          className="fixed bottom-24 right-4 z-[60] flex w-[min(390px,calc(100vw-2rem))] max-h-[min(640px,calc(100dvh-7.5rem))] flex-col overflow-hidden rounded-2xl border border-ink-100 bg-white shadow-2xl sm:right-6"
          aria-label="BluePace Careers help chat"
          role="dialog"
          aria-modal="false"
        >
          <header className="flex items-center justify-between bg-ink-950 px-4 py-3 text-white">
            <div className="flex items-center gap-3">
              <span className="grid h-9 w-9 place-items-center rounded-xl bg-white/10 text-sm font-bold">BP</span>
              <div>
                <p className="text-sm font-semibold">BluePace Careers Help</p>
                <p className="text-[11px] text-white/70">Instant answers · no email sent</p>
              </div>
            </div>
            <button type="button" onClick={() => setOpen(false)} aria-label="Close help chat" className="rounded-md px-2 py-1 text-xl text-white/80 hover:bg-white/10">×</button>
          </header>
          <div className="min-h-0 flex-1 space-y-3 overflow-y-auto overscroll-contain bg-[#f5f8fb] p-4" aria-live="polite">
            {messages.map((item, index) => (
              <div key={index} className={`flex ${item.role === "user" ? "justify-end" : "justify-start"}`}>
                <div className={item.role === "user" ? "max-w-[88%] rounded-2xl rounded-br-md bg-[#1769d3] px-3.5 py-2.5 text-sm leading-5 text-white" : "max-w-[94%] whitespace-pre-wrap rounded-2xl rounded-bl-md border border-ink-100 bg-white px-3.5 py-2.5 text-sm leading-5 text-ink-700"}>
                  {item.text}
                </div>
              </div>
            ))}
            {busy && <p className="text-xs text-ink-500">Preparing answer…</p>}
          </div>
          <div className="border-t border-ink-100 bg-white p-3">
            <div className="mb-2 flex gap-1.5 overflow-x-auto pb-1">
              {quickQuestions.map((question) => (
                <button key={question} type="button" onClick={() => send(question)} className="shrink-0 rounded-full border border-ink-100 px-2.5 py-1.5 text-[11px] font-semibold text-ink-600 hover:bg-ink-50" disabled={busy}>
                  {question}
                </button>
              ))}
            </div>
            <form onSubmit={(event) => { event.preventDefault(); send(); }} className="flex items-end gap-2">
              <label className="sr-only" htmlFor="public-careers-chat-input">Ask a careers question</label>
              <textarea id="public-careers-chat-input" rows={2} maxLength={600} value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); send(); } }} placeholder="Ask about careers or applying…" className="min-h-11 min-w-0 flex-1 resize-none rounded-xl border border-ink-100 px-3 py-2.5 text-sm outline-hidden focus:border-blue-500 focus:ring-2 focus:ring-blue-100" disabled={busy} />
              <button type="submit" aria-label="Send message" disabled={busy || !draft.trim()} className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-[#1769d3] text-lg text-white hover:bg-[#0b4ea2] disabled:opacity-50">↗</button>
            </form>
            <p className="mt-2 text-[10px] leading-4 text-ink-400">Please don’t share passwords or sensitive personal information.</p>
          </div>
        </section>
      )}
      <button type="button" onClick={() => setOpen((value) => !value)} className="fixed bottom-5 right-4 z-[60] inline-flex h-14 w-14 items-center justify-center rounded-full bg-[#1769d3] text-white shadow-xl ring-4 ring-white hover:bg-[#0b4ea2] sm:right-6" aria-label={open ? "Close careers help chat" : "Open careers help chat"} title="Careers help">
        {open ? <span aria-hidden="true">×</span> : <span aria-hidden="true" className="text-xl">✦</span>}
      </button>
    </>
  );
}
