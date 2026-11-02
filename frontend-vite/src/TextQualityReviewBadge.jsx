/**
 * Text-quality review badge for candidate/application surfaces.
 * Shows observable signals only — never an AI-vs-human verdict.
 */
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

export default function TextQualityReviewBadge({ profile, review: reviewProp, compact = false, className = "" }) {
  const review = reviewProp || textQualityReviewFromProfile(profile);
  const meta = textQualityBadgeMeta(review);
  if (!meta) return null;

  if (compact) {
    return (
      <span
        className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-semibold ${meta.tone} ${className}`.trim()}
        title={meta.detail}
      >
        {meta.label}
      </span>
    );
  }

  return (
    <div className={`rounded-xl border px-3 py-2 ${meta.tone} ${className}`.trim()}>
      <p className="text-xs font-semibold">{meta.label}</p>
      <p className="mt-1 text-[11px] leading-4 opacity-90">{meta.detail}</p>
      <p className="mt-1 text-[10px] opacity-70">Authorship assessment: undetermined · not used for auto-reject</p>
    </div>
  );
}
