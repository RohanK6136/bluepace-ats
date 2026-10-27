"""Small, pure text helpers shared by stages."""

from __future__ import annotations

import re
import string
from functools import lru_cache

import pysbd

from app.features.jd_standardizer.pipeline.policy import Policy, alias_key

MARKER = "• "
EDGE_PUNCT = string.punctuation + "“”‘’«»•–—…"
KV_RE = re.compile(r"^(?P<key>[A-Za-z][A-Za-z /&\-]{1,30}?)\s*:\s*(?P<val>\S.*)$")
TOKEN_RE = re.compile(r"[a-z0-9]+")
STOPWORDS = frozenset(
    "a an and or the of to in on for with by at from as is are be will this that these those it its into "
    "across within per via all any each other such than then".split()
)
MODE_ORDER = ["remote", "hybrid", "onsite"]


def has_marker(text: str) -> bool:
    return text.startswith(MARKER)


def strip_marker(text: str) -> str:
    return text[len(MARKER):] if has_marker(text) else text


def word_count(text: str) -> int:
    return len(strip_marker(text).split())


def norm(text: str) -> str:
    """casefold, collapse whitespace, strip edge punctuation (quote check / dedupe)."""
    t = re.sub(r"\s+", " ", strip_marker(text).casefold()).strip()
    return t.strip(EDGE_PUNCT + " ")


def tokens(text: str) -> list[str]:
    return TOKEN_RE.findall(text.casefold())


def content_tokens(text: str) -> set[str]:
    return {t for t in tokens(text) if t not in STOPWORDS}


def jaccard(a: str, b: str) -> float:
    sa, sb = set(tokens(a)), set(tokens(b))
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


@lru_cache(maxsize=1)
def _segmenter() -> pysbd.Segmenter:
    return pysbd.Segmenter(language="en", clean=False)


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _segmenter().segment(text) if s.strip()]


# ------------------------------------------------------------------ headings/kv
def heading_key(text: str) -> str:
    t = strip_marker(text).casefold().replace("’", "'").replace("‘", "'")
    t = re.sub(r"^\s*(?:\d{1,2}|[ivx]{1,4}|[a-z])[.)]\s+", "", t)
    t = t.replace(",", " ")
    t = re.sub(r"[\s:\-–—]+$", "", t)
    return re.sub(r"\s+", " ", t).strip()


def heading_text(text: str) -> str:
    """Original heading text without trailing colon/dashes (for groups)."""
    return re.sub(r"[\s:\-–—]+$", "", strip_marker(text)).strip()


def match_section_heading(text: str, policy: Policy) -> tuple[str | None, str | None]:
    """Return (section_id, foreign_company_name) for a heading line, else (None, None)."""
    if has_marker(text) or len(text) > 80:
        return None, None
    key = heading_key(text)
    for k in (key, key.replace("&", "and"), re.sub(r"\s+", " ", key.replace("&", " ")).strip()):
        if k in policy.alias_to_section:
            return policy.alias_to_section[k], None
    cand = heading_text(text)
    if cand[:5].casefold() == "about":
        probe = "about" + cand[5:]
        if policy.company_about_re.match(probe):
            return "company_about", cand[5:].strip()
    return None, None


def match_kv(text: str, policy: Policy) -> tuple[str, str, str] | None:
    """Return (key, value, kind) for a known kv line."""
    if has_marker(text):
        return None
    m = KV_RE.match(text)
    if not m:
        return None
    key = re.sub(r"\s+", " ", m["key"].strip().casefold())
    kind = policy.kv_keys.get(key)
    return (m["key"].strip(), m["val"].strip(), kind) if kind else None


# ------------------------------------------------------------- vocab lookups
def _find_alias_values(text: str, aliases: dict[str, str]) -> list[str]:
    t = f" {alias_key(text)} "
    found: list[str] = []
    for alias in sorted(aliases, key=len, reverse=True):
        pat = re.compile(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])")
        if pat.search(t):
            t = pat.sub(" ", t)
            if aliases[alias] not in found:
                found.append(aliases[alias])
    return found


def canonical_role_types(text: str, policy: Policy) -> list[str]:
    return _find_alias_values(text, policy.role_type_aliases)


def canonical_work_modes(text: str, policy: Policy) -> list[str]:
    return sorted(set(_find_alias_values(text, policy.work_mode_aliases)), key=MODE_ORDER.index)
