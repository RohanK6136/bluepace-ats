import { useMemo, useState } from "react";

const cleanList = (value) => (Array.isArray(value) ? value : []).filter(Boolean);

function EvidenceRow({ title, detail, status = "found", source = "Resume-derived" }) {
  const tone = status === "found"
    ? "border-emerald-200 bg-emerald-50 text-emerald-900"
    : status === "unknown"
      ? "border-amber-200 bg-amber-50 text-amber-950"
      : "border-slate-200 bg-slate-50 text-slate-800";
  return (
    <div className={`rounded-lg border p-3 ${tone}`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <p className="text-sm font-semibold">{title}</p>
        <span className="rounded-full border border-current/20 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide">
          {status === "found" ? "Evidence found" : status === "unknown" ? "Not established" : "Review"}
        </span>
      </div>
      {detail && <p className="mt-1 text-xs leading-5 opacity-90">{detail}</p>}
      <p className="mt-2 text-[10px] font-medium uppercase tracking-wide opacity-70">Source: {source}</p>
    </div>
  );
}

/**
 * Makes the existing role-fit result auditable without changing the underlying
 * score. Resume-derived claims are deliberately not labelled as independently
 * verified facts.
 */
export default function EvidenceReviewPanel({ analysis }) {
  const [showAll, setShowAll] = useState(false);
  const [copiedQuestion, setCopiedQuestion] = useState(false);

  const matchedSkills = cleanList(analysis?.matched_skills);
  const gaps = cleanList(analysis?.missing_skills || analysis?.skill_gaps);
  const experience = cleanList(analysis?.experience);
  const projects = cleanList(analysis?.projects);
  const explanations = cleanList(analysis?.explanations);
  const scoreBreakdown = analysis?.score_breakdown && typeof analysis.score_breakdown === "object" ? analysis.score_breakdown : {};
  const scoreWeights = analysis?.score_weights && typeof analysis.score_weights === "object" ? analysis.score_weights : {};
  const matchEvidence = analysis?.match_evidence && typeof analysis.match_evidence === "object" ? analysis.match_evidence : {};
  const sourceLineText = (sources) => cleanList(sources).flatMap((source) => cleanList(source?.source_lines)).filter((line) => Number.isFinite(Number(line))).map((line) => `line ${line}`).join(", ");
  const scoreLabels = {
    required_skill_coverage: "Required skills",
    preferred_skill_coverage: "Preferred skills",
    experience_alignment: "Experience",
    education_alignment: "Education",
    location_alignment: "Location",
    work_mode_alignment: "Work mode",
    project_evidence: "Project evidence",
    semantic_similarity: "Semantic similarity",
  };
  const scoreRows = Object.keys(scoreLabels).filter((key) => Number.isFinite(Number(scoreBreakdown[key])));
  const skillEvidenceRows = [
    ...cleanList(matchEvidence.required_skills).map((item) => ({ ...item, category: "Required skill" })),
    ...cleanList(matchEvidence.preferred_skills).map((item) => ({ ...item, category: "Preferred skill" })),
  ];
  const projectEvidenceRows = cleanList(matchEvidence.projects);
  const evidenceItems = useMemo(() => [
    ...skillEvidenceRows.map((item) => ({
      title: `${item.category}: ${item.skill || "Skill"}`,
      detail: sourceLineText(item.sources) ? `Source reference: ${sourceLineText(item.sources)}. Check the original resume before treating this as verified.` : "The matcher found this skill in parsed resume content, but a precise source-line reference is unavailable.",
      source: "Parsed resume content (not independently verified)",
    })),
    ...projectEvidenceRows.map((item) => ({
      title: item.project || "Relevant project",
      detail: [cleanList(item.matched_required_skills).length ? `Matched terms: ${item.matched_required_skills.join(", ")}.` : "", item.excerpt || ""].filter(Boolean).join(" "),
      source: "Parsed project text",
    })),
    ...experience.map((item) => ({
      title: item?.title || "Relevant experience",
      detail: item?.details || "Experience was extracted from the resume; review the original document to confirm context.",
      source: "Resume-derived experience",
    })),
    ...projects.map((item) => ({
      title: typeof item === "string" ? item : (item?.title || "Relevant project"),
      detail: typeof item === "string" ? "Project mentioned in the parsed resume." : (item?.details || "Project details were parsed from the resume."),
      source: "Resume-derived project",
    })),
  ], [experience, projects, skillEvidenceRows.length, projectEvidenceRows.length]);

  const primaryGap = gaps[0];
  const followUpQuestion = primaryGap
    ? `Could you walk us through a specific example of using ${primaryGap} in a project or work setting, including your contribution and the outcome?`
    : "Could you walk us through one relevant project, your individual contribution, and how you measured its outcome?";

  const copyQuestion = async () => {
    try {
      await navigator.clipboard.writeText(followUpQuestion);
      setCopiedQuestion(true);
      window.setTimeout(() => setCopiedQuestion(false), 1800);
    } catch {
      setCopiedQuestion(false);
    }
  };

  const visibleEvidence = showAll ? evidenceItems : evidenceItems.slice(0, 4);

  return (
    <section className="mt-5 rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-700 dark:bg-slate-900">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-3xl">
          <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-blue-700 dark:text-blue-300">Explainability & evidence</p>
          <h5 className="mt-1 text-base font-semibold text-slate-900 dark:text-slate-100">What supports this match?</h5>
          <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">
            This view exposes the resume-derived signals behind the existing score. It does not independently verify a skill or predict job performance.
          </p>
        </div>
        <span className="rounded-full border border-amber-300 bg-amber-50 px-2.5 py-1 text-[11px] font-semibold text-amber-900">Recruiter review required</span>
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-3">
        <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-700">
          <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">Skills identified</p>
          <p className="mt-1 text-2xl font-semibold text-slate-900 dark:text-slate-100">{matchedSkills.length}</p>
          <p className="mt-1 text-xs text-slate-500">Resume claims, not verified competencies</p>
        </div>
        <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-700">
          <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">Requirements to clarify</p>
          <p className="mt-1 text-2xl font-semibold text-slate-900 dark:text-slate-100">{gaps.length}</p>
          <p className="mt-1 text-xs text-slate-500">Missing evidence is not proof of missing ability</p>
        </div>
        <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-700">
          <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">Experience / project records</p>
          <p className="mt-1 text-2xl font-semibold text-slate-900 dark:text-slate-100">{evidenceItems.length}</p>
          <p className="mt-1 text-xs text-slate-500">Parsed items that can be checked against the CV</p>
        </div>
      </div>

      {scoreRows.length > 0 && (
        <div className="mt-4 rounded-lg border border-slate-200 p-3 dark:border-slate-700">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h6 className="text-xs font-semibold uppercase tracking-wide text-slate-500">How the score is composed</h6>
            <span className="text-[10px] text-slate-500">Current model components and weights</span>
          </div>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            {scoreRows.map((key) => {
              const score = Math.max(0, Math.min(100, Number(scoreBreakdown[key])));
              const weight = Number(scoreWeights[key]);
              return (
                <div key={key}>
                  <div className="flex items-center justify-between gap-2 text-xs">
                    <span className="font-medium text-slate-700 dark:text-slate-200">{scoreLabels[key]}</span>
                    <span className="tabular-nums text-slate-600 dark:text-slate-300">{score}%{Number.isFinite(weight) ? ` · ${Math.round(weight * 100)}% weight` : ""}</span>
                  </div>
                  <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
                    <div className="h-full rounded-full bg-slate-500" style={{ width: `${score}%` }} />
                  </div>
                </div>
              );
            })}
          </div>
          <p className="mt-3 text-[10px] leading-5 text-slate-500">Component percentages describe the current matching model, not a probability of success or a verified measure of job performance.</p>
        </div>
      )}

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <div>
          <h6 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Evidence identified</h6>
          <div className="mt-2 grid gap-2">
            {matchedSkills.length > 0 ? (
              <EvidenceRow title={`Skills listed: ${matchedSkills.slice(0, 8).join(", ")}`} detail="These skills were identified by the current matching process. Check the original resume for the context, depth, and recency of use." source="Parsed resume / matching output" />
            ) : (
              <EvidenceRow title="No structured skills returned" detail="The parser did not return structured skill evidence for this profile. Inspect the original resume before drawing a conclusion." status="unknown" source="Matching output" />
            )}
            {visibleEvidence.map((item, index) => <EvidenceRow key={`${item.title}-${index}`} title={item.title} detail={item.detail} source={item.source} />)}
            {evidenceItems.length > 4 && (
              <button type="button" onClick={() => setShowAll((value) => !value)} className="self-start text-xs font-semibold text-blue-700 underline dark:text-blue-300">
                {showAll ? "Show fewer evidence items" : `Show all ${evidenceItems.length} evidence items`}
              </button>
            )}
            {explanations.slice(0, 3).map((item, index) => <p key={index} className="rounded-lg bg-slate-50 p-3 text-xs leading-5 text-slate-700 dark:bg-slate-800 dark:text-slate-200">{item}</p>)}
          </div>
        </div>

        <div>
          <h6 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Unknowns and verification</h6>
          <div className="mt-2 grid gap-2">
            {gaps.length > 0 ? gaps.slice(0, 8).map((gap) => (
              <EvidenceRow key={gap} title={gap} detail="The current profile does not show enough evidence to confirm this requirement. Ask a consistent, job-related follow-up question." status="unknown" source="No supporting match evidence returned" />
            )) : (
              <EvidenceRow title="No explicit skill gaps returned" detail="This means the current matcher did not report a gap; it does not establish that every requirement has been verified." status="review" source="Matching output" />
            )}
          </div>
          <div className="mt-3 rounded-lg border border-blue-200 bg-blue-50 p-3 dark:border-blue-900 dark:bg-blue-950/40">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-blue-800 dark:text-blue-200">Suggested structured follow-up</p>
            <p className="mt-2 text-sm leading-6 text-slate-800 dark:text-slate-100">{followUpQuestion}</p>
            <button type="button" onClick={copyQuestion} className="mt-3 rounded-md border border-blue-300 px-3 py-1.5 text-xs font-semibold text-blue-800 hover:bg-blue-100 dark:text-blue-200 dark:hover:bg-blue-900">
              {copiedQuestion ? "Copied" : "Copy question"}
            </button>
          </div>
        </div>
      </div>

      <p className="mt-4 border-t border-slate-200 pt-3 text-[11px] leading-5 text-slate-500 dark:border-slate-700">
        Governance note: use the score as decision support only. Review the source evidence, ask consistent role-related questions, document the human decision, and never interpret absent resume evidence as proof that a candidate lacks a skill.
      </p>
    </section>
  );
}
