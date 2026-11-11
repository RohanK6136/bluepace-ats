import test from "node:test";
import assert from "node:assert/strict";
import { buildSourceGroundedRubric, isExtraInputValidationError } from "./rubricFallback.mjs";

test("builds source-linked must-have and preferred criteria without inventing requirements", () => {
  const jd = [
    "Frontend Engineer",
    "Responsibilities",
    "- Build web applications using React and TypeScript",
    "- Work with REST APIs and collaborate with product teams",
    "Requirements",
    "- 4 years of experience",
    "- Professional experience with JavaScript",
    "- Strong knowledge of HTML, CSS and Git",
    "Nice to have",
    "- Experience with AWS and Docker",
  ].join("\n");
  const rubric = buildSourceGroundedRubric(jd);

  assert.equal(rubric.title, "Frontend Engineer");
  assert.equal(rubric.required_years, 4);
  assert.ok(rubric.items.some((item) => item.label === "React" && item.importance === "must"));
  assert.ok(rubric.items.some((item) => item.label === "TypeScript" && item.importance === "must"));
  assert.ok(rubric.items.some((item) => item.label === "AWS" && item.importance === "nice"));
  assert.ok(rubric.items.every((item) => item.source_line && item.source_text));
  assert.ok(rubric.job_lines.length > 0);
  assert.equal(rubric.rubric_id, null);
});

test("extracts education and preserves it as a dedicated rubric criterion", () => {
  const jd = [
    "Data Analyst",
    "Requirements",
    "- 3+ years of relevant experience",
    "- Bachelor's degree in Computer Science or equivalent",
    "- Strong SQL and Python skills",
  ].join("\n");
  const rubric = buildSourceGroundedRubric(jd);

  assert.equal(rubric.required_years, 3);
  assert.equal(rubric.education.min_level, "bachelor");
  assert.ok(rubric.education.source_line);
  assert.equal(rubric.education.equivalent_experience_ok, true);
  assert.ok(rubric.items.some((item) => item.label === "SQL"));
  assert.ok(rubric.items.some((item) => item.label === "Python"));
});

test("rejects a JD with no usable job requirements instead of creating a fake rubric", () => {
  assert.throws(
    () => buildSourceGroundedRubric("Frontend Engineer\nLocation: Hyderabad\nSalary: competitive"),
    /did not contain clear job-related requirements/i,
  );
});

test("identifies only explicit Pydantic extra-input validation failures", () => {
  assert.equal(isExtraInputValidationError({
    response: { status: 422, data: { detail: [
      { type: "extra_forbidden", loc: ["body", "options", "fast"], msg: "Extra inputs are not permitted" },
    ] } },
  }), true);
  assert.equal(isExtraInputValidationError({
    response: { status: 422, data: { detail: "Extra inputs are not permitted" } },
  }), true);
  assert.equal(isExtraInputValidationError({
    response: { status: 401, data: { detail: "invalid API key" } },
  }), false);
});
