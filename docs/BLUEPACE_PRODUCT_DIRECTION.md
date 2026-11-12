# BluePace ATS product direction: evidence-led recruitment

## Product principle

BluePace should be recognisably its own product. External product demonstrations are useful prompts for problem discovery, not UI, copy, workflow, or feature specifications to reproduce. We should build from problems in our own recruitment operation and use our current codebase, data contracts, and customer workflows as the source of truth.

## Differentiating product thesis

BluePace should help recruiters make faster, more consistent, and more explainable decisions while keeping hiring authority with people. The product should make the next useful action obvious, expose the evidence behind assessments, and make uncertainty visible rather than disguising it as a score.

## First implementation: Role Evidence Map

The Role Evidence Map is a recruiter-side evidence review embedded in the existing candidate profile.

- It consumes the existing application fit-analysis response; it does not create a second scoring engine or new AI endpoint.
- It maps listed required skills to existing parsed-resume evidence, project references, and extraction source-line references.
- It treats criteria not located in parsed data as questions to verify, never as proof that a candidate lacks a skill.
- It shows experience and education context separately from skills coverage.
- It drafts job-related clarification prompts for recruiter review and can hand the user to the existing candidate-question area.
- It does not automatically reject, rank, contact, or move candidates.

## Product opportunities to explore next

### 1. Hiring Evidence Ledger

Capture each meaningful human decision with the role, stage, reviewer, timestamp, evidence considered, unresolved questions, and a short rationale. Keep model output, extracted facts, and human judgment visibly distinct.

### 2. Candidate Momentum Signals

Measure waiting time and hand-off friction from application events. Show where the process is stalled and who owns the next action. Do not use response speed as a proxy for candidate quality.

### 3. Job Clarity Review

Before a job is published, surface ambiguous requirements, duplicated criteria, untestable adjectives, inconsistent seniority, and missing location/work-mode details. Let the hiring manager confirm changes; never invent mandatory requirements.

### 4. Evidence-aware Candidate Rediscovery

When a new role opens, identify candidates who may be relevant using consent-aware profile data. Explain the exact evidence overlap and let a recruiter review before an invitation is sent. Do not auto-apply on a candidate's behalf.

### 5. Assessment Quality Monitor

Track extraction confidence, missing source coverage, stale resumes, and rubric changes. Warn reviewers when the evidence base is weak or the job criteria changed after an assessment. Avoid presenting an unreliable score as precise.

## Delivery rules

- Extend existing components and API contracts before creating new ones.
- Keep the current 5 MB document limit and existing privacy controls.
- Do not send candidate communications without an explicit recruiter action.
- Keep candidate information and assessment evidence scoped to the recruiter's organisation.
- Add unit tests for deterministic logic and integration tests for API-backed workflows.
- Use a separate feature branch and pull request; do not deploy unreviewed changes.
