import assert from "node:assert/strict";
import { test } from "node:test";
import { buildRoleEvidenceMap } from "./roleEvidenceMap.mjs";

test("maps explicit required-skill evidence to source lines and project references", () => {
  const result = buildRoleEvidenceMap({
    required_skills_met: ["Python"],
    mandatory_skills_missed: ["Kubernetes"],
    match_evidence: {
      required_skills: [{ skill: "Python", evidenced: true, sources: [{ source_lines: [4, 8] }] }],
      projects: [{ project: "Payments API", matched_required_skills: ["Python"], excerpt: "Built a Python service." }],
    },
  });

  assert.deepEqual(result.coverage, { supported: 1, total: 2, percent: 50 });
  assert.equal(result.requirements[0].status, "located");
  assert.deepEqual(result.requirements[0].sourceLines, ["4", "8"]);
  assert.equal(result.requirements[0].projectReferences[0].title, "Payments API");
  assert.equal(result.requirements[1].status, "verify");
  assert.match(result.requirements[1].explanation, /not proof/i);
  assert.match(result.followUpQuestions[0], /Kubernetes/);
});

test("treats parsed experience below the stated minimum as a verification point, not a rejection", () => {
  const result = buildRoleEvidenceMap({
    experience_years: 3,
    required_experience_years: 5,
    match_evidence: { experience: { parsed_years: 3, required_years: 5 } },
  });

  assert.equal(result.experience.status, "verify");
  assert.match(result.experience.explanation, /Check overlapping dates/i);
  assert.match(result.followUpQuestions[0], /work-history dates/i);
});

test("returns an empty, safe model when no assessment is loaded", () => {
  const result = buildRoleEvidenceMap(null);
  assert.deepEqual(result.coverage, { supported: 0, total: 0, percent: 0 });
  assert.deepEqual(result.requirements, []);
  assert.deepEqual(result.followUpQuestions, []);
});

test("does not invent an education criterion when the job has none", () => {
  const result = buildRoleEvidenceMap({
    match_evidence: { education: { required: null, resume_fields: [] } },
  });
  assert.equal(result.education, null);
});

test("does not interpret an empty work-history section as zero years of experience", () => {
  const result = buildRoleEvidenceMap({
    experience_years: 0,
    required_experience_years: 4,
    match_evidence: { experience: { parsed_years: 0, required_years: 4, resume_fields: [] } },
  });
  assert.equal(result.experience.parsedYears, null);
  assert.equal(result.experience.status, "verify");
  assert.match(result.experience.explanation, /could not be reliably summarised/i);
});
