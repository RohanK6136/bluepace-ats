const CATEGORY_ROWS = [
  ["required_skills", "Required skills"],
  ["experience", "Relevant experience"],
  ["preferred_skills", "Preferred skills"],
  ["education", "Education"],
];

function statusCounts(items) {
  const rows = Array.isArray(items) ? items : [];
  return {
    total: rows.length,
    met: rows.filter((item) => item?.status === "met").length,
    partial: rows.filter((item) => item?.status === "partial").length,
    unclear: rows.filter((item) => item?.status === "unclear").length,
    not_evidenced: rows.filter((item) => item?.status === "not_evidenced").length,
  };
}

function buildRecommendation(result, evidence, scores) {
  const match = scores?.match == null ? null : Math.max(0, Math.min(100, Number(scores.match)));
  const required = evidence.filter((item) => item?.importance === "must");
  const unconfirmedRequired = required.filter((item) => item?.status !== "met");
  if (result?.status === "manual" || match == null) {
    return {
      title: "Manual evidence review required",
      detail: result?.reason || "The assessment did not return a reliable numeric match score.",
      action: "Review the original resume and confirm the relevant experience and qualifications directly. Do not infer that missing information is a negative result.",
      tone: "warn",
    };
  }
  if (!required.length) {
    return {
      title: "Review rubric coverage",
      detail: "The rubric contains no criteria explicitly marked as must-have, so the score may not reflect the role's essential requirements.",
      action: "Review the rubric with the hiring manager and identify the genuinely essential, job-related requirements before comparing applicants.",
      tone: "warn",
    };
  }
  if (unconfirmedRequired.length) {
    return {
      title: "Verify must-have criteria",
      detail: `${unconfirmedRequired.length} of ${required.length} must-have criteria are not fully evidenced in the resume. This includes partial, unclear and not-evidenced items.`,
      action: "Use a consistent, structured screening question or request specific evidence for the outstanding requirements. Do not treat missing resume evidence as proof that the candidate lacks the skill.",
      tone: "warn",
    };
  }
  if (match >= 80) {
    return {
      title: "Strong evidence alignment",
      detail: `The weighted match is ${match}/100 and all ${required.length} must-have criteria are marked as met in the available resume evidence.`,
      action: "Prioritise a recruiter-led review and validate the cited experience, scope of work and role context before deciding on next steps.",
      tone: "good",
    };
  }
  if (match >= 60) {
    return {
      title: "Potential alignment",
      detail: `The weighted match is ${match}/100. Must-have criteria are evidenced, but the overall score indicates that other weighted areas need closer review.`,
      action: "Review the category breakdown and discuss role-specific depth, preferred skills and examples during a structured screen.",
      tone: "neutral",
    };
  }
  return {
    title: "Further evidence review recommended",
    detail: `The weighted match is ${match}/100. The score reflects the evidence available in this resume and is not a hiring decision.`,
    action: "Check whether the resume contains relevant work in another section or format, confirm that the rubric reflects the actual role, and gather additional evidence consistently before deciding.",
    tone: "warn",
  };
}

export function buildMatchAssessmentInsights(result) {
  const evidence = Array.isArray(result?.evidence) ? result.evidence : [];
  const strengths = evidence
    .filter((item) => item?.status === "met")
    .sort((a, b) => (a.importance === b.importance ? 0 : a.importance === "must" ? -1 : 1));
  const gaps = Array.isArray(result?.gaps)
    ? result.gaps
    : evidence.filter((item) => item?.status && item.status !== "met");
  const scores = result?.scores || {};
  const breakdown = CATEGORY_ROWS
    .map(([key, label]) => {
      const score = key === "experience"
        ? scores.experience?.pct
        : key === "education"
          ? scores.education?.pct
          : scores[key]?.pct;
      if (score == null || !Number.isFinite(Number(score))) return null;
      const weight = scores.weights_used?.[key];
      const counts = key === "required_skills" ? scores.required_skills
        : key === "preferred_skills" ? scores.preferred_skills : null;
      return {
        key, label,
        score: Math.max(0, Math.min(100, Number(score))),
        weight: Number.isFinite(Number(weight)) ? Number(weight) : null,
        detail: counts ? `${counts.met ?? 0} met · ${counts.partial ?? 0} partial · ${counts.total ?? 0} total` : "",
      };
    })
    .filter(Boolean);
  for (const group of Array.isArray(scores.groups) ? scores.groups : []) {
    if (group?.pct == null || !Number.isFinite(Number(group.pct))) continue;
    breakdown.push({
      key: `group:${group.name || group.label}`,
      label: group.label || group.name || "Requirement group",
      score: Math.max(0, Math.min(100, Number(group.pct))),
      weight: null,
      detail: `${group.met ?? 0} met · ${group.partial ?? 0} partial · ${group.total ?? 0} total`,
    });
  }
  const requiredEvidence = evidence.filter((item) => item?.importance === "must");
  const preferredEvidence = evidence.filter((item) => item?.importance === "nice");
  const match = scores.match == null ? null : Math.max(0, Math.min(100, Number(scores.match)));
  const counts = statusCounts(evidence);
  const requiredCounts = statusCounts(requiredEvidence);
  const preferredCounts = statusCounts(preferredEvidence);
  const evidenceCovered = counts.met + counts.partial + counts.unclear;
  return {
    strengths,
    gaps,
    breakdown,
    summary: result?.summary || null,
    match,
    counts,
    requiredCounts,
    preferredCounts,
    evidenceCoverage: counts.total ? Math.round((evidenceCovered / counts.total) * 100) : null,
    recommendation: buildRecommendation(result, evidence, scores),
    profile: result?.profile || {},
    scores,
  };
}
