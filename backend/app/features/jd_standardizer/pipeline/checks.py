"""§12 validators for AI drafts and summaries. Pure functions."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.features.jd_standardizer.pipeline.models import Fact, Line
from app.features.jd_standardizer.pipeline.policy import Policy
from app.features.jd_standardizer.pipeline.textutil import content_tokens, jaccard, sentences, tokens

DUPLICATE_JACCARD = 0.8
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#.&'’\-]*")


@dataclass
class CheckContext:
    vocab: set[str]
    numbers: set[str]
    has_work_mode: bool
    lines: dict[str, Line]
    existing: list[str] = field(default_factory=list)


def fact_strings(fields: dict[str, Fact]) -> list[str]:
    out: list[str] = []
    for f in fields.values():
        if f.status not in ("verified", "override") or f.value in (None, [], ""):
            continue
        v = f.value
        if isinstance(v, dict):
            out += [str(x) for x in v.values() if x is not None]
        elif isinstance(v, list):
            out += [str(x) for x in v]
        else:
            out.append(str(v))
    return out


def build_context(lines: list[Line], chrome_ids: set[str], fields: dict[str, Fact], existing: list[str],
                  policy: Policy) -> CheckContext:
    source = " ".join(ln.text for ln in lines if ln.id not in chrome_ids)
    facts = " ".join(fact_strings(fields))
    vocab = set(tokens(source)) | set(tokens(facts)) | set(policy.allowed_acronyms)
    numbers = set(re.findall(r"\d+", source)) | set(re.findall(r"\d+", facts))
    wm = fields.get("work_mode")
    return CheckContext(vocab=vocab, numbers=numbers, has_work_mode=bool(wm and wm.value),
                        lines={ln.id: ln for ln in lines}, existing=list(existing))


# ----------------------------------------------------------------- primitives
def banned_word_hits(text: str, policy: Policy, allow_work_mode: bool,
                     categories: tuple[str, ...] | None = None) -> list[str]:
    hits: list[str] = []
    for cat, words in policy.banned_words.items():
        if categories is not None and cat not in categories:
            continue
        if cat == "work_mode" and allow_work_mode:
            continue
        for w in words:
            cs = policy.case_sensitive_words.get(w.casefold())
            if cs is not None:
                pat = re.compile(rf"(?<![\w-]){re.escape(cs)}(?![\w-])")
            else:
                pat = re.compile(rf"(?<![\w-]){re.escape(w)}(?![\w-])", re.I)
            if pat.search(text):
                hits.append(f"{cat}:{w}")
    return hits


def banned_pattern_hits(text: str, policy: Policy, numbers: set[str]) -> list[str]:
    hits: list[str] = []
    for p in policy.banned_patterns:
        for m in p.regex.finditer(text):
            if p.allowed_if_in_source and m.group(0) in numbers:
                continue
            hits.append(f"{p.name}:{m.group(0)}")
            break
    return hits


def ungrounded_tokens(text: str, ctx: CheckContext) -> list[str]:
    bad: list[str] = []
    for sent in sentences(text) or [text]:
        for i, m in enumerate(_WORD_RE.finditer(sent)):
            w = m.group(0).strip(".'’-")
            letters = re.sub(r"[^A-Za-z]", "", w)
            if not letters:
                continue
            all_caps = len(letters) >= 2 and letters.isupper()
            mid_cap = i > 0 and w[0].isupper()
            if not (all_caps or mid_cap):
                continue
            if not all(t in ctx.vocab or (t.endswith("s") and t[:-1] in ctx.vocab) for t in tokens(w)):
                bad.append(w)
    return bad


def basis_ok(text: str, basis: str | None, line: str | None, ctx: CheckContext) -> bool:
    if basis != "brief":
        return True
    if not line or line not in ctx.lines:
        return False
    return bool(content_tokens(text) & content_tokens(ctx.lines[line].text))


# --------------------------------------------------------------- list rules
def check_bullet(text: str, basis: str | None, line: str | None, section: str, bounds: tuple[int, int],
                 ctx: CheckContext, earlier: list[str], policy: Policy) -> list[str]:
    codes: list[str] = []
    if banned_word_hits(text, policy, ctx.has_work_mode):
        codes.append("banned_word")
    if banned_pattern_hits(text, policy, ctx.numbers):
        codes.append("banned_pattern")
    if ungrounded_tokens(text, ctx):
        codes.append("ungrounded_proper_noun")
    n = len(text.split())
    if not bounds[0] <= n <= bounds[1]:
        codes.append("length")
    if section == "responsibilities":
        first = re.sub(r"[^A-Za-z]", "", text.split()[0]).casefold() if text.split() else ""
        if first not in policy.verbs:
            codes.append("not_verb_first")
    if any(jaccard(text, e) >= DUPLICATE_JACCARD for e in [*ctx.existing, *earlier]):
        codes.append("duplicate")
    if not basis_ok(text, basis, line, ctx):
        codes.append("bad_basis")
    return codes


def filter_bullets(items: list[dict[str, Any]], section: str, bounds: tuple[int, int], ctx: CheckContext,
                   policy: Policy) -> tuple[list[dict[str, Any]], list[tuple[str, list[str]]]]:
    accepted: list[dict[str, Any]] = []
    failures: list[tuple[str, list[str]]] = []
    for it in items:
        text = it["text"].strip().rstrip(".").strip()
        codes = check_bullet(text, it.get("basis"), it.get("line"), section, bounds, ctx,
                             [a["text"] for a in accepted], policy)
        if codes:
            failures.append((text, codes))
        else:
            accepted.append({**it, "text": text})
    return accepted, failures


# --------------------------------------------------------------- about rules
def check_about(text: str, basis: str | None, line: str | None, ctx: CheckContext, policy: Policy,
                spec: dict[str, Any]) -> list[str]:
    codes: list[str] = []
    s_lo, s_hi = spec.get("sentences", [2, 3])
    w_lo, w_hi = spec.get("words", [25, 70])
    if not s_lo <= len(sentences(text)) <= s_hi:
        codes.append("sentence_count")
    if not w_lo <= len(text.split()) <= w_hi:
        codes.append("length")
    if banned_word_hits(text, policy, ctx.has_work_mode):
        codes.append("banned_word")
    if banned_pattern_hits(text, policy, ctx.numbers):
        codes.append("banned_pattern")
    if ungrounded_tokens(text, ctx):
        codes.append("ungrounded_proper_noun")
    if any(jaccard(text, e) >= DUPLICATE_JACCARD for e in ctx.existing):
        codes.append("duplicate")
    if not basis_ok(text, basis, line, ctx):
        codes.append("bad_basis")
    return codes


# ------------------------------------------------------------- summary rules
def check_summary(text: str, title: str | None, ctx: CheckContext, policy: Policy, max_chars: int) -> list[str]:
    codes: list[str] = []
    if not text or len(text) > max_chars:
        codes.append("length")
    if title and not (content_tokens(title) & set(tokens(text))):
        codes.append("missing_title_word")
    if banned_word_hits(text, policy, ctx.has_work_mode):
        codes.append("banned_word")
    if banned_pattern_hits(text, policy, ctx.numbers):
        codes.append("banned_pattern")
    return codes


def repair_hint(failures: list[tuple[str, list[str]]], limit: int = 6) -> str:
    parts = [f'"{t[:80]}" → {", ".join(c)}' for t, c in failures[:limit]]
    return "; ".join(parts)
