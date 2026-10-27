"""Profile extraction: the model lists roles, education, certifications and languages with cited line ids;
code verifies every citation, parses the dates and computes years. One repair attempt if the citations are wrong.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.config import Settings
from app.features.applicant_match.dates import parse_date, years_of
from app.features.applicant_match.llm_schemas import profile_schema
from app.features.applicant_match.policy import MatchPolicy, education_levels_in, fold, load_prompt
from app.features.applicant_match.resume import ResumeText
from app.llm.client import CallContext, ChatLLM, call_with_retry


@dataclass
class VRole:
    title: str
    company: str | None
    start: str | None
    end: str | None
    first: int  # position in resume.lines
    last: int
    interval: tuple[date, date] | None
    approximate: bool


@dataclass
class VProfile:
    roles: list[VRole] = field(default_factory=list)
    education: list[dict[str, Any]] = field(default_factory=list)
    education_level: str | None = None
    certifications: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    location: str | None = None
    flags: list[str] = field(default_factory=list)

    def role_at(self, pos: int) -> VRole | None:
        return next((r for r in self.roles if r.first <= pos <= r.last), None)


def _norm(s: str) -> str:
    return " ".join("".join(ch if ch.isalnum() else " " for ch in fold(s)).split())


def _in(text: str | None, haystack: str) -> bool:
    return not text or _norm(text) in _norm(haystack)


def resume_prompt_text(resume: ResumeText, max_chars: int) -> tuple[str, bool]:
    out: list[str] = []
    used = 0
    for ln in resume.lines:
        row = f"{ln.id} {ln.text}"
        if used + len(row) > max_chars:
            return "\n".join(out), True
        out.append(row)
        used += len(row) + 1
    return "\n".join(out), False


def verify(parsed: dict[str, Any], resume: ResumeText, as_of: date, levels: list[str]) -> tuple[VProfile, list[str]]:
    """Returns the verified profile and the problems found (used as the repair hint)."""
    pos = {ln.id: i for i, ln in enumerate(resume.lines)}
    lines = resume.lines
    prof = VProfile()
    problems: list[str] = []

    for i, r in enumerate(parsed.get("roles", [])):
        title = " ".join((r.get("title") or "").split())
        a, b = pos.get(r.get("first_line", "")), pos.get(r.get("last_line", ""))
        if a is None or b is None:
            problems.append(f"role '{title}': first_line/last_line must be existing line ids")
            prof.flags.append(f"role_unverified:{i + 1}")
            continue
        if a > b:
            a, b = b, a
        block = " ".join(ln.text for ln in lines[a:b + 1])
        if not title or not _in(title, block):
            problems.append(f"role '{title}': the title is not written in lines {lines[a].id}-{lines[b].id}")
            prof.flags.append(f"role_unverified:{i + 1}")
            continue
        company = " ".join((r.get("company") or "").split()) or None
        if company and not _in(company, block):
            company = None
        start_txt, end_txt = r.get("start"), r.get("end")
        if (start_txt and not _in(start_txt, block)) or (end_txt and not _in(end_txt, block)):
            problems.append(f"role '{title}': start/end must be copied from lines {lines[a].id}-{lines[b].id}")
        s = parse_date(start_txt, end=False, as_of=as_of)
        e = parse_date(end_txt, end=True, as_of=as_of)
        interval = None
        approximate = False
        if s and e and min(e.value, as_of) > s.value:
            interval = (s.value, min(e.value, as_of))  # future end dates count up to as_of only
            approximate = s.approximate or e.approximate
            if approximate:
                prof.flags.append("date_approximate")
        else:
            prof.flags.append(f"date_unparsed:{i + 1}")
        prof.roles.append(VRole(title=title, company=company, start=start_txt, end=end_txt, first=a, last=b,
                                interval=interval, approximate=approximate))

    ranges = sorted((r.first, r.last) for r in prof.roles)
    if any(ranges[k][1] >= ranges[k + 1][0] for k in range(len(ranges) - 1)):
        problems.append("role blocks overlap: each line belongs to at most one role")

    def cited(items: list[dict[str, Any]], what: str) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        for it in items:
            lid, text = it.get("line", ""), " ".join((it.get("text") or "").split())
            if lid not in pos or not text:
                problems.append(f"{what} '{text}': cite an existing line id")
            elif not _in(text, lines[pos[lid]].text):
                problems.append(f"{what} '{text}': not written in line {lid}")
            else:
                out.append((lid, text))
        return out

    for lid, text in cited(parsed.get("education", []), "education"):
        found = education_levels_in(lines[pos[lid]].text)
        prof.education.append({"line": lid, "text": text, "level": found[0] if found else None})
    found_levels = [e["level"] for e in prof.education if e["level"]]
    if found_levels:
        prof.education_level = max(found_levels, key=levels.index)
    prof.certifications = list(dict.fromkeys(t for _, t in cited(parsed.get("certifications", []), "certification")))
    prof.languages = list(dict.fromkeys(t for _, t in cited(parsed.get("languages", []), "language")))
    loc = parsed.get("location")
    if loc:
        got = cited([loc], "location")
        prof.location = got[0][1] if got else None
    prof.flags = list(dict.fromkeys(prof.flags))
    return prof, problems


async def extract_profile(resume: ResumeText, llm: ChatLLM, ctx: CallContext, settings: Settings, mp: MatchPolicy,
                          as_of: date, resume_text: str) -> VProfile:
    tpl = load_prompt("profile")
    schema = profile_schema()
    max_tokens = mp.settings["llm"]["profile_max_tokens"]
    levels = mp.settings["education_levels"]
    system, user = tpl.render(resume=resume_text, repair=None)
    res = await call_with_retry(llm, ctx, settings, "match_profile", tpl.version, system, user, schema, max_tokens)
    prof, problems = verify(res.parsed, resume, as_of, levels)
    if problems:
        ctx.repairs += 1
        system, user = tpl.render(resume=resume_text, repair="; ".join(problems[:8]))
        res = await call_with_retry(llm, ctx, settings, "match_profile", tpl.version, system, user, schema,
                                    max_tokens)
        prof, problems = verify(res.parsed, resume, as_of, levels)
        if problems:
            prof.flags.append("profile_citations_unverified")
    return prof


def total_years(prof: VProfile) -> float | None:
    return years_of([r.interval for r in prof.roles if r.interval])
