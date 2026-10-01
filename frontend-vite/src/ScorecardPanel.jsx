import { useEffect, useState } from "react";

const CRITERIA = [
  ["technical", "Technical skills"],
  ["problem_solving", "Problem solving"],
  ["communication", "Communication"],
  ["role_knowledge", "Role knowledge"],
];

export default function ScorecardPanel({ token, applicationId, candidateName, apiRequest, onNotice, onError }) {
  const [ratings, setRatings] = useState({ technical: 3, problem_solving: 3, communication: 3, role_knowledge: 3 });
  const [recommendation, setRecommendation] = useState("");
  const [saving, setSaving] = useState(false);
  const [history, setHistory] = useState([]);

  useEffect(() => {
    if (!applicationId) {
      setHistory([]);
      return undefined;
    }
    let active = true;
    apiRequest(token, "get", "/applications/" + applicationId + "/scorecard")
      .then((response) => {
        if (!active) return;
        const rows = response.data || [];
        setHistory(rows);
        if (rows[0]) {
          setRatings({ technical: rows[0].ratings?.technical ?? 3, problem_solving: rows[0].ratings?.problem_solving ?? 3, communication: rows[0].ratings?.communication ?? 3, role_knowledge: rows[0].ratings?.role_knowledge ?? 3 });
          setRecommendation(rows[0].recommendation || "");
        }
      })
      .catch((error) => { if (active) onError(error); });
    return () => { active = false; };
  }, [token, applicationId, apiRequest, onError]);

  async function save() {
    if (!applicationId) return;
    setSaving(true);
    try {
      await apiRequest(token, "post", "/applications/" + applicationId + "/scorecard", {
        data: { ratings, recommendation: recommendation || null },
      });
      onNotice("Interview scorecard saved");
      const refreshed = await apiRequest(token, "get", "/applications/" + applicationId + "/scorecard");
      setHistory(refreshed.data || []);
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
        <div><p className="text-xs font-semibold uppercase tracking-[0.18em] text-blue-700">Interview scorecard</p><h4 className="mt-1 font-semibold">Feedback for {candidateName}</h4></div>
        {history[0]?.submitted_at && <span className="text-xs text-ink-500">Last submitted {new Date(history[0].submitted_at).toLocaleString()}</span>}
      </div>
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        {CRITERIA.map(([key, label]) => (
          <label key={key} className="grid gap-1.5 text-xs font-semibold text-ink-700">
            {label}
            <select className="rounded-md border border-ink-100 bg-white px-3 py-2.5 text-sm" value={ratings[key]} onChange={(event) => setRatings({ ...ratings, [key]: Number(event.target.value) })}>
              {[1,2,3,4,5].map((value) => <option key={value} value={value}>{value} / 5</option>)}
            </select>
          </label>
        ))}
        <label className="grid gap-1.5 text-xs font-semibold text-ink-700 sm:col-span-2">
          Recommendation
          <select className="rounded-md border border-ink-100 bg-white px-3 py-2.5 text-sm" value={recommendation} onChange={(event) => setRecommendation(event.target.value)}>
            <option value="">Choose recommendation</option><option value="Strong">Strong</option><option value="Proceed">Proceed</option><option value="Hold">Hold</option><option value="Do not proceed">Do not proceed</option>
          </select>
        </label>
      </div>
      <button className="mt-4 inline-flex items-center rounded-md bg-[#1769d3] px-4 py-2 text-sm font-semibold text-white" disabled={saving}>{saving ? "Saving…" : "Save feedback"}</button>
      {history.length > 1 && <p className="mt-3 text-xs text-ink-500">{history.length} scorecard submission(s) recorded.</p>}
    </section>
  );
}
