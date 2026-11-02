/** Shared deterministic metadata helpers for the text-quality review badge. */

export function textQualityReviewFromProfile(profile) {
  const review = profile?.text_quality_review;
  if (!review || typeof review !== "object") return null;
  return review;
}

export function textQualityBadgeMeta(review) {
  if (!review) return null;
  const status = review.status || "unknown";
  if (status === "review_recommended") {
    return {
      label: "Text quality · review",
      tone: "border-amber-200 bg-amber-50 text-amber-900",
      detail: (review.signals || []).map((s) => s.label).filter(Boolean).slice(0, 3).join(" · ") || "Observable text signals flagged for human review",
    };
  }
  if (status === "insufficient_evidence") {
    return {
      label: "Text quality · limited sample",
      tone: "border-slate-200 bg-slate-50 text-slate-700",
      detail: "Not enough extracted text for a meaningful review",
    };
  }
  if (status === "no_text_quality_alerts") {
    return {
      label: "Text quality · clear",
      tone: "border-emerald-200 bg-emerald-50 text-emerald-900",
      detail: "No repetition or generic-phrase alerts",
    };
  }
  return {
    label: "Text quality",
    tone: "border-ink-100 bg-ink-50 text-ink-700",
    detail: String(status),
  };
}

