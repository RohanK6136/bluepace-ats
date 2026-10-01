import { useEffect, useState } from "react";

const inputStyle = "w-full rounded-md border border-ink-100 bg-white px-3 py-2.5 text-sm text-ink-900 outline-none focus:border-gold-500 focus:ring-2 focus:ring-gold-100";
const buttonPrimary = "inline-flex items-center justify-center gap-2 rounded-md bg-[#c49a4a] px-4 py-2 text-sm font-semibold text-[#10131c] disabled:cursor-not-allowed disabled:opacity-50";
const buttonSecondary = "inline-flex items-center justify-center gap-2 rounded-md border border-ink-100 bg-white px-3 py-2 text-sm font-semibold text-ink-800 disabled:cursor-not-allowed disabled:opacity-50";

export default function TalentPoolsPanel({ token, candidates, apiRequest, onNotice, onError }) {
  const [pools, setPools] = useState([]);
  const [activePool, setActivePool] = useState(null);
  const [members, setMembers] = useState([]);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [candidateId, setCandidateId] = useState("");
  const [loading, setLoading] = useState(false);

  async function loadPools() {
    setLoading(true);
    try {
      const response = await apiRequest(token, "get", "/talent-pools");
      setPools(response.data || []);
      if (activePool) {
        const current = (response.data || []).find((pool) => pool.id === activePool.id);
        if (current) setActivePool(current);
      }
    } catch (error) { onError(error); }
    finally { setLoading(false); }
  }

  useEffect(() => { loadPools(); }, [token]);

  useEffect(() => {
    if (!activePool) { setMembers([]); return; }
    let mounted = true;
    apiRequest(token, "get", "/talent-pools/" + activePool.id + "/candidates")
      .then((response) => { if (mounted) setMembers(response.data || []); })
      .catch(onError);
    return () => { mounted = false; };
  }, [activePool, token]);

  async function createPool(event) {
    event.preventDefault();
    if (!name.trim()) return;
    try {
      await apiRequest(token, "post", "/talent-pools", { data: { name: name.trim(), description: description.trim() || null } });
      setName(""); setDescription("");
      await loadPools();
      onNotice("Talent pool created");
    } catch (error) { onError(error); }
  }

  async function addCandidate(event) {
    event.preventDefault();
    if (!activePool || !candidateId) return;
    try {
      await apiRequest(token, "post", "/talent-pools/" + activePool.id + "/candidates", { data: { candidate_id: Number(candidateId) } });
      setCandidateId("");
      await loadPools();
      const response = await apiRequest(token, "get", "/talent-pools/" + activePool.id + "/candidates");
      setMembers(response.data || []);
      onNotice("Candidate added to talent pool");
    } catch (error) { onError(error); }
  }

  async function removeCandidate(candidate) {
    if (!activePool) return;
    try {
      await apiRequest(token, "delete", "/talent-pools/" + activePool.id + "/candidates/" + candidate.id);
      setMembers((items) => items.filter((item) => item.id !== candidate.id));
      await loadPools();
      onNotice("Candidate removed");
    } catch (error) { onError(error); }
  }

  return (
    <section>
      <div className="mb-5"><p className="text-sm text-ink-500">Build reusable candidate lists for future hiring.</p><h2 className="mt-1 text-xl font-semibold">Talent pools</h2></div>
      <div className="grid gap-5 lg:grid-cols-[330px_1fr]">
        <section className="rounded-xl border border-ink-100 bg-white p-5">
          <h3 className="font-semibold">Create pool</h3>
          <form className="mt-4 grid gap-3" onSubmit={createPool}>
            <label className="grid gap-1.5 text-xs font-semibold text-ink-700">Pool name<input className={inputStyle} value={name} onChange={(e) => setName(e.target.value)} placeholder="Python developers" /></label>
            <label className="grid gap-1.5 text-xs font-semibold text-ink-700">Description<textarea className={inputStyle + " min-h-20"} value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Candidates to revisit for backend roles" /></label>
            <button className={buttonPrimary} type="submit">Create pool</button>
          </form>
          <div className="mt-6 border-t border-ink-100 pt-4">
            <p className="mb-2 text-xs font-semibold uppercase tracking-[0.14em] text-ink-500">Existing pools</p>
            {loading && <p className="text-sm text-ink-500">Loading…</p>}
            <div className="grid gap-1">
              {pools.map((pool) => (
                <button type="button" key={pool.id} onClick={() => setActivePool(pool)} className={"rounded-lg px-3 py-2 text-left " + (activePool?.id === pool.id ? "bg-blue-50 text-blue-800" : "hover:bg-ink-50")}>
                  <div className="flex items-center justify-between gap-2"><span className="text-sm font-semibold">{pool.name}</span><span className="text-xs text-ink-500">{pool.candidate_count}</span></div>
                  {pool.description && <p className="mt-0.5 text-xs text-ink-500">{pool.description}</p>}
                </button>
              ))}
              {!pools.length && !loading && <p className="text-sm text-ink-500">No pools created yet.</p>}
            </div>
          </div>
        </section>

        <section className="rounded-xl border border-ink-100 bg-white p-5">
          {!activePool ? (
            <div className="grid min-h-80 place-items-center text-center"><div><p className="font-semibold">Select a talent pool</p><p className="mt-1 text-sm text-ink-500">Create a pool and add candidates you want to keep warm.</p></div></div>
          ) : (
            <>
              <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-xs font-semibold uppercase tracking-[0.14em] text-blue-700">Pool</p><h3 className="mt-1 text-xl font-semibold">{activePool.name}</h3></div><span className="rounded-full bg-blue-50 px-3 py-1 text-xs font-semibold text-blue-800">{members.length} members</span></div>
              <form onSubmit={addCandidate} className="mt-5 flex flex-col gap-2 sm:flex-row"><select className={inputStyle} value={candidateId} onChange={(e) => setCandidateId(e.target.value)}><option value="">Add candidate…</option>{candidates.map((candidate) => <option key={candidate.id} value={candidate.id}>{candidate.first_name} {candidate.last_name} · {candidate.email}</option>)}</select><button className={buttonPrimary} type="submit">Add candidate</button></form>
              <div className="mt-5 overflow-x-auto border-y border-ink-100"><table className="w-full min-w-[650px] text-left text-sm"><thead className="bg-[#fafaf8] text-[11px] uppercase text-ink-500"><tr><th className="px-3 py-3">Candidate</th><th className="px-3 py-3">Skills</th><th className="px-3 py-3">Source</th><th className="px-3 py-3"></th></tr></thead><tbody className="divide-y divide-ink-50">{members.map((candidate) => <tr key={candidate.id}><td className="px-3 py-3"><p className="font-semibold">{candidate.first_name} {candidate.last_name}</p><p className="text-xs text-ink-500">{candidate.email}</p></td><td className="max-w-72 px-3 py-3 text-xs">{candidate.skills?.slice(0,8).join(", ") || "—"}</td><td className="px-3 py-3 text-xs text-ink-500">{candidate.source || "—"}</td><td className="px-3 py-3 text-right"><button type="button" className={buttonSecondary} onClick={() => removeCandidate(candidate)}>Remove</button></td></tr>)}</tbody></table>{!members.length && <div className="p-8 text-center text-sm text-ink-500">No candidates in this pool yet.</div>}</div>
            </>
          )}
        </section>
      </div>
    </section>
  );
}
