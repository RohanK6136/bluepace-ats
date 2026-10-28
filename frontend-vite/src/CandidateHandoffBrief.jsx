import { useMemo, useState } from "react";

function clean(value) {
  return String(value ?? "").trim();
}

export default function CandidateHandoffBrief({ candidate, profile = {}, application, fitAnalysis, events = [] }) {
  const [copied, setCopied] = useState(false);
  const brief = useMemo(() => {
    const name = [candidate?.first_name, candidate?.last_name].map(clean).filter(Boolean).join(" ") || "Candidate";
    const skills = (profile.skills || []).filter(Boolean).slice(0, 12);
    const recentEvents = [...events].slice(0, 4);
    const gaps = (fitAnalysis?.missing_skills || fitAnalysis?.skill_gaps || []).filter(Boolean).slice(0, 8);
    const reviewSignals = (profile.resume_quality?.missing_fields || []).map((field) => `Confirm ${field}`).slice(0, 5);
    const lines = [
      `CANDIDATE HANDOFF · ${name}`,
      `Role: ${application?.job_title || "Select an application to add role context"}`,
      `Current stage: ${application?.stage_name || "Unknown"}`,
      `Contact: ${[candidate?.email, candidate?.phone].filter(Boolean).join(" · ") || "Not available"}`,
      `Experience: ${profile.years_of_experience != null ? `${profile.years_of_experience} years (resume parsed)` : "Not confirmed"}`,
      `Location: ${profile.current_location || "Not listed"}`,
      `Skills listed on resume: ${skills.length ? skills.join(", ") : "Not parsed"}`,
      fitAnalysis ? `Role-fit evidence: ${fitAnalysis.summary || fitAnalysis.fit || fitAnalysis.alignment || "Review the role-fit panel"}` : "Role-fit evidence: Not generated for this session",
      gaps.length ? `Requirements to verify: ${gaps.join(", ")}` : "Requirements to verify: Use the job description and interview kit",
      reviewSignals.length ? `Profile checks: ${reviewSignals.join("; ")}` : "Profile checks: No missing required fields flagged by the parser",
      "Recent ATS activity:",
      ...(recentEvents.length ? recentEvents.map((event) => `- ${event.title || event.type}${event.created_at ? ` (${new Date(event.created_at).toLocaleDateString()})` : ""}`) : ["- No recent activity recorded"]),
      "Use job-related evidence and the structured interview scorecard. Verify details with the candidate; this brief is a navigation aid, not a recommendation.",
    ];
    return lines.join("\n");
  }, [application, candidate, events, fitAnalysis, profile]);

  async function copyBrief() {
    try {
      await navigator.clipboard.writeText(brief);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      setCopied(false);
    }
  }

  return (
    <section className="mt-5 rounded-xl border border-blue-100 bg-blue-50/40 p-4 sm:p-5" aria-labelledby="handoff-brief-heading">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-blue-700">Team handoff</p>
          <h4 id="handoff-brief-heading" className="mt-1 font-semibold text-ink-950">Candidate handoff brief</h4>
          <p className="mt-1 max-w-2xl text-xs leading-5 text-ink-600">A concise, shareable brief from the ATS profile and current session. Confirm details with the candidate; it is not a hiring recommendation.</p>
        </div>
        <button type="button" className="inline-flex items-center justify-center rounded-md border border-ink-200 bg-white px-3 py-2 text-sm font-semibold text-ink-800 hover:bg-ink-50" onClick={copyBrief}>{copied ? "Copied" : "Copy brief"}</button>
      </div>
      <pre className="mt-4 max-h-64 overflow-auto whitespace-pre-wrap rounded-lg border border-ink-100 bg-white p-3 text-xs leading-5 text-ink-700">{brief}</pre>
    </section>
  );
}

