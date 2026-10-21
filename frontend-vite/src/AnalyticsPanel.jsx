import { useEffect, useState } from "react";

export default function AnalyticsPanel({ token, apiRequest, onError }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let mounted = true;
    setLoading(true);
    apiRequest(token, "get", "/analytics")
      .then((response) => { if (mounted) setData(response.data); })
      .catch((error) => { if (mounted) onError(error); })
      .finally(() => { if (mounted) setLoading(false); });
    return () => { mounted = false; };
  }, [token]);
  if (loading) return <section className="rounded-xl border border-ink-100 bg-white p-6 text-sm text-ink-500">Loading analytics…</section>;
  if (!data) return null;
  return (
    <section>
      <div className="mb-5"><p className="text-sm text-ink-500">Recruiting performance and funnel diagnostics.</p><h2 className="mt-1 text-xl font-semibold">Recruitment analytics</h2></div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[[ "Applications", data.total_applications ], [ "Avg. days / application", data.avg_days_in_application ], [ "Avg. days to hire", data.avg_days_to_hire ], [ "Sources", data.sources?.length || 0 ]].map(([label,value]) => <div key={label} className="rounded-xl border border-ink-100 bg-white p-5"><p className="text-[11px] uppercase tracking-[0.14em] text-ink-500">{label}</p><p className="mt-2 text-3xl font-bold">{value}</p></div>)}
      </div>
      <div className="mt-5 grid gap-5 lg:grid-cols-2">
        <section className="rounded-xl border border-ink-100 bg-white p-5"><h3 className="font-semibold">Funnel</h3><div className="mt-4 grid gap-3">{Object.entries(data.stage_counts || {}).map(([stage,count]) => <div key={stage}><div className="flex justify-between text-sm"><span>{stage}</span><span className="font-semibold">{count}</span></div><div className="mt-1 h-2 rounded-full bg-ink-50"><div className="h-full rounded-full bg-[#1769d3]" style={{width: Math.min(100, (count / Math.max(data.total_applications,1))*100) + "%"}} /></div></div>)}</div></section>
        <section className="rounded-xl border border-ink-100 bg-white p-5"><h3 className="font-semibold">Application sources</h3><div className="mt-4 grid gap-3">{(data.sources || []).map((item) => <div key={item.name} className="flex items-center justify-between border-b border-ink-50 pb-2 text-sm"><span>{item.name}</span><span className="font-semibold">{item.count}</span></div>)}{!data.sources?.length && <p className="text-sm text-ink-500">No source data yet.</p>}</div></section>
      </div>
    </section>
  );
}
