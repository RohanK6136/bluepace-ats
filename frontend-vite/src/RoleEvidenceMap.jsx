import { useMemo, useState } from "react";
import { buildRoleEvidenceMap } from "./roleEvidenceMap.mjs";

const statusStyles = {
  located: "border-emerald-200 bg-emerald-50 text-emerald-800",
  verify: "border-amber-200 bg-amber-50 text-amber-900",
};

function StatusLabel({ status }) {
  return (
    <span className={"inline-flex rounded-full border px-2 py-1 text-[10px] font-semibold uppercase tracking-wide " + statusStyles[status]}>
      {status === "located" ? "Evidence located" : "Needs clarification"}
    </span>
  );
}

function EvidenceRow({ item }) {
  return (
    <article className="rounded-lg border border-ink-100 bg-white p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <h5 className="text-sm font-semibold text-ink-900">{item.label}</h5>
        <StatusLabel status={item.status} />
      </div>
      <p className="mt-2 text-xs leading-5 text-ink-600">{item.explanation}</p>
      {item.sourceLines.length > 0 && (
        <p className="mt-2 text-[11px] font-medium text-ink-500">Resume source lines: {item.sourceLines.join(", ")}</p>
      )}
      {item.projectReferences.length > 0 && (
        <div className="mt-3 grid gap-2">
          {item.projectReferences.map((project, index) => (
            <div key={project.title + "-" + index} className="rounded-md bg-ink-50 p-2">
              <p className="text-[11px] font-semibold text-ink-700">Project reference · {project.title}</p>
              {project.excerpt && <p className="mt-1 text-xs leading-5 text-ink-600">{project.excerpt}</p>}
            </div>
          ))}
        </div>
      )}
      {item.status === "verify" && (
        <p className="mt-2 text-[11px] font-medium text-amber-800">Follow up before recording a conclusion.</p>
      )}
    </article>
  );
}

export default function RoleEvidenceMap({ analysis, onNotice }) {
  const [copied, setCopied] = useState(false);
  const model = useMemo(() => buildRoleEvidenceMap(analysis), [analysis]);

  async function copyQuestions() {
    if (!model.followUpQuestions.length) return;
    const text = model.followUpQuestions.map((question, index) => (index + 1) + ". " + question).join("\n");
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      onNotice?.("Evidence follow-up questions copied.");
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      onNotice?.(text);
    }
  }

  function openCandidateQuestions() {
    const target = document.getElementById("candidate-questions");
    if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
    else onNotice?.("Use the Candidate questions section in this profile to publish a follow-up.");
  }

  return (
    <section className="mt-5 rounded-xl border border-ink-100 bg-[#fafaf8] p-4 sm:p-5" aria-labelledby="role-evidence-map-title">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-blue-700">Evidence trace</p>
          <h4 id="role-evidence-map-title" className="mt-1 text-lg font-semibold text-ink-950">Role Evidence Map</h4>
          <p className="mt-1 max-w-3xl text-xs leading-5 text-ink-600">A requirement-by-requirement view of what the parsed profile supports and what still needs a conversation.</p>
        </div>
        <div className="rounded-lg border border-ink-100 bg-white px-3 py-2 text-right">
          <p className="text-[10px] font-semibold uppercase tracking-wide text-ink-500">Requirements supported</p>
          <p className="mt-0.5 text-xl font-semibold tabular-nums text-ink-950">{model.coverage.supported}<span className="text-sm font-medium text-ink-400"> / {model.coverage.total}</span></p>
        </div>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1.5fr)_minmax(250px,1fr)]">
        <div>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h5 className="text-xs font-semibold uppercase tracking-wide text-ink-600">Required skill evidence</h5>
            <span className="text-[11px] text-ink-500">{model.coverage.percent}% located in parsed fields</span>
          </div>
          {model.requirements.length ? (
            <div className="mt-2 grid gap-2 sm:grid-cols-2">
              {model.requirements.map((item) => <EvidenceRow key={item.id} item={item} />)}
            </div>
          ) : (
            <p className="mt-2 rounded-lg border border-ink-100 bg-white p-3 text-sm text-ink-500">No structured required-skill list was returned for this assessment. Review the job requirements before drawing conclusions.</p>
          )}
        </div>

        <aside className="grid content-start gap-3">
          {model.experience && (
            <div className="rounded-lg border border-ink-100 bg-white p-3">
              <div className="flex items-center justify-between gap-2">
                <h5 className="text-xs font-semibold uppercase tracking-wide text-ink-600">Experience context</h5>
                <StatusLabel status={model.experience.status} />
              </div>
              <p className="mt-2 text-sm font-semibold text-ink-900">
                {model.experience.parsedYears === null ? "Not reliably parsed" : model.experience.parsedYears + " years parsed"}
                {model.experience.requiredYears !== null ? " · " + model.experience.requiredYears + " years requested" : ""}
              </p>
              <p className="mt-1 text-xs leading-5 text-ink-600">{model.experience.explanation}</p>
            </div>
          )}
          {model.education && (
            <div className="rounded-lg border border-ink-100 bg-white p-3">
              <div className="flex items-center justify-between gap-2">
                <h5 className="text-xs font-semibold uppercase tracking-wide text-ink-600">Education context</h5>
                <StatusLabel status={model.education.status} />
              </div>
              <p className="mt-2 text-sm font-medium text-ink-900">Role requirement: {model.education.required}</p>
              <p className="mt-1 text-xs leading-5 text-ink-600">{model.education.explanation}</p>
            </div>
          )}
          <div className="rounded-lg border border-blue-100 bg-blue-50/60 p-3">
            <p className="text-xs font-semibold text-blue-900">How to use this map</p>
            <p className="mt-1 text-xs leading-5 text-blue-900">“Evidence located” means a matching field or reference was found. “Needs clarification” means the parser did not establish it. Neither label is a hiring decision.</p>
          </div>
        </aside>
      </div>

      <div className="mt-4 border-t border-ink-100 pt-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h5 className="text-sm font-semibold text-ink-900">Suggested recruiter follow-ups</h5>
            <p className="mt-1 text-xs text-ink-500">Questions are drafted from unverified criteria. Review them before using them with a candidate.</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="button" className="rounded-md border border-ink-200 bg-white px-3 py-2 text-xs font-semibold text-ink-700 hover:bg-ink-50" onClick={openCandidateQuestions}>Open candidate questions</button>
            <button type="button" className="rounded-md bg-[#c49a4a] px-3 py-2 text-xs font-semibold text-[#10131c] hover:bg-[#d4b06a] disabled:cursor-not-allowed disabled:opacity-50" onClick={copyQuestions} disabled={!model.followUpQuestions.length}>{copied ? "Copied" : "Copy questions"}</button>
          </div>
        </div>
        {model.followUpQuestions.length ? (
          <ol className="mt-3 grid gap-2 sm:grid-cols-2">
            {model.followUpQuestions.map((question, index) => <li key={index} className="rounded-lg border border-ink-100 bg-white p-3 text-xs leading-5 text-ink-700"><span className="mr-2 font-semibold text-ink-400">{index + 1}.</span>{question}</li>)}
          </ol>
        ) : (
          <p className="mt-3 rounded-lg border border-emerald-100 bg-white p-3 text-xs text-ink-600">No follow-up questions were generated from the available structured fields. Continue with the normal recruiter review.</p>
        )}
      </div>
    </section>
  );
}
