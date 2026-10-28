import { useMemo, useState } from "react";

const primary = "inline-flex items-center justify-center rounded-md bg-[#c49a4a] px-3 py-2 text-xs font-semibold text-[#11141c] transition hover:bg-[#d4b06a] disabled:cursor-not-allowed disabled:opacity-50";

function canonicalSkill(value) {
  const compact = String(value || "").toLowerCase().replace(/[^a-z0-9+#]/g, "");
  const aliases = { postgres: "postgresql", nodejs: "nodejs", node: "nodejs", js: "javascript", ts: "typescript", k8s: "kubernetes" };
  return aliases[compact] || compact;
}

function listedSkills(candidate) {
  const profile = candidate?.resume_data || {};
  const values = [profile.skills, profile.technical_skills, profile.skills_detected]
    .flatMap((group) => Array.isArray(group) ? group : []);
  const seen = new Set();
  return values.map((value) => typeof value === "string" ? value.trim() : String(value?.name || "").trim())
    .filter((value) => {
      const key = canonicalSkill(value);
      if (!key || seen.has(key)) return false;
      seen.add(key);
      return true;
    });
}

function CandidateRoleRediscovery({ candidate, jobs = [], applications = [], canWrite = false, token, apiRequest, onCreated, onNotice, onError }) {
  const [addingJobId, setAddingJobId] = useState(null);
  const skills = useMemo(() => listedSkills(candidate), [candidate]);
  const matches = useMemo(() => {
    if (!skills.length) return [];
    const appliedJobIds = new Set(applications.filter((row) => row.candidate_id === candidate?.id).map((row) => String(row.job_id)));
    const candidateSkills = new Map(skills.map((skill) => [canonicalSkill(skill), skill]));
    return jobs
      .filter((job) => job.status === "open" && !job.archived && !appliedJobIds.has(String(job.id)))
      .map((job) => {
        const requirements = Array.isArray(job.required_skills)
          ? Array.from(new Set(job.required_skills.map((value) => String(value || "").trim()).filter(Boolean)))
          : [];
        const matched = requirements.filter((requirement) => candidateSkills.has(canonicalSkill(requirement)));
        const missing = requirements.filter((requirement) => !candidateSkills.has(canonicalSkill(requirement)));
        return { job, requirements, matched, missing };
      })
      .filter((match) => match.requirements.length > 0 && match.matched.length > 0)
      .sort((a, b) => b.matched.length - a.matched.length || a.missing.length - b.missing.length || a.job.title.localeCompare(b.job.title))
      .slice(0, 5);
  }, [applications, candidate?.id, jobs, skills]);

  async function addToRole(match) {
    const candidateLabel = [candidate?.first_name, candidate?.last_name].filter(Boolean).join(" ") || "this candidate";
    const confirmed = window.confirm(
      `Create an application for ${candidateLabel} in “${match.job.title}”? This starts a new application and may trigger configured Applied-stage emails or automations. The skill overlap is a review aid, not a qualification decision.`
    );
    if (!confirmed) return;
    setAddingJobId(match.job.id);
    try {
      const response = await apiRequest(token, "post", "/applications", { data: { candidate_id: candidate.id, job_id: match.job.id } });
      onCreated?.(response.data);
      onNotice?.(`Application created for ${match.job.title}.`);
    } catch (error) {
      onError?.(error);
    } finally {
      setAddingJobId(null);
    }
  }

  return (
    <section className="mt-5 rounded-xl border border-ink-100 bg-[#fafaf8] p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div><p className="text-xs font-semibold uppercase tracking-[0.16em] text-blue-700">Candidate rediscovery</p><h3 className="mt-1 text-lg font-semibold text-ink-950">Other open roles to review</h3><p className="mt-1 max-w-2xl text-sm leading-6 text-ink-600">Find possible next roles from explicit skill overlap. This does not rank the candidate or decide whether they qualify.</p></div>
        <span className="rounded-full border border-ink-200 bg-white px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wide text-ink-600">{skills.length} profile skill{skills.length === 1 ? "" : "s"} listed</span>
      </div>

      {!skills.length && <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm leading-6 text-amber-950">This profile has no structured skill list to compare. Review or update the candidate’s parsed skills before using role rediscovery.</div>}
      {skills.length > 0 && !matches.length && <div className="mt-4 rounded-lg border border-ink-100 bg-white p-4 text-sm leading-6 text-ink-600">No open role matched the skills explicitly listed on this profile. That does not mean the candidate lacks skills; it means there is no direct overlap in the structured fields checked.</div>}
      {matches.length > 0 && <div className="mt-4 grid gap-3">{matches.map(({ job, matched, missing, requirements }) => <article key={job.id} className="rounded-lg border border-ink-100 bg-white p-4">
        <div className="flex flex-wrap items-start justify-between gap-3"><div className="min-w-0"><h4 className="truncate text-sm font-semibold text-ink-950">{job.title}</h4><p className="mt-1 text-xs text-ink-500">{job.department || "Department not set"}{job.location ? ` · ${job.location}` : ""}</p></div><span className="shrink-0 rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-800">{matched.length} of {requirements.length} listed requirements overlap</span></div>
        <div className="mt-3"><p className="text-[10px] font-semibold uppercase tracking-wide text-ink-500">Evidence overlap</p><div className="mt-1.5 flex flex-wrap gap-1.5">{matched.map((requirement) => <span key={requirement} className="rounded-full border border-emerald-200 bg-emerald-50 px-2 py-1 text-[11px] font-medium text-emerald-900">{requirement}</span>)}</div></div>
        {missing.length > 0 && <div className="mt-3"><p className="text-[10px] font-semibold uppercase tracking-wide text-ink-500">Not listed on the profile · verify before deciding</p><div className="mt-1.5 flex flex-wrap gap-1.5">{missing.map((requirement) => <span key={requirement} className="rounded-full border border-amber-200 bg-amber-50 px-2 py-1 text-[11px] font-medium text-amber-900">{requirement}</span>)}</div></div>}
        <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-ink-100 pt-3"><p className="text-[11px] leading-5 text-ink-500">Only directly listed skill names are compared. Experience, context, and unlisted skills are not inferred.</p>{canWrite && <button type="button" className={primary} disabled={addingJobId !== null} onClick={() => addToRole({ job, matched, missing, requirements })}>{addingJobId === job.id ? "Creating…" : "Review & add to role"}</button>}</div>
      </article>)}</div>}
      {!canWrite && <p className="mt-3 text-xs text-ink-500">A recruiter can review and create an application for a suggested role.</p>}
      {canWrite && <p className="mt-3 text-[11px] leading-5 text-ink-500">Creating an application may trigger the role’s configured stage automations or candidate email. You’ll confirm before that happens.</p>}
    </section>
  );
}

export default CandidateRoleRediscovery;

