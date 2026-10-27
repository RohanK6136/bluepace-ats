"""Job → rubric. The model only splits requirement lines into atomic items and names a type and group; code
checks every label is copied from its line, sets importance from the section, aliases from the taxonomy,
min_years and the education minimum from the line text, and freezes saved versions with a SHA-256 hash.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.config import Settings
from app.core.hashing import canonical_json, sha256_hex
from app.core.ingest import ingest_text
from app.features.applicant_match.llm_schemas import rubric_schema
from app.features.applicant_match.models import (
    CompileNote,
    EducationRequirement,
    JobLine,
    Rubric,
    RubricItem,
    Weights,
)
from app.features.applicant_match.policy import MatchPolicy, education_levels_in, fold, load_prompt
from app.features.jd_standardizer.pipeline.assemble import source_items
from app.features.jd_standardizer.pipeline.candidates import find_candidates
from app.features.jd_standardizer.pipeline.clean import clean
from app.features.jd_standardizer.pipeline.generate import title_guess
from app.features.jd_standardizer.pipeline.models import Overrides
from app.features.jd_standardizer.pipeline.policy import Policy
from app.features.jd_standardizer.pipeline.segment import segment
from app.features.jd_standardizer.pipeline.validate import validate
from app.llm.client import CallContext, ChatLLM, call_with_retry

YEARS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*\+?\s*(?:(?:-|–|to)\s*\d+(?:\.\d+)?\s*)?\+?\s*(?:years?|yrs?)\b", re.I)
OVERALL_YEARS_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*\+?\s*(?:(?:-|–|to)\s*\d+(?:\.\d+)?\s*)?\+?\s*(?:years?|yrs?)\s+(?:of\s+)?"
    r"(?:\w+\s+){0,3}?experience", re.I)
YEARS_ONLY_LABEL_RE = re.compile(r"^(?:\d|years?\b|experience\b|relevant experience|work experience)", re.I)


class JobError(ValueError):
    """The job input cannot produce a rubric (unknown run, several JDs, no text)."""


@dataclass
class JobSource:
    title: str | None
    lines: list[JobLine]
    required_years: float | None
    job_ref: str
    notes: list[CompileNote] = field(default_factory=list)


# ------------------------------------------------------------------ job inputs
def _number(entries: list[tuple[str, str, str]]) -> list[JobLine]:
    seen: set[str] = set()
    out: list[JobLine] = []
    for section, text, origin in entries:
        key = fold(text)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(JobLine(id=f"J{len(out) + 1:02d}", section=section, text=" ".join(text.split()),  # type: ignore[arg-type]
                           origin=origin))
    return out


def job_from_result(result: dict[str, Any], run_id: str) -> JobSource:
    """A stored JD Standardizer result (fast or strict mode)."""
    entries: list[tuple[str, str, str]] = []
    for sec in result.get("sections") or []:
        section = {"requirements": "must", "nice_to_have": "nice"}.get(sec.get("id", ""))
        if section:
            entries += [(section, it["text"], it.get("origin", "source")) for it in sec.get("items", [])]
    fields = result.get("fields") or {}
    title = (result.get("title") or {}).get("text") if isinstance(result.get("title"), dict) else None
    title = title or (fields.get("title") or {}).get("value")
    exp = (fields.get("experience") or {}).get("value") or {}
    years = exp.get("min_years") if isinstance(exp, dict) else None
    return JobSource(title=title, lines=_number(entries), required_years=years, job_ref=run_id)


def job_from_text(text: str, jd_policy: Policy, settings: Settings) -> JobSource:
    """Pasted JD text, parsed with the JD Standardizer's rule stages (no model call)."""
    cleaned = clean(ingest_text(text), jd_policy, settings)
    if cleaned.split_hints:
        raise JobError("more than one job description detected; paste one at a time")
    seg = segment(cleaned, jd_policy, settings)
    v = validate(cleaned, seg, find_candidates(cleaned, seg, jd_policy), None, Overrides(), jd_policy, settings)
    lines = {ln.id: ln for ln in cleaned.lines}
    entries = [("must", i.text, "source") for i in source_items("requirements", v.blocks, lines, "light")]
    entries += [("nice", i.text, "source") for i in source_items("nice_to_have", v.blocks, lines, "light")]
    notes: list[CompileNote] = []
    if not entries:  # no requirements heading: use unheaded bullets, and say so
        unheaded = [b for b in v.blocks if b.section == "unclassified" and b.kind == "bullet"]
        entries = [("must", b.text, "source") for b in unheaded]
        notes.append(CompileNote(code="no_requirements_heading", message=(
            "No Requirements / Qualifications heading found. " + (
                "Unheaded bullet lines were used as must-haves; review them." if entries else
                "Add requirement items by hand, or run the text through JD Standardizer first."))))
    title_fact = v.fields.get("title")
    title = title_fact.value if title_fact and title_fact.value else title_guess(cleaned, v)
    exp = (v.fields.get("experience").value if v.fields.get("experience") else None) or {}
    years = exp.get("min_years") if isinstance(exp, dict) else None
    return JobSource(title=title, lines=_number(entries), required_years=years,
                     job_ref=f"text:{sha256_hex(text)[:12]}", notes=notes)


# ------------------------------------------------------------------ deterministic rules
def education_requirement(lines: list[JobLine], mp: MatchPolicy) -> EducationRequirement:
    """The lowest level named on the first must-have degree line ("Bachelor's or Master's" → bachelor)."""
    equiv = re.compile("|".join(re.escape(p) for p in mp.settings["equivalent_experience_patterns"]), re.I)
    for ln in lines:
        if ln.section == "must" and (found := education_levels_in(ln.text)):
            return EducationRequirement(min_level=found[-1], equivalent_experience_ok=bool(equiv.search(ln.text)),  # type: ignore[arg-type]
                                        source_line=ln.id)
    return EducationRequirement()


def is_education_label(label: str, mp: MatchPolicy) -> bool:
    return bool(education_levels_in(label))


def overall_years(lines: list[JobLine]) -> float | None:
    for ln in lines:
        if ln.section == "must" and (m := OVERALL_YEARS_RE.search(ln.text)):
            return float(m.group(1))
    return None


def item_min_years(label: str, line: str) -> float | None:
    """Years stated for this item in its own clause: "3+ years of Python", "Python (2 years)"."""
    for clause in re.split(r"[;.]\s|\s[–—]\s", line):
        if fold(label) in fold(clause) and (m := YEARS_RE.search(clause)) and "experience" not in fold(label):
            return float(m.group(1))
    return None


def _contains(line: str, label: str) -> bool:
    norm = lambda s: re.sub(r"[\s\-]+", " ", fold(s)).strip(" .,;:()")  # noqa: E731
    return bool(norm(label)) and norm(label) in norm(line)


def build_items(raw_items: list[dict[str, Any]], lines: list[JobLine], mp: MatchPolicy,
                notes: list[CompileNote]) -> list[RubricItem]:
    by_id = {ln.id: ln for ln in lines}
    items: list[RubricItem] = []
    seen: set[str] = set()
    order = {ln.id: i for i, ln in enumerate(lines)}
    for raw in sorted(raw_items, key=lambda r: order.get(r.get("line", ""), 10**6)):
        ln = by_id.get(raw.get("line", ""))
        label = " ".join(str(raw.get("label", "")).split()).strip(" .,;:")
        if ln is None:
            notes.append(CompileNote(code="unknown_line",
                                     message=f"dropped '{label}': cites a line that does not exist"))
            continue
        if not _contains(ln.text, label):
            notes.append(CompileNote(code="label_not_in_line", line=ln.id,
                                     message=f"dropped '{label}': not written in the job line"))
            continue
        if YEARS_ONLY_LABEL_RE.match(label) or is_education_label(label, mp):
            continue  # overall years and degrees are handled by required_years / education
        if fold(label) in seen:
            continue
        seen.add(fold(label))
        entry = mp.lookup(label)
        typ = entry.type if entry else raw.get("type", "skill")
        group = (entry.group if entry and entry.group else raw.get("group", "other"))
        if entry:
            aliases = list(entry.aliases)
        elif typ == "other" or group == "soft" or len(label.split()) > 1:
            # fuzzy ("communication skills") or an unknown phrase ("endpoint management tooling") that a resume
            # would rarely repeat word for word: judged by the model with a cited, verified line
            aliases = []
        else:
            aliases = [label]  # an unknown single term ("Okta") is matched as written
        items.append(RubricItem(
            id=f"R{len(items) + 1:02d}", label=label, type=typ, group=group,
            importance="must" if ln.section == "must" else "nice", weight=1,
            min_years=item_min_years(label, ln.text), aliases=aliases, source_line=ln.id, source_text=ln.text))
    return items


# ------------------------------------------------------------------ compile + freeze
async def compile_rubric(job: JobSource, llm: ChatLLM, ctx: CallContext, settings: Settings,
                         mp: MatchPolicy) -> tuple[Rubric, list[CompileNote]]:
    notes = list(job.notes)
    cfg = mp.settings
    lines = job.lines[: cfg["llm"]["max_rubric_lines"]]
    if len(job.lines) > len(lines):
        notes.append(CompileNote(code="too_many_lines", message=f"only the first {len(lines)} requirement lines "
                                                                 "were split; add the rest by hand"))
    items: list[RubricItem] = []
    if lines:
        tpl = load_prompt("rubric_compile")
        system, user = tpl.render(title=job.title, lines=[{"id": ln.id, "text": ln.text[:300]} for ln in lines])
        res = await call_with_retry(llm, ctx, settings, "match_rubric", tpl.version, system, user,
                                    rubric_schema(), cfg["llm"]["rubric_max_tokens"])
        items = build_items(res.parsed.get("items", []), lines, mp, notes)
        covered = {it.source_line for it in items}
        for ln in lines:
            if ln.id not in covered and not OVERALL_YEARS_RE.search(ln.text) \
                    and not is_education_label(ln.text, mp):
                notes.append(CompileNote(code="line_without_items", line=ln.id,
                                         message=f"no item taken from: \"{ln.text}\" — add one if it matters"))
    w = cfg["weights"]
    rubric = Rubric(job_ref=job.job_ref, title=job.title, weights=Weights(**w),
                    required_years=job.required_years if job.required_years is not None else overall_years(lines),
                    education=education_requirement(lines, mp), items=items, job_lines=lines)
    return rubric, notes


def canonical_rubric(rubric: Rubric) -> Rubric:
    """Renumber items R01… in their current order (ids are positional)."""
    items = [it.model_copy(update={"id": f"R{i + 1:02d}"}) for i, it in enumerate(rubric.items)]
    return rubric.model_copy(update={"items": items, "rubric_id": None, "rubric_hash": None, "created_at": None})


def rubric_hash(rubric: Rubric) -> str:
    content = canonical_rubric(rubric).model_dump(mode="json", exclude={"rubric_id", "rubric_hash", "created_at"})
    return sha256_hex(canonical_json(content))


def freeze(rubric: Rubric, created_at: str) -> Rubric:
    if not rubric.items and rubric.required_years is None and rubric.education.min_level == "none":
        raise JobError("the rubric is empty: add at least one requirement, required years or an education minimum")
    labels = [fold(it.label) for it in rubric.items]
    if len(labels) != len(set(labels)):
        raise JobError("two items have the same label; merge them")
    c = canonical_rubric(rubric)
    h = rubric_hash(c)
    return c.model_copy(update={"rubric_id": f"rb_{h[:12]}", "rubric_hash": h, "created_at": created_at})
