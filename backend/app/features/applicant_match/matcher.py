"""Boundary-safe alias matching over numbered resume lines, plus the negation cue.

Java never matches JavaScript, C never matches C++ or C#, and .NET / Node.js / CI/CD match as written.
An alias starting with "=" is case-sensitive ("=Swift" matches "Swift", not "swift delivery").
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

BOUNDARY_CHARS = r"A-Za-z0-9+#"
TERM = r"(?<![" + BOUNDARY_CHARS + r"])({term})(?![" + BOUNDARY_CHARS + r"])"


@dataclass(frozen=True)
class Line:
    id: str
    text: str
    redacted: bool = False


def _alias_body(alias: str) -> str:
    # words may be separated by any run of spaces or hyphens: "ci cd" ≠ "ci/cd", but "node js" = "node-js"
    parts = [re.escape(p) for p in re.split(r"[\s\-]+", alias.strip()) if p]
    return r"[\s\-]+".join(parts)


@lru_cache(maxsize=4096)
def alias_pattern(alias: str) -> re.Pattern[str]:
    case_sensitive = alias.startswith("=")
    body = _alias_body(alias.lstrip("="))
    return re.compile(TERM.format(term=body), 0 if case_sensitive else re.IGNORECASE)


def find_lines(aliases: list[str] | tuple[str, ...], lines: list[Line]) -> list[Line]:
    """Lines (in document order) where any alias occurs. Redacted lines never match."""
    pats = [alias_pattern(a) for a in aliases if a.strip("= ")]
    if not pats:
        return []
    return [ln for ln in lines if not ln.redacted and any(p.search(ln.text) for p in pats)]


@lru_cache(maxsize=64)
def _negation_pattern(cues: tuple[str, ...]) -> re.Pattern[str]:
    alts = "|".join(sorted((_alias_body(c) for c in cues), key=len, reverse=True))
    return re.compile(r"(?<![A-Za-z])(?:" + alts + r")(?![A-Za-z])", re.IGNORECASE)


CLAUSE_SPLIT_RE = re.compile(r"(?<=[.;!?])\s+|\s+(?:but|however|whereas)\s+", re.IGNORECASE)


def is_negated(text: str, cues: tuple[str, ...], aliases: list[str] | tuple[str, ...] = ()) -> bool:
    """True when a negation cue sits in the same clause as the matched term ("No Kubernetes", "learning
    PowerShell"). A cue in another sentence of the line does not count."""
    if not cues:
        return False
    neg = _negation_pattern(cues)
    pats = [alias_pattern(a) for a in aliases if a.strip("= ")]
    clauses = CLAUSE_SPLIT_RE.split(text) if pats else [text]
    return any(neg.search(c) for c in clauses if not pats or any(p.search(c) for p in pats))
