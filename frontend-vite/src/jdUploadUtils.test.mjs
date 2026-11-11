import assert from "node:assert/strict";
import test from "node:test";
import { extractJdTextFromResult, getJdUploadError, normalizeJdText, normalizeJdPublicationGate, getUnsupportedJdOptionFields, formatJdValidationErrors } from "./jdUploadUtils.mjs";

test("surfaces the backend extraction reason for image-only or empty-text uploads", () => {
  const message = getJdUploadError({
    status: "needs_text",
    message: "only 14 characters of text found",
    sections: [],
  });
  assert.match(message, /only 14 characters of text found/i);
  assert.match(message, /scanned or image-only/i);
  assert.match(message, /text-searchable PDF or DOCX/i);
});

test("uses backend diagnostics for multiple-JD responses", () => {
  assert.equal(
    getJdUploadError({ status: "needs_split", message: "more than one job description detected", sections: [] }),
    "more than one job description detected",
  );
});

test("provides a safe fallback when the backend returns no sections or reason", () => {
  assert.match(getJdUploadError({ sections: [] }), /complete job description with selectable text/i);
});

test("does not report an error when the backend returns structured sections", () => {
  assert.equal(getJdUploadError({ sections: [{ heading: "Responsibilities", items: [{ text: "Build APIs" }] }] }), "");
});

test("rebuilds JD text using the actual API response schema", () => {
  const text = extractJdTextFromResult({
    title: { text: "Python Developer", origin: "source" },
    sections: [
      { id: "responsibilities", heading: "Key Responsibilities", items: [{ text: "Build APIs", origin: "source" }, { text: "Write tests", origin: "source" }] },
      { id: "requirements", heading: "Qualifications", items: [{ text: "3 years of Python", origin: "source" }] },
    ],
  });
  assert.equal(text, "Python Developer\n\nKey Responsibilities\n\nBuild APIs\n\nWrite tests\n\nQualifications\n\n3 years of Python");
  assert.equal(text.includes("[object Object]"), false);
});

test("falls back to the plain-text rendered output when structured fields are absent", () => {
  assert.equal(extractJdTextFromResult({ long_description_text: "Python Developer\nResponsibilities" }), "Python Developer\nResponsibilities");
});

test("normalizes a legacy workspace JD object before textarea or assistant use", () => {
  assert.equal(normalizeJdText({ text: "Python Developer\nRequired Qualifications" }), "Python Developer\nRequired Qualifications");
});

test("normalizes a structured JD result into plain text", () => {
  assert.equal(normalizeJdText({
    title: { text: "Python Developer" },
    sections: [{ heading: "Required Qualifications", items: [{ text: "Python and SQL" }] }],
  }), "Python Developer\n\nRequired Qualifications\n\nPython and SQL");
});

test("normalizes arrays without leaking object string representations", () => {
  assert.equal(normalizeJdText(["Python", { text: "Build APIs" }, {}]), "Python\n\nBuild APIs");
  assert.equal(normalizeJdText({ unrelated: true }).includes("[object Object]"), false);
});


test("treats a legacy LLM-unavailable diagnostic as a warning, not a publication blocker", () => {
  const result = normalizeJdPublicationGate({
    publishable: false,
    publish_blockers: ["flag: llm_unavailable"],
    flags: [{ code: "llm_unavailable", severity: "warn", message: "Rules-based extraction was used." }],
  });
  assert.equal(result.publishable, true);
  assert.deepEqual(result.publish_blockers, []);
  assert.equal(result.flags[0].code, "llm_unavailable");
});

test("keeps genuine publication blockers when LLM is unavailable", () => {
  const result = normalizeJdPublicationGate({
    publishable: false,
    publish_blockers: ["title: missing", "flag: llm_unavailable", "requirements: empty"],
  });
  assert.equal(result.publishable, false);
  assert.deepEqual(result.publish_blockers, ["title: missing", "requirements: empty"]);
});

test("leaves modern publication responses and invalid values unchanged", () => {
  const modern = { publishable: false, publish_blockers: ["requirements: empty"] };
  assert.equal(normalizeJdPublicationGate(modern), modern);
  assert.equal(normalizeJdPublicationGate(null), null);
});


test("identifies only unsupported optional JD options in Pydantic extra-field errors", () => {
  const error = { response: { data: { detail: [
    { type: "extra_forbidden", loc: ["body", "options", "detail"], msg: "Extra inputs are not permitted" },
    { type: "extra_forbidden", loc: ["body", "options", "profile"], msg: "Extra inputs are not permitted" },
    { type: "extra_forbidden", loc: ["body", "text"], msg: "Extra inputs are not permitted" },
    { type: "value_error", loc: ["body", "options", "mode"], msg: "Invalid mode" },
  ] } } };
  assert.deepEqual(getUnsupportedJdOptionFields(error), ["detail", "profile"]);
  assert.equal(
    formatJdValidationErrors(error),
    "options.detail: Extra inputs are not permitted; options.profile: Extra inputs are not permitted; text: Extra inputs are not permitted; options.mode: Invalid mode",
  );
});

test("does not retry or hide unrelated JD request validation errors", () => {
  const error = { response: { data: { detail: [
    { type: "extra_forbidden", loc: ["body", "text"], msg: "Extra inputs are not permitted" },
    { type: "value_error", loc: ["body", "options", "mode"], msg: "Invalid mode" },
  ] } } };
  assert.deepEqual(getUnsupportedJdOptionFields(error), []);
});


test("recognizes legacy multipart option-validation text", () => {
  const error = {
    response: {
      data: {
        detail: "invalid options: 1 validation error for Options\\ndetail\\n  Extra inputs are not permitted [type=extra_forbidden]",
      },
    },
  };
  assert.deepEqual(getUnsupportedJdOptionFields(error), ["detail"]);
});
