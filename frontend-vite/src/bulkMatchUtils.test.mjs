import test from "node:test";
import assert from "node:assert/strict";
import {
  buildBulkMatchCsv,
  BULK_MATCH_CONCURRENCY,
  getBulkMatchConcurrency,
  getBulkBatchStopReason,
  getBulkResultStopReason,
  runWithConcurrency,
  MAX_BULK_RESUMES,
  MAX_RESUME_BYTES,
  validateBulkResume,
} from "./bulkMatchUtils.mjs";
import { unwrapRubricDraft } from "./matchRubricUtils.mjs";
import { deleteBulkQueue, loadBulkQueue, moveBulkQueue, restoreBulkQueueRows, saveBulkQueue } from "./bulkQueueStorage.mjs";

function file(name, size = 120, lastModified = 10) {
  return { name, size, lastModified };
}

function fakeIndexedDB() {
  const records = new Map();
  let hasStore = false;
  return {
    open() {
      const request = {};
      queueMicrotask(() => {
        const database = {
          objectStoreNames: { contains: () => hasStore },
          createObjectStore() { hasStore = true; },
          close() {},
          transaction() {
            const transaction = {
              objectStore: () => ({
                get(key) {
                  const result = {};
                  queueMicrotask(() => {
                    result.result = records.get(key);
                    result.onsuccess?.();
                  });
                  return result;
                },
                put(value) {
                  records.set(value.workspaceId, value);
                  queueMicrotask(() => transaction.oncomplete?.());
                },
                delete(key) {
                  records.delete(key);
                  queueMicrotask(() => transaction.oncomplete?.());
                },
              }),
            };
            return transaction;
          },
        };
        request.result = database;
        request.onupgradeneeded?.();
        request.onsuccess?.();
      });
      return request;
    },
  };
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
        model_call_time_ms: 838,
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

test("stops remaining bulk work when the backend returns a rules-only AI-unavailable fallback", () => {
  const reason = getBulkResultStopReason({
    flags: ["rules_only_assessment", "ai_profile_unavailable", "experience_not_assessed"],
    versions: { assessment_mode: "rules_only" },
  });
  assert.match(reason, /provider is unavailable/i);
  assert.match(reason, /avoid repeating unavailable AI calls/i);
});

test("does not stop bulk work for an intentional rules-only assessment", () => {
  assert.equal(getBulkResultStopReason({
    flags: ["rules_only_assessment"],
    versions: { profile: "rules" },
  }), "");
});

test("stops remaining bulk work when the provider has no credits", () => {
  const reason = getBulkBatchStopReason({ response: { status: 402 } });
  assert.match(reason, /insufficient credits/i);
  assert.match(reason, /avoid repeating/i);
});

test("stops remaining bulk work when the provider rate-limits requests", () => {
  const reason = getBulkBatchStopReason({ response: { status: 429 } });
  assert.match(reason, /rate-limiting/i);
  assert.match(reason, /before resuming/i);
});

test("stops remaining bulk work on shared authentication, route and service failures", () => {
  for (const status of [401, 403, 404, 502, 503, 504]) {
    assert.notEqual(getBulkBatchStopReason({ response: { status } }), "", String(status));
  }
});

test("does not stop a batch for a resume-specific validation failure", () => {
  for (const status of [400, 413, 422]) {
    assert.equal(getBulkBatchStopReason({ response: { status } }), "", String(status));
  }
});

test("stops claiming new resumes after a shared provider block while active workers finish", async () => {
  const started = [];
  let stop = false;

  await runWithConcurrency([1, 2, 3, 4], 2, async (item) => {
    started.push(item);
    if (item === 1) {
      await Promise.resolve();
      stop = Boolean(getBulkBatchStopReason({ response: { status: 402 } }));
    }
    await Promise.resolve();
  }, () => stop);

  // The second worker was already in flight and can finish; queued work is not claimed.
  assert.deepEqual(started, [1, 2]);
});


test("persists and restores bulk queue rows per workspace", async () => {
  const indexedDB = fakeIndexedDB();
  const rows = [
    { id: "row-1", file: file("candidate.pdf", 2048, 77), status: "queued", result: null, error: "" },
    { id: "row-2", file: file("other.txt", 512, 88), status: "complete", result: { applicant_id: "A-2" }, error: "" },
  ];

  await saveBulkQueue("workspace-a", rows, indexedDB);
  const loaded = await loadBulkQueue("workspace-a", indexedDB);

  assert.equal(loaded.rows.length, 2);
  assert.equal(loaded.rows[0].file.name, "candidate.pdf");
  assert.equal(loaded.rows[0].file.size, 2048);
  assert.equal(loaded.rows[1].status, "complete");
  assert.equal(loaded.rows[1].file, null, "completed rows should not retain their original resume binary");
  assert.equal(loaded.rows[1].fileName, "other.txt");
  assert.equal(loaded.rows[1].fileSize, 512);
  assert.deepEqual(loaded.rows[1].result, { applicant_id: "A-2" });
  assert.equal((await loadBulkQueue("workspace-b", indexedDB)).rows.length, 0);
});

test("rehydrates a stored Blob with its original resume filename", () => {
  const blob = new Blob(["resume contents"], { type: "text/plain" });
  const restored = restoreBulkQueueRows([{
    id: "blob-row",
    file: blob,
    fileMeta: { name: "candidate.txt", size: blob.size, type: "text/plain", lastModified: 123 },
    status: "queued",
  }]);
  assert.equal(restored.rows[0].file.name, "candidate.txt");
  assert.equal(restored.rows[0].file.size, blob.size);
  assert.equal(restored.rows[0].file.type, "text/plain");
});

test("returns interrupted processing rows to queued with an explicit warning", async () => {
  const indexedDB = fakeIndexedDB();
  await saveBulkQueue("workspace-a", [{
    id: "row-1",
    file: file("candidate.pdf"),
    status: "processing",
    result: null,
  }], indexedDB);

  const loaded = await loadBulkQueue("workspace-a", indexedDB);
  assert.equal(loaded.interrupted, 1);
  assert.equal(loaded.rows[0].status, "queued");
  assert.match(loaded.rows[0].error, /previous browser session ended/i);
});

test("marks queue rows when the browser no longer has their binary file", async () => {
  const indexedDB = fakeIndexedDB();
  await saveBulkQueue("workspace-a", [{
    id: "row-1",
    file: null,
    fileMeta: { name: "candidate.pdf", size: 2048, lastModified: 77 },
    status: "queued",
  }], indexedDB);

  const loaded = await loadBulkQueue("workspace-a", indexedDB);
  assert.equal(loaded.rows[0].status, "file_missing");
  assert.equal(loaded.rows[0].fileName, "candidate.pdf");
  assert.match(loaded.rows[0].error, /select the file again/i);
});

test("moves an unsaved queue when the recruiter saves a workspace", async () => {
  const indexedDB = fakeIndexedDB();
  await saveBulkQueue("__unsaved_workspace__", [{
    id: "row-1",
    file: file("candidate.pdf"),
    status: "queued",
  }], indexedDB);

  await moveBulkQueue("__unsaved_workspace__", "workspace-a", indexedDB);

  assert.equal((await loadBulkQueue("__unsaved_workspace__", indexedDB)).rows.length, 0);
  assert.equal((await loadBulkQueue("workspace-a", indexedDB)).rows[0].file.name, "candidate.pdf");
});

test("deleting a workspace queue removes its saved files and progress", async () => {
  const indexedDB = fakeIndexedDB();
  await saveBulkQueue("workspace-a", [{ id: "row-1", file: file("candidate.pdf"), status: "queued" }], indexedDB);
  await deleteBulkQueue("workspace-a", indexedDB);
  assert.equal((await loadBulkQueue("workspace-a", indexedDB)).rows.length, 0);
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
