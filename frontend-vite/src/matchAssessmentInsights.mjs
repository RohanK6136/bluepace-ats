const CATEGORY_ROWS = [
  ["required_skills", "Required skills"],
  ["experience", "Relevant experience"],
  ["preferred_skills", "Preferred skills"],
  ["education", "Education"],
];

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
      return { key, label, score: Math.max(0, Math.min(100, Number(score))), weight: Number.isFinite(Number(weight)) ? Number(weight) : null };
    })
    .filter(Boolean);
  return {
    strengths,
    gaps,
    breakdown,
    summary: result?.summary || null,
    match: scores.match == null ? null : Math.max(0, Math.min(100, Number(scores.match))),
  };
}
