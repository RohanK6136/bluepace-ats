import { useMemo, useState } from "react";

const STAGES = ["Applied", "Screening", "Interview", "Offer", "Hired", "Rejected"];

const stageDescriptions = {
  Applied: "New applications to review",
  Screening: "Recruiter screening in progress",
  Interview: "Interview loop and feedback",
  Offer: "Offers being prepared or reviewed",
  Hired: "Completed hires",
  Rejected: "Closed applications",
};

function normalizeSkill(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/[.\-_+#]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function getRequiredSkills(job) {
  if (!job) return [];
  if (Array.isArray(job.required_skills)) return job.required_skills;
  return String(job.required_skills || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function skillCoverage(application, jobs) {
  const job = jobs.find((item) => Number(item.id) === Number(application.job_id));
  const required = getRequiredSkills(job);
  const candidateSkills = application.candidate?.resume_data?.skills || [];
  if (!required.length || !candidateSkills.length) {
    return { covered: 0, total: required.length, label: "Not assessed", detail: "No structured skill evidence yet" };
  }

  const candidateSet = new Set(candidateSkills.map(normalizeSkill));
  const covered = required.filter((skill) => {
    const normalized = normalizeSkill(skill);
    return candidateSet.has(normalized)
      || [...candidateSet].some((item) => item.includes(normalized) || normalized.includes(item));
  }).length;

  const percentage = Math.round((covered / required.length) * 100);
  return {
    covered,
    total: required.length,
    label: percentage >= 80 ? "Strong" : percentage >= 50 ? "Partial" : "Gap",
    detail: `${covered}/${required.length} required skills evidenced`,
  };
}

function daysSince(value) {
  if (!value) return null;
  const timestamp = new Date(value).getTime();
  if (!Number.isFinite(timestamp)) return null;
  return Math.max(0, Math.floor((Date.now() - timestamp) / 86_400_000));
}

function candidateName(application) {
  return `${application.candidate?.first_name || ""} ${application.candidate?.last_name || ""}`.trim() || "Unnamed candidate";
}

function nextAction(stage) {
  if (stage === "Applied") return "Review application";
  if (stage === "Screening") return "Complete screening";
  if (stage === "Interview") return "Collect feedback";
  if (stage === "Offer") return "Review offer";
  if (stage === "Hired") return "Complete";
  return "Review";
}

function stageTone(stage) {
  if (stage === "Interview") return "border-blue-200 bg-blue-50 text-blue-800";
  if (stage === "Offer") return "border-gold-200 bg-[#fbf7ef] text-[#6f5425]";
  if (stage === "Hired") return "border-emerald-200 bg-emerald-50 text-emerald-800";
  if (stage === "Rejected") return "border-rose-200 bg-rose-50 text-rose-800";
  if (stage === "Screening") return "border-violet-200 bg-violet-50 text-violet-800";
  return "border-ink-100 bg-ink-50 text-ink-700";
}

export default function HiringPipelineKanban({
  applications = [],
  jobs = [],
  canWrite,
  onChangeStage,
  onOpenCandidate,
  onRefresh,
  onNotice,
  onError,
}) {
  const [jobFilter, setJobFilter] = useState("");
  const [search, setSearch] = useState("");
  const [draggedApplicationId, setDraggedApplicationId] = useState(null);

  const filteredApplications = useMemo(() => {
    const query = search.trim().toLowerCase();
    return applications.filter((application) => {
      if (jobFilter && String(application.job_id) !== String(jobFilter)) return false;
      if (!query) return true;
      const haystack = [
        candidateName(application),
        application.candidate?.email,
        application.job_title,
        application.candidate?.source,
      ].filter(Boolean).join(" ").toLowerCase();
      return haystack.includes(query);
    });
  }, [applications, jobFilter, search]);

  const columns = useMemo(() => STAGES.map((stage) => ({
    stage,
    items: filteredApplications.filter((application) => (application.stage_name || "Applied") === stage),
  })), [filteredApplications]);

  async function dropApplication(stage) {
    if (!canWrite || !draggedApplicationId) return;
    const application = applications.find((item) => Number(item.id) === Number(draggedApplicationId));
    setDraggedApplicationId(null);
    if (!application) return;

    const currentStage = application.stage_name || "Applied";
    if (currentStage === stage) return;

    try {
      await onChangeStage(application.id, stage);
      if (onNotice) onNotice(`${candidateName(application)} moved to ${stage}`);
    } catch (error) {
      if (onError) onError(error);
    }
  }

  async function refresh() {
    try {
      await onRefresh();
      if (onNotice) onNotice("Pipeline refreshed");
    } catch (error) {
      if (onError) onError(error);
    }
  }

  return (
    <section aria-label="Hiring pipeline" className="grid gap-5">
      <div className="flex flex-col gap-4 rounded-xl border border-ink-100 bg-white p-4 sm:p-5">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.12em] text-ink-500">Hiring pipeline</p>
            <h2 className="mt-1 text-xl font-semibold tracking-tight text-ink-950">Move candidates through every hiring stage</h2>
            <p className="mt-1 text-sm text-ink-500">Drag a card to another stage. AI signals stay neutral and evidence-based.</p>
          </div>
          <button type="button" className="rounded-md border border-ink-100 bg-white px-3 py-2 text-sm font-semibold text-ink-700 hover:bg-ink-50" onClick={refresh}>
            Refresh
          </button>
        </div>

        <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_240px]">
          <label className="grid gap-1.5 text-xs font-semibold text-ink-700">
            Search pipeline
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Candidate, email, role or source"
              className="w-full rounded-md border border-ink-100 bg-white px-3 py-2.5 text-sm font-normal text-ink-900 outline-none placeholder:text-ink-400 focus:border-blue-300 focus:ring-2 focus:ring-blue-100"
            />
          </label>
          <label className="grid gap-1.5 text-xs font-semibold text-ink-700">
            Job
            <select value={jobFilter} onChange={(event) => setJobFilter(event.target.value)} className="w-full rounded-md border border-ink-100 bg-white px-3 py-2.5 text-sm font-normal text-ink-900 outline-none focus:border-blue-300 focus:ring-2 focus:ring-blue-100">
              <option value="">All jobs</option>
              {jobs.filter((job) => job.status !== "archived").map((job) => (
                <option key={job.id} value={job.id}>{job.title}</option>
              ))}
            </select>
          </label>
        </div>

        <div className="flex flex-wrap gap-2 text-xs text-ink-500">
          <span className="rounded-full border border-ink-100 bg-ink-50 px-2.5 py-1.5"><strong className="text-ink-800">{filteredApplications.length}</strong> applications shown</span>
          <span className="rounded-full border border-ink-100 bg-ink-50 px-2.5 py-1.5">Drag-and-drop enabled for recruiters</span>
        </div>
      </div>

      <div className="grid min-w-0 gap-3 overflow-x-auto pb-2 xl:grid-cols-6">
        {columns.map(({ stage, items }) => (
          <section
            key={stage}
            className="min-w-[280px] rounded-xl border border-ink-100 bg-[#f7f8f6] p-2.5"
            onDragOver={(event) => {
              if (canWrite) event.preventDefault();
            }}
            onDrop={(event) => {
              event.preventDefault();
              void dropApplication(stage);
            }}
          >
            <div className="mb-2.5 flex items-start justify-between gap-2 px-1.5 py-1">
              <div>
                <div className="flex items-center gap-2">
                  <h3 className="text-sm font-semibold text-ink-900">{stage}</h3>
                  <span className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold ${stageTone(stage)}`}>{items.length}</span>
                </div>
                <p className="mt-1 text-[11px] leading-4 text-ink-500">{stageDescriptions[stage]}</p>
              </div>
            </div>

            <div className="grid min-h-[180px] content-start gap-2">
              {items.map((application) => {
                const name = candidateName(application);
                const coverage = skillCoverage(application, jobs);
                const age = daysSince(application.applied_at);
                const stageName = application.stage_name || "Applied";
                const canSchedule = stageName === "Interview";

                return (
                  <article
                    key={application.id}
                    draggable={Boolean(canWrite)}
                    onDragStart={(event) => {
                      if (!canWrite) return;
                      event.dataTransfer.effectAllowed = "move";
                      event.dataTransfer.setData("text/plain", String(application.id));
                      setDraggedApplicationId(application.id);
                    }}
                    onDragEnd={() => setDraggedApplicationId(null)}
                    className={`rounded-lg border bg-white p-3 shadow-sm transition hover:shadow-md ${draggedApplicationId === application.id ? "opacity-50" : "border-ink-100"}`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <button type="button" className="min-w-0 text-left" onClick={() => onOpenCandidate?.(application.candidate_id)}>
                        <p className="truncate text-sm font-semibold text-ink-950 hover:underline">{name}</p>
                        <p className="mt-0.5 truncate text-[11px] text-ink-500">{application.candidate?.email || "No email"}</p>
                      </button>
                      <span className={`shrink-0 rounded-full border px-2 py-1 text-[10px] font-semibold ${stageTone(stageName)}`}>{stageName}</span>
                    </div>

                    <div className="mt-3 border-t border-ink-100 pt-3">
                      <p className="truncate text-xs font-semibold text-ink-800">{application.job_title || "Role not specified"}</p>
                      <p className="mt-1 text-[11px] text-ink-500">{application.candidate?.source || "Direct"} {age !== null ? `· ${age}d in process` : ""}</p>
                    </div>

                    <div className="mt-3 grid gap-1.5">
                      <div className="flex items-center justify-between text-[11px]">
                        <span className="text-ink-500">Required-skill coverage</span>
                        <span className="font-semibold text-ink-800">{coverage.label}</span>
                      </div>
                      <p className="text-[11px] text-ink-500">{coverage.detail}</p>
                    </div>

                    <div className="mt-3 flex flex-wrap gap-2">
                      <button type="button" className="rounded-md border border-ink-100 px-2.5 py-1.5 text-[11px] font-semibold text-ink-700 hover:bg-ink-50" onClick={() => onOpenCandidate?.(application.candidate_id)}>
                        Candidate
                      </button>
                      {canWrite && (stage === "Applied" || stage === "Screening") && (
                        <button type="button" className="rounded-md border border-blue-200 bg-blue-50 px-2.5 py-1.5 text-[11px] font-semibold text-blue-800 hover:bg-blue-100" onClick={() => void onChangeStage(application.id, stage === "Applied" ? "Screening" : "Interview")}>
                          {stage === "Applied" ? "Start screening" : "Schedule interview"}
                        </button>
                      )}
                      {canWrite && canSchedule && (
                        <button type="button" className="rounded-md border border-blue-200 bg-blue-50 px-2.5 py-1.5 text-[11px] font-semibold text-blue-800 hover:bg-blue-100" onClick={() => void onChangeStage(application.id, "Interview")}>
                          Schedule
                        </button>
                      )}
                    </div>

                    {stage === "Applied" && (
                      <p className="mt-2 text-[10px] font-medium uppercase tracking-[0.08em] text-ink-400">Next: {nextAction(stage)}</p>
                    )}
                    {stage === "Screening" && (
                      <p className="mt-2 text-[10px] font-medium uppercase tracking-[0.08em] text-ink-400">Next: {nextAction(stage)}</p>
                    )}
                    {stage === "Interview" && (
                      <p className="mt-2 text-[10px] font-medium uppercase tracking-[0.08em] text-ink-400">Next: {nextAction(stage)}</p>
                    )}
                  </article>
                );
              })}

              {!items.length && (
                <div className="grid min-h-[150px] place-items-center rounded-lg border border-dashed border-ink-100 bg-white/60 p-4 text-center">
                  <div>
                    <p className="text-xs font-semibold text-ink-600">No candidates here</p>
                    <p className="mt-1 text-[11px] text-ink-400">{canWrite ? "Drop a candidate into this stage." : "Nothing is currently in this stage."}</p>
                  </div>
                </div>
              )}
            </div>
          </section>
        ))}
      </div>
    </section>
  );
}
