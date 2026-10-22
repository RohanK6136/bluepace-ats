import { useCallback, useEffect, useState } from "react";

const panelCard = "rounded-xl border border-ink-100 bg-white p-5 shadow-sm";
const stateLabel = (enabled) => enabled ? "Configured" : "Needs setup";

function StatusPill({ enabled, label }) {
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-semibold ${enabled ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-800"}`}>
      {label || stateLabel(enabled)}
    </span>
  );
}

export default function ZohoRecruitPanel({ token, apiRequest, onNotice, onError }) {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [lastSync, setLastSync] = useState(null);

  const loadStatus = useCallback(async () => {
    setLoading(true);
    try {
      const response = await apiRequest(token, "get", "/integrations/zoho/status");
      setStatus(response.data);
      onError?.(null);
    } catch (error) {
      setStatus(null);
      onError?.(error);
    } finally {
      setLoading(false);
    }
  }, [token, apiRequest, onError]);

  useEffect(() => { void loadStatus(); }, [loadStatus]);

  async function runSync() {
    setSyncing(true);
    try {
      const response = await apiRequest(token, "post", "/integrations/zoho/sync", { data: {} });
      setLastSync(response.data);
      onNotice?.(`Zoho reconciliation completed: ${response.data?.candidates_synced ?? 0} candidates and ${response.data?.jobs_synced ?? 0} jobs processed.`);
      onError?.(null);
      await loadStatus();
    } catch (error) {
      onError?.(error);
    } finally {
      setSyncing(false);
    }
  }

  return (
    <section className="space-y-5" aria-labelledby="zoho-title">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-ink-500">Connected systems</p>
          <h2 id="zoho-title" className="mt-1 text-2xl font-semibold tracking-tight text-ink-950">Zoho Recruit</h2>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-ink-600">Bring candidate and job-opening records from Zoho Recruit into BluePace ATS. Credentials stay on the backend; this screen never displays tokens or secrets.</p>
        </div>
        <button type="button" onClick={() => void loadStatus()} disabled={loading} className="rounded-md border border-ink-200 bg-white px-3 py-2 text-sm font-semibold text-ink-700 hover:bg-ink-50 disabled:opacity-50">
          {loading ? "Checking…" : "Refresh status"}
        </button>
      </header>

      {status && (
        <div className="grid gap-3 sm:grid-cols-3">
          <div className={panelCard}>
            <p className="text-xs font-semibold uppercase tracking-wide text-ink-500">API credentials</p>
            <div className="mt-3"><StatusPill enabled={status.configured} /></div>
            <p className="mt-2 text-sm text-ink-600">OAuth refresh flow for server-side API access.</p>
          </div>
          <div className={panelCard}>
            <p className="text-xs font-semibold uppercase tracking-wide text-ink-500">Automatic reconciliation</p>
            <div className="mt-3"><StatusPill enabled={status.automatic_sync_enabled} label={status.automatic_sync_enabled ? "Enabled" : "Disabled"} /></div>
            <p className="mt-2 text-sm text-ink-600">Runs every {status.reconciliation_interval_minutes || 15} minutes when enabled.</p>
          </div>
          <div className={panelCard}>
            <p className="text-xs font-semibold uppercase tracking-wide text-ink-500">Webhook receiver</p>
            <div className="mt-3"><StatusPill enabled={status.webhook_configured} /></div>
            <p className="mt-2 break-all text-sm text-ink-600">{status.webhook_url || "/integrations/zoho/webhook"}</p>
          </div>
        </div>
      )}

      <div className={panelCard}>
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h3 className="text-base font-semibold text-ink-950">Sync Zoho data</h3>
            <p className="mt-1 max-w-2xl text-sm leading-6 text-ink-600">A manual sync fetches canonical records through Zoho OAuth and reconciles candidates and job openings. Webhook payloads are treated only as a trigger, not as trusted record data.</p>
          </div>
          <button type="button" onClick={() => void runSync()} disabled={syncing || loading || !status?.configured} className="inline-flex shrink-0 items-center justify-center rounded-md bg-ink-950 px-4 py-2.5 text-sm font-semibold text-white hover:bg-ink-800 disabled:cursor-not-allowed disabled:opacity-50">
            {syncing ? "Syncing…" : "Run sync now"}
          </button>
        </div>
        {!status?.configured && !loading && (
          <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-4">
            <p className="text-sm font-semibold text-amber-900">Backend configuration required</p>
            <p className="mt-1 text-sm leading-6 text-amber-900">Add the following variables to the BluePace FastAPI backend service in Railway. Never put these values in the frontend.</p>
            <code className="mt-3 block whitespace-pre-wrap break-words text-xs leading-6 text-amber-950">ZOHO_CLIENT_ID\nZOHO_CLIENT_SECRET\nZOHO_REFRESH_TOKEN\nZOHO_ACCOUNTS_DOMAIN=in\nZOHO_RECRUIT_API_BASE=https://recruit.zoho.in/recruit/v2</code>
            <p className="mt-2 text-xs leading-5 text-amber-900">For scheduled sync, also set ZOHO_SYNC_ENABLED=true and ZOHO_ORGANIZATION_ID to the intended ATS organization ID. For webhooks, set a long random ZOHO_WEBHOOK_SECRET and configure the same token in Zoho Recruit.</p>
          </div>
        )}
        {lastSync && (
          <p className="mt-4 text-xs text-ink-500" role="status">Last manual sync completed at {lastSync.completed_at ? new Date(lastSync.completed_at).toLocaleString() : "just now"}.</p>
        )}
      </div>

      <div className={panelCard}>
        <h3 className="text-base font-semibold text-ink-950">Production safeguards</h3>
        <ul className="mt-3 grid gap-2 text-sm leading-6 text-ink-600 sm:grid-cols-2">
          <li>• OAuth tokens remain server-side.</li>
          <li>• Only admin and recruiter roles can trigger a sync.</li>
          <li>• External record IDs are mapped to avoid duplicate imports.</li>
          <li>• Webhook tokens are compared securely before reconciliation.</li>
          <li>• Zoho rate limits are surfaced as retryable service errors.</li>
          <li>• Sync direction is Zoho Recruit → BluePace ATS.</li>
        </ul>
      </div>
    </section>
  );
}
