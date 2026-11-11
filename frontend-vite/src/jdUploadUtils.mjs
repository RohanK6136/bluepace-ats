const STATUS_MESSAGES = {
  needs_split: "This file appears to contain more than one job description. Upload one JD at a time.",
  llm_unavailable: "The extracted text was accepted, but the selected AI model is unavailable. Check the local AI connection and retry.",
  llm_timeout: "The selected AI model timed out while generating the JD. Check the local AI service and retry.",
};

export function getJdUploadError(result) {
  if (Array.isArray(result?.sections) && result.sections.length > 0) return "";
  const status = String(result?.status || "").trim().toLowerCase();
  const detail = String(result?.message || "").trim();
  if (status === "needs_text") {
    const reason = detail || "The document contains too little selectable text.";
    return `${reason}. The PDF may be scanned or image-only. Upload a text-searchable PDF or DOCX, or paste the JD text instead.`;
  }
  if (detail) return detail;
  if (STATUS_MESSAGES[status]) return STATUS_MESSAGES[status];
  return "The upload returned no structured JD sections. Check that the file contains a complete job description with selectable text, then retry.";
}

export function extractJdTextFromResult(result) {
  const parts = [];
  const title = typeof result?.title === "string" ? result.title : result?.title?.text;
  if (title?.trim()) parts.push(title.trim());
  for (const section of Array.isArray(result?.sections) ? result.sections : []) {
    const heading = String(section?.heading || section?.title || section?.name || "").trim();
    if (heading) parts.push(heading);
    for (const item of Array.isArray(section?.items) ? section.items : []) {
      const text = typeof item === "string" ? item : item?.text;
      if (typeof text === "string" && text.trim()) parts.push(text.trim());
    }
  }
  const structured = parts.join("\n\n").trim();
  if (structured) return structured;
  return typeof result?.long_description_text === "string" ? result.long_description_text.trim() : "";
}

export function normalizeJdText(value) {
  if (typeof value === "string") return value;
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  if (Array.isArray(value)) {
    return value
      .map((item) => typeof item === "string" ? item : (typeof item?.text === "string" ? item.text : ""))
      .filter((item) => item.trim())
      .join("\n\n");
  }
  if (!value || typeof value !== "object") return "";
  const directText = [
    value.long_description_text,
    value.description,
    value.description_text,
    value.description_markdown,
    value.job_description,
    value.jobDescription,
    value.jd,
    value.text,
  ].find((item) => typeof item === "string" && item.trim());
  if (directText) return directText.trim();
  return extractJdTextFromResult(value);
}


/**
 * Compatibility guard for older local/hosted JD Standardizer instances.
 * Provider availability is a diagnostic warning, not a content publication
 * blocker. Keep every other blocker untouched and retain the warning in flags.
 */
export function normalizeJdPublicationGate(result) {
  if (!result || typeof result !== "object" || Array.isArray(result)) return result;
  const blockers = Array.isArray(result.publish_blockers) ? result.publish_blockers : null;
  if (!blockers) return result;
  const normalized = blockers.filter((item) => String(item).trim() !== "flag: llm_unavailable");
  if (normalized.length === blockers.length) return result;
  return {
    ...result,
    publish_blockers: normalized,
    publishable: normalized.length === 0,
  };
}


/**
 * Identify only optional JD request options rejected by older FastAPI/Pydantic
 * companions. Do not retry unrelated validation errors or remove recruiter data.
 */
export function getUnsupportedJdOptionFields(error) {
  const detail = error?.response?.data?.detail;
  // These are optional controls with backend defaults. If an older companion
  // rejects one as an extra field, retry without it; never strip JD content.
  const allowed = new Set(["profile", "detail", "mode", "fast", "use_cache", "draft_gaps", "debug"]);
  if (!Array.isArray(detail)) {
    const message = String(detail || "");
    return [...allowed].filter((field) => new RegExp(
      `(?:^|\\n)\\s*${field}\\s*\\n[\\s\\S]{0,180}?Extra inputs are not permitted`,
      "i",
    ).test(message));
  }
  return [...new Set(detail.flatMap((item) => {
    const location = Array.isArray(item?.loc) ? item.loc : [];
    const field = location[0] === "body" && location[1] === "options" ? location[2] : null;
    const isExtra = item?.type === "extra_forbidden"
      || /extra inputs are not permitted/i.test(String(item?.msg || ""));
    return isExtra && allowed.has(field) ? [field] : [];
  }))];
}

export function formatJdValidationErrors(error) {
  const detail = error?.response?.data?.detail;
  if (!Array.isArray(detail)) return "";
  return detail.map((item) => {
    const location = Array.isArray(item?.loc) ? item.loc.filter((part) => part !== "body") : [];
    const path = location.join(".");
    const message = String(item?.msg || item || "Invalid request");
    return path ? `${path}: ${message}` : message;
  }).join("; ");
}
