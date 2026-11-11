import test from "node:test";
import assert from "node:assert/strict";
import { buildMatchAssessmentInsights } from "./matchAssessmentInsights.mjs";
import { SAMPLE_JOB_DESCRIPTION, SAMPLE_MANUAL_REFERENCE, SAMPLE_RESUME_TEXT } from "./sampleApplicantMatchScenario.mjs";

test("sample scenario includes a usable backend JD and resume", () => {
  assert.match(SAMPLE_JOB_DESCRIPTION, /Python Backend Engineer/);
  assert.match(SAMPLE_JOB_DESCRIPTION, /PostgreSQL/);
  assert.match(SAMPLE_RESUME_TEXT, /FastAPI/);
  assert.match(SAMPLE_RESUME_TEXT, /pytest/);
  assert.ok(SAMPLE_RESUME_TEXT.length > 1000);
  assert.equal(SAMPLE_MANUAL_REFERENCE.score, 75);
});

test("assessment insights only label explicitly met evidence as strengths", () => {
  const result = buildMatchAssessmentInsights({
    evidence: [
      { item_id: "R01", label: "Python", status: "met", importance: "must", lines: [{ id: "L1", text: "Used Python in production." }] },
      { item_id: "R02", label: "Redis", status: "not_evidenced", importance: "nice" },
      { item_id: "R03", label: "Async", status: "partial", importance: "must" },
    ],
    scores: { match: 72, required_skills: { pct: 80 }, experience: { pct: 100 }, preferred_skills: { pct: 0 }, education: { pct: 100 }, weights_used: { required_skills: 50, experience: 25, preferred_skills: 15, education: 10 } },
  });
  assert.deepEqual(result.strengths.map((item) => item.label), ["Python"]);
  assert.equal(result.gaps.length, 2);
  assert.equal(result.breakdown.length, 4);
  assert.equal(result.match, 72);
});

test("missing result scores do not create synthetic percentages", () => {
  const result = buildMatchAssessmentInsights({ evidence: [], gaps: [] });
  assert.equal(result.match, null);
  assert.deepEqual(result.breakdown, []);
});
