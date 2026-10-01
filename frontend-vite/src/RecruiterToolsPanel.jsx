import { useEffect, useState } from "react";

const input = "w-full rounded-md border border-ink-100 bg-white px-3 py-2.5 text-sm text-ink-900 outline-none focus:border-gold-500 focus:ring-2 focus:ring-gold-100";
const primary = "inline-flex items-center justify-center rounded-md bg-[#1769d3] px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50";
const secondary = "inline-flex items-center justify-center rounded-md border border-ink-100 bg-white px-3 py-2 text-sm font-semibold text-ink-800 disabled:cursor-not-allowed disabled:opacity-50";

export default function RecruiterToolsPanel({
  token,
  candidates = [],
  applications = [],
  candidateId = null,
  compact = false,
  canWrite = true,
  apiRequest,
  onNotice,
  onError,
}) {
  const [selectedCandidateId, setSelectedCandidateId] = useState(candidateId ? String(candidateId) : "");
  const [tags, setTags] = useState([]);
  const [tagInput, setTagInput] = useState("");
  const [duplicates, setDuplicates] = useState([]);
  const [duplicateLoading, setDuplicateLoading] = useState(false);
  const [assistantApplicationId, setAssistantApplicationId] = useState("");
  const [assistantQuestion, setAssistantQuestion] = useState("Give me a factual summary of this application.");
  const [assistantResult, setAssistantResult] = useState(null);
  const [assistantLoading, setAssistantLoading] = useState(false);
  const [reportLoading, setReportLoading] = useState(false);
  const [recruitingUsers, setRecruitingUsers] = useState([]);
  const [collaboration, setCollaboration] = useState({ owner_id: "", starred: false, needs_review: false, priority: "normal" });

  useEffect(() => {
    const next = candidateId ? String(candidateId) : "";
    setSelectedCandidateId(next);
  }, [candidateId]);

  useEffect(() => {
    apiRequest(token, "get", "/recruiting-users")
      .then((response) => setRecruitingUsers(response.data || []))
      .catch(onError);
  }, [token]);

  useEffect(() => {
    if (!selectedCandidateId) {
      setTags([]);
      return undefined;
    }
    let active = true;
    apiRequest(token, "get", "/candidates/" + selectedCandidateId)
      .then((response) => {
        if (active) {
          setTags(response.data?.tags || []);
          setCollaboration({
            owner_id: response.data?.owner_id ? String(response.data.owner_id) : "",
            starred: Boolean(response.data?.starred),
            needs_review: Boolean(response.data?.needs_review),
            priority: response.data?.priority || "normal",
          });
        }
      })
      .catch((error) => { if (active) onError(error); });
    return () => { active = false; };
  }, [selectedCandidateId, token]);

  useEffect(() => {
    if (!assistantApplicationId && applications.length) {
      setAssistantApplicationId(String(applications[0].id));
    }
  }, [applications, assistantApplicationId]);

  async function saveTags(nextTags) {
    if (!selectedCandidateId || !canWrite) return;
    try {
      const response = await apiRequest(token, "patch", "/candidates/" + selectedCandidateId + "/tags", {
        data: { tags: nextTags },
      });
      setTags(response.data.tags || []);
      setTagInput("");
      onNotice("Candidate tags updated");
    } catch (error) { onError(error); }
  }

  async function addTag(event) {
    event.preventDefault();
    const value = tagInput.trim();
    if (!value || !selectedCandidateId) return;
    await saveTags([...tags, value]);
  }

  async function scanDuplicates() {
    setDuplicateLoading(true);
    try {
      const response = await apiRequest(token, "get", "/candidate-tools/duplicate-scan");
      setDuplicates(response.data?.duplicates || []);
      onNotice(response.data?.count ? `${response.data.count} possible duplicate pair(s) found` : "No possible duplicates found");
    } catch (error) { onError(error); }
    finally { setDuplicateLoading(false); }
  }

  async function mergeCandidates(keepId, duplicateId) {
    if (!canWrite) return;
    const keep = candidates.find((candidate) => candidate.id === keepId);
    const duplicate = candidates.find((candidate) => candidate.id === duplicateId);
    const keepLabel = keep ? `${keep.first_name} ${keep.last_name}` : "selected candidate";
    const duplicateLabel = duplicate ? `${duplicate.first_name} ${duplicate.last_name}` : "duplicate candidate";
    if (!window.confirm(`Merge ${duplicateLabel} into ${keepLabel}? The duplicate profile will be archived and non-conflicting applications will be moved.`)) return;
    try {
      const response = await apiRequest(token, "post", "/candidate-tools/candidates/merge", {
        data: { keep_candidate_id: keepId, duplicate_candidate_id: duplicateId },
      });
      setDuplicates((items) => items.filter((item) => !(
        (item.candidate_a.id === keepId && item.candidate_b.id === duplicateId) ||
        (item.candidate_a.id === duplicateId && item.candidate_b.id === keepId)
      )));
      onNotice(`Candidate merged. ${response.data.conflicting_applications || 0} conflicting application(s) were kept on the archived profile.`);
    } catch (error) { onError(error); }
  }

  async function runAssistant(event) {
    event.preventDefault();
    if (!assistantApplicationId) return;
    setAssistantLoading(true);
    try {
      const response = await apiRequest(token, "post", "/candidate-tools/applications/" + assistantApplicationId + "/assistant", {
        data: { question: assistantQuestion.trim() || "Give me a factual summary of this application." },
      });
      setAssistantResult(response.data);
    } catch (error) { onError(error); }
    finally { setAssistantLoading(false); }
  }

  async function downloadReport() {
    setReportLoading(true);
    try {
      const response = await apiRequest(token, "get", "/reports/recruitment.csv", { responseType: "blob" });
      const url = URL.createObjectURL(response.data);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "blupace-recruitment-report.csv";
      anchor.click();
      URL.revokeObjectURL(url);
      onNotice("Recruitment report downloaded");
    } catch (error) { onError(error); }
    finally { setReportLoading(false); }
  }

  const candidate = candidates.find((item) => item.id === Number(selectedCandidateId));
  const candidateApplications = applications.filter((item) => item.candidate_id === Number(selectedCandidateId));

  return (
    <section className={compact ? "mt-6 border-t border-ink-100 pt-5" : ""}>
      {!compact && (
        <div className="mb-5">
          <p className="text-sm text-ink-500">Candidate quality tools, duplicate control, recruiter assistant and reporting.</p>
          <h2 className="mt-1 text-xl font-semibold">Recruiter tools</h2>
        </div>
      )}

      <div className="grid gap-5 lg:grid-cols-2">
        <section className="rounded-xl border border-ink-100 bg-white p-5">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-blue-700">Candidate tags</p>
              <h3 className="mt-1 font-semibold">{candidate ? candidate.first_name + " " + candidate.last_name : "Organize candidate profiles"}</h3>
            </div>
            {!candidateId && (
              <select className={input + " max-w-sm"} value={selectedCandidateId} onChange={(event) => setSelectedCandidateId(event.target.value)}>
                <option value="">Select candidate…</option>
                {candidates.filter((item) => !item.archived).map((item) => (
                  <option key={item.id} value={item.id}>{item.first_name} {item.last_name} · {item.email}</option>
                ))}
              </select>
            )}
          </div>
          {selectedCandidateId ? (
            <>
              <div className="mb-3 flex flex-wrap items-center gap-2"><p className="text-xs font-semibold uppercase tracking-[0.14em] text-ink-500">Collaboration</p>{collaboration.starred && <span className="rounded-full bg-gold-50 px-2 py-1 text-[11px] font-semibold text-gold-700">Starred</span>}{collaboration.needs_review && <span className="rounded-full bg-amber-50 px-2 py-1 text-[11px] font-semibold text-amber-800">Needs review</span>}</div>
              <div className="mb-4 grid gap-3 rounded-lg border border-ink-100 bg-[#fafaf8] p-3 sm:grid-cols-4">
                <label className="grid gap-1 text-xs font-semibold">Owner<select className={input} value={collaboration.owner_id} disabled={!canWrite} onChange={async (event) => {
                  const owner_id = event.target.value ? Number(event.target.value) : null;
                  try { await apiRequest(token, "patch", "/candidates/" + selectedCandidateId + "/collaboration", { data: { owner_id } }); setCollaboration((value) => ({ ...value, owner_id: event.target.value })); onNotice("Candidate owner updated"); } catch (error) { onError(error); }
                }}><option value="">Unassigned</option>{recruitingUsers.map((person) => <option key={person.id} value={person.id}>{person.full_name}</option>)}</select></label>
                <label className="grid gap-1 text-xs font-semibold">Priority<select className={input} value={collaboration.priority} disabled={!canWrite} onChange={async (event) => {
                  const priority = event.target.value;
                  try { await apiRequest(token, "patch", "/candidates/" + selectedCandidateId + "/collaboration", { data: { priority } }); setCollaboration((value) => ({ ...value, priority })); } catch (error) { onError(error); }
                }}><option value="low">Low</option><option value="normal">Normal</option><option value="high">High</option><option value="urgent">Urgent</option></select></label>
                <label className="flex items-center gap-2 text-xs font-semibold sm:pt-5"><input type="checkbox" checked={collaboration.starred} disabled={!canWrite} onChange={async (event) => {
                  const starred = event.target.checked;
                  try { await apiRequest(token, "patch", "/candidates/" + selectedCandidateId + "/collaboration", { data: { starred } }); setCollaboration((value) => ({ ...value, starred })); } catch (error) { onError(error); }
                }} /> Star</label>
                <label className="flex items-center gap-2 text-xs font-semibold sm:pt-5"><input type="checkbox" checked={collaboration.needs_review} disabled={!canWrite} onChange={async (event) => {
                  const needs_review = event.target.checked;
                  try { await apiRequest(token, "patch", "/candidates/" + selectedCandidateId + "/collaboration", { data: { needs_review } }); setCollaboration((value) => ({ ...value, needs_review })); } catch (error) { onError(error); }
                }} /> Needs review</label>
              </div>
              <div className="mt-4 flex flex-wrap gap-2">
                {tags.map((tag) => (
                  <button key={tag} type="button" disabled={!canWrite} onClick={() => saveTags(tags.filter((item) => item.toLowerCase() !== tag.toLowerCase()))} className="rounded-full bg-blue-50 px-3 py-1 text-xs font-semibold text-blue-800">
                    {tag} <span className="ml-1 text-blue-500">×</span>
                  </button>
                ))}
                {!tags.length && <span className="text-sm text-ink-500">No tags yet.</span>}
              </div>
              <form onSubmit={addTag} className="mt-4 flex gap-2">
                <input className={input} value={tagInput} onChange={(event) => setTagInput(event.target.value)} placeholder="Add tag e.g. React, Immediate Joiner" disabled={!canWrite} />
                <button className={primary} type="submit" disabled={!canWrite || !tagInput.trim()}>Add</button>
              </form>
              {candidateApplications.length > 0 && (
                <p className="mt-3 text-xs text-ink-500">{candidateApplications.length} application(s) linked to this candidate.</p>
              )}
            </>
          ) : (
            <p className="mt-4 text-sm text-ink-500">Use tags to group candidates by technology, geography, availability or recruiter workflow.</p>
          )}
        </section>

        <section className="rounded-xl border border-ink-100 bg-white p-5">
          <div className="flex items-center justify-between gap-3">
            <div><p className="text-xs font-semibold uppercase tracking-[0.14em] text-blue-700">Duplicate control</p><h3 className="mt-1 font-semibold">Find possible duplicate profiles</h3></div>
            <button className={primary} onClick={scanDuplicates} disabled={duplicateLoading}>{duplicateLoading ? "Scanning…" : "Scan"}</button>
          </div>
          <div className="mt-4 grid gap-3">
            {duplicates.map((pair, index) => (
              <div key={index} className="rounded-lg border border-ink-100 p-3">
                <div className="grid gap-3 md:grid-cols-2">
                  {[pair.candidate_a, pair.candidate_b].map((item) => (
                    <div key={item.id}>
                      <p className="font-semibold">{item.name}</p>
                      <p className="text-xs text-ink-500">{item.email}</p>
                      <p className="text-xs text-ink-500">{item.phone || "No phone"}</p>
                    </div>
                  ))}
                </div>
                <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
                  <span className="text-[11px] text-ink-500">{pair.reasons.join(" · ")} · {pair.score}% similarity</span>
                  {canWrite && <div className="flex gap-2"><button className={secondary} onClick={() => mergeCandidates(pair.candidate_a.id, pair.candidate_b.id)}>Keep A</button><button className={secondary} onClick={() => mergeCandidates(pair.candidate_b.id, pair.candidate_a.id)}>Keep B</button></div>}
                </div>
              </div>
            ))}
            {!duplicates.length && <p className="text-sm text-ink-500">Run a scan to identify matching phone numbers or highly similar names.</p>}
          </div>
        </section>

        <section className="rounded-xl border border-ink-100 bg-white p-5">
          <p className="text-xs font-semibold uppercase tracking-[0.14em] text-blue-700">Recruiter assistant</p>
          <h3 className="mt-1 font-semibold">Ask about a single application</h3>
          <form onSubmit={runAssistant} className="mt-4 grid gap-3">
            <select className={input} value={assistantApplicationId} onChange={(event) => setAssistantApplicationId(event.target.value)}>
              <option value="">Select application…</option>
              {applications.map((item) => <option key={item.id} value={item.id}>#{item.id} · {item.job_title} · {item.candidate.first_name} {item.candidate.last_name}</option>)}
            </select>
            <textarea className={input + " min-h-20"} value={assistantQuestion} onChange={(event) => setAssistantQuestion(event.target.value)} placeholder="Ask for skills, experience, projects, education, interviews or offer status." />
            <button className={primary} disabled={!assistantApplicationId || assistantLoading}>{assistantLoading ? "Reviewing…" : "Ask assistant"}</button>
          </form>
          {assistantResult && (
            <div className="mt-4 rounded-lg border border-blue-100 bg-blue-50 p-4">
              <p className="text-sm font-semibold">{assistantResult.summary}</p>
              <ul className="mt-3 grid gap-2 text-sm text-blue-950">
                {(assistantResult.key_facts || []).map((fact, index) => <li key={index}>• {fact}</li>)}
              </ul>
              <p className="mt-3 text-[11px] text-blue-700">Evidence-only assistant. It does not make a hiring decision.</p>
            </div>
          )}
        </section>

        <section className="rounded-xl border border-ink-100 bg-white p-5">
          <p className="text-xs font-semibold uppercase tracking-[0.14em] text-blue-700">Reports</p>
          <h3 className="mt-1 font-semibold">Recruitment export</h3>
          <p className="mt-2 text-sm text-ink-500">Download applications, stages, sources, interview rounds, offer status and candidate tags as a CSV report.</p>
          <button className={primary + " mt-4"} onClick={downloadReport} disabled={reportLoading}>{reportLoading ? "Preparing…" : "Download recruitment report"}</button>
        </section>
      </div>
    </section>
  );
}
