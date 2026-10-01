import { useEffect, useState } from "react";

const buttonPrimary = "inline-flex items-center justify-center rounded-md bg-[#c49a4a] px-4 py-2 text-sm font-semibold text-[#10131c] disabled:opacity-50";
const buttonSecondary = "inline-flex items-center justify-center rounded-md border border-ink-100 bg-white px-4 py-2 text-sm font-semibold text-ink-800 disabled:opacity-50";

export default function CalendarIntegrations({ token, apiRequest, onNotice, onError }) {
  const [connections, setConnections] = useState([]);
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    try {
      const response = await apiRequest(token, "get", "/calendar/connections");
      setConnections(response.data || []);
    } catch (error) {
      onError(error);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    const params = new URLSearchParams(window.location.search);
    if (params.get("calendar") === "connected") {
      onNotice((params.get("provider") === "microsoft" ? "Microsoft Outlook / 365" : "Google Calendar") + " connected successfully.");
      window.history.replaceState({}, "", window.location.pathname + "?mode=admin");
    } else if (params.get("calendar") === "error") {
      onError({ message: params.get("message") || "Calendar connection failed." });
      window.history.replaceState({}, "", window.location.pathname + "?mode=admin");
    }
  }, []);

  async function connect(provider) {
    try {
      const response = await apiRequest(token, "get", "/calendar/oauth/" + provider + "/start");
      window.location.href = response.data.authorization_url;
    } catch (error) {
      onError(error);
    }
  }

  async function makeDefault(id) {
    try {
      await apiRequest(token, "patch", "/calendar/connections/" + id + "/default");
      await load();
      onNotice("Default calendar provider updated.");
    } catch (error) {
      onError(error);
    }
  }

  async function disconnect(connection) {
    const name = connection.provider === "microsoft" ? "Microsoft Outlook / 365" : "Google Calendar";
    if (!window.confirm("Disconnect " + name + "? Existing calendar events will remain in the provider calendar.")) return;
    try {
      await apiRequest(token, "delete", "/calendar/connections/" + connection.id);
      await load();
      onNotice("Calendar connection disconnected.");
    } catch (error) {
      onError(error);
    }
  }

  return (
    <section className="space-y-5">
      <div>
        <p className="text-sm text-ink-500">Scheduling integrations</p>
        <h2 className="mt-1 text-2xl font-semibold">Google Calendar / Outlook</h2>
        <p className="mt-1 max-w-3xl text-sm leading-6 text-ink-500">
          Connect a recruiter calendar once. BluePace will create, update and remove real calendar events for scheduled interviews.
          Interviewers and candidates are added as attendees, and Google Meet or Microsoft Teams links can be generated automatically.
        </p>
      </div>

      <div className="grid gap-5 md:grid-cols-2">
        <div className="rounded-xl border border-ink-100 bg-white p-5">
          <div className="flex items-start justify-between gap-4">
            <div><h3 className="font-semibold">Google Calendar</h3><p className="mt-1 text-xs text-ink-500">Google Calendar + Google Meet</p></div>
            <span className="rounded-full bg-blue-50 px-2 py-1 text-xs font-semibold text-blue-800">OAuth 2.0</span>
          </div>
          <p className="mt-4 text-sm text-ink-600">Creates events on the connected primary calendar and can request a unique Google Meet conference for each online interview.</p>
          <button className={buttonPrimary + " mt-5"} onClick={() => connect("google")}>Connect Google Calendar</button>
        </div>

        <div className="rounded-xl border border-ink-100 bg-white p-5">
          <div className="flex items-start justify-between gap-4">
            <div><h3 className="font-semibold">Microsoft Outlook / 365</h3><p className="mt-1 text-xs text-ink-500">Outlook Calendar + Microsoft Teams</p></div>
            <span className="rounded-full bg-blue-50 px-2 py-1 text-xs font-semibold text-blue-800">OAuth 2.0</span>
          </div>
          <p className="mt-4 text-sm text-ink-600">Creates Outlook calendar events and can enable Microsoft Teams online meetings where the connected calendar supports Teams.</p>
          <button className={buttonPrimary + " mt-5"} onClick={() => connect("microsoft")}>Connect Outlook / 365</button>
        </div>
      </div>

      <div className="rounded-xl border border-ink-100 bg-white p-5">
        <div className="flex items-center justify-between gap-3">
          <div><h3 className="font-semibold">Connected calendars</h3><p className="mt-1 text-xs text-ink-500">The default connection receives new interview events.</p></div>
          <button className={buttonSecondary} onClick={load} disabled={loading}>{loading ? "Refreshing…" : "Refresh"}</button>
        </div>
        <div className="mt-4 divide-y divide-ink-50">
          {connections.map((connection) => (
            <div key={connection.id} className="flex flex-wrap items-center justify-between gap-4 py-4">
              <div>
                <div className="flex items-center gap-2">
                  <p className="font-semibold">{connection.provider === "microsoft" ? "Microsoft Outlook / 365" : "Google Calendar"}</p>
                  {connection.is_default && <span className="rounded-full bg-emerald-50 px-2 py-1 text-xs font-semibold text-emerald-700">Default</span>}
                </div>
                <p className="mt-1 text-sm text-ink-600">{connection.account_email || connection.display_name || "Connected account"}</p>
                {connection.last_error && <p className="mt-1 text-xs text-rose-700">{connection.last_error}</p>}
              </div>
              <div className="flex gap-2">
                {!connection.is_default && connection.is_active && <button className={buttonSecondary} onClick={() => makeDefault(connection.id)}>Make default</button>}
                <button className={buttonSecondary} onClick={() => disconnect(connection)}>Disconnect</button>
              </div>
            </div>
          ))}
          {!connections.length && !loading && <p className="py-8 text-center text-sm text-ink-500">No calendar is connected yet.</p>}
        </div>
      </div>

      <div className="rounded-xl border border-blue-100 bg-blue-50 p-5 text-sm text-blue-950">
        <p className="font-semibold">How interview sync works</p>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-blue-900">
          <li>Schedule interview → create a real calendar event.</li>
          <li>Reschedule → update the same event instead of creating a duplicate.</li>
          <li>Cancel → remove the provider event.</li>
          <li>Panel interview → interviewer emails are added as attendees automatically.</li>
          <li>Online interview without a link → Google Meet or Microsoft Teams is generated when the provider supports it.</li>
          <li>Existing <code>.ics</code> download endpoints remain available as a manual fallback.</li>
        </ul>
      </div>
    </section>
  );
}
