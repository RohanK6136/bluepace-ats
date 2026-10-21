import { useState } from "react";

const suggestions = [
  "How many applications are in the pipeline?",
  "What jobs are currently open?",
  "Show the current application stage counts.",
  "What can I review first today?",
];

export default function AtsChatbot({ token, apiRequest, onError }) {
  const [open, setOpen] = useState(false);
  const [message, setMessage] = useState("");
  const [messages, setMessages] = useState([
    {
      role: "assistant",
      text: "Hi! I’m the BluePace ATS assistant. Ask me about jobs, candidates, applications, pipeline stages, skills, or recruiter workflow.",
    },
  ]);
  const [loading, setLoading] = useState(false);

  async function sendMessage(value = message) {
    const text = value.trim();
    if (!text || loading) return;

    setMessage("");
    setMessages((current) => [...current, { role: "user", text }]);
    setLoading(true);

    try {
      const response = await apiRequest(token, "post", "/chatbot", {
        data: { message: text },
      });
      setMessages((current) => [
        ...current,
        {
          role: "assistant",
          text: response.data?.answer || "I couldn’t generate a response.",
          ai: response.data?.ai_enabled,
        },
      ]);
    } catch (error) {
      onError?.(error);
      setMessages((current) => [
        ...current,
        { role: "assistant", text: "I couldn’t reach the ATS assistant right now. Please retry." },
      ]);
    } finally {
      setLoading(false);
    }
  }

  function handleKeyDown(event) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendMessage();
    }
  }

  return (
    <>
      {open && (
        <section
          className="fixed bottom-24 right-4 z-50 flex w-[min(380px,calc(100vw-2rem))] max-h-[min(680px,calc(100dvh-7rem))] flex-col overflow-hidden rounded-2xl border border-ink-100 bg-white shadow-2xl sm:right-6 dark:border-slate-700 dark:bg-slate-900"
          aria-label="BluePace ATS chatbot"
        >
          <div className="flex items-center justify-between bg-ink-950 px-4 py-3 text-white">
            <div>
              <p className="text-sm font-semibold">BluePace ATS Assistant</p>
              <p className="text-[11px] text-white/65">Live workspace data · recruiter decision support</p>
            </div>
            <button
              type="button"
              className="rounded-md px-2 py-1 text-lg leading-none text-white/70 hover:bg-white/10 hover:text-white"
              onClick={() => setOpen(false)}
              aria-label="Close chatbot"
            >
              ×
            </button>
          </div>

          <div className="min-h-0 flex-1 space-y-3 overflow-y-auto overscroll-contain bg-[#f8fafc] p-4 dark:bg-slate-950">
            {messages.map((item, index) => (
              <div key={index} className={`flex ${item.role === "user" ? "justify-end" : "justify-start"}`}>
                <div
                  className={
                    item.role === "user"
                      ? "max-w-[88%] rounded-2xl rounded-br-md bg-[#1769d3] px-3.5 py-2.5 text-sm leading-5 text-white"
                      : "max-w-[92%] rounded-2xl rounded-bl-md border border-ink-100 bg-white px-3.5 py-2.5 text-sm leading-5 text-ink-700 shadow-sm dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
                  }
                >
                  <p className="whitespace-pre-wrap">{item.text}</p>
                </div>
              </div>
            ))}

            {loading && (
              <div className="flex justify-start">
                <div className="rounded-2xl rounded-bl-md border border-ink-100 bg-white px-3.5 py-2.5 text-sm text-ink-500 shadow-sm dark:border-slate-700 dark:bg-slate-900">
                  Thinking…
                </div>
              </div>
            )}
          </div>

          <div className="border-t border-ink-100 bg-white p-3 dark:border-slate-700 dark:bg-slate-900">
            <div className="mb-2 flex gap-1.5 overflow-x-auto pb-1">
              {suggestions.map((suggestion) => (
                <button
                  key={suggestion}
                  type="button"
                  className="shrink-0 rounded-full border border-ink-100 bg-white px-2.5 py-1.5 text-[11px] font-semibold text-ink-600 hover:bg-ink-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300"
                  onClick={() => sendMessage(suggestion)}
                  disabled={loading}
                >
                  {suggestion}
                </button>
              ))}
            </div>
            <div className="flex items-end gap-2">
              <textarea
                rows={2}
                value={message}
                onChange={(event) => setMessage(event.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask about the ATS…"
                className="min-h-11 flex-1 resize-none rounded-xl border border-ink-100 bg-white px-3 py-2.5 text-sm text-ink-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
                disabled={loading}
              />
              <button
                type="button"
                className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-[#1769d3] text-white hover:bg-[#0b4ea2] disabled:cursor-not-allowed disabled:opacity-50"
                onClick={() => sendMessage()}
                disabled={loading || !message.trim()}
                aria-label="Send message"
              >
                ↗
              </button>
            </div>
          </div>
        </section>
      )}

      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        className="fixed bottom-5 right-4 z-50 inline-flex h-14 w-14 items-center justify-center rounded-full bg-[#1769d3] text-white shadow-xl ring-4 ring-white hover:bg-[#0b4ea2] sm:right-6 dark:ring-slate-950"
        aria-label={open ? "Close ATS chatbot" : "Open ATS chatbot"}
        title={open ? "Close ATS chatbot" : "Open ATS chatbot"}
      >
        {open ? "×" : "✦"}
      </button>
    </>
  );
}
