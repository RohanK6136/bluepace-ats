export const PIPELINE_STAGES = ["Applied", "Screening", "Interview", "Offer", "Hired", "Rejected"];
export const BOARD_STAGES = [...PIPELINE_STAGES, "Withdrawn"];
export const PROGRESSION_STAGES = ["Applied", "Screening", "Interview", "Offer", "Hired"];
export const TERMINAL_STATUSES = new Set(["hired", "rejected", "withdrawn"]);

export function getWorkflowStage(application) {
  const status = String(application?.status || "").toLowerCase();
  if (status === "withdrawn") return "Withdrawn";
  if (status === "hired") return "Hired";
  if (status === "rejected") return "Rejected";
  const stage = String(application?.stage_name || "");
  return BOARD_STAGES.includes(stage) ? stage : "Applied";
}

export function isTerminalApplication(application) {
  return TERMINAL_STATUSES.has(String(application?.status || "").toLowerCase())
    || ["Hired", "Rejected", "Withdrawn"].includes(getWorkflowStage(application));
}

export function getNextWorkflowStage(stage) {
  const index = PROGRESSION_STAGES.indexOf(stage);
  if (index < 0 || index >= PROGRESSION_STAGES.length - 1) return null;
  return PROGRESSION_STAGES[index + 1];
}

export function filterWorkflowApplications(applications, filters = {}) {
  const query = String(filters.search || "").trim().toLowerCase();
  const jobId = String(filters.jobId || "all");
  const stageFilter = String(filters.stage || "all");
  const statusFilter = String(filters.status || "active");

  return (Array.isArray(applications) ? applications : []).filter((application) => {
    const stage = getWorkflowStage(application);
    const terminal = isTerminalApplication(application);
    if (jobId !== "all" && String(application.job_id) !== jobId) return false;
    if (stageFilter !== "all" && stage !== stageFilter) return false;
    if (statusFilter === "active" && terminal) return false;
    if (statusFilter === "closed" && !terminal) return false;

    if (query) {
      const candidate = application.candidate || {};
      const name = [candidate.first_name, candidate.last_name].filter(Boolean).join(" ");
      const haystack = [
        name,
        candidate.email,
        application.job_title,
        application.id,
        candidate.source,
      ].filter(Boolean).join(" ").toLowerCase();
      if (!haystack.includes(query)) return false;
    }
    return true;
  });
}

export function summarizeWorkflow(applications) {
  const rows = Array.isArray(applications) ? applications : [];
  const summary = {
    total: rows.length,
    active: 0,
    interviews: 0,
    offers: 0,
    hired: 0,
    rejected: 0,
    withdrawn: 0,
  };
  for (const application of rows) {
    const stage = getWorkflowStage(application);
    if (stage === "Withdrawn") summary.withdrawn += 1;
    else if (stage === "Hired") summary.hired += 1;
    else if (stage === "Rejected") summary.rejected += 1;
    else {
      summary.active += 1;
      if (stage === "Interview") summary.interviews += 1;
      if (stage === "Offer") summary.offers += 1;
    }
  }
  return summary;
}

export function validateInterviewDetails(form = {}) {
  if (!String(form.starts_at || "").trim()) return "Choose an interview date and time.";
  const start = new Date(form.starts_at);
  if (Number.isNaN(start.getTime())) return "Enter a valid interview date and time.";
  if (start.getTime() <= Date.now()) return "The interview must be scheduled in the future.";
  const duration = Number(form.duration_minutes);
  if (!Number.isInteger(duration) || duration < 15 || duration > 480) {
    return "Interview duration must be between 15 and 480 minutes.";
  }
  if (form.mode === "online" && !String(form.meeting_url || "").trim()) {
    return "Add a meeting link for an online interview.";
  }
  if (form.mode === "offline" && !String(form.location || "").trim()) {
    return "Add a location for an in-person interview.";
  }
  return "";
}

export function buildWorkflowStagePayload(stageName, interviewForm = {}) {
  if (!PIPELINE_STAGES.includes(stageName)) throw new Error("Choose a valid workflow stage.");
  const payload = { stage_name: stageName };
  if (stageName !== "Interview") return payload;
  const validationError = validateInterviewDetails(interviewForm);
  if (validationError) throw new Error(validationError);
  payload.interview_starts_at = new Date(interviewForm.starts_at).toISOString();
  payload.interview_duration_minutes = Number(interviewForm.duration_minutes);
  payload.interview_mode = interviewForm.mode;
  payload.interview_meeting_url = interviewForm.mode === "online" ? String(interviewForm.meeting_url).trim() : null;
  payload.interview_location = interviewForm.mode === "offline" ? String(interviewForm.location).trim() : null;
  return payload;
}
