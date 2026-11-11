import { buildMatchAssessmentInsights } from "./matchAssessmentInsights.mjs";

function StatusPill({ status }) {
  const label = String(status || "not_evidenced").replaceAll("_", " ");
  const tone = status === "met" ? "bg-emerald-50 text-emerald-800 border-emerald-200"
    : status === "partial" || status === "unclear" ? "bg-amber-50 text-amber-800 border-amber-200"
      : "bg-ink-50 text-ink-600 border-ink-200";
  return <span className={`inline-flex rounded-full border px-2 py-0.5 text-[10px] font-semibold capitalize ${tone}`}>{label}</span>;
}

function ProgressRow({ label, score, weight, detail }) {
  return (
    <div>
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2 text-xs">
        <span className="font-medium text-ink-700">{label}</span>
        <span className="tabular-nums text-ink-600">{score}%{weight == null ? "" : ` · ${weight}% weight`}</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-ink-100" role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={score}>
        <div className="h-full rounded-full bg-[#c49a4a]" style={{ width: `${score}%` }} />
      </div>
      {detail && <p className="mt-1 text-[10px] text-ink-500">{detail}</p>}
    </div>
  );
}

function CountTile({ label, value, detail }) {
  return (
    <div className="rounded-lg border border-ink-100 bg-white p-3">
      <p className="text-[10px] font-semibold uppercase tracking-wide text-ink-500">{label}</p>
      <p className="mt-1 text-xl font-semibold tabular-nums text-ink-950">{value}</p>
      {detail && <p className="mt-0.5 text-[10px] text-ink-500">{detail}</p>}
    </div>
  );
}

function formatYears(value) {
  if (value == null || !Number.isFinite(Number(value))) return "Not established";
  const amount = Number(value);
  return `${Number.isInteger(amount) ? amount : amount.toFixed(1)} years`;
}

function ProfileFacts({ profile, scores }) {
  const experience = scores?.experience || {};
  const education = scores?.education || {};
  const facts = [
    ["Latest role", profile?.latest_title || "Not established"],
    ["Latest employer", profile?.latest_company || "Not established"],
    ["Total experience", formatYears(experience.total_years ?? profile?.total_years)],
    ["Relevant experience", formatYears(experience.relevant_years ?? profile?.relevant_years)],
    ["Required experience", experience.required_years == null ? "Not specified in rubric" : formatYears(experience.required_years)],
    ["Education level", education.level || profile?.education_level || "Not established"],
    ["Minimum education", education.required || "Not specified in rubric"],
  ];
  return (
    <section className="rounded-lg border border-ink-100 bg-white p-4">
      <h3 className="text-sm font-semibold text-ink-900">Candidate profile analysis</h3>
      <p className="mt-1 text-xs leading-5 text-ink-500">Facts extracted from the resume. Missing or undated history must be checked with the candidate.</p>
      <dl className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {facts.map(([label, value]) => (
          <div key={label} className="rounded-md bg-[#fafaf8] px-3 py-2">
            <dt className="text-[10px] font-semibold uppercase tracking-wide text-ink-500">{label}</dt>
            <dd className="mt-1 text-sm font-medium text-ink-800">{value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

export default function MatchAssessmentInsights({ result, sampleReference = null }) {
  const {
    strengths, gaps, breakdown, summary, match, counts, requiredCounts,
    preferredCounts, evidenceCoverage, recommendation, profile, scores,
  } = buildMatchAssessmentInsights(result);

  const recommendationTone = recommendation.tone === "good"
    ? "border-emerald-200 bg-emerald-50/60"
    : recommendation.tone === "warn"
      ? "border-amber-200 bg-amber-50/60"
      : "border-ink-200 bg-[#fafaf8]";

  return (
    <div className="space-y-4">
      {sampleReference && (
        <div className="rounded-lg border border-blue-100 bg-blue-50 px-4 py-3 text-xs leading-5 text-blue-900">
          <strong>Sample reference:</strong> {sampleReference.score}/100 manual benchmark. This uses a separate rubric; compare the evidence and reasoning, not the numeric score alone.
        </div>
      )}

      <section className="grid gap-3 xl:grid-cols-[minmax(220px,0.7fr)_minmax(0,1.3fr)]">
        <div className="rounded-lg border border-ink-200 bg-white p-4">
          <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-ink-500">Overall evidence-weighted match</p>
          <div className="mt-2 flex items-end gap-2">
            <p className="text-4xl font-semibold tracking-tight tabular-nums text-ink-950">{match == null ? "—" : match}</p>
            <p className="pb-1 text-sm text-ink-500">{match == null ? "Manual review" : "/ 100"}</p>
          </div>
          {match != null && (
            <div className="mt-3 h-2.5 overflow-hidden rounded-full bg-ink-100" role="progressbar" aria-label="Overall evidence-weighted match" aria-valuemin={0} aria-valuemax={100} aria-valuenow={match}>
              <div className="h-full rounded-full bg-[#c49a4a]" style={{ width: `${match}%` }} />
            </div>
          )}
          <p className="mt-3 text-xs leading-5 text-ink-500">Calculated from the available category scores and the rubric weights. It is not a probability of job performance or a hiring decision.</p>
          {evidenceCoverage != null && <p className="mt-2 text-xs font-medium text-ink-700">Evidence present for {evidenceCoverage}% of rubric criteria.</p>}
        </div>

        <div className={`rounded-lg border p-4 ${recommendationTone}`}>
          <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-ink-500">Recommended next step · recruiter review</p>
          <h3 className="mt-2 text-base font-semibold text-ink-950">{recommendation.title}</h3>
          <p className="mt-2 text-sm leading-6 text-ink-800">{recommendation.detail}</p>
          <p className="mt-3 border-t border-black/5 pt-3 text-xs leading-5 text-ink-700">{recommendation.action}</p>
          <p className="mt-2 text-[10px] leading-4 text-ink-500">Decision support only. A recruiter must verify the evidence and decide the next hiring step.</p>
        </div>
      </section>

      <section className="rounded-lg border border-ink-100 bg-[#fafaf8] p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-semibold text-ink-900">Requirement coverage</h3>
          <span className="text-[11px] text-ink-500">{counts.total} rubric criteria assessed</span>
        </div>
        <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
          <CountTile label="Met" value={counts.met} detail="Evidence marked met" />
          <CountTile label="Partial" value={counts.partial} detail="Some supporting evidence" />
          <CountTile label="Unclear" value={counts.unclear} detail="Needs verification" />
          <CountTile label="Not evidenced" value={counts.not_evidenced} detail="Not found in resume" />
        </div>
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          <div className="rounded-md border border-ink-100 bg-white px-3 py-2">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-ink-500">Must-have requirements</p>
            <p className="mt-1 text-sm font-semibold text-ink-900">{requiredCounts.met} / {requiredCounts.total} fully met</p>
            <p className="mt-0.5 text-[11px] text-ink-500">{requiredCounts.partial} partial · {requiredCounts.unclear} unclear · {requiredCounts.not_evidenced} not evidenced</p>
          </div>
          <div className="rounded-md border border-ink-100 bg-white px-3 py-2">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-ink-500">Preferred requirements</p>
            <p className="mt-1 text-sm font-semibold text-ink-900">{preferredCounts.met} / {preferredCounts.total} fully met</p>
            <p className="mt-0.5 text-[11px] text-ink-500">{preferredCounts.partial} partial · {preferredCounts.unclear} unclear · {preferredCounts.not_evidenced} not evidenced</p>
          </div>
        </div>
      </section>

      <ProfileFacts profile={profile} scores={scores} />

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
          <h3 className="text-sm font-semibold text-ink-900">Analytical score breakdown</h3>
          <span className="text-[11px] text-ink-500">Category weights are applied by the Applicant Match API</span>
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
          {strengths.length ? <ul className="mt-3 space-y-3">{strengths.slice(0, 12).map((item) => (
            <li key={item.item_id} className="border-b border-ink-100 pb-3 last:border-0 last:pb-0">
              <div className="flex flex-wrap items-center justify-between gap-2"><p className="text-sm font-medium text-ink-800">{item.label}</p><span className="text-[10px] text-ink-500">{item.importance === "must" ? "Required" : "Preferred"}</span></div>
              {item.lines?.length ? <p className="mt-1 border-l-2 border-emerald-300 pl-2 text-xs leading-5 text-ink-600">{item.lines[0].text}</p>
                : <p className="mt-1 text-xs text-ink-500">Marked met by the assessment; open the criterion evidence below to inspect its support.</p>}
            </li>
          ))}</ul> : <p className="mt-3 text-xs leading-5 text-ink-500">No criteria were marked fully met. Review partial, unclear and not-demonstrated evidence below.</p>}
        </section>

        <section className="rounded-lg border border-ink-100 bg-white p-4">
          <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="text-sm font-semibold text-ink-900">Gaps and verification points</h3><span className="text-[10px] text-ink-500">{gaps.length} item(s)</span></div>
          {gaps.length ? <ul className="mt-3 space-y-3">{gaps.slice(0, 12).map((item) => (
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
