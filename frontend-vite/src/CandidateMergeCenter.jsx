import { useEffect, useMemo, useState } from "react";

const buttonPrimary = "rounded-md bg-ink-950 px-3 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50";
const buttonSecondary = "rounded-md border border-ink-200 bg-white px-3 py-2 text-sm font-semibold text-ink-700 disabled:opacity-50";

export default function CandidateMergeCenter({ token, apiRequest, onNotice, onError }) {
  const [duplicates, setDuplicates] = useState([]);
  const [history, setHistory] = useState([]);
  const [selected, setSelected] = useState(null);
  const [comparison, setComparison] = useState(null);
  const [choices, setChoices] = useState({});
  const [loading, setLoading] = useState(false);
  const [merging, setMerging] = useState(false);

  const scan = async () => {
    setLoading(true);
    try { const response = await apiRequest(token, "GET", "/merge-center/duplicates"); setDuplicates(response.data || []); setSelected(null); setComparison(null); }
    catch (error) { onError(error); } finally { setLoading(false); }
  };
  const loadHistory = async () => { try { const response = await apiRequest(token, "GET", "/merge-center/history"); setHistory(response.data || []); } catch (error) { onError(error); } };
  useEffect(() => { scan(); loadHistory(); }, []);

  const choosePair = async (pair) => {
    setSelected(pair); setComparison(null);
    try { const response = await apiRequest(token, "GET", `/merge-center/compare/${pair.candidate_id}/${pair.id}`); setComparison(response.data); const next = {}; (response.data.fields || []).forEach((field) => { next[field.field] = field.recommended || "survivor"; }); setChoices(next); }
    catch (error) { onError(error); }
  };
  const merge = async () => {
    if (!selected || !comparison) return;
    setMerging(true);
    try {
      const response = await apiRequest(token, "POST", "/merge-center/merge", { data: { survivor_id: selected.candidate_id, merged_id: selected.id, field_choices: choices } });
      onNotice(`Candidates merged successfully. Audit #${response.data.audit_id} recorded.`);
      await scan(); await loadHistory();
    } catch (error) { onError(error); } finally { setMerging(false); }
  };

  const groupedFields = useMemo(() => comparison?.fields || [], [comparison]);
  const card = (candidate, side) => <div className="rounded-xl border border-ink-100 bg-[#fafaf8] p-4"><div className="flex items-start justify-between gap-3"><div><p className="text-xs font-semibold uppercase tracking-[0.16em] text-blue-700">{side}</p><h3 className="mt-1 text-lg font-semibold">{candidate.first_name} {candidate.last_name}</h3></div><span className="rounded-full bg-white px-2 py-1 text-xs text-ink-500">#{candidate.id}</span></div><dl className="mt-4 grid gap-3 text-sm"><div><dt className="text-xs text-ink-400">Email</dt><dd>{candidate.email || "—"}</dd></div><div><dt className="text-xs text-ink-400">Source</dt><dd>{candidate.source || "—"}</dd></div><div><dt className="text-xs text-ink-400">Skills / profile</dt><dd className="max-h-32 overflow-auto whitespace-pre-wrap">{JSON.stringify(candidate.resume_data || {}, null, 2)}</dd></div></dl></div>;

  return <section className="space-y-5">
    <div className="flex flex-wrap items-end justify-between gap-3"><div><p className="text-sm text-ink-500">Data quality</p><h2 className="mt-1 text-2xl font-semibold">Duplicate Merge Center</h2><p className="mt-1 text-sm text-ink-500">Review similarity signals before combining candidate records.</p></div><button className={buttonPrimary} onClick={scan} disabled={loading}>{loading ? "Scanning…" : "Scan duplicates"}</button></div>
    <div className="grid gap-4 lg:grid-cols-[360px_1fr]">
      <div className="rounded-xl border border-ink-100 bg-white">
        <div className="border-b border-ink-100 px-4 py-3"><p className="text-sm font-semibold">{duplicates.length} possible duplicate pair(s)</p><p className="text-xs text-ink-500">Email, phone and name similarity are scored.</p></div>
        <div className="max-h-[680px] overflow-auto">
          {duplicates.map((pair) => <button key={`${pair.candidate_id}-${pair.id}`} onClick={() => choosePair(pair)} className={`w-full border-b border-ink-50 px-4 py-3 text-left hover:bg-ink-50 ${selected && selected.candidate_id === pair.candidate_id && selected.id === pair.id ? "bg-blue-50" : ""}`}><div className="flex items-center justify-between gap-3"><span className="font-semibold">{pair.first_name} {pair.last_name}</span><span className="text-xs font-bold text-blue-700">{pair.similarity_score}%</span></div><p className="mt-1 text-xs text-ink-500">{pair.email}</p><p className="mt-1 text-[11px] text-ink-400">{pair.matched_by.join(" · ")}</p></button>)}
          {!duplicates.length && <div className="p-5 text-sm text-ink-500">No likely duplicates found.</div>}
        </div>
      </div>
      <div className="space-y-5">
        {comparison ? <><div className="grid gap-4 md:grid-cols-2">{card(comparison.survivor, "Surviving candidate")}{card(comparison.merged, "Record to merge")}</div>
          <div className="rounded-xl border border-ink-100 bg-white"><div className="border-b border-ink-100 px-4 py-3"><h3 className="font-semibold">Choose fields to keep</h3><p className="text-xs text-ink-500">Every field can come from either record. Employment history and projects are combined automatically.</p></div><div className="divide-y divide-ink-50">
            {groupedFields.map((field) => <div key={field.field} className="grid gap-3 px-4 py-3 md:grid-cols-[150px_1fr_1fr_190px] md:items-center"><div className="text-sm font-semibold capitalize">{field.field.replaceAll("_", " ")}</div><div className="max-h-24 overflow-auto rounded-lg bg-ink-50 p-2 text-xs whitespace-pre-wrap">{JSON.stringify(field.survivor_value, null, 2)}</div><div className="max-h-24 overflow-auto rounded-lg bg-ink-50 p-2 text-xs whitespace-pre-wrap">{JSON.stringify(field.merged_value, null, 2)}</div><select className="rounded-md border border-ink-200 px-2 py-2 text-sm" value={choices[field.field] || "survivor"} onChange={(event) => setChoices({ ...choices, [field.field]: event.target.value })}><option value="survivor">Keep surviving record</option><option value="merged">Keep merged record</option></select></div>)}
          </div></div>
          <div className="grid gap-4 md:grid-cols-3"><div className="rounded-xl border border-ink-100 bg-white p-4"><p className="text-xs font-semibold uppercase text-ink-500">Employment</p><p className="mt-2 text-2xl font-bold">{comparison.employment_history?.length || 0}</p><p className="text-xs text-ink-500">combined entries</p></div><div className="rounded-xl border border-ink-100 bg-white p-4"><p className="text-xs font-semibold uppercase text-ink-500">Projects</p><p className="mt-2 text-2xl font-bold">{comparison.projects?.length || 0}</p><p className="text-xs text-ink-500">combined entries</p></div><div className="rounded-xl border border-ink-100 bg-white p-4"><p className="text-xs font-semibold uppercase text-ink-500">Applications</p><p className="mt-2 text-2xl font-bold">{comparison.applications?.length || 0}</p><p className="text-xs text-ink-500">across both records</p></div></div>
          <div className="flex flex-wrap justify-end gap-2"><button className={buttonSecondary} onClick={() => setComparison(null)}>Cancel</button><button className={buttonPrimary} disabled={merging} onClick={merge}>{merging ? "Merging…" : "Merge candidates"}</button></div>
        </> : <div className="grid min-h-96 place-items-center rounded-xl border border-dashed border-ink-200 bg-white p-8 text-center"><div><h3 className="font-semibold">Select a duplicate pair</h3><p className="mt-1 text-sm text-ink-500">The comparison view will show both records and let you choose field-by-field values.</p></div></div>}
      </div>
    </div>
    <div className="rounded-xl border border-ink-100 bg-white"><div className="border-b border-ink-100 px-4 py-3"><h3 className="font-semibold">Merge audit history</h3><p className="text-xs text-ink-500">Every merge records the actor, field choices, original values and consolidation summary.</p></div><div className="divide-y divide-ink-50">{history.map((item) => <div key={item.id} className="grid gap-2 px-4 py-3 text-sm md:grid-cols-[80px_1fr_1fr_1fr]"><span className="font-semibold">#{item.id}</span><span>#{item.merged_candidate_id} → #{item.survivor_candidate_id}</span><span>{item.actor_name}</span><span className="text-xs text-ink-500">{new Date(item.created_at).toLocaleString()}</span></div>)}{!history.length && <p className="p-4 text-sm text-ink-500">No merges recorded yet.</p>}</div></div>
  </section>;
}
