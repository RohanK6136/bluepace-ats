import { useMemo, useState } from "react";

const PUBLIC_FAQS = [
  {
    category: "Applying",
    question: "How do I apply for a job?",
    answer:
      "Choose an open position, select “Apply for this position,” enter your name and email, add your phone if needed, and upload a PDF or DOCX resume up to 10MB.",
  },
  {
    category: "Applying",
    question: "What resume formats are accepted?",
    answer: "The public application form accepts PDF and DOCX resumes up to 10MB.",
  },
  {
    category: "Application status",
    question: "How can I track my application?",
    answer:
      "After applying, the recruiting team can send you a secure candidate portal link by email. Use that link to view your application status, timeline, interviews, documents, and offer information.",
  },
  {
    category: "Application status",
    question: "Will I receive application updates?",
    answer:
      "Application and recruiting updates are sent to the email address you provide when applying. Keep that email address current so you do not miss updates.",
  },
  {
    category: "Interviews",
    question: "Where will I see my interview details?",
    answer:
      "When an interview is scheduled, your secure candidate portal can show the date, time, duration, online meeting link or on-site location, and a calendar option.",
  },
  {
    category: "Documents",
    question: "How do I upload a requested document?",
    answer:
      "Open the secure candidate portal link from the recruiting team. The Documents section shows any requested files and lets you upload supported documents.",
  },
  {
    category: "Offers",
    question: "How do I respond to an offer?",
    answer:
      "Open your secure candidate portal and review the Offer section. When an offer is available for response, the portal provides accept and decline controls.",
  },
  {
    category: "Privacy & support",
    question: "Can I contact the recruiting team?",
    answer:
      "Yes. Use the contact or question feature available in your secure candidate portal for application-specific questions. Do not share passwords or other sensitive credentials in messages.",
  },
];

const QUICK_QUESTIONS = [
  "How do I apply?",
  "What resume formats are accepted?",
  "How do I track my application?",
  "How do interview updates work?",
];

function answerQuestion(question) {
  const normalized = question.trim().toLowerCase();
  const match = PUBLIC_FAQS.find((faq) => {
    const words = faq.question
      .toLowerCase()
      .replace(/[^a-z0-9 ]/g, " ")
      .split(/\s+/)
      .filter((word) => word.length > 3);
    return words.filter((word) => normalized.includes(word)).length >= Math.min(3, words.length);
  });

  if (match) return match.answer;

  if (/apply|application|resume|job|position|opening/.test(normalized)) {
    return "I can help with applying for jobs, accepted resume formats, application updates, interviews, documents, and offers. Try one of the quick questions above.";
  }
  if (/status|track|where.*application|progress/.test(normalized)) {
    return "For application-specific status, open the secure candidate portal link sent by the recruiting team. That portal contains your latest status and timeline.";
  }
  if (/interview|meeting|calendar/.test(normalized)) {
    return "Interview details appear in the secure candidate portal after the recruiting team schedules an interview.";
  }
  if (/offer|salary|ctc/.test(normalized)) {
    return "Offer information is only available to the intended candidate through the secure candidate portal when an offer has been issued.";
  }
  return "I’m the BluePace Help Center. I can answer common questions about applying, resumes, application status, interviews, documents, and offers. Try a suggested question.";
}

function SupportHeader({ portal }) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-ink-100 px-5 py-4">
      <div>
        <p className="text-sm font-semibold text-ink-900">blupace Help Center</p>
        <p className="mt-0.5 text-xs text-ink-500">
          {portal ? "Help for your candidate application portal" : "Help with applications and careers"}
        </p>
      </div>
    </div>
  );
}

export default function PublicHelpCenter({ portal = false }) {
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState("chat");
  const [query, setQuery] = useState("");
  const [messages, setMessages] = useState([
    {
      id: 1,
      role: "assistant",
      text: "Hello. I can help with applications, interview updates, documents, offers, and using the candidate portal.",
    },
  ]);

  const visibleFaqs = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return PUBLIC_FAQS;
    return PUBLIC_FAQS.filter((faq) =>
      (faq.question + " " + faq.answer + " " + faq.category).toLowerCase().includes(normalized)
    );
  }, [query]);

  function sendQuestion(value = query) {
    const text = value.trim();
    if (!text) return;
    setMessages((current) => [
      ...current,
      { id: Date.now(), role: "user", text },
      { id: Date.now() + 1, role: "assistant", text: answerQuestion(text) },
    ]);
    setQuery("");
  }

  function openSection() {
    setOpen(true);
    if (!portal) {
      window.setTimeout(() => document.getElementById("jobs")?.scrollIntoView({ behavior: "smooth", block: "start" }), 80);
    }
  }

  return (
    <>
      <button
        type="button"
        onClick={openSection}
        className="fixed bottom-5 right-5 z-[70] inline-flex h-14 w-14 items-center justify-center rounded-full bg-ink-950 text-lg font-bold text-gold-300 shadow-[0_14px_34px_rgba(15,23,42,0.25)] transition hover:-translate-y-0.5 hover:bg-ink-900 focus:outline-none focus:ring-4 focus:ring-gold-200"
        aria-label="Open BluePace Help Center"
        title="Help Center"
      >
        <span className="bp-help-icon" aria-hidden="true">?</span>
      </button>

      {open && (
        <div className="fixed inset-0 z-[80] bg-black/35" onClick={() => setOpen(false)}>
          <aside
            className="absolute bottom-5 right-5 flex h-[min(720px,calc(100dvh-2.5rem))] w-[min(440px,calc(100vw-2rem))] flex-col overflow-hidden rounded-2xl border border-ink-100 bg-white shadow-2xl max-sm:inset-x-0 max-sm:bottom-0 max-sm:right-0 max-sm:h-[100dvh] max-sm:w-full max-sm:max-w-none max-sm:rounded-none"
            aria-label="BluePace Help Center"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-center justify-between gap-3 border-b border-ink-100 px-5 py-3">
              <SupportHeader portal={portal} />
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="grid h-9 w-9 shrink-0 place-items-center rounded-md border border-ink-100 text-lg text-ink-400 hover:bg-ink-50 hover:text-ink-800"
                aria-label="Close Help Center"
              >
                ×
              </button>
            </div>

            <div className="flex border-b border-ink-100 bg-[#fafaf8]">
              <button
                type="button"
                className={`flex-1 px-4 py-3 text-sm font-semibold ${mode === "chat" ? "border-b-2 border-gold-500 text-ink-900" : "text-ink-500"}`}
                onClick={() => setMode("chat")}
              >
                Chat
              </button>
              <button
                type="button"
                className={`flex-1 px-4 py-3 text-sm font-semibold ${mode === "faq" ? "border-b-2 border-gold-500 text-ink-900" : "text-ink-500"}`}
                onClick={() => setMode("faq")}
              >
                FAQs
              </button>
            </div>

            {mode === "chat" ? (
              <>
                <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
                  <div className="space-y-3">
                    {messages.map((message) => (
                      <div key={message.id} className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}>
                        <div
                          className={`max-w-[88%] rounded-2xl px-3.5 py-2.5 text-sm leading-6 ${message.role === "user"
                            ? "rounded-br-md bg-ink-950 text-white"
                            : "rounded-bl-md border border-ink-100 bg-[#fafaf8] text-ink-700"}`}
                        >
                          {message.text}
                        </div>
                      </div>
                    ))}
                  </div>

                  <div className="mt-5">
                    <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-400">Common questions</p>
                    <div className="mt-2 grid gap-2">
                      {QUICK_QUESTIONS.map((question) => (
                        <button
                          key={question}
                          type="button"
                          className="rounded-xl border border-ink-100 bg-white px-3 py-2.5 text-left text-xs font-semibold text-ink-700 transition hover:bg-ink-50"
                          onClick={() => sendQuestion(question)}
                        >
                          {question}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>

                <form
                  className="border-t border-ink-100 bg-white p-3"
                  onSubmit={(event) => {
                    event.preventDefault();
                    sendQuestion();
                  }}
                >
                  <div className="flex items-center gap-2">
                    <input
                      value={query}
                      onChange={(event) => setQuery(event.target.value)}
                      className="min-w-0 flex-1 rounded-xl border border-ink-100 bg-[#fafaf8] px-3 py-2.5 text-sm outline-none focus:border-gold-500 focus:ring-2 focus:ring-gold-100"
                      placeholder="Ask how the portal works…"
                      aria-label="Ask the BluePace Help Center"
                    />
                    <button type="submit" className="rounded-xl bg-ink-950 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50" disabled={!query.trim()}>
                      Send
                    </button>
                  </div>
                </form>
              </>
            ) : (
              <div className="min-h-0 flex-1 overflow-y-auto p-4">
                <label className="grid gap-1.5 text-xs font-semibold text-ink-700">
                  Search help
                  <input
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    className="rounded-xl border border-ink-100 bg-[#fafaf8] px-3 py-2.5 text-sm outline-none focus:border-gold-500 focus:ring-2 focus:ring-gold-100"
                    placeholder="Search applications, interviews, offers…"
                  />
                </label>

                <div className="mt-4 space-y-2">
                  {visibleFaqs.map((faq) => (
                    <details key={faq.question} className="rounded-xl border border-ink-100 bg-white p-3">
                      <summary className="cursor-pointer list-none text-sm font-semibold text-ink-800">
                        <span className="mr-2 text-[10px] uppercase tracking-wider text-gold-700">{faq.category}</span>
                        {faq.question}
                      </summary>
                      <p className="mt-2 text-sm leading-6 text-ink-600">{faq.answer}</p>
                    </details>
                  ))}
                  {!visibleFaqs.length && (
                    <p className="rounded-xl border border-ink-100 bg-[#fafaf8] p-4 text-sm text-ink-500">
                      No matching help article found. Try a different search phrase.
                    </p>
                  )}
                </div>

                {!portal && (
                  <button
                    type="button"
                    onClick={openSection}
                    className="mt-4 w-full rounded-xl border border-gold-200 bg-gold-50 px-4 py-3 text-sm font-semibold text-gold-800 hover:bg-gold-100"
                  >
                    Browse open positions
                  </button>
                )}
              </div>
            )}
          </aside>
        </div>
      )}
    </>
  );
}
