"""Deterministic, explainable quality checks for recruiter-authored job descriptions.

This module deliberately does not call an LLM. Scores are repeatable and every
finding includes an actionable suggestion. The result is advisory, not a
publication gate or a candidate suitability assessment.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any

RUBRIC_VERSION = "1.0"
HEADING_ALIASES = {
    "responsibilities": {
        "responsibilities", "key responsibilities", "what you will do",
        "what you'll do", "duties", "role and responsibilities",
    },
    "requirements": {
        "requirements", "qualifications", "required qualifications", "essential qualifications", "what you will bring",
        "what we're looking for", "what we are looking for",
        "must have", "essential skills", "required skills",
    },
    "preferred": {
        "preferred qualifications", "preferred skills", "nice to have",
        "good to have", "desirable skills",
    },
}
BULLET_RE = re.compile(r"^\s*(?:[-*•]\s+|\d+[.)]\s+)\S")
WORD_RE = re.compile(r"[A-Za-z0-9+#.]+")
EXPERIENCE_RE = re.compile(
    r"\b(?:\d+(?:\.\d+)?\s*(?:-|to)\s*\d+(?:\.\d+)?|\d+(?:\.\d+)?\s*\+?)\s*(?:years?|yrs?)\b",
    re.I,
)
LEVEL_RE = re.compile(r"\b(entry[- ]level|graduate|junior|mid[- ]level|senior|lead|principal|staff)\b", re.I)


def _clean_line(line: str) -> str:
    return re.sub(r"\s+", " ", line.strip().lstrip("#>*•- ")).strip(" :")


def _heading_key(line: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", _clean_line(line).casefold())


def _find_heading(lines: list[str], aliases: set[str]) -> int | None:
    keys = {_heading_key(alias) for alias in aliases}
    for index, line in enumerate(lines):
        if _heading_key(line) in keys:
            return index
    return None


def _section_bullets(lines: list[str], start: int | None) -> int:
    if start is None:
        return 0
    count = 0
    for line in lines[start + 1:]:
        if not line.strip():
            continue
        key = _heading_key(line)
        if line.lstrip().startswith("#") or key in {
            _heading_key(v) for group in HEADING_ALIASES.values() for v in group
        }:
            break
        if BULLET_RE.match(line):
            count += 1
    return count


def _finding(code: str, severity: str, message: str, suggestion: str) -> dict[str, str]:
    return {"code": code, "severity": severity, "message": message, "suggestion": suggestion}


def _category(category_id: str, label: str, score: int, maximum: int, detail: str) -> dict[str, Any]:
    ratio = score / maximum if maximum else 0
    status = "good" if ratio >= 0.8 else "partial" if score else "missing"
    return {
        "id": category_id,
        "label": label,
        "score": score,
        "max_score": maximum,
        "status": status,
        "detail": detail,
    }


def assess_jd_quality(text: str) -> dict[str, Any]:
    """Assess a JD using deterministic text checks; never invent missing facts."""
    source = text.strip() if isinstance(text, str) else ""
    if not source:
        raise ValueError("Job description text is required.")

    lines = source.splitlines()
    visible_lines = [line for line in lines if line.strip()]
    plain_lines = [_clean_line(line) for line in visible_lines]
    lower = source.casefold()
    words = WORD_RE.findall(source)
    word_count = len(words)
    findings: list[dict[str, str]] = []

    # Role clarity (15): explicit role title / position label.
    title_line = next((line for line in plain_lines if line), "")
    title_label = re.search(r"(?im)^\s*(?:job title|position|role)\s*:\s*(.+)$", source)
    looks_like_title = bool(title_label) or (
        bool(title_line) and len(title_line.split()) <= 10
        and not title_line.casefold() in {"job description", "about the company", "overview"}
    )
    role_score = 15 if looks_like_title else 0
    if not looks_like_title:
        findings.append(_finding(
            "missing_role_title", "warning", "The job title is not clear from the opening lines.",
            "Add a specific role title at the top, including seniority where relevant.",
        ))

    # Responsibilities (20): count actionable items in a clearly labelled section.
    resp_heading = _find_heading(visible_lines, HEADING_ALIASES["responsibilities"])
    resp_bullets = _section_bullets(visible_lines, resp_heading)
    if resp_heading is None:
        all_bullets = sum(1 for line in visible_lines if BULLET_RE.match(line))
        resp_bullets = min(all_bullets, 5)
    if resp_heading is not None and resp_bullets >= 3:
        resp_score = 20
    elif resp_bullets >= 3:
        resp_score = 15
    elif resp_bullets in (1, 2):
        resp_score = 10
    elif resp_heading is not None:
        resp_score = 5
    else:
        resp_score = 0
    if resp_score < 20:
        findings.append(_finding(
            "responsibilities_need_detail", "warning",
            "Responsibilities are missing, too brief, or not grouped under a clear heading.",
            "Add a Responsibilities section with at least three specific outcomes or tasks, using clear action verbs.",
        ))

    # Required and preferred criteria (25).
    req_heading = _find_heading(visible_lines, HEADING_ALIASES["requirements"])
    preferred_heading = _find_heading(visible_lines, HEADING_ALIASES["preferred"])
    req_bullets = _section_bullets(visible_lines, req_heading)
    has_required_language = bool(re.search(
        r"\b(required|must[- ]have|essential|minimum qualifications|you need)\b", lower
    ))
    if req_heading is not None and req_bullets >= 3 and (has_required_language or req_bullets >= 4):
        req_score = 25
    elif req_heading is not None and req_bullets >= 1:
        req_score = 18
    elif has_required_language or re.search(r"\b(skills|qualifications|experience with)\b", lower):
        req_score = 12
    else:
        req_score = 0
    if req_score < 25:
        findings.append(_finding(
            "requirements_need_detail", "warning",
            "Required qualifications or skills are not sufficiently explicit.",
            "List essential skills and qualifications as separate, verifiable requirements.",
        ))
    if preferred_heading is None and req_heading is not None:
        findings.append(_finding(
            "preferred_requirements_not_separated", "info",
            "Preferred criteria are not clearly separated from essential requirements.",
            "Add a Preferred or Nice-to-have section so optional skills are not treated as mandatory.",
        ))

    # Experience expectations (15); level labels are valid alternatives to a year range.
    if EXPERIENCE_RE.search(source):
        experience_score = 15
    elif LEVEL_RE.search(source):
        experience_score = 12
    else:
        experience_score = 5
        findings.append(_finding(
            "experience_expectation_unclear", "info",
            "No explicit experience range or seniority level was found.",
            "State the expected experience range or seniority level when it is relevant to the role.",
        ))

    # Work context (15): location, work arrangement, and employment type.
    has_location = bool(re.search(
        r"\b(location|based in|hyderabad|bengaluru|bangalore|mumbai|pune|delhi|chennai|india|united states|uk)\b",
        lower,
    ))
    has_work_mode = bool(re.search(r"\b(remote|hybrid|on[- ]site|onsite|work from home)\b", lower))
    has_employment_type = bool(re.search(
        r"\b(full[- ]time|part[- ]time|contract(?:or)?|temporary|internship|permanent)\b", lower
    ))
    context_score = (5 if has_location else 0) + (5 if has_work_mode else 0) + (5 if has_employment_type else 0)
    if not has_location:
        findings.append(_finding(
            "location_missing", "info", "The job location is not clear.",
            "Add the work location or state that the role is location-independent.",
        ))
    if not has_work_mode:
        findings.append(_finding(
            "work_mode_missing", "info", "The work arrangement is not specified.",
            "State whether the role is remote, hybrid, or on-site.",
        ))
    if not has_employment_type:
        findings.append(_finding(
            "employment_type_missing", "info", "The employment type is not specified.",
            "Specify full-time, part-time, contract, internship, or another applicable type.",
        ))

    # Readability (10): sensible length, section structure, and repeated lines.
    length_score = 4 if 100 <= word_count <= 1500 else 3 if 60 <= word_count < 100 or 1500 < word_count <= 2200 else 1
    heading_count = sum(1 for line in visible_lines if line.lstrip().startswith("#")) + sum(
        1 for line in visible_lines if _heading_key(line) in {
            _heading_key(v) for group in HEADING_ALIASES.values() for v in group
        }
    )
    structure_score = 3 if heading_count >= 3 else 2 if heading_count in (1, 2) else 0
    normalized_content = [
        re.sub(r"[^a-z0-9]+", " ", _clean_line(line).casefold()).strip()
        for line in visible_lines
    ]
    normalized_content = [line for line in normalized_content if len(line.split()) >= 4]
    counts = Counter(normalized_content)
    duplicate_count = sum(count - 1 for count in counts.values() if count > 1)
    duplicate_ratio = duplicate_count / max(1, len(normalized_content))
    duplication_score = 3 if duplicate_ratio == 0 else 2 if duplicate_ratio <= 0.05 else 0
    readability_score = length_score + structure_score + duplication_score
    if word_count < 60:
        findings.append(_finding(
            "jd_too_short", "warning", "The job description is very short.",
            "Add enough context for candidates to understand the role, responsibilities, and essential criteria.",
        ))
    elif word_count > 2200:
        findings.append(_finding(
            "jd_too_long", "info", "The job description is unusually long.",
            "Remove repeated or unrelated content and keep the role requirements easy to scan.",
        ))
    if duplicate_count:
        findings.append(_finding(
            "repeated_content", "warning", "Some lines appear to repeat.",
            "Remove repeated responsibilities or requirements while keeping distinct criteria.",
        ))

    categories = [
        _category("role_clarity", "Role clarity", role_score, 15, "Checks whether a clear role title is present."),
        _category("responsibilities", "Responsibilities", resp_score, 20, "Checks for a labelled section and actionable items."),
        _category("requirements", "Required and preferred criteria", req_score, 25, "Checks whether essential criteria are explicit and separated."),
        _category("experience", "Experience expectations", experience_score, 15, "Checks for a stated experience range or seniority level."),
        _category("work_context", "Work context", context_score, 15, "Checks location, work arrangement, and employment type."),
        _category("readability", "Structure and readability", readability_score, 10, "Checks length, headings, and repeated content."),
    ]
    score = sum(item["score"] for item in categories)
    band = "strong" if score >= 85 else "good" if score >= 70 else "needs_improvement" if score >= 50 else "incomplete"

    return {
        "score": score,
        "band": band,
        "rubric_version": RUBRIC_VERSION,
        "assessment_type": "deterministic_text_checks",
        "word_count": word_count,
        "categories": categories,
        "findings": findings,
        "disclaimer": (
            "This score checks JD structure and completeness only. It does not measure job attractiveness, "
            "legal compliance, candidate suitability, or hiring quality. Review suggestions before applying them."
        ),
    }
