/**
 * Text-quality review badge for candidate/application surfaces.
 * Shows observable signals only — never an AI-vs-human verdict.
 */
import { textQualityBadgeMeta, textQualityReviewFromProfile } from "./textQualityReviewUtils.js";

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
