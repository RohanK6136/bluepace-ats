# AI Recruiter Assistant evaluation

Grounding checks for the recruiter assistant:

1. Retrieval relevance: recruiter questions should surface matching JD, resume, match, or scorecard evidence.
2. Retrieval bounds: model context uses a small top-k evidence set instead of the full raw record.
3. Schema safety: model output is validated by AssistantOutput before use.
4. Gap safety: missing_required_skills is independently constrained to the deterministic JD-versus-resume gap set.
5. Decision boundary: assistant output cannot move stages, reject, hire, or rank candidates.

Manual smoke-test questions:
- What evidence shows FastAPI experience?
- Which required skills are not explicitly evidenced?
- Give three neutral interview questions for this role.
- Summarize submitted interview feedback.
- Why is a specific requirement not evidenced?

Expected behavior: every factual claim must be supported by ATS evidence; absence from the parsed resume must be described as not evidenced, not as proof that a candidate lacks the skill.
