import assert from "node:assert/strict";
import test from "node:test";

import { standardizeJD } from "../api/jd-standardizer.mjs";

const completeJD = [
  "Senior Software Engineer",
  "Employment Type: Full-Time",
  "Location: Hyderabad, Telangana, India / Hybrid",
  "Experience: 5+ years",
  "About the Role",
  "Join the engineering team to build reliable products for enterprise customers.",
  "Responsibilities",
  "- Build and maintain REST APIs using Python and FastAPI.",
  "- Deploy services on AWS and support production operations.",
  "Requirements",
  "- 5+ years of software engineering experience.",
  "- Strong Python, SQL and PostgreSQL skills.",
  "Preferred Skills",
  "- Kubernetes and Docker experience.",
  "Benefits",
  "- Health insurance and paid leave.",
].join("\n");

test("extracts job facts, sections and skill taxonomy with source references", () => {
  const result = standardizeJD(completeJD);

  assert.equal(result.title, "Senior Software Engineer");
  assert.equal(result.category_hint, "software_engineering");
  assert.equal(result.role_type, "Full-Time");
  assert.deepEqual(result.country, { iso2: "IN", name: "India" });
  assert.equal(result.city, "Hyderabad");
  assert.equal(result.state, "Telangana");
  assert.deepEqual(result.work_mode, ["hybrid"]);
  assert.equal(result.experience.min_years, 5);
  assert.equal(result.experience.max_years, null);
  assert.ok(result.responsibilities.some((line) => /REST APIs/i.test(line)));
  assert.ok(result.requirements.some((line) => /PostgreSQL/i.test(line)));
  assert.ok(result.nice_to_have.some((line) => /Kubernetes/i.test(line)));
  assert.ok(result.offer.some((line) => /Health insurance/i.test(line)));
  assert.ok(result.required_skills.includes("Python"));
  assert.ok(result.required_skills.includes("PostgreSQL"));
  assert.ok(result.preferred_skills.includes("Kubernetes"));
  assert.equal(result.source_mode, "deterministic");
  assert.ok(result.source_lines.some((line) => line.id === "J01" && line.text === "Senior Software Engineer"));
  assert.ok(result.source_line_refs.responsibilities.length >= 2);
  assert.equal(result.quality.score, 100);
  assert.equal(result.field_evidence.title.status, "verified");
  assert.ok(result.review_flags.some((flag) => /No generative model was called/i.test(flag)));
});

test("normalizes markdown and inline section headings", () => {
  const result = standardizeJD([
    "# Backend Engineer",
    "## Responsibilities: Build API services with FastAPI.",
    "## Requirements: 4+ years of Python experience.",
    "## Preferred Skills: Kubernetes.",
  ].join("\n"));

  assert.equal(result.title, "Backend Engineer");
  assert.ok(result.responsibilities.some((line) => /Build API services/i.test(line)));
  assert.ok(result.requirements.some((line) => /Python experience/i.test(line)));
  assert.ok(result.nice_to_have.some((line) => /Kubernetes/i.test(line)));
  assert.ok(result.required_skills.includes("Python"));
  assert.ok(result.preferred_skills.includes("Kubernetes"));
});

test("reports conflicting source facts instead of choosing one silently", () => {
  const result = standardizeJD([
    "Job Title: Senior Software Engineer",
    "Position Title: Backend Engineer",
    "Employment Type: Full-Time",
    "Responsibilities",
    "- Build APIs.",
    "Requirements",
    "- Python and SQL experience.",
  ].join("\n"));

  assert.equal(result.title, null);
  assert.equal(result.field_evidence.title.status, "conflict");
  assert.equal(result.conflicts[0].field, "title");
  assert.ok(result.conflicts[0].candidates.length >= 2);
  assert.ok(result.review_flags.some((flag) => /conflict/i.test(flag)));
  assert.ok(result.missing_information.some((item) => /title: conflicting source values/i.test(item)));
});

test("deduplicates repeated requirements while retaining the duplicate source line", () => {
  const result = standardizeJD([
    "QA Automation Engineer",
    "Responsibilities",
    "- Build automated tests.",
    "Requirements",
    "- Experience with Playwright and JavaScript.",
    "- Experience with Playwright and JavaScript.",
  ].join("\n"));

  assert.equal(result.requirements.length, 1);
  assert.equal(result.quality.duplicate_items, 1);
  assert.ok(result.review_flags.some((flag) => /duplicate/i.test(flag)));
});

test("does not invent role facts for a company profile without a job description", () => {
  const result = standardizeJD([
    "About Blupace Tech",
    "Blupace Tech works with global enterprise customers.",
    "Our teams deliver technology services across multiple industries.",
  ].join("\n"));

  assert.equal(result.title, null);
  assert.equal(result.role_type, null);
  assert.equal(result.country, null);
  assert.equal(result.experience.min_years, null);
  assert.equal(result.experience.max_years, null);
  assert.deepEqual(result.about_role, []);
  assert.ok(result.missing_information.some((item) => /job title/i.test(item)));
  assert.ok(result.review_flags.some((flag) => /company profile rather than a role-specific/i.test(flag)));
});

test("preserves labelled salary and education details in recruiter-facing sections", () => {
  const result = standardizeJD([
    "Data Analyst",
    "Salary: INR 12–16 LPA",
    "Education: Bachelor's degree in Statistics or a related field",
    "Responsibilities",
    "- Prepare data reports.",
    "Requirements",
    "- Strong SQL and Excel skills.",
  ].join("\n"));

  assert.ok(result.offer.some((line) => /INR 12–16 LPA/i.test(line)));
  assert.ok(result.requirements.some((line) => /Bachelor's degree/i.test(line)));
  assert.ok(result.required_skills.includes("SQL"));
  assert.ok(result.required_skills.includes("Microsoft Excel"));
});

test("rejects empty and over-limit source text", () => {
  assert.throws(() => standardizeJD("Too short"), /at least 15 characters/i);
  assert.throws(() => standardizeJD("x".repeat(60001)), /60,000 character limit/i);
});

test("does not create skills from partial token matches", () => {
  const result = standardizeJD([
    "Operations Coordinator",
    "Responsibilities",
    "- Coordinate internal processes.",
    "Requirements",
    "- Must be proactive and reliable.",
  ].join("\n"));

  assert.equal(result.extracted_skills.includes("Go"), false);
  assert.equal(result.extracted_skills.includes("Java"), false);
});
