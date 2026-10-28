import { useEffect, useMemo, useState } from "react";

const STAGES = [
  { id: "Applied", label: "Initial review", effort: 0.3, capacity: 10 },
  { id: "Screening", label: "Screening", effort: 0.5, capacity: 8 },
  { id: "Interview", label: "Interviews", effort: 1.5, capacity: 8 },
  { id: "Offer", label: "Offer decisions", effort: 0.5, capacity: 4 },
];
const field = "w-24 rounded-md border border-ink-200 bg-white px-2.5 py-2 text-sm tabular-nums text-ink-900";

function Metric({ label, value, detail, tone = "ink" }) {
  const color = tone === "amber" ? "text-amber-800" : tone === "blue" ? "text-blue-800" : "text-ink-950";
  return <div className="rounded-lg border border-ink-100 bg-white p-4"><p className="text-[10px] font-semibold uppercase tracking-wide text-ink-500">{label}</p><p className={`mt-1 text-2xl font-semibold tabular-nums ${color}`}>{value}</p><p className="mt-1 text-xs leading-5 text-ink-500">{detail}</p></div>;
}

function numberInput(value, onChange, { min = 0, max = 1000, step = 0.5, label }) {
  return <input aria-label={label} className={field} type="number" min={min} max={max} step={step} value={value} onChange={(event) => onChange(Math.max(min, Math.min(max, Number(event.target.value) || 0)))} />;
}

export default function HiringFlowSimulator({ token, apiRequest, onError }) {
  const [analytics, setAnalytics] = useState(null);
  const [loading, setLoading] = useState(true);
  const [assumptions, setAssumptions] = useState(() => Object.fromEntries(STAGES.map((stage) => [stage.id, { hoursPerApplication: stage.effort, capacityPerWeek: stage.capacity }])));
  const [scenarioStage, setScenarioStage] = useState("Interview");
  const [extraCapacity, setExtraCapacity] = useState(4);
  const [effortReduction, setEffortReduction] = useState(20);

  useEffect(() => {
    let active = true;
    apiRequest(token, "get", "/analytics")
      .then((response) => { if (active) setAnalytics(response.data || null); })
      .catch((error) => { if (active) onError(error); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [apiRequest, onError, token]);

  const rows = useMemo(() => STAGES.map((stage) => {
    const count = Math.max(0, Number(analytics?.stage_counts?.[stage.id]) || 0);
    const input = assumptions[stage.id] || { hoursPerApplication: stage.effort, capacityPerWeek: stage.capacity };
    const workload = count * input.hoursPerApplication;
    const baselineWeeks = workload === 0 ? 0 : input.capacityPerWeek > 0 ? workload / input.capacityPerWeek : null;
    const isScenario = stage.id === scenarioStage;
    const scenarioWorkload = isScenario ? workload * (1 - effortReduction / 100) : workload;
    const scenarioWeeklyCapacity = input.capacityPerWeek + (isScenario ? extraCapacity : 0);
    const scenarioWeeks = scenarioWorkload === 0 ? 0 : scenarioWeeklyCapacity > 0 ? scenarioWorkload / scenarioWeeklyCapacity : null;
    return { ...stage, count, ...input, workload, baselineWeeks, scenarioWorkload, scenarioWeeks, isScenario };
  }), [analytics, assumptions, extraCapacity, effortReduction, scenarioStage]);

  const activeApplications = rows.reduce((sum, row) => sum + row.count, 0);
  const totalWorkload = rows.reduce((sum, row) => sum + row.workload, 0);
  const bottleneck = rows.filter((row) => row.count > 0).sort((a, b) => (b.baselineWeeks ?? Number.POSITIVE_INFINITY) - (a.baselineWeeks ?? Number.POSITIVE_INFINITY))[0] || null;
  const scenario = rows.find((row) => row.id === scenarioStage) || rows[0];
  const baselineLabel = (value) => value === null ? "Capacity not set" : `${value.toFixed(1)} wk`;
  const changeHours = (stageId, key, value) => setAssumptions((current) => ({ ...current, [stageId]: { ...current[stageId], [key]: value } }));

  if (loading) return <section className="rounded-xl border border-ink-100 bg-white p-6 text-sm text-ink-500">Loading pipeline snapshot…</section>;
  if (!analytics) return null;

  return (
    <section className="grid gap-5">
      <header>
        <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-500">Planning sandbox</p>
        <h2 className="mt-1 text-xl font-semibold tracking-tight text-ink-950">Hiring-Process Simulator</h2>
        <p className="mt-1 max-w-3xl text-sm leading-6 text-ink-600">Explore how workload assumptions change when you adjust effort or add team capacity. This estimates handling effort for today’s pipeline snapshot; it does not forecast time-to-hire, candidate conversion, or hiring outcomes.</p>
      </header>

      <div className="grid gap-3 sm:grid-cols-3">
        <Metric label="Active pipeline" value={activeApplications} detail="Applications currently in the four open workflow stages" />
        <Metric label="Estimated handling effort" value={`${totalWorkload.toFixed(1)} h`} detail="Uses the editable hours-per-application assumptions below" tone="blue" />
        <Metric label="Most constrained stage" value={bottleneck?.label || "No active applications"} detail={bottleneck ? `${baselineLabel(bottleneck.baselineWeeks)} at its assumed weekly capacity` : "Nothing to simulate yet"} tone="amber" />
      </div>

      <section className="overflow-hidden rounded-xl border border-ink-100 bg-white">
        <div className="border-b border-ink-100 px-4 py-4 sm:px-5"><h3 className="font-semibold text-ink-950">Set your baseline assumptions</h3><p className="mt-1 text-xs leading-5 text-ink-500">The ATS provides current counts by stage. Effort and available hours are your planning inputs and are not measured recruiter performance.</p></div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] text-left text-sm">
            <thead className="bg-[#fafaf8] text-[10px] font-semibold uppercase tracking-wide text-ink-500"><tr><th className="px-4 py-3">Stage</th><th className="px-4 py-3">Current applications</th><th className="px-4 py-3">Hours per application</th><th className="px-4 py-3">Team hours per week</th><th className="px-4 py-3">Effort at capacity</th></tr></thead>
            <tbody>{rows.map((row) => <tr key={row.id} className="border-t border-ink-100"><td className="px-4 py-3 font-medium">{row.label}</td><td className="px-4 py-3 tabular-nums">{row.count}</td><td className="px-4 py-3">{numberInput(row.hoursPerApplication, (value) => changeHours(row.id, "hoursPerApplication", value), { max: 80, step: 0.25, label: `${row.label} effort hours per application` })}</td><td className="px-4 py-3">{numberInput(row.capacityPerWeek, (value) => changeHours(row.id, "capacityPerWeek", value), { max: 500, step: 1, label: `${row.label} team hours per week` })}</td><td className="px-4 py-3 font-semibold tabular-nums">{baselineLabel(row.baselineWeeks)}</td></tr>)}</tbody>
          </table>
        </div>
      </section>

      <section className="grid gap-5 rounded-xl border border-blue-100 bg-blue-50/50 p-4 sm:p-5 lg:grid-cols-[minmax(0,1fr)_minmax(240px,0.8fr)]">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-wide text-blue-700">What-if scenario</p>
          <h3 className="mt-1 text-lg font-semibold text-ink-950">Change one stage’s workload</h3>
          <p className="mt-1 text-xs leading-5 text-ink-600">Apply extra weekly capacity and/or reduce effort for one stage. The rest of the pipeline remains unchanged.</p>
          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            <label className="grid gap-1.5 text-xs font-semibold text-ink-700">Stage to change
              <select className="rounded-md border border-ink-200 bg-white px-2.5 py-2 text-sm" value={scenarioStage} onChange={(event) => setScenarioStage(event.target.value)}>{STAGES.map((stage) => <option key={stage.id} value={stage.id}>{stage.label}</option>)}</select>
            </label>
            <label className="grid gap-1.5 text-xs font-semibold text-ink-700">Additional hours per week
              {numberInput(extraCapacity, setExtraCapacity, { max: 100, step: 1, label: "Additional weekly capacity for selected stage" })}
            </label>
            <label className="grid gap-1.5 text-xs font-semibold text-ink-700">Effort reduction
              {numberInput(effortReduction, setEffortReduction, { max: 80, step: 5, label: "Effort reduction percentage for selected stage" })}
            </label>
          </div>
        </div>
        <div className="rounded-lg border border-blue-100 bg-white p-4">
          <p className="text-xs font-semibold text-ink-700">Scenario result · {scenario?.label}</p>
          <div className="mt-3 grid grid-cols-2 gap-3">
            <div><p className="text-[10px] uppercase tracking-wide text-ink-500">Baseline effort</p><p className="mt-1 text-xl font-semibold tabular-nums text-ink-900">{baselineLabel(scenario?.baselineWeeks)}</p></div>
            <div><p className="text-[10px] uppercase tracking-wide text-ink-500">Scenario effort</p><p className="mt-1 text-xl font-semibold tabular-nums text-blue-800">{baselineLabel(scenario?.scenarioWeeks)}</p></div>
          </div>
          {scenario?.baselineWeeks !== null && scenario?.scenarioWeeks !== null && scenario?.baselineWeeks > scenario?.scenarioWeeks
            ? <p className="mt-3 text-xs leading-5 text-emerald-800">About {(scenario.baselineWeeks - scenario.scenarioWeeks).toFixed(1)} fewer stage-work weeks under these assumptions.</p>
            : <p className="mt-3 text-xs leading-5 text-ink-500">Adjust capacity or effort above to compare a different scenario.</p>}
        </div>
      </section>

      <p className="text-[11px] leading-5 text-ink-500">Stage counts are a current snapshot, not a cohort conversion funnel. Workloads at different stages can overlap in time; the estimates are planning aids and should not be treated as service-level promises or individual performance metrics.</p>
    </section>
  );
}

