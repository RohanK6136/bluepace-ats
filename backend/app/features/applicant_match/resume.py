"""Resume text → numbered lines → deterministic redaction → parse-quality and is-it-a-resume checks.

Redaction runs before any model call and before anything is stored: emails, phone numbers, links, postal
addresses, the name line (and the name wherever it reappears), and lines about age, gender, nationality,
marital status, religion or a photo. Line ids stay stable, so evidence still points at the right line.
There is no NER model: every rule is a pinned pattern in code or config/redaction.yaml.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from app.core.ingest import RawLine
from app.features.applicant_match.matcher import Line
from app.features.applicant_match.policy import MatchPolicy, fold

BULLET_RE = re.compile(r"^[\s•●▪■◦○◆►▸➤✓✔\-*·–—]+\s*")
EMAIL_RE = re.compile(r"[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+")
URL_RE = re.compile(r"(?:https?://|www\.)\S+|\b(?:linkedin|github|gitlab|behance|dribbble)\.com/\S*", re.I)
PHONE_RE = re.compile(r"(?<![\w/])\+?\(?\d[\d\s().\-]{6,}\d(?![\w/])")
YEARISH_RE = re.compile(r"^(?:19|20)\d\d$")
STREET_RE = re.compile(
    r"\b\d{1,5}[A-Za-z]?,?\s+(?:[A-Za-z'.\-]+\s+){0,4}(?:street|st|road|rd|avenue|ave|lane|ln|drive|dr|boulevard|"
    r"blvd|way|court|ct|close|crescent|place|pl|terrace|parkway|pkwy|highway|hwy|nagar|marg|cross|main)\b\.?",
    re.I)
UK_POSTCODE_RE = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s+\d[A-Z]{2}\b")
US_ZIP_RE = re.compile(r"\b[A-Z]{2}\s+\d{5}(?:-\d{4})?\b")
PIN_RE = re.compile(r"\b(?:pin|pincode|pin code|zip|zip code|postcode|postal code)\s*[:\-]?\s*\d{4,6}\b", re.I)
NAME_TOKEN_RE = re.compile(r"^(?:[A-Z][a-z'\-]+|[A-Z]{2,}|[A-Z]\.)$")
SEPARATORS_RE = re.compile(r"\s*[|•·,–—:]\s*|\s+-\s+")
VALUE_ONLY_LINES = {"male", "female", "married", "single", "unmarried", "divorced", "widowed"}
SECTION_WORDS_RE = re.compile(
    r"\b(experience|employment|work history|education|skills|projects|qualifications|certifications|"
    r"professional summary|career|internship|achievements)\b", re.I)
YEAR_RE = re.compile(r"\b(19[5-9]\d|20\d\d)\b")


@dataclass
class ResumeText:
    lines: list[Line]
    redactions: dict[str, int] = field(default_factory=dict)
    quality: list[str] = field(default_factory=list)  # parse_quality:* flags
    chars: int = 0

    @property
    def text(self) -> str:
        return "\n".join(f"{ln.id} {ln.text}" for ln in self.lines)

    def by_id(self) -> dict[str, Line]:
        return {ln.id: ln for ln in self.lines}


def number_lines(raw: list[RawLine]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for r in raw:
        t = " ".join(BULLET_RE.sub("", r.text).split())
        if t:
            out.append((f"L{len(out) + 1:03d}", t))
    return out


# ------------------------------------------------------------------ redaction
def _phone_like(m: re.Match[str], min_digits: int) -> bool:
    s = m.group(0)
    digits = re.sub(r"\D", "", s)
    if len(digits) < min_digits:
        return False
    groups = re.findall(r"\d+", s)
    return not all(YEARISH_RE.match(g) for g in groups)  # "2015 - 2019 2020" is a date run, not a phone


def _alts(labels: list[str]) -> str:
    return "|".join(sorted((re.escape(x) for x in labels), key=len, reverse=True))


def _is_personal(text: str, labelled: re.Pattern[str], starts: re.Pattern[str]) -> bool:
    if labelled.search(text) or fold(text).strip(" .") in VALUE_ONLY_LINES:
        return True
    return bool(starts.match(text)) and len(text.split()) <= 6


def _looks_like_name(segment: str, not_a_name: set[str]) -> bool:
    tokens = segment.split()
    if not 2 <= len(tokens) <= 4:
        return False
    if any(fold(t.strip(".")) in not_a_name for t in tokens):
        return False
    return all(NAME_TOKEN_RE.match(t) for t in tokens)


def redact(pairs: list[tuple[str, str]], policy: MatchPolicy) -> ResumeText:
    cfg = policy.redaction
    labelled = re.compile(rf"(?<![A-Za-z])(?:{_alts(cfg['personal_line_labels'])})\s*(?::|\s-|–)", re.I)
    starts = re.compile(rf"^(?:{_alts(cfg['personal_line_starts'])})\b", re.I)
    address = re.compile(rf"^(?:{'|'.join(re.escape(x) for x in cfg['address_labels'])})\b", re.I)
    not_a_name = {fold(x) for x in cfg["not_a_name"]}
    min_digits = int(cfg.get("phone_min_digits", 9))
    counts: dict[str, int] = {}

    def bump(kind: str, n: int = 1) -> None:
        if n:
            counts[kind] = counts.get(kind, 0) + n

    # the name: first title-case 2-4 word segment among the first three lines
    name_tokens: list[str] = []
    name_line: str | None = None
    for lid, text in pairs[:3]:
        first = SEPARATORS_RE.split(EMAIL_RE.sub("", text))[0].strip()
        if _looks_like_name(first, not_a_name):
            name_line, name_tokens = lid, [t.strip(".") for t in first.split() if len(t.strip(".")) >= 3]
            break
    name_re = (re.compile(r"\b(?:" + "|".join(re.escape(t) for t in name_tokens) + r")\b", re.I)
               if name_tokens else None)

    lines: list[Line] = []
    for lid, text in pairs:
        t = text
        if _is_personal(t, labelled, starts):
            bump("personal_details")
            lines.append(Line(lid, "[redacted: personal details]", redacted=True))
            continue
        if address.search(t) or STREET_RE.search(t) or UK_POSTCODE_RE.search(t) or US_ZIP_RE.search(t) \
                or PIN_RE.search(t):
            bump("address")
            lines.append(Line(lid, "[redacted: address]", redacted=True))
            continue
        t, n = EMAIL_RE.subn("[email]", t)
        bump("email", n)
        t, n = URL_RE.subn("[link]", t)
        bump("link", n)
        n = 0

        def _phone(m: re.Match[str]) -> str:
            nonlocal n
            if _phone_like(m, min_digits):
                n += 1
                return "[phone]"
            return m.group(0)

        t = PHONE_RE.sub(_phone, t)
        bump("phone", n)
        if name_re:
            t, n = name_re.subn("[name]", t)
            bump("name", 1 if (n and lid == name_line) else 0)
        stripped = re.sub(r"\[(?:email|link|phone|name)\]|[|,;:•·\s\-–—/]", "", t)
        if not stripped:
            lines.append(Line(lid, "[redacted: name]" if lid == name_line else "[redacted: contact details]",
                              redacted=True))
            continue
        lines.append(Line(lid, t))
    return ResumeText(lines=lines, redactions=counts)


# ------------------------------------------------------------------ checks
def parse_quality(pairs: list[tuple[str, str]], policy: MatchPolicy) -> list[str]:
    cfg = policy.settings["resume"]["parse_quality"]
    flags: list[str] = []
    if pairs:
        short = sum(1 for _, t in pairs if len(t.split()) <= 2) / len(pairs)
        if short > cfg["short_line_ratio"] and len(pairs) >= 15:
            flags.append("parse_quality:fragmented_layout")
    text = "".join(t for _, t in pairs)
    if text:
        odd = sum(1 for ch in text if ch == "�" or unicodedata.category(ch) in ("Co", "Cc", "Cs"))
        if odd / len(text) > cfg["odd_char_ratio"]:
            flags.append("parse_quality:garbled_text")
    return flags


def looks_like_resume(pairs: list[tuple[str, str]]) -> bool:
    text = "\n".join(t for _, t in pairs)
    return bool(YEAR_RE.search(text)) and bool(SECTION_WORDS_RE.search(text))


def prepare_resume(raw: list[RawLine], policy: MatchPolicy) -> ResumeText:
    pairs = number_lines(raw)
    res = redact(pairs, policy)
    res.quality = parse_quality(pairs, policy)
    # counted after redaction: the card must not change with the length of a name or email address
    res.chars = sum(len(ln.text) for ln in res.lines if not ln.redacted)
    return res
