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
