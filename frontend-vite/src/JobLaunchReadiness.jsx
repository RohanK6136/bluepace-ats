const card = "rounded-lg border border-ink-100 bg-white p-4";

function checksFor(job) {
  const description = String(job.description || "").trim();
  const skills = job.required_skills?.length || job.jd_analysis?.required_skills?.length || 0;
  const mode = job.work_mode || job.jd_analysis?.work_mode || "onsite";
  return [
    { label: "Role title", ready: Boolean(job.title?.trim()) },
    { label: "Job description has role context", ready: description.length >= 180 },
    { label: "Required skills listed", ready: skills > 0 },
    { label: "Employment type set", ready: Boolean(job.employment_type?.trim()) },
    { label: mode === "remote" ? "Remote work mode stated" : "Work location provided", ready: mode === "remote" || Boolean(job.location?.trim()) },
  ];
}

export default function JobLaunchReadiness({ jobs = [], canWrite, onEdit }) {
  const activeJobs = jobs.filter((job) => !["closed", "archived"].includes(job.status));
  const roleChecks = activeJobs.map((job) => ({ job, checks: checksFor(job) }));
  const readyCount = roleChecks.filter(({ checks }) => checks.every((check) => check.ready)).length;
  const reviewRoles = roleChecks.filter(({ checks }) => !checks.every((check) => check.ready));

  return <section className="mb-5 rounded-xl border border-blue-100 bg-blue-50/40 p-4 sm:p-5" aria-labelledby="job-readiness-heading">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><p className="text-xs font-semibold uppercase tracking-wide text-blue-700">Requisition quality</p><h3 id="job-readiness-heading" className="mt-1 font-semibold text-ink-950">Job launch readiness</h3><p className="mt-1 max-w-2xl text-xs leading-5 text-ink-600">A quick completeness check before sourcing or publishing. It is guidance only and does not block a job from opening.</p></div>
      <div className="flex gap-2"><span className="rounded-full bg-white px-3 py-1 text-xs font-semibold text-emerald-800">{readyCount} ready</span><span className="rounded-full bg-white px-3 py-1 text-xs font-semibold text-amber-900">{reviewRoles.length} to review</span></div>
    </div>
    {reviewRoles.length ? <div className="mt-4 grid gap-3 lg:grid-cols-2">{reviewRoles.slice(0, 6).map(({ job, checks }) => {
      const missing = checks.filter((check) => !check.ready);
      return <article key={job.id} className={card}>
        <div className="flex flex-wrap items-start justify-between gap-2"><div><h4 className="text-sm font-semibold text-ink-950">{job.title || "Untitled role"}</h4><p className="mt-1 text-[11px] text-ink-500">{job.status} · {job.department || "Department not set"}</p></div><span className="rounded-full bg-amber-50 px-2 py-1 text-[10px] font-bold uppercase text-amber-800">{missing.length} item{missing.length === 1 ? "" : "s"} to review</span></div>
        <ul className="mt-3 grid gap-1.5 sm:grid-cols-2">{checks.map((check) => <li key={check.label} className={`text-xs ${check.ready ? "text-emerald-800" : "text-amber-900"}`}><span aria-hidden="true" className="mr-1.5 font-bold">{check.ready ? "✓" : "○"}</span>{check.label}</li>)}</ul>
        {canWrite && <button type="button" className="mt-3 text-xs font-semibold text-blue-800 underline underline-offset-2" onClick={() => onEdit?.(job)}>Edit role details</button>}
      </article>;
    })}{reviewRoles.length > 6 && <p className="text-xs text-ink-500 lg:col-span-2">Showing 6 of {reviewRoles.length} roles that could use a completeness review.</p>}</div> : <p className="mt-4 rounded-lg border border-emerald-100 bg-white p-3 text-sm text-emerald-800">All active roles meet these basic completeness checks.</p>}
  </section>;
}

