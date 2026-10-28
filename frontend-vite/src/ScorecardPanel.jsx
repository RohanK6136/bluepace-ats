import { useEffect, useMemo, useState } from "react";

const input = "w-full rounded-md border border-ink-100 bg-white px-3 py-2.5 text-sm text-ink-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100";
const primary = "mt-4 inline-flex items-center rounded-md bg-[#1769d3] px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50";
const secondary = "inline-flex items-center rounded-md border border-ink-100 bg-white px-3 py-2 text-xs font-semibold text-ink-700 hover:bg-ink-50";
const ratingAnchors = [
  [1, "No relevant evidence"],
  [2, "Limited or unclear evidence"],
  [3, "Meets the role requirement"],
  [4, "Strong example with clear choices and outcome"],
  [5, "Exceptional depth, trade-offs, and impact"],
];

function slug(value) {
  return String(value || "competency").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "competency";
}

function buildInterviewKit(job) {
  const descriptionSkills = String(job?.description || "")
    .split(/\r?\n/)
    .map((line) => line.replace(/^\s*(?:[-*•]|\d+[.)])\s*/, "").trim())
    .filter((line) => line.length > 2 && line.length < 100 && !/^(responsibilities|requirements|qualifications|about the role)\b/i.test(line));
  const rawSkills = Array.isArray(job?.required_skills) && job.required_skills.length
    ? job.required_skills
    : descriptionSkills;
  const seen = new Set();
  const skills = rawSkills.map((value) => String(value || "").trim()).filter((value) => {
    const key = value.toLowerCase();
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  }).slice(0, 4);
  const role = String(job?.title || "this role").trim();
  const questions = skills.map((skill) => ({
    id: `skill-${slug(skill)}`,
    competency: skill,
    question: `Tell me about a project, coursework, or other work where you used ${skill}. What problem were you solving, what did you personally do, and what was the result?`,
    probe: "What alternatives or trade-offs did you consider? What would you change if you did it again?",
  }));
  questions.push(
    {
      id: "problem-solving",
      competency: "Problem solving",
      question: `Describe a difficult problem relevant to ${role}. How did you break it down, check your assumptions, and decide what to do first?`,
      probe: "What evidence changed your approach, and what was the outcome?",
    },
    {
      id: "collaboration",
      competency: "Collaboration and communication",
      question: "Describe a piece of work where you had to coordinate with people in different roles. How did you make the hand-offs and decisions clear?",
      probe: "What did you do when priorities or expectations differed?",
    },
  );
  const kitId = `structured-v1-${job?.id || "role"}-${questions.map((item) => item.id).join("-")}`;
  return { kitId, role, questions };
}

function emptyResponses(questions) {
  return Object.fromEntries(questions.map((question) => [question.id, { rating: "", evidence: "" }]));
}

function ScoreRange({ scores }) {
  if (!scores.length) return <span className="text-xs text-ink-400">No submitted ratings yet</span>;
  const average = scores.reduce((total, score) => total + score, 0) / scores.length;
  const minimum = Math.min(...scores);
  const maximum = Math.max(...scores);
  const spread = maximum - minimum;
  return <span className={`text-xs font-semibold ${spread >= 2 ? "text-amber-800" : "text-ink-700"}`}>{average.toFixed(1)} average · range {minimum}–{maximum}{spread >= 2 ? " · discuss" : ""}</span>;
}

export default function ScorecardPanel({ token, applicationId, candidateName, job = null, userId, apiRequest, onNotice, onError }) {
  const generatedKit = useMemo(() => buildInterviewKit(job), [job]);
  const [kit, setKit] = useState(generatedKit);
  const [responses, setResponses] = useState(() => emptyResponses(generatedKit.questions));
  const [recommendation, setRecommendation] = useState("");
  const [saving, setSaving] = useState(false);
  const [history, setHistory] = useState([]);
  const [legacyFeedback, setLegacyFeedback] = useState(false);

  useEffect(() => { setKit(generatedKit); }, [generatedKit]);

  useEffect(() => {
    if (!applicationId) {
      setHistory([]);
      setKit(generatedKit);
      setResponses(emptyResponses(generatedKit.questions));
      setRecommendation("");
      setLegacyFeedback(false);
      return undefined;
    }
    let active = true;
    apiRequest(token, "get", "/applications/" + applicationId + "/scorecard")
      .then((response) => {
        if (!active) return;
        const rows = Array.isArray(response.data) ? response.data : [];
        setHistory(rows);
        // Each interviewer starts with their own draft. Other reviewers' ratings
        // remain hidden until this interviewer has submitted independently.
        const own = rows.find((row) => Number(row.interviewer_id) === Number(userId)) || null;
        const savedKit = own?.ratings?._interviewKit;
        setKit(savedKit?.questions?.length ? { kitId: savedKit.kitId, role: savedKit.role || generatedKit.role, questions: savedKit.questions } : generatedKit);
        setResponses(savedKit?.responses && typeof savedKit.responses === "object"
          ? { ...emptyResponses(savedKit.questions?.length ? savedKit.questions : generatedKit.questions), ...savedKit.responses }
          : emptyResponses(generatedKit.questions));
        setRecommendation(own?.recommendation || "");
        setLegacyFeedback(Boolean(own && !savedKit));
      })
      .catch((error) => { if (active) onError(error); });
    return () => { active = false; };
  }, [token, applicationId, userId, generatedKit]);

  const ownSubmission = history.find((row) => Number(row.interviewer_id) === Number(userId) && row.submitted_at) || null;
  const peerSubmissions = ownSubmission
    ? history.filter((row) => row.submitted_at && row.ratings?._interviewKit?.kitId === kit.kitId)
    : [];
  const panelRecommendations = peerSubmissions.map((row) => row.recommendation).filter(Boolean);
  const recommendationCounts = panelRecommendations.reduce((counts, value) => ({ ...counts, [value]: (counts[value] || 0) + 1 }), {});
  const disagreementCues = kit.questions.map((question) => {
    const scores = peerSubmissions.map((row) => Number(row.ratings?._interviewKit?.responses?.[question.id]?.rating)).filter((value) => Number.isFinite(value) && value >= 1 && value <= 5);
    return { competency: question.competency, scores, spread: scores.length > 1 ? Math.max(...scores) - Math.min(...scores) : 0 };
  }).filter((item) => item.spread >= 2);
  const allRated = kit.questions.length > 0 && kit.questions.every((question) => Number(responses[question.id]?.rating) >= 1 && Number(responses[question.id]?.rating) <= 5);

  function updateResponse(questionId, patch) {
    setResponses((current) => ({
      ...current,
      [questionId]: { ...(current[questionId] || { rating: "", evidence: "" }), ...patch },
    }));
  }

  async function copyGuide() {
    const guide = [
      `${kit.role} · structured interview guide`,
      "Ask every candidate the same core questions. Take notes on job-related evidence, then rate independently before the panel debrief.",
      ...kit.questions.flatMap((question, index) => [
        `${index + 1}. ${question.competency}: ${question.question}`,
        `Probe: ${question.probe}`,
      ]),
      "Rating anchors:",
      ...ratingAnchors.map(([value, label]) => `${value}/5 · ${label}`),
    ].join("\n");
    try {
      await navigator.clipboard.writeText(guide);
      onNotice("Structured interview guide copied.");
    } catch {
      onError(new Error("Clipboard access is unavailable in this browser."));
    }
  }

  async function copyDebriefAgenda() {
    const agenda = [
      `${kit.role} · panel debrief for ${candidateName}`,
      "Start with job-related evidence from each independently submitted scorecard.",
      "Recommendation distribution:",
      ...(Object.keys(recommendationCounts).length ? Object.entries(recommendationCounts).map(([value, count]) => `- ${value}: ${count}`) : ["- No submitted recommendations"]),
      "Competencies with a rating spread of 2 or more:",
      ...(disagreementCues.length ? disagreementCues.map((item) => `- ${item.competency}: ratings ${Math.min(...item.scores)}–${Math.max(...item.scores)}`) : ["- None flagged by the rating spread check"]),
      "Discuss the evidence behind differences. These summaries are prompts and do not make a hiring decision.",
    ].join("\n");
    try {
      await navigator.clipboard.writeText(agenda);
      onNotice("Panel debrief agenda copied.");
    } catch {
      onError(new Error("Clipboard access is unavailable in this browser."));
    }
  }

  async function save() {
    if (!applicationId || !allRated) return;
    setSaving(true);
    const savedAt = new Date().toISOString();
    try {
      await apiRequest(token, "post", "/applications/" + applicationId + "/scorecard", {
        data: {
          ratings: {
            _interviewKit: {
              version: 1,
              kitId: kit.kitId,
              role: kit.role,
              jobId: job?.id || null,
              questions: kit.questions,
              responses: Object.fromEntries(kit.questions.map((question) => [
                question.id,
                { rating: Number(responses[question.id].rating), evidence: String(responses[question.id].evidence || "").trim() },
              ])),
              independentlyRatedAt: savedAt,
            },
          },
          recommendation: recommendation || null,
        },
      });
      onNotice("Structured interview feedback saved.");
      const refreshed = await apiRequest(token, "get", "/applications/" + applicationId + "/scorecard");
      setHistory(Array.isArray(refreshed.data) ? refreshed.data : []);
      setLegacyFeedback(false);
    } catch (error) {
      onError(error);
    } finally {
      setSaving(false);
    }
  }

  if (!applicationId) return null;

  return (
    <section className="mt-6 border-t border-ink-100 pt-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div><p className="text-xs font-semibold uppercase tracking-[0.18em] text-blue-700">Structured interview kit</p><h4 className="mt-1 font-semibold">{kit.role} · {candidateName}</h4></div>
        <div className="flex items-center gap-2">{ownSubmission?.submitted_at && <span className="text-xs text-ink-500">Your feedback submitted {new Date(ownSubmission.submitted_at).toLocaleString()}</span>}<button type="button" className={secondary} onClick={copyGuide}>Copy interview guide</button></div>
      </div>
      <p className="mt-2 text-sm leading-6 text-ink-600">Use the same core questions for this role, record the candidate’s evidence, and score independently before discussing the panel’s ratings.</p>
      {legacyFeedback && <p className="mt-3 rounded-md border border-blue-100 bg-blue-50 px-3 py-2 text-xs leading-5 text-blue-900">Your earlier scorecard is still in the history. Start this structured kit to record question-level evidence.</p>}
      <div className="mt-4 space-y-3">
        {kit.questions.map((question, index) => {
          const response = responses[question.id] || { rating: "", evidence: "" };
          return <article key={question.id} className="rounded-lg border border-ink-100 bg-white p-4">
            <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-[10px] font-semibold uppercase tracking-wide text-ink-500">Question {index + 1} · {question.competency}</p><p className="mt-2 text-sm font-medium leading-6 text-ink-900">{question.question}</p><p className="mt-2 text-xs leading-5 text-ink-500"><strong>Optional probe:</strong> {question.probe}</p></div>
              <label className="grid min-w-48 gap-1 text-xs font-semibold text-ink-700">Evidence rating
                <select className={input} value={response.rating} onChange={(event) => updateResponse(question.id, { rating: event.target.value ? Number(event.target.value) : "" })}>
                  <option value="">Choose 1–5</option>{ratingAnchors.map(([value, label]) => <option key={value} value={value}>{value} · {label}</option>)}
                </select>
              </label>
            </div>
            <label className="mt-3 grid gap-1.5 text-xs font-semibold text-ink-700">Notes: specific examples, decisions, and outcomes
              <textarea className={input} rows={2} maxLength={3000} value={response.evidence || ""} onChange={(event) => updateResponse(question.id, { evidence: event.target.value })} placeholder="Capture the candidate's job-related evidence; avoid impressions unrelated to the role." />
            </label>
          </article>;
        })}
      </div>
      <div className="mt-4 rounded-lg border border-blue-100 bg-blue-50 p-3">
        <p className="text-xs font-semibold text-blue-950">Shared rating anchors</p>
        <ul className="mt-2 grid gap-1 text-xs leading-5 text-blue-900 sm:grid-cols-2">{ratingAnchors.map(([value, label]) => <li key={value}><strong>{value}/5</strong> · {label}</li>)}</ul>
      </div>
      <div className="mt-4 grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
        <label className="grid gap-1.5 text-xs font-semibold text-ink-700">Your recommendation
          <select className={input} value={recommendation} onChange={(event) => setRecommendation(event.target.value)}><option value="">Choose recommendation</option><option value="Strong">Strong</option><option value="Proceed">Proceed</option><option value="Hold">Hold</option><option value="Do not proceed">Do not proceed</option></select>
        </label>
        <button type="button" onClick={save} className={primary} disabled={saving || !allRated}>{saving ? "Saving…" : "Submit independent feedback"}</button>
      </div>
      {!allRated && <p className="mt-2 text-xs text-amber-800">Rate each question before submitting. Notes are saved with your scorecard and remain separate for each interviewer.</p>}
      {peerSubmissions.length > 1 && <section className="mt-5 rounded-lg border border-ink-100 bg-[#fafaf8] p-4">
        <p className="text-xs font-semibold uppercase tracking-wide text-ink-600">Panel debrief cues</p><p className="mt-1 text-xs leading-5 text-ink-500">Ratings are compared only after you submit your own. A wide spread is a prompt to discuss evidence, not an automatic hiring decision.</p>
        <div className="mt-3 rounded-lg border border-ink-100 bg-white p-3"><div className="flex flex-wrap items-center justify-between gap-2"><p className="text-xs font-semibold text-ink-800">Recommendation alignment</p><button type="button" className={secondary} onClick={copyDebriefAgenda}>Copy debrief agenda</button></div><div className="mt-2 flex flex-wrap gap-2">{Object.entries(recommendationCounts).map(([value, count]) => <span key={value} className="rounded-full bg-blue-50 px-2.5 py-1 text-[11px] font-semibold text-blue-900">{value} · {count}</span>)}{!Object.keys(recommendationCounts).length && <span className="text-xs text-ink-500">No recommendations recorded</span>}</div><p className="mt-2 text-xs leading-5 text-ink-600">{Object.keys(recommendationCounts).length > 1 ? "Recommendations differ; compare the evidence each interviewer observed." : "Review the question-level ranges before the team debrief."}</p>{disagreementCues.length > 0 && <p className="mt-2 text-xs font-medium text-amber-900">Discuss first: {disagreementCues.map((item) => item.competency).join(", ")}.</p>}</div>
        <div className="mt-3 divide-y divide-ink-100">{kit.questions.map((question) => {
          const scores = peerSubmissions.map((row) => Number(row.ratings?._interviewKit?.responses?.[question.id]?.rating)).filter((value) => Number.isFinite(value) && value >= 1 && value <= 5);
          return <div key={question.id} className="flex flex-wrap items-center justify-between gap-2 py-2"><span className="text-xs font-medium text-ink-800">{question.competency}</span><ScoreRange scores={scores} /></div>;
        })}</div>
      </section>}
      {history.length > 1 && <p className="mt-3 text-xs text-ink-500">{history.length} interviewer submission(s) recorded for this application.</p>}
    </section>
  );
}

