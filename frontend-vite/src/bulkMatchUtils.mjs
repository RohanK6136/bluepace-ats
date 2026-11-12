export const MAX_BULK_RESUMES = 50;
export const BULK_MATCH_CONCURRENCY = 2;
export const MAX_RESUME_BYTES = 5 * 1024 * 1024;
export const RESUME_ACCEPT = ".pdf,.docx,.txt,.md";

const SUPPORTED_RESUME_NAME = /\.(pdf|docx|txt|md)$/i;

/**
 * Classify failures that are shared across the batch rather than specific to
 * one resume. Stop claiming more files after these responses so a provider
 * outage, exhausted credit balance, or rate limit is not repeated 50 times.
 */
/**
 * The backend may deliberately return HTTP 200 with a rules-only card when
 * provider credits are exhausted. Pause on its explicit unavailable-provider
 * flag; do not infer a provider outage from every rules-only assessment.
 */
export function getBulkResultStopReason(result) {
  const flags = new Set(Array.isArray(result?.flags) ? result.flags : []);
  if (flags.has("ai_profile_unavailable")) {
    return "The selected AI provider is unavailable or out of credits. This resume has a limited rules-only result; the batch paused to avoid repeating unavailable AI calls.";
  }
  return "";
}

export function getBulkBatchStopReason(error) {
  const status = Number(error?.response?.status);
  if (status === 402) {
    return "The AI provider reports insufficient credits (HTTP 402). The batch stopped to avoid repeating the same provider failure.";
  }
  if (status === 429) {
    return "The AI service is rate-limiting requests (HTTP 429). The batch stopped; wait for the limit to reset before resuming.";
  }
  if (status === 401 || status === 403) {
    return "The AI API rejected authentication or access (HTTP " + status + "). Restore access before resuming the batch.";
  }
  if (status === 404) {
    return "The Applicant Match API route is unavailable (HTTP 404). Restore the deployed route before resuming the batch.";
  }
  if ([502, 503, 504].includes(status)) {
    return "The shared AI service is unavailable or timing out (HTTP " + status + "). The batch stopped to preserve the remaining queue.";
  }
  return "";
}

function unwrapFile(item) {
  return item?.file || item;
}

export function validateBulkResume(file, existingFiles = []) {
  if (!file || typeof file.name !== "string") {
    return { valid: false, reason: "Choose a resume file." };
  }
  if (!SUPPORTED_RESUME_NAME.test(file.name)) {
    return { valid: false, reason: "Use a PDF, DOCX, TXT or MD resume." };
  }
  if (!Number.isFinite(file.size) || file.size <= 0) {
    return { valid: false, reason: "The file is empty or its size is invalid." };
  }
  if (file.size > MAX_RESUME_BYTES) {
    return { valid: false, reason: "Each resume must be 5 MB or smaller." };
  }

  const duplicate = existingFiles.some((item) => {
    const existing = unwrapFile(item);
    return existing
      && String(existing.name || "").toLocaleLowerCase() === file.name.toLocaleLowerCase()
      && existing.size === file.size
      && existing.lastModified === file.lastModified;
  });
  if (duplicate) {
    return { valid: false, reason: "This file is already in the batch queue." };
  }
  return { valid: true, reason: "" };
}

function csvCell(value) {
  let text;
  if (value == null) text = "";
  else if (Array.isArray(value)) text = value.join("; ");
  else if (typeof value === "object") text = JSON.stringify(value);
  else text = String(value);

  // Prevent formula injection when exported data is opened in spreadsheet software.
  if (/^[\u0000-\u0020]*[=+\-@]/.test(text)) text = "'" + text;
  return '"' + text.replace(/"/g, '""') + '"';
}

export function buildBulkMatchCsv(rows) {
  const headers = [
    "Resume file",
    "Processing status",
    "Candidate reference",
    "Match score (%)",
    "Required skills (%)",
    "Experience (%)",
    "Education (%)",
    "Latest role",
    "Latest company",
    "Total experience (years)",
    "Relevant experience (years)",
    "Gaps to review",
    "Review flags",
    "Evidence summary",
    "Resume extraction (ms)",
    "Preprocessing (ms)",
    "Provider round trip (ms)",
    "Model request sum (ms)",
    "Server total (ms)",
    "Browser round trip (ms)",
    "Assessment mode",
    "Input mode",
    "Error",
  ];

  const records = (rows || []).map((row) => {
    const result = row?.result || {};
    const scores = result.scores || {};
    const profile = result.profile || {};
    const gaps = (result.gaps || []).map((gap) => {
      const context = [gap.importance, gap.status].filter(Boolean).join(", ");
      return context ? gap.label + " (" + context + ")" : gap.label;
    });
    return [
      row?.file?.name || "",
      row?.status || "",
      result.applicant_id || "",
      scores.match,
      scores.required_skills?.pct,
      scores.experience?.pct,
      scores.education?.pct,
      profile.latest_title,
      profile.latest_company,
      profile.total_years,
      profile.relevant_years,
      gaps,
      result.flags || [],
      result.summary?.value,
      result.performance?.resume_extraction_ms,
      result.performance?.preprocessing_ms,
      result.performance?.provider_round_trip_ms,
      result.performance?.model_call_time_ms,
      result.performance?.total_ms,
      result.performance?.client_round_trip_ms,
      result.performance?.assessment_mode,
      result.performance?.input_mode,
      row?.error || "",
    ];
  });

  return "\uFEFF" + [headers, ...records].map((record) => record.map(csvCell).join(",")).join("\r\n") + "\r\n";
}


/**
 * Run queued work with a fixed concurrency limit.
 * shouldStop is checked before each new item is claimed, so a systemic failure
 * can stop unstarted work while allowing already-running tasks to finish.
 */
export async function runWithConcurrency(items, concurrency, worker, shouldStop = () => false) {
  if (typeof worker !== "function") throw new TypeError("worker must be a function");
  const rows = Array.from(items || []);
  const requested = Number(concurrency);
  const limit = rows.length
    ? Math.min(rows.length, Math.max(1, Number.isInteger(requested) ? requested : 1))
    : 0;
  let nextIndex = 0;

  const runWorker = async () => {
    while (!shouldStop()) {
      const index = nextIndex;
      nextIndex += 1;
      if (index >= rows.length) return;
      await worker(rows[index], index);
    }
  };

  await Promise.all(Array.from({ length: limit }, () => runWorker()));
}



/**
 * Local Ollama is configured for one inference at a time. Sending multiple
 * full resume requests concurrently only builds a queue and increases memory
 * pressure; hosted providers retain the bounded parallel path.
 */
export function getBulkMatchConcurrency(profile, fallback = BULK_MATCH_CONCURRENCY) {
  return profile === "local-ollama" ? 1 : fallback;
}
