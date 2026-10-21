import { useMemo, useState } from "react";

const primaryButton = "inline-flex items-center justify-center gap-2 rounded-md bg-[#c49a4a] px-4 py-2 text-sm font-semibold text-[#10131c] transition hover:bg-[#d4b06a] disabled:cursor-not-allowed disabled:opacity-50";
const secondaryButton = "inline-flex items-center justify-center gap-2 rounded-md border border-ink-100 bg-white px-3 py-2 text-sm font-semibold text-ink-800 transition hover:bg-ink-50 disabled:cursor-not-allowed disabled:opacity-50";
const inputStyle = "w-full rounded-md border border-ink-100 bg-white px-3 py-2.5 text-sm text-ink-900 outline-none transition placeholder:text-ink-400 focus:border-gold-500 focus:ring-2 focus:ring-gold-100";

function uniqueJobs(applications) {
  const byId = new Map();
  applications.forEach((application) => {
    if (application.job_id && !byId.has(application.job_id)) {
      byId.set(application.job_id, { id: application.job_id, title: application.job_title || "Untitled role" });
    }
  });
  return [...byId.values()];
}

function scoreTone(value) {
  const score = Number(value);
  if (score >= 80) return "text-emerald-800 bg-emerald-50 border-emerald-100";
  if (score >= 50) return "text-amber-800 bg-amber-50 border-amber-100";
  return "text-ink-600 bg-ink-50 border-ink-100";
}

export default function CandidateComparisonPanel({ token, apiRequest, applications, onNotice, onError }) {
  const [jobId, setJobId] = useState("");
  const [selected, setSelected] = useState([]);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);

  const jobs = useMemo(() => uniqueJobs(applications), [applications]);
  const visibleApplications = useMemo(
    () => applications.filter((application) => !jobId || Number(application.job_id) === Number(jobId)),
    [applications, jobId],
  );

  function toggleApplication(id) {
    setResult(null);
    setSelected((current) => {
      if (current.includes(id)) return current.filter((value) => value !== id);
      if (current.length >= 3) return current;
      return [...current, id];
    });
  }

  function chooseJob(value) {
    setJobId(value);
    setResult(null);
    setSelected([]);
  }

  async function compareCandidates() {
    if (selected.length < 2) return;
    setLoading(true);
    setResult(null);
    onError?.(null);
    try {
      const response = await apiRequest(token, "post", "/candidate-tools/compare", {
        data: { application_ids: selected },
      });
      setResult(response.data);
      onNotice?.("Candidate evidence comparison generated");
    } catch (requestError) {
      onError?.(requestError);
    } finally {
      setLoading(false);
    }
  }

  const selectedApplications = visibleApplications.filter((application) => selected.includes(application.id));

  return (
    <section className="grid gap-5">
      <div className="border-b border-ink-200 pb-5">
        <p className="text-xs font-medium text-ink-500">Decision support</p>
        <h2 className="mt-1 text-2xl font-semibold tracking-tight">Compare candidates</h2>
        <p className="mt-1 max-w-3xl text-sm leading-6 text-ink-500">
          Compare two or three applications side by side using stored resume and job evidence. The comparison is neutral and does not rank, hire, reject, or move candidates.
        </p>
      </div>

      <div className="rounded-xl border border-ink-100 bg-white p-4 sm:p-5">
        <div className="grid gap-4 lg:grid-cols-[280px_1fr_auto] lg:items-end">
          <label className="grid gap-1.5 text-xs font-semibold text-ink-700">
            Role
            <select className={inputStyle} value={jobId} onChange={(event) => chooseJob(event.target.value)}>
              <option value="">All roles</option>
              {jobs.map((job) => <option key={job.id} value={job.id}>{job.title}</option>)}
            </select>
          </label>
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.12em] text-ink-500">Selected</p>
            <p className="mt-1 text-sm text-ink-600">{selected.length} of 3 candidates · choose applications for the same role for the clearest comparison.</p>
          </div>
          <button type="button" className={primaryButton} disabled={selected.length < 2 || loading} onClick={compareCandidates}>
            {loading ? "Comparing evidence…" : "Compare selected"}
          </button>
        </div>

        <div className="mt-5 grid gap-2">
          {visibleApplications.map((application) => {
            const name = `${application.candidate?.first_name || ""} ${application.candidate?.last_name || ""}`.trim() || "Unnamed candidate";
            const checked = selected.includes(application.id);
            return (
              <label key={application.id} className={`flex cursor-pointer items-center gap-3 rounded-lg border px-3 py-3 transition ${checked ? "border-gold-300 bg-[#fbf7ef]" : "border-ink-100 bg-white hover:bg-ink-50"}`}>
                <input type="checkbox" checked={checked} onChange={() => toggleApplication(application.id)} disabled={!checked && selected.length >= 3} className="h-4 w-4" />
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-semibold text-ink-900">{name}</span>
                  <span className="block truncate text-xs text-ink-500">{application.job_title || "Role not specified"} · {application.stage_name || "Applied"} · {application.candidate?.email || "No email"}</span>
                </span>
              </label>
            );
          })}
          {!visibleApplications.length && <p className="text-sm text-ink-500">No applications are available for comparison.</p>}
        </div>
      </div>

      {result && (
        <div className="grid gap-5">
          <div className="rounded-xl border border-blue-100 bg-blue-50/50 p-4 sm:p-5">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.16em] text-blue-700">Evidence comparison</p>
                <h3 className="mt-1 text-lg font-semibold">{result.job?.title || "Selected role"}</h3>
                <p className="mt-2 max-w-4xl text-sm leading-6 text-ink-700">{result.summary}</p>
              </div>
              <span className="rounded-full border border-blue-100 bg-white px-3 py-1.5 text-xs font-semibold text-blue-800">
                {result.data_coverage ?? 0}% evidence coverage · {result.confidence || "medium"} confidence
              </span>
            </div>
          </div>

          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {(result.items || []).map((item) => (
              <article key={item.application_id} className="rounded-xl border border-ink-100 bg-white p-4 shadow-sm">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-lg font-semibold truncate">{item.candidate_name}</p>
                    <p className="mt-1 text-xs text-ink-500">{item.stage || "Applied"}</p>
                  </div>
                  <span className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${scoreTone(item.skill_coverage)}`}>
                    {item.skill_coverage}% required-skill coverage
                  </span>
                </div>

                <div className="mt-4 grid grid-cols-2 gap-2">
                  <div className="rounded-lg bg-[#fafaf8] p-3">
                    <p className="text-[11px] font-semibold uppercase tracking-wide text-ink-500">Experience</p>
                    <p className="mt-1 text-sm font-semibold">{item.experience_years != null ? `${item.experience_years} years` : "Not evidenced"}</p>
                  </div>
                  <div className="rounded-lg bg-[#fafaf8] p-3">
                    <p className="text-[11px] font-semibold uppercase tracking-wide text-ink-500">Education</p>
                    <p className="mt-1 text-sm font-semibold">{item.education || "Not evidenced"}</p>
                  </div>
                </div>

                <div className="mt-4">
                  <p className="text-xs font-semibold uppercase tracking-wide text-ink-500">Evidence summary</p>
                  <p className="mt-2 text-sm leading-6 text-ink-700">{item.evidence_summary}</p>
                </div>

                <div className="mt-4 grid gap-3">
                  <div>
                    <p className="text-xs font-semibold text-emerald-800">Strengths evidenced</p>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {(item.strengths || []).map((value, index) => <span key={index} className="rounded-full bg-emerald-50 px-2.5 py-1 text-[11px] font-medium text-emerald-800">{value}</span>)}
                      {!(item.strengths || []).length && <span className="text-xs text-ink-400">None highlighted</span>}
                    </div>
                  </div>
                  <div>
                    <p className="text-xs font-semibold text-amber-800">Gaps / verification points</p>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {(item.gaps || []).map((value, index) => <span key={index} className="rounded-full bg-amber-50 px-2.5 py-1 text-[11px] font-medium text-amber-800">{value}</span>)}
                      {!(item.gaps || []).length && <span className="text-xs text-ink-400">None highlighted</span>}
                    </div>
                  </div>
                </div>
              </article>
            ))}
          </div>

          {!!(result.cross_candidate_considerations || []).length && (
            <div className="rounded-xl border border-ink-100 bg-white p-4 sm:p-5">
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-ink-500">Across the selected applications</p>
              <ul className="mt-3 grid gap-2 text-sm leading-6 text-ink-700">
                {(result.cross_candidate_considerations || []).map((value, index) => <li key={index} className="border-b border-ink-50 pb-2 last:border-0 last:pb-0">• {value}</li>)}
              </ul>
            </div>
          )}

          <div className="text-xs leading-5 text-ink-500">
            This comparison summarizes recorded evidence only. It is decision support, not an automated hiring recommendation.
          </div>
        </div>
      )}
    </section>
  );
}
