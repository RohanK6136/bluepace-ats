import { useRef, useState } from "react";

function statusLabel(status) {
  if (status === "review_recommended") return "Review recommended";
  if (status === "insufficient_evidence") return "Insufficient evidence";
  if (status === "no_text_quality_alerts") return "No text-quality alerts";
  return status || "Unknown";
}

function statusTone(status) {
  if (status === "review_recommended") return "border-amber-200 bg-amber-50 text-amber-900";
  if (status === "insufficient_evidence") return "border-slate-200 bg-slate-50 text-slate-700";
  return "border-emerald-200 bg-emerald-50 text-emerald-900";
}

/** Resume text-quality review. Never presents an AI-vs-human verdict. */
export default function ResumeAuthorshipReviewPanel({ token, apiRequest }) {
  const fileRef = useRef(null);
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);
  const [sourceLabel, setSourceLabel] = useState("");

  async function runTextReview() {
    const payload = text.trim();
    if (payload.length < 100) {
      setError("Paste at least 100 characters of resume text.");
      return;
    }
    setLoading(true);
    setError("");
    setResult(null);
    setSourceLabel("pasted text");
    try {
      const response = await apiRequest(token, "post", "/v1/resume-authorship/assess", {
        data: { text: payload },
      });
      setResult(response.data || null);
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setError(typeof detail === "string" ? detail : err?.message || "Review failed.");
    } finally {
      setLoading(false);
    }
  }

  async function runFileReview(event) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setLoading(true);
    setError("");
    setResult(null);
    setSourceLabel(file.name);
    try {
      const form = new FormData();
      form.append("file", file);
      const response = await apiRequest(token, "post", "/v1/resume-authorship/assess/upload", {
        data: form,
      });
      setResult(response.data || null);
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setError(typeof detail === "string" ? detail : err?.message || "Upload review failed.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-5">
      <div className="rounded-2xl border border-ink-100 bg-white p-5 shadow-sm">
        <p className="text-xs font-semibold uppercase tracking-wide text-ink-500">Resume text-quality review</p>
        <h3 className="mt-1 text-lg font-semibold text-ink-900">Observable signals only — not an AI detector</h3>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-ink-600">
          Reviews extracted resume text for repetition, uniform bullets, and generic corporate phrases.
          Always returns <strong>undetermined</strong> authorship. OpenAPI:{" "}
          <code className="rounded bg-ink-50 px-1">POST /v1/resume-authorship/assess</code>
        </p>
        <label className="mt-4 block text-sm font-medium text-ink-800" htmlFor="authorship-text">
          Paste extracted resume text
        </label>
        <textarea
          id="authorship-text"
          className="mt-1 min-h-40 w-full rounded-xl border border-ink-200 bg-white px-3 py-2 text-sm text-ink-900 shadow-sm focus:border-blue-400 focus:outline-none focus:ring-2 focus:ring-blue-100"
          placeholder="Paste resume text (minimum 100 characters)…"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button
            type="button"
            className="rounded-xl bg-ink-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
            onClick={runTextReview}
            disabled={loading}
          >
            {loading ? "Reviewing…" : "Review pasted text"}
          </button>
          <button
            type="button"
            className="rounded-xl border border-ink-200 bg-white px-4 py-2 text-sm font-semibold text-ink-800 disabled:opacity-50"
            onClick={() => fileRef.current?.click()}
            disabled={loading}
          >
            Upload PDF / DOCX / TXT
          </button>
          <input
            ref={fileRef}
            type="file"
            accept=".pdf,.docx,.txt,.md,application/pdf"
            className="hidden"
            onChange={runFileReview}
          />
        </div>
        {error && (
          <p role="alert" className="mt-3 text-sm text-rose-700">{error}</p>
        )}
      </div>

      {result && (
        <div className="rounded-2xl border border-ink-100 bg-white p-5 shadow-sm">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-ink-500">Result</p>
              <p className="mt-1 text-sm text-ink-600">
                Source: {sourceLabel || "text"} ·{" "}
                {result.text_characters?.toLocaleString?.() || result.text_characters} characters · detector{" "}
                {result.detector_version}
              </p>
            </div>
            <span className={`rounded-full border px-3 py-1 text-xs font-semibold ${statusTone(result.status)}`}>
              {statusLabel(result.status)}
            </span>
          </div>
          <dl className="mt-4 grid gap-3 sm:grid-cols-3">
            <div className="rounded-xl border border-ink-100 bg-ink-50/60 p-3">
              <dt className="text-xs text-ink-500">Authorship assessment</dt>
              <dd className="mt-1 text-sm font-semibold text-ink-900">{result.assessment}</dd>
            </div>
            <div className="rounded-xl border border-ink-100 bg-ink-50/60 p-3">
              <dt className="text-xs text-ink-500">Confidence</dt>
              <dd className="mt-1 text-sm font-semibold text-ink-900">{result.confidence}</dd>
            </div>
            <div className="rounded-xl border border-ink-100 bg-ink-50/60 p-3">
              <dt className="text-xs text-ink-500">Human review</dt>
              <dd className="mt-1 text-sm font-semibold text-ink-900">
                {result.human_review_required ? "Required" : "Optional"}
              </dd>
            </div>
          </dl>
          {result.signals?.length > 0 ? (
            <ul className="mt-4 space-y-2">
              {result.signals.map((signal) => (
                <li key={signal.code} className="rounded-xl border border-ink-100 px-3 py-2 text-sm">
                  <p className="font-semibold text-ink-900">
                    {signal.label}{" "}
                    <span className="text-xs font-normal text-ink-500">({signal.severity || "low"})</span>
                  </p>
                  <p className="mt-1 text-ink-600">{signal.detail}</p>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-4 text-sm text-ink-600">No text-quality signals were raised for this sample.</p>
          )}
          {result.limitations?.length > 0 && (
            <div className="mt-4 rounded-xl border border-amber-100 bg-amber-50/70 p-3">
              <p className="text-xs font-semibold uppercase tracking-wide text-amber-800">Limitations</p>
              <ul className="mt-2 list-disc space-y-1 pl-4 text-xs leading-5 text-amber-900">
                {result.limitations.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
