import assert from "node:assert/strict";
import { test } from "node:test";
import {
  BOARD_STAGES,
  buildWorkflowStagePayload,
  filterWorkflowApplications,
  getNextWorkflowStage,
  getWorkflowStage,
  isTerminalApplication,
  summarizeWorkflow,
  validateInterviewDetails,
} from "./hiringWorkflowUtils.mjs";

const applications = [
  { id: 1, job_id: 10, job_title: "Backend Engineer", stage_name: "Applied", status: "active", candidate: { first_name: "Asha", last_name: "Rao", email: "asha@example.test", source: "Direct" } },
  { id: 2, job_id: 10, job_title: "Backend Engineer", stage_name: "Interview", status: "active", candidate: { first_name: "Imran", last_name: "Khan", email: "imran@example.test", source: "Referral" } },
  { id: 3, job_id: 11, job_title: "Product Manager", stage_name: "Offer", status: "active", candidate: { first_name: "Mira", last_name: "Das", email: "mira@example.test", source: "Agency" } },
  { id: 4, job_id: 11, job_title: "Product Manager", stage_name: "Hired", status: "hired", candidate: { first_name: "Dev", last_name: "Patel", email: "dev@example.test" } },
  { id: 5, job_id: 12, job_title: "Designer", stage_name: "Rejected", status: "rejected", candidate: { first_name: "Noor", last_name: "Ali", email: "noor@example.test" } },
  { id: 6, job_id: 12, job_title: "Designer", stage_name: "Interview", status: "withdrawn", candidate: { first_name: "Kiran", last_name: "Sen", email: "kiran@example.test" } },
];

test("workflow stage mapping preserves terminal and withdrawn states", () => {
  assert.equal(getWorkflowStage(applications[3]), "Hired");
  assert.equal(getWorkflowStage(applications[4]), "Rejected");
  assert.equal(getWorkflowStage(applications[5]), "Withdrawn");
  assert.equal(getWorkflowStage({}), "Applied");
  assert.deepEqual(BOARD_STAGES, ["Applied", "Screening", "Interview", "Offer", "Hired", "Rejected", "Withdrawn"]);
  assert.equal(isTerminalApplication(applications[0]), false);
  assert.equal(isTerminalApplication(applications[5]), true);
});

test("workflow advances through the intended stages and stops at terminal states", () => {
  assert.equal(getNextWorkflowStage("Applied"), "Screening");
  assert.equal(getNextWorkflowStage("Screening"), "Interview");
  assert.equal(getNextWorkflowStage("Interview"), "Offer");
  assert.equal(getNextWorkflowStage("Offer"), "Hired");
  assert.equal(getNextWorkflowStage("Hired"), null);
  assert.equal(getNextWorkflowStage("Rejected"), null);
});

test("workflow filtering supports job, stage, search, and active/closed status", () => {
  assert.deepEqual(filterWorkflowApplications(applications, { jobId: "10" }).map((row) => row.id), [1, 2]);
  assert.deepEqual(filterWorkflowApplications(applications, { stage: "Interview", status: "all" }).map((row) => row.id), [2]);
  assert.deepEqual(filterWorkflowApplications(applications, { stage: "Withdrawn", status: "all" }).map((row) => row.id), [6]);
  assert.deepEqual(filterWorkflowApplications(applications, { search: "mira", status: "all" }).map((row) => row.id), [3]);
  assert.deepEqual(filterWorkflowApplications(applications, { status: "closed" }).map((row) => row.id), [4, 5, 6]);
  assert.deepEqual(filterWorkflowApplications(applications, { status: "active" }).map((row) => row.id), [1, 2, 3]);
});

test("workflow summary counts active stages and outcomes", () => {
  assert.deepEqual(summarizeWorkflow(applications), {
    total: 6, active: 3, interviews: 1, offers: 1, hired: 1, rejected: 1, withdrawn: 1,
  });
});

test("interview transition requires future date/time and mode-specific details", () => {
  assert.match(validateInterviewDetails({}), /date and time/i);
  assert.match(validateInterviewDetails({ starts_at: "not-a-date", duration_minutes: "60", mode: "online", meeting_url: "https://meet.example.test" }), /valid interview date/i);
  const past = new Date(Date.now() - 60_000).toISOString().slice(0, 16);
  assert.match(validateInterviewDetails({ starts_at: past, duration_minutes: "60", mode: "online", meeting_url: "https://meet.example.test" }), /future/i);
  const future = new Date(Date.now() + 86_400_000).toISOString().slice(0, 16);
  assert.match(validateInterviewDetails({ starts_at: future, duration_minutes: "10", mode: "online", meeting_url: "https://meet.example.test" }), /between 15 and 480/i);
  assert.match(validateInterviewDetails({ starts_at: future, duration_minutes: "60", mode: "online", meeting_url: "" }), /meeting link/i);
  assert.match(validateInterviewDetails({ starts_at: future, duration_minutes: "60", mode: "offline", location: "" }), /location/i);
  assert.equal(validateInterviewDetails({ starts_at: future, duration_minutes: "60", mode: "offline", location: "Office" }), "");
});

test("interview stage payload is timezone-aware and keeps only the selected meeting details", () => {
  const future = new Date(Date.now() + 86_400_000).toISOString().slice(0, 16);
  const online = buildWorkflowStagePayload("Interview", {
    starts_at: future, duration_minutes: "45", mode: "online",
    meeting_url: " https://meet.example.test/room ", location: "",
  });
  assert.equal(online.stage_name, "Interview");
  assert.equal(online.interview_duration_minutes, 45);
  assert.equal(online.interview_meeting_url, "https://meet.example.test/room");
  assert.equal(online.interview_location, null);
  assert.match(online.interview_starts_at, /Z$/);
  assert.deepEqual(buildWorkflowStagePayload("Screening"), { stage_name: "Screening" });
});
