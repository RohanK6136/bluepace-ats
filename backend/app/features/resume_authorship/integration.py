"""Candidate-record integration for conservative resume text-quality review.

The module stores only derived review metadata, never extracted resume text.
The result is advisory-only and is intentionally separate from matching scores.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.features.resume_authorship.analysis import assess_resume_text

MAX_REVIEW_TEXT_CHARACTERS = 60_000
MIN_REVIEW_TEXT_CHARACTERS = 100


def build_resume_text_review(text: str, source: str) -> dict[str, Any]:
    """Build a bounded advisory report without retaining the source text."""
    cleaned = str(text or "").replace("\x00", " ").strip()
    if len(cleaned) < MIN_REVIEW_TEXT_CHARACTERS:
        report = assess_resume_text(cleaned)
    elif len(cleaned) > MAX_REVIEW_TEXT_CHARACTERS:
        report = {
            "assessment": "undetermined",
            "status": "insufficient_evidence",
            "confidence": "not_assessed",
            "text_characters": len(cleaned),
            "signals": [{
                "code": "text_sample_too_large",
                "label": "Text sample exceeds review limit",
                "detail": (
                    "The extracted resume text exceeds the review limit. No partial authorship "
                    "judgement was attempted; inspect the original document manually."
                ),
                "severity": "low",
            }],
            "limitations": [
                "Text-only heuristics cannot reliably determine whether a resume was written by a person or an AI system.",
                "No AI-authorship probability or binary verdict is produced.",
                "This review is not evidence of misconduct and must not affect hiring decisions.",
            ],
            "human_review_required": True,
            "detector_version": "text-quality-signals-0.1.0",
        }
    else:
        report = assess_resume_text(cleaned)

    # No resume text, PII, file bytes, or prompt is persisted in the candidate JSON.
    return {
        **report,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "source": str(source or "recruiter_review")[:40],
        "decision_support_only": True,
        "not_used_for_matching": True,
    }


def attach_resume_text_review(
    profile: dict[str, Any] | None,
    text: str,
    source: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return a copied candidate profile with a payload-free review summary."""
    updated = dict(profile or {})
    review = build_resume_text_review(text, source)
    updated["resume_text_quality_review"] = review
    return updated, review
