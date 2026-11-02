"""Deterministic resume-text quality signals; deliberately not an AI detector.

Text-only heuristics cannot reliably establish who or what authored a resume.
This module surfaces observable repetition/formatting issues for human review
without assigning an AI-authorship probability or making hiring recommendations.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ReviewSignal:
    code: str
    label: str
    detail: str
    severity: str = "low"


def _normalise_line(line: str) -> str:
    line = re.sub(r"^\\s*(?:[-*•]|\\d+[.)])\\s*", "", line)
    return re.sub(r"\\s+", " ", line).strip().casefold()


def assess_resume_text(text: str) -> dict:
    """Return observable text-quality signals, never an authorship verdict."""
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    cleaned = text.replace("\\x00", " ").strip()
    if len(cleaned) > 60_000:
        raise ValueError("resume text exceeds the 60000 character limit")

    lines = [_normalise_line(line) for line in cleaned.splitlines()]
    content_lines = [line for line in lines if len(line) >= 24]
    counts = Counter(content_lines)
    duplicates = sorted((line, count) for line, count in counts.items() if count > 1)
    signals: list[ReviewSignal] = []

    if len(cleaned) < 500:
        signals.append(ReviewSignal(
            code="limited_text_sample",
            label="Limited text sample",
            detail="There is not enough extracted text for a meaningful authorship assessment. Check the original document and extraction quality.",
        ))

    if duplicates:
        total_repeated = sum(count - 1 for _, count in duplicates)
        signals.append(ReviewSignal(
            code="repeated_content",
            label="Repeated resume content",
            detail=f"Found {total_repeated} repeated long line(s). This may reflect duplicated sections, formatting, or copied content; it does not establish AI authorship.",
        ))

    bullets = [line for line in cleaned.splitlines() if re.match(r"^\\s*(?:[-*•]|\\d+[.)])\\s+", line)]
    if len(bullets) >= 8:
        lengths = [len(_normalise_line(line)) for line in bullets]
        mean = sum(lengths) / len(lengths)
        if mean and max(lengths) <= mean * 1.35 and min(lengths) >= mean * 0.65:
            signals.append(ReviewSignal(
                code="uniform_bullet_lengths",
                label="Highly uniform bullet formatting",
                detail="Bullet lengths are unusually consistent. This is a formatting observation only and is common in both human-edited and AI-assisted resumes.",
            ))

    return {
        "assessment": "undetermined",
        "status": "insufficient_evidence" if len(cleaned) < 500 else ("review_recommended" if duplicates else "no_text_quality_alerts"),
        "confidence": "not_assessed",
        "text_characters": len(cleaned),
        "signals": [asdict(signal) for signal in signals],
        "limitations": [
            "Text-only heuristics cannot reliably determine whether a resume was written by a person or an AI system.",
            "No AI-authorship probability or binary verdict is produced.",
            "Formatting and repetition signals are not evidence of misconduct and must not affect hiring decisions.",
        ],
        "human_review_required": True,
        "detector_version": "text-quality-signals-0.1.0",
    }
