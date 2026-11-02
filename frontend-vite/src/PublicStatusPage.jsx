import { useCallback, useEffect, useState } from "react";

function frontendCommit() {
  return document.querySelector('meta[name="bluepace-build-commit"]')?.getAttribute("content") || "unknown";
}

async function getJson(url) {
  const response = await fetch(url, { cache: "no-store", headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

function StatusCard({ label, state, detail }) {
  const badge = state === "ok"
    ? "border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-200"
    : state === "checking"
      ? "border-slate-200 bg-slate-50 text-slate-700 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200"
      : "border-rose-200 bg-rose-50 text-rose-800 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-200";
  return (
    <article className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">{label}</h2>
        <span className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${badge}`}>
          {state === "ok" ? "Operational" : state === "checking" ? "Checking" : "Needs attention"}
        </span>
      </div>
      <p className="mt-3 text-sm leading-6 text-slate-600 dark:text-slate-300">{detail}</p>
    </article>
  );
}

export default function PublicStatusPage({ apiUrl, theme = "light", onToggleTheme }) {
  const pending = { state: "checking", detail: "Checking…" };
  const [checks, setChecks] = useState({ api: pending, database: pending, vacancies: pending, backendVersion: pending });
  const [checking, setChecking] = useState(false);
  const [lastChecked, setLastChecked] = useState(null);

  const refresh = useCallback(async () => {
    setChecking(true);
    const [api, database, vacancies, backendVersion] = await Promise.all([
      getJson(`${apiUrl}/healthz`)
        .then((v) => v?.status === "ok" && v?.service === "bluepace-ats"
          ? { state: "ok", detail: "The BluePace ATS API is responding." }
          : { state: "error", detail: "The health endpoint returned an unexpected response." })
        .catch((e) => ({ state: "error", detail: `The ATS API could not be reached: ${e.message}` })),
      getJson(`${apiUrl}/readyz`)
        .then((v) => v?.status === "ready"
          ? { state: "ok", detail: "The API can connect to its configured database." }
          : { state: "error", detail: "The database readiness check returned an unexpected response." })
        .catch((e) => ({ state: "error", detail: `Database readiness failed: ${e.message}` })),
      getJson(`${apiUrl}/public/jobs?limit=1&offset=0`)
        .then((v) => Array.isArray(v)
          ? { state: "ok", detail: "The live vacancies endpoint is reachable. An empty array is valid when no genuine open roles are published." }
          : { state: "error", detail: "The vacancies endpoint did not return a JSON array." })
        .catch((e) => ({ state: "error", detail: `The vacancies feed could not be read: ${e.message}` })),
      getJson(`${apiUrl}/version`)
        .then((v) => {
          if (v?.service !== "bluepace-ats") return { state: "error", detail: "Unexpected backend service identity." };
          if (!/^[a-f0-9]{40}$/i.test(v.commit || "")) return { state: "error", detail: "Backend responds, but its deployed Git commit is unavailable." };
          return { state: "ok", detail: `Backend commit ${v.commit.slice(0, 12)} on ${v.branch || "unknown"}.` };
        })
        .catch((e) => ({ state: "error", detail: `Backend deployment identity is unavailable: ${e.message}` })),
    ]);
    setChecks({ api, database, vacancies, backendVersion });
    setLastChecked(new Date());
    setChecking(false);
  }, [apiUrl]);

  useEffect(() => { void refresh(); }, [refresh]);

  const commit = frontendCommit();
  const passed = Object.values(checks).filter((v) => v.state === "ok").length;
  const failed = Object.values(checks).some((v) => v.state === "error");
  const allChecked = Object.values(checks).every((v) => v.state !== "checking");
  const overallState = failed ? "error" : allChecked && passed === 4 ? "ok" : "checking";

  return (
    <main className="min-h-screen bg-slate-50 px-5 py-8 text-slate-900 dark:bg-slate-950 dark:text-slate-100 sm:py-12">
      <div className="mx-auto max-w-5xl">
        <header className="flex flex-wrap items-center justify-between gap-4">
          <a href="/" className="inline-flex items-center gap-3 font-semibold no-underline">
            <span className="grid h-10 w-10 place-items-center rounded-lg bg-slate-950 text-sm font-bold text-amber-300 dark:bg-slate-800">BP</span>
            <span>BluePace <span className="font-normal text-slate-500 dark:text-slate-400">Status</span></span>
          </a>
          <div className="flex items-center gap-2">
            <button type="button" onClick={onToggleTheme} aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"} aria-pressed={theme === "dark"} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800">
              {theme === "dark" ? "Light theme" : "Dark theme"}
            </button>
            <a href="/" className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 no-underline hover:bg-slate-100 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-900">Careers portal</a>
          </div>
        </header>

        <section className="mt-10 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-slate-900 sm:p-8">
          <p className="text-xs font-bold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">Production verification</p>
          <div className="mt-3 flex flex-wrap items-center justify-between gap-4">
            <div>
              <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">BluePace service status</h1>
              <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600 dark:text-slate-300">Live checks for the frontend, ATS API, database readiness and genuine public vacancies.</p>
            </div>
            <span className={`rounded-full border px-3 py-1.5 text-sm font-semibold ${failed ? "border-rose-200 bg-rose-50 text-rose-800 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-200" : "border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-200"}`}>
              {passed}/4 checks passed
            </span>
          </div>
          <div className="mt-6 grid gap-3 sm:grid-cols-2">
            <div className="rounded-lg bg-slate-50 p-4 dark:bg-slate-950">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">Frontend build commit</p>
              <p className="mt-2 break-all font-mono text-sm text-slate-800 dark:text-slate-200">{commit}</p>
            </div>
            <div className="rounded-lg bg-slate-50 p-4 dark:bg-slate-950">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">Last checked</p>
              <p className="mt-2 text-sm text-slate-800 dark:text-slate-200">{lastChecked ? lastChecked.toLocaleString() : "Checking…"}</p>
            </div>
          </div>
        </section>

        <section className="mt-5 grid gap-4 sm:grid-cols-2" aria-live="polite">
          <StatusCard label="ATS API" {...checks.api} />
          <StatusCard label="Database readiness" {...checks.database} />
          <StatusCard label="Public vacancies feed" {...checks.vacancies} />
          <StatusCard label="Backend deployment identity" {...checks.backendVersion} />
        </section>

        <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
          <p className="text-xs text-slate-500 dark:text-slate-400">This page checks connectivity and release identity. It does not expose recruiter or candidate records.</p>
          <button type="button" onClick={() => void refresh()} disabled={checking} className="rounded-lg bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white hover:bg-slate-700 disabled:cursor-wait disabled:opacity-60 dark:bg-slate-100 dark:text-slate-950 dark:hover:bg-white">
            {checking ? "Checking…" : "Refresh checks"}
          </button>
        </div>
      </div>
    </main>
  );
}
