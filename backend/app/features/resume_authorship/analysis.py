"""Deterministic resume-text quality signals; deliberately not an AI detector.

Text-only heuristics cannot reliably establish who or what authored a resume.
This module surfaces observable repetition/formatting/phrase issues for human review
without assigning an AI-authorship probability or making hiring recommendations.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict, dataclass

DETECTOR_VERSION = "text-quality-signals-0.2.0"

# Common corporate/AI-resume filler phrases. Presence is a review signal only.
GENERIC_PHRASES = (
    "synergistic",
    "leverage cross-functional",
    "drive impactful outcomes",
    "proven track record of success",
    "results-driven professional",
    "passionate about leveraging",
    "utilize cutting-edge",
    "utilize cutting edge",
    "dynamic and fast-paced environment",
    "excel at communicating",
    "spearheaded initiatives",
    "robust and scalable solutions",
    "end-to-end ownership of complex",
    "highly motivated self-starter",
)


@dataclass(frozen=True)
class ReviewSignal:
    code: str
    label: str
    detail: str
    severity: str = "low"


def _normalise_line(line: str) -> str:
    line = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", line)
    return re.sub(r"\s+", " ", line).strip().casefold()


def assess_resume_text(text: str) -> dict:
    """Return observable text-quality signals, never an authorship verdict."""
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    cleaned = text.replace("\x00", " ").strip()
    if len(cleaned) > 60_000:
        raise ValueError("resume text exceeds the 60000 character limit")

    lines = [_normalise_line(line) for line in cleaned.splitlines()]
    content_lines = [line for line in lines if len(line) >= 24]
    counts = Counter(content_lines)
    duplicates = sorted((line, count) for line, count in counts.items() if count > 1)
    signals: list[ReviewSignal] = []
    folded = cleaned.casefold()

    if len(cleaned) < 500:
        signals.append(ReviewSignal(
            code="limited_text_sample",
            label="Limited text sample",
            detail=(
                "There is not enough extracted text for a meaningful authorship assessment. "
                "Check the original document and extraction quality."
            ),
        ))

    if duplicates:
        total_repeated = sum(count - 1 for _, count in duplicates)
        signals.append(ReviewSignal(
            code="repeated_content",
            label="Repeated resume content",
            detail=(
                f"Found {total_repeated} repeated long line(s). This may reflect duplicated sections, "
                "formatting, or copied content; it does not establish AI authorship."
            ),
        ))

    bullets = [line for line in cleaned.splitlines() if re.match(r"^\s*(?:[-*•]|\d+[.)])\s+", line)]
    if len(bullets) >= 8:
        lengths = [len(_normalise_line(line)) for line in bullets]
        mean = sum(lengths) / len(lengths)
        if mean and max(lengths) <= mean * 1.35 and min(lengths) >= mean * 0.65:
            signals.append(ReviewSignal(
                code="uniform_bullet_lengths",
                label="Highly uniform bullet formatting",
                detail=(
                    "Bullet lengths are unusually consistent. This is a formatting observation only "
                    "and is common in both human-edited and AI-assisted resumes."
                ),
            ))

    phrase_hits = [phrase for phrase in GENERIC_PHRASES if phrase in folded]
    if len(phrase_hits) >= 3:
        preview = ", ".join(phrase_hits[:5])
        more = f" (+{len(phrase_hits) - 5} more)" if len(phrase_hits) > 5 else ""
        signals.append(ReviewSignal(
            code="generic_corporate_phrases",
            label="Multiple generic corporate phrases",
            detail=(
                f"Found {len(phrase_hits)} generic phrases often seen in templated or AI-assisted writing "
                f"({preview}{more}). Humans use these too; treat as a review cue only."
            ),
            severity="low",
        ))

    review_signal_present = any(signal.code != "limited_text_sample" for signal in signals)

    return {
        "assessment": "undetermined",
        "status": (
            "insufficient_evidence"
            if len(cleaned) < 500
            else ("review_recommended" if review_signal_present else "no_text_quality_alerts")
        ),
        "confidence": "not_assessed",
        "text_characters": len(cleaned),
        "signals": [asdict(signal) for signal in signals],
        "limitations": [
            "Text-only heuristics cannot reliably determine whether a resume was written by a person or an AI system.",
            "No AI-authorship probability or binary verdict is produced.",
            "Formatting and repetition signals are not evidence of misconduct and must not affect hiring decisions.",
        ],
        "human_review_required": True,
        "detector_version": DETECTOR_VERSION,
    }


def build_text_quality_review(raw_text: str | None) -> dict | None:
    """Run text-quality signals for intake pipelines. Never blocks application acceptance.

    Returns None when there is no usable text. Always keeps assessment undetermined.
    """
    if not raw_text or not str(raw_text).strip():
        return None
    text = str(raw_text).strip()
    if len(text) < 100:
        return {
            "assessment": "undetermined",
            "status": "insufficient_evidence",
            "confidence": "not_assessed",
            "text_characters": len(text),
            "signals": [
                {
                    "code": "limited_text_sample",
                    "label": "Limited text sample",
                    "detail": "Extracted resume text was too short for a meaningful text-quality review.",
                    "severity": "low",
                }
            ],
            "limitations": [
                "Text-only heuristics cannot reliably determine whether a resume was written by a person or an AI system.",
                "No AI-authorship probability or binary verdict is produced.",
            ],
            "human_review_required": True,
            "detector_version": DETECTOR_VERSION,
            "source": "application_intake",
        }
    try:
        result = assess_resume_text(text)
    except (TypeError, ValueError):
        return None
    result["source"] = "application_intake"
    return result


def attach_text_quality_review(resume_data: dict, raw_text: str | None) -> dict:
    """Copy resume_data and attach text_quality_review when signals can be computed."""
    payload = dict(resume_data or {})
    review = build_text_quality_review(raw_text)
    if review is not None:
        payload["text_quality_review"] = review
    return payload
