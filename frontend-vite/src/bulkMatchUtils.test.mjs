import test from "node:test";
import assert from "node:assert/strict";
import {
  buildBulkMatchCsv,
  BULK_MATCH_CONCURRENCY,
  getBulkMatchConcurrency,
  runWithConcurrency,
  MAX_BULK_RESUMES,
  MAX_RESUME_BYTES,
  validateBulkResume,
} from "./bulkMatchUtils.mjs";
import { unwrapRubricDraft } from "./matchRubricUtils.mjs";

function file(name, size = 120, lastModified = 10) {
  return { name, size, lastModified };
}

test("accepts supported resume extensions case-insensitively", () => {
  for (const name of ["candidate.PDF", "candidate.docx", "candidate.txt", "candidate.md"]) {
    assert.equal(validateBulkResume(file(name)).valid, true, name);
  }
});

test("rejects unsupported, empty and oversized resumes", () => {
  assert.match(validateBulkResume(file("candidate.exe")).reason, /PDF, DOCX, TXT or MD/);
  assert.match(validateBulkResume(file("empty.pdf", 0)).reason, /empty/);
  assert.match(validateBulkResume(file("large.pdf", MAX_RESUME_BYTES + 1)).reason, /5 MB or smaller/);
});

test("rejects the same file being queued twice", () => {
  const original = file("candidate.pdf", 1024, 1234);
  assert.equal(validateBulkResume(original, [original]).reason, "This file is already in the batch queue.");
  assert.equal(validateBulkResume(file("different.pdf", 1024, 1234), [original]).valid, true);
});

test("documents the bounded batch size", () => {
  assert.equal(MAX_BULK_RESUMES, 50);
});

test("exports comparison fields with quoted CSV cells and escaped quotes", () => {
  const csv = buildBulkMatchCsv([{
    file: { name: 'candidate,"one".pdf' },
    status: "complete",
    result: {
      applicant_id: "A-123",
      scores: {
        match: 88,
        required_skills: { pct: 90 },
        experience: { pct: 75 },
        education: { pct: 100 },
      },
      profile: { latest_title: "Data Engineer", total_years: 4.5, relevant_years: 3 },
      gaps: [{ label: "Airflow", importance: "must", status: "not_evidenced" }],
      flags: ["experience_undated"],
      summary: { value: "Strong SQL evidence" },
    },
    error: "",
  }]);
  assert.match(csv, /"candidate,""one""\.pdf"/);
  assert.match(csv, /"88"/);
  assert.match(csv, /"Airflow \(must, not_evidenced\)"/);
  assert.match(csv, /"Strong SQL evidence"/);
});

test("escapes formula-like values before spreadsheet export", () => {
  const csv = buildBulkMatchCsv([{
    file: { name: '=HYPERLINK("https://example.test")' },
    status: "failed",
    result: null,
    error: "+2+2",
  }]);
  assert.match(csv, /"'=HYPERLINK\(""https:\/\/example\.test""\)"/);
  assert.match(csv, /"'\+2\+2"/);
});


test("limits concurrent bulk work to the configured low parallelism", async () => {
  assert.equal(BULK_MATCH_CONCURRENCY, 2);
  let active = 0;
  let peak = 0;
  const completed = [];

  await runWithConcurrency([0, 1, 2, 3, 4, 5], BULK_MATCH_CONCURRENCY, async (item) => {
    active += 1;
    peak = Math.max(peak, active);
    await new Promise((resolve) => setTimeout(resolve, 5));
    completed.push(item);
    active -= 1;
  });

  assert.equal(peak, 2);
  assert.deepEqual(completed.sort((a, b) => a - b), [0, 1, 2, 3, 4, 5]);
});

test("stops claiming queued work after a systemic batch failure", async () => {
  const completed = [];
  let stop = false;

  await runWithConcurrency([1, 2, 3, 4], 2, async (item) => {
    completed.push(item);
    if (item === 1) stop = true;
  }, () => stop);

  assert.deepEqual(completed, [1]);
});


test("exports Applicant Match timing breakdown for batch comparison", () => {
  const csv = buildBulkMatchCsv([{
    file: { name: "candidate.pdf" },
    status: "complete",
    result: {
      performance: {
        resume_extraction_ms: 12,
        preprocessing_ms: 3,
        provider_round_trip_ms: 840,
        model_inference_ms: 838,
        total_ms: 860,
        client_round_trip_ms: 1120,
        assessment_mode: "model",
        input_mode: "uploaded_file",
      },
    },
  }]);
  assert.match(csv, /"Resume extraction \(ms\)"/);
  assert.match(csv, /"12","3","840","838","860","1120","model","uploaded_file"/);
});


test("uses one bulk worker for local Ollama and bounded parallelism for hosted models", () => {
  assert.equal(getBulkMatchConcurrency("local-ollama"), 1);
  assert.equal(getBulkMatchConcurrency("openrouter"), BULK_MATCH_CONCURRENCY);
  assert.equal(getBulkMatchConcurrency(""), BULK_MATCH_CONCURRENCY);
});


test("unwraps the local Python API rubric draft before saving", () => {
  const draft = { rubric_id: null, items: [{ id: "R01", label: "Python" }] };
  assert.equal(unwrapRubricDraft({ run_id: "run-1", rubric: draft, notes: [] }), draft);
});

test("accepts a frozen rubric returned directly by the hosted API", () => {
  const saved = { rubric_id: "rb_123", items: [{ id: "R01", label: "Python" }] };
  assert.equal(unwrapRubricDraft(saved), saved);
});

test("rejects an empty rubric response with an actionable error", () => {
  assert.throws(() => unwrapRubricDraft({ rubric: { items: [] } }), /clear requirements/);
});


test("accepts a valid rubric with an experience requirement and no skill items", () => {
  const experienceOnly = { rubric_id: null, required_years: 5, items: [] };
  assert.equal(unwrapRubricDraft({ rubric: experienceOnly }).required_years, 5);
});

test("accepts a valid rubric with an education requirement and no skill items", () => {
  const educationOnly = { rubric_id: null, education: { min_level: "bachelor" }, items: [] };
  assert.equal(unwrapRubricDraft({ rubric: educationOnly }).education.min_level, "bachelor");
});
