"""Compact, deterministic evidence contract for recruiter-facing match results.

The helper deliberately avoids hiring recommendations. It converts the ATS's
structured match evidence into a small, stable object that the UI can render
without exposing scoring internals or hidden reasoning.
"""

from __future__ import annotations


def build_match_explanation(
    *,
    candidate_name: str,
    job_title: str,
    match_score: int,
    matched_required: list[str] | None = None,
    matched_preferred: list[str] | None = None,
    skill_gaps: list[str] | None = None,
    experience_years: float | None = None,
    required_experience_years: int | None = None,
    evidence: list[dict] | None = None,
) -> dict:
    required = [str(item).strip() for item in (matched_required or []) if str(item).strip()]
    preferred = [str(item).strip() for item in (matched_preferred or []) if str(item).strip()]
    gaps = [str(item).strip() for item in (skill_gaps or []) if str(item).strip()]

    try:
        score = max(0, min(100, int(match_score)))
    except (TypeError, ValueError):
        score = 0

    strengths: list[str] = []
    if required:
        strengths.append("Required skills evidenced: " + ", ".join(required[:6]))
    if preferred:
        strengths.append("Preferred skills evidenced: " + ", ".join(preferred[:6]))
    if required_experience_years is not None and experience_years is not None:
        strengths.append(
            f"Experience evidence: {round(float(experience_years), 1)} years "
            f"against {int(required_experience_years)} years requested."
        )

    review_flags: list[str] = []
    if gaps:
        review_flags.append("Some required skills are not evidenced in the current profile.")
    if required_experience_years is not None and experience_years is not None:
        if float(experience_years) < int(required_experience_years):
            review_flags.append("Reported experience is below the stated minimum; verify context with the candidate.")
    if not required and not preferred:
        review_flags.append("No structured skill evidence was available for a strong comparison.")

    if score >= 75:
        review_signal = "Strong evidence"
    elif score >= 50:
        review_signal = "Partial evidence"
    else:
        review_signal = "Limited evidence"

    clean_evidence = []
    for item in (evidence or [])[:6]:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "evidence").strip()
        title = str(item.get("title") or "").strip()
        details = str(item.get("details") or "").strip()
        if title or details:
            clean_evidence.append(
                {
                    "type": item_type,
                    "title": title[:200],
                    "details": details[:600],
                }
            )

    summary = (
        f"{candidate_name} shows {review_signal.lower()} against {job_title}. "
        f"The {score}/100 signal is based on structured resume-to-JD evidence; "
        "missing evidence should be verified rather than treated as proof of absence."
    )

    return {
        "summary": summary,
        "review_signal": review_signal,
        "strengths": strengths[:4],
        "gaps": gaps[:8],
        "review_flags": review_flags[:4],
        "evidence": clean_evidence,
        "decision_support_only": True,
    }
