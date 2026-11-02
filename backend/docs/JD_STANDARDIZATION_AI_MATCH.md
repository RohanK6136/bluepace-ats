# JD Standardization and AI Match — integration notes

This document records the intended integration boundary for the two recruiting AI features sourced from the RecruiterPortal AI experiments ZIP.

## Scope

- **JD Standardization**: convert pasted or uploaded job-description text into structured sections while preserving source facts, surfacing gaps/conflicts, and marking generated text for recruiter review.
- **AI Match / Applicant Assessment**: compare a resume with a standardized or raw job description, provide evidence-backed rubric scores, explain strengths and gaps, and support recruiter review.
- The AI provides recommendations only. A recruiter remains responsible for every hiring decision.

## Existing ATS integration

The feature modules live under `backend/app/features/jd_standardizer/` and `backend/app/features/applicant_match/`. They use the shared LLM gateway and model profiles under `backend/app/llm/` and `backend/config/models.yaml`; API routes are mounted under `/v1/jd/` and `/v1/match/`.

The existing ATS remains the system of record. This feature work must not create a separate candidate database, organization-creation flow, or parallel login system. It must not depend on SMTP/email delivery.

## Safe operating rules

1. Keep facts from the source JD authoritative; flag unsupported or conflicting values instead of inventing them.
2. Show the evidence behind match scores and requirement assessments.
3. Do not automatically shortlist, reject, hide, or hire candidates.
4. Do not enable payload retention or change privacy settings without explicit approval.
5. Do not claim that live model inference is available until the deployment has a configured provider credential and an end-to-end request has been verified.

## API list limits

Applicant Match list endpoints cap requested history sizes to 1–100 records. The regression tests in `backend/tests/test_applicant_match_query_limits.py` cover both out-of-range rejection and the maximum accepted value.

## Known limitations to validate before production claims

The source experiment describes itself as a prototype. In particular, OCR for scanned resumes and durable background queueing for very large bulk batches are not guaranteed by these two features alone. Do not promise thousands of resumes at 1–100 ms per resume without a measured load test and a separately verified asynchronous processing design.
