"""Requirement statuses and every number on the card. Pure code; the same inputs always give the same card.

Status values: met 1, partial 0.5, unclear 0 (flagged for the recruiter), not_evidenced 0.
- group score       Σ weight·value / Σ weight over the group's items
- required skills   same, over must-have skill / certification / language items
- preferred skills  same, over nice-to-have items
- experience        min(1, relevant years / required years); excluded when the rubric has no required years
- education         1 if the highest level meets the minimum; 0.5 if it does not but equivalent experience is
                    allowed and experience is 100%; else 0; excluded when the rubric has no minimum
- match             Σ category weight · category score / Σ included weights · 100
Percentages are whole numbers rounded half up. Unmet must-haves are gaps; they never knock a candidate out.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.features.applicant_match.dates import years_of
from app.features.applicant_match.judge import Judgment
from app.features.applicant_match.matcher import find_lines, is_negated
from app.features.applicant_match.models import (
    CountScore,
    EducationScore,
    Evidence,
    EvidenceLine,
    ExperienceScore,
    Gap,
    GroupScore,
    Rubric,
    RubricItem,
    Scores,
)
from app.features.applicant_match.policy import MatchPolicy
from app.features.applicant_match.profile import VProfile
from app.features.applicant_match.resume import ResumeText
from app.features.applicant_match.rounding import half_up, pct

SKILL_TYPES = ("skill", "certification", "language")
GAP_NOTES = {
    "not_evidenced": "not found in the resume",
    "unclear": "mentioned next to a negation (e.g. \"no\", \"learning\"); check the resume",
}


@dataclass
class Evaluation:
    evidence: list[Evidence]
    gaps: list[Gap]
    scores: Scores
    relevant_years: float | None
    total_years: float | None
    flags: list[str] = field(default_factory=list)


def judged_items(rubric: Rubric) -> list[RubricItem]:
    return [it for it in rubric.items if not it.aliases]


def _evaluate_item(it: RubricItem, resume: ResumeText, prof: VProfile, mp: MatchPolicy,
                   judgments: dict[str, Judgment] | None, flags: list[str]) -> Evidence:
    pos = {ln.id: i for i, ln in enumerate(resume.lines)}
    base = {"item_id": it.id, "label": it.label, "importance": it.importance, "group": it.group,
            "min_years": it.min_years}
    if it.aliases:
        hits = find_lines(it.aliases, resume.lines)
        clean = [ln for ln in hits if not is_negated(ln.text, mp.negations, it.aliases)]
        if not hits:
            return Evidence(**base, status="not_evidenced")
        if not clean:
            flags.append(f"unclear:{it.id}")
            return Evidence(**base, status="unclear", lines=[EvidenceLine(id=ln.id, text=ln.text) for ln in hits],
                            note=GAP_NOTES["unclear"])
        matched = clean
        strength = "role" if any(prof.role_at(pos[ln.id]) for ln in matched) else "listed"
    else:
        if judgments is None:
            flags.append(f"unclear:{it.id}")
            return Evidence(**base, status="unclear", note="the model could not be asked about this requirement")
        j = judgments.get(it.id)
        if j is None or j.status == "not_evidenced" or j.line is None:
            if j and j.note:
                flags.append(f"judge_unverified:{it.id}")
            return Evidence(**base, status="not_evidenced", note=j.note if j else None)
        matched = [ln for ln in resume.lines if ln.id == j.line]
        strength = "judged"
        if j.status == "partial":
            role = prof.role_at(pos[j.line])
            return Evidence(**base, status="partial", strength=strength,
                            lines=[EvidenceLine(id=ln.id, text=ln.text) for ln in matched],
                            source=role.company if role else None, note="related evidence only")

    roles: list = []
    for ln in matched:
        r = prof.role_at(pos[ln.id])
        if r is not None and all(r is not seen for seen in roles):
            roles.append(r)
    yrs = years_of([r.interval for r in roles if r.interval]) if roles else None
    status = "met"
    note = None
    if it.min_years is not None:
        if yrs is None or yrs < it.min_years:
            status = "partial"
            note = (f"{yrs:g} of {it.min_years:g} years in roles that mention it" if yrs is not None
                    else f"years not shown (needs {it.min_years:g})")
    return Evidence(**base, status=status, strength=strength, years=yrs,
                    lines=[EvidenceLine(id=ln.id, text=ln.text) for ln in matched],
                    source=roles[0].company if roles else None, note=note)


def _count(evs: list[Evidence], weights: dict[str, int], mp: MatchPolicy) -> tuple[CountScore, float | None]:
    values = mp.settings["status_values"]
    num = sum(weights[e.item_id] * values[e.status] for e in evs)
    den = sum(weights[e.item_id] for e in evs)
    score = CountScore(pct=pct(num, den), met=sum(e.status == "met" for e in evs),
                       partial=sum(e.status == "partial" for e in evs), total=len(evs))
    return score, (num / den if den else None)


def evaluate(rubric: Rubric, resume: ResumeText, prof: VProfile, mp: MatchPolicy,
             judgments: dict[str, Judgment] | None) -> Evaluation:
    flags: list[str] = []
    evidence = [_evaluate_item(it, resume, prof, mp, judgments, flags) for it in rubric.items]
    weights = {it.id: it.weight for it in rubric.items}
    by_id = {it.id: it for it in rubric.items}
    pos = {ln.id: i for i, ln in enumerate(resume.lines)}

    # experience: union of dated roles; relevant = roles holding evidence for at least one must-have skill,
    # certification or language (soft / judged items do not make a role relevant)
    total = years_of([r.interval for r in prof.roles if r.interval])
    relevant_roles = {id(r): r for e in evidence
                      if e.importance == "must" and e.status in ("met", "partial")
                      and by_id[e.item_id].type in SKILL_TYPES and by_id[e.item_id].aliases
                      for ln in e.lines if (r := prof.role_at(pos[ln.id]))}
    relevant = years_of([r.interval for r in relevant_roles.values() if r.interval]) if relevant_roles else None
    if total is not None and relevant is None:
        relevant = 0.0
    if prof.roles and total is None:
        flags.append("experience_undated")

    must_skills = [e for e in evidence if e.importance == "must" and by_id[e.item_id].type in SKILL_TYPES]
    required, req_frac = _count(must_skills, weights, mp)
    preferred, pref_frac = _count([e for e in evidence if e.importance == "nice"], weights, mp)
    groups: list[GroupScore] = []
    for gid, glabel in mp.settings["groups"].items():
        evs = [e for e in evidence if e.group == gid]
        if evs:
            c, _ = _count(evs, weights, mp)
            groups.append(GroupScore(name=gid, label=glabel, **c.model_dump()))

    exp_frac: float | None = None
    if rubric.required_years:
        exp_frac = min(1.0, (relevant or 0.0) / rubric.required_years)
    experience = ExperienceScore(pct=pct(exp_frac, 1) if exp_frac is not None else None, relevant_years=relevant,
                                 total_years=total, required_years=rubric.required_years)

    levels: list[str] = mp.settings["education_levels"]
    edu_frac: float | None = None
    need = rubric.education.min_level
    if need != "none":
        have = prof.education_level
        if have and levels.index(have) >= levels.index(need):
            edu_frac = 1.0
        elif rubric.education.equivalent_experience_ok and exp_frac == 1.0:
            edu_frac = 0.5
        else:
            edu_frac = 0.0
    education = EducationScore(pct=pct(edu_frac, 1) if edu_frac is not None else None,
                               level=prof.education_level, required=need if need != "none" else None)  # type: ignore[arg-type]

    cats = {"required_skills": req_frac, "experience": exp_frac, "preferred_skills": pref_frac,
            "education": edu_frac}
    w = rubric.weights.model_dump()
    used = {k: w[k] for k, frac in cats.items() if frac is not None and w[k] > 0}
    match = None
    if used:
        match = int(half_up(sum(used[k] * cats[k] for k in used) / sum(used.values()) * 100))  # type: ignore[operator]
    scores = Scores(match=match, required_skills=required, groups=groups, experience=experience,
                    preferred_skills=preferred, education=education, weights_used=used)

    gaps = [Gap(item_id=e.item_id, label=e.label, importance=e.importance, status=e.status,
                note=e.note or GAP_NOTES.get(e.status))
            for e in evidence if e.status != "met"]
    gaps.sort(key=lambda g: (g.importance != "must", g.item_id))
    return Evaluation(evidence=evidence, gaps=gaps, scores=scores, relevant_years=relevant, total_years=total,
                      flags=list(dict.fromkeys(flags)))
