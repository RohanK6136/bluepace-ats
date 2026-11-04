import assert from "node:assert/strict";
import test from "node:test";
import { extractJdTextFromResult, getJdUploadError } from "./jdUploadUtils.mjs";

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
