export const MAX_BULK_RESUMES = 50;
export const BULK_MATCH_CONCURRENCY = 2;
export const MAX_RESUME_BYTES = 5 * 1024 * 1024;
export const RESUME_ACCEPT = ".pdf,.docx,.txt,.md";

const SUPPORTED_RESUME_NAME = /\.(pdf|docx|txt|md)$/i;

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
    "Model inference (ms)",
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
      result.performance?.model_inference_ms,
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
