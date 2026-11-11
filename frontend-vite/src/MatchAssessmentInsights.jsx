import { buildMatchAssessmentInsights } from "./matchAssessmentInsights.mjs";

function StatusPill({ status }) {
  const label = String(status || "not_evidenced").replaceAll("_", " ");
  const tone = status === "met" ? "bg-emerald-50 text-emerald-800 border-emerald-200"
    : status === "partial" ? "bg-amber-50 text-amber-800 border-amber-200"
      : "bg-ink-50 text-ink-600 border-ink-200";
  return <span className={`inline-flex rounded-full border px-2 py-0.5 text-[10px] font-semibold capitalize ${tone}`}>{label}</span>;
}

function ProgressRow({ label, score, weight }) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between gap-3 text-xs">
        <span className="font-medium text-ink-700">{label}</span>
        <span className="tabular-nums text-ink-600">{score}%{weight == null ? "" : ` · ${weight}% weight`}</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-ink-100" role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={score}>
        <div className="h-full rounded-full bg-[#c49a4a]" style={{ width: `${score}%` }} />
      </div>
    </div>
  );
}

export default function MatchAssessmentInsights({ result, sampleReference = null }) {
  const { strengths, gaps, breakdown, summary } = buildMatchAssessmentInsights(result);
  return (
    <div className="space-y-3">
      {sampleReference && (
        <div className="rounded-lg border border-blue-100 bg-blue-50 px-4 py-3 text-xs leading-5 text-blue-900">
          <strong>Sample reference:</strong> {sampleReference.score}/100 manual benchmark. This uses a separate rubric; compare the evidence and reasoning, not the numeric score alone.
        </div>
      )}
      {summary?.value && (
        <section className="rounded-lg border border-ink-100 bg-white p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-sm font-semibold text-ink-900">Candidate summary</h3>
            <span className="text-[10px] font-semibold uppercase tracking-wide text-ink-500">{summary.status || "summary"}</span>
          </div>
          <p className="mt-2 text-sm leading-6 text-ink-800">{summary.value}</p>
          {summary.reason && <p className="mt-2 text-xs text-ink-500">{summary.reason}</p>}
        </section>
      )}
      <section className="rounded-lg border border-ink-100 bg-white p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-semibold text-ink-900">Score breakdown</h3>
          <span className="text-[11px] text-ink-500">Calculated by the Applicant Match API</span>
        </div>
        {breakdown.length ? <div className="mt-4 grid gap-4 sm:grid-cols-2">{breakdown.map((item) => <ProgressRow key={item.key} {...item} />)}</div>
          : <p className="mt-2 text-xs text-ink-500">No category scores were returned for this assessment.</p>}
      </section>
      <div className="grid gap-3 xl:grid-cols-2">
        <section className="rounded-lg border border-ink-100 bg-white p-4">
          <div className="flex items-center justify-between gap-2">
            <h3 className="text-sm font-semibold text-ink-900">Evidence-backed strengths</h3>
            <StatusPill status="met" />
          </div>
          {strengths.length ? <ul className="mt-3 space-y-3">{strengths.slice(0, 8).map((item) => (
            <li key={item.item_id} className="border-b border-ink-100 pb-3 last:border-0 last:pb-0">
              <div className="flex flex-wrap items-center justify-between gap-2"><p className="text-sm font-medium text-ink-800">{item.label}</p><span className="text-[10px] text-ink-500">{item.importance === "must" ? "Required" : "Preferred"}</span></div>
              {item.lines?.length ? <p className="mt-1 border-l-2 border-emerald-300 pl-2 text-xs leading-5 text-ink-600">{item.lines[0].text}</p>
                : <p className="mt-1 text-xs text-ink-500">Marked met by the assessment; open the criterion evidence below to inspect its support.</p>}
            </li>
          ))}</ul> : <p className="mt-3 text-xs leading-5 text-ink-500">No criteria were marked fully met. Review partial, unclear and not-demonstrated evidence below.</p>}
        </section>
        <section className="rounded-lg border border-ink-100 bg-white p-4">
          <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="text-sm font-semibold text-ink-900">Gaps and verification points</h3><span className="text-[10px] text-ink-500">{gaps.length} item(s)</span></div>
          {gaps.length ? <ul className="mt-3 space-y-3">{gaps.slice(0, 8).map((item) => (
            <li key={item.item_id} className="border-b border-ink-100 pb-3 last:border-0 last:pb-0">
              <div className="flex flex-wrap items-center justify-between gap-2"><p className="text-sm font-medium text-ink-800">{item.label}</p><StatusPill status={item.status} /></div>
              <p className="mt-1 text-[10px] font-medium uppercase tracking-wide text-ink-500">{item.importance === "must" ? "Required" : "Preferred"}</p>
              {item.note && <p className="mt-1 text-xs leading-5 text-ink-600">{item.note}</p>}
            </li>
          ))}</ul> : <p className="mt-3 text-xs leading-5 text-ink-500">No gaps were returned. Confirm the cited evidence before relying on the result.</p>}
          <p className="mt-3 border-t border-ink-100 pt-3 text-[11px] leading-5 text-ink-500">Not demonstrated in a resume does not prove the candidate lacks a skill. Verify material gaps consistently during screening.</p>
        </section>
      </div>
    </div>
  );
}
