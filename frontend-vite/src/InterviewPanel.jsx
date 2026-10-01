import { useEffect, useState } from "react";

const input = "w-full rounded-md border border-ink-100 bg-white px-3 py-2 text-sm";
const primary = "rounded-md bg-[#1769d3] px-3 py-2 text-sm font-semibold text-white disabled:opacity-50";
const secondary = "rounded-md border border-ink-100 bg-white px-3 py-2 text-sm font-semibold text-ink-800 disabled:opacity-50";

export default function InterviewPanel({ token, applications = [], apiRequest, onNotice, onError }) {
  const [applicationId, setApplicationId] = useState(applications[0]?.id ? String(applications[0].id) : "");
  const [interviews, setInterviews] = useState([]);
  const [users, setUsers] = useState([]);
  const [participants, setParticipants] = useState({});
  const [selectedUser, setSelectedUser] = useState({});
  const [reschedule, setReschedule] = useState({});
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setApplicationId(applications[0]?.id ? String(applications[0].id) : "");
  }, [applications]);

  useEffect(() => {
    apiRequest(token, "get", "/recruiting-users")
      .then((response) => setUsers(response.data || []))
      .catch(onError);
  }, [token]);

  async function load() {
    if (!applicationId) return;
    setLoading(true);
    try {
      const response = await apiRequest(token, "get", "/applications/" + applicationId + "/interviews");
      const rows = response.data || [];
      setInterviews(rows);
      const participantMap = {};
      await Promise.all(rows.map(async (row) => {
        try {
          const p = await apiRequest(token, "get", "/interviews/" + row.id + "/participants");
          participantMap[row.id] = p.data || [];
        } catch (error) { onError(error); }
      }));
      setParticipants(participantMap);
    } catch (error) { onError(error); }
    finally { setLoading(false); }
  }

  useEffect(() => { load(); }, [applicationId]);

  async function addParticipant(interviewId) {
    const userId = Number(selectedUser[interviewId]);
    if (!userId) return;
    try {
      const response = await apiRequest(token, "post", "/interviews/" + interviewId + "/participants", { data: { user_id: userId } });
      setParticipants((current) => ({ ...current, [interviewId]: [...(current[interviewId] || []).filter((item) => item.user_id !== response.data.user_id), response.data] }));
      setSelectedUser((current) => ({ ...current, [interviewId]: "" }));
      onNotice("Interviewer added to panel");
    } catch (error) { onError(error); }
  }

  async function removeParticipant(interviewId, userId) {
    try {
      await apiRequest(token, "delete", "/interviews/" + interviewId + "/participants/" + userId);
      setParticipants((current) => ({ ...current, [interviewId]: (current[interviewId] || []).filter((item) => item.user_id !== userId) }));
      onNotice("Interviewer removed");
    } catch (error) { onError(error); }
  }

  async function saveReschedule(interview) {
    const form = reschedule[interview.id];
    if (!form?.starts_at) return;
    try {
      await apiRequest(token, "patch", "/interviews/" + interview.id, {
        data: {
          starts_at: new Date(form.starts_at).toISOString(),
          duration_minutes: Number(form.duration_minutes || interview.duration_minutes),
          mode: form.mode || interview.mode,
          location: form.mode === "offline" ? form.location : null,
          meeting_url: form.mode === "online" ? form.meeting_url : null,
          round_name: form.round_name || interview.round_name,
        },
      });
      onNotice("Interview rescheduled and candidate notified");
      await load();
    } catch (error) { onError(error); }
  }

  async function cancel(interviewId) {
    if (!window.confirm("Cancel this interview and notify the candidate?")) return;
    try {
      await apiRequest(token, "post", "/interviews/" + interviewId + "/cancel");
      onNotice("Interview cancelled");
      await load();
    } catch (error) { onError(error); }
  }

  function update(id, patch) {
    setReschedule((current) => ({ ...current, [id]: { ...(current[id] || {}), ...patch } }));
  }

  const selected = applications.find((item) => item.id === Number(applicationId));

  return (
    <section className="mt-6 border-t border-ink-100 pt-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div><p className="text-xs font-semibold uppercase tracking-[0.18em] text-blue-700">ATS 3.0</p><h4 className="mt-1 font-semibold">Interview command center</h4></div>
        <select className={input + " min-w-72"} value={applicationId} onChange={(e) => setApplicationId(e.target.value)}>{applications.map((item) => <option key={item.id} value={item.id}>#{item.id} · {item.job_title} · {item.candidate.first_name} {item.candidate.last_name}</option>)}</select>
      </div>

      <div className="mt-4 grid gap-4">
        {!selected && <p className="text-sm text-ink-500">No application selected.</p>}
        {loading && <p className="text-sm text-ink-500">Loading interview rounds…</p>}
        {interviews.map((interview) => {
          const form = reschedule[interview.id] || {
            starts_at: new Date(interview.starts_at).toISOString().slice(0,16),
            duration_minutes: String(interview.duration_minutes),
            mode: interview.mode,
            location: interview.location || "",
            meeting_url: interview.meeting_url || "",
            round_name: interview.round_name || "",
          };
          const panel = participants[interview.id] || [];
          return (
            <article key={interview.id} className="rounded-xl border border-ink-100 bg-white p-5">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div><p className="font-semibold">Round {interview.round_number} · {interview.round_name}</p><p className="mt-1 text-sm text-ink-500">{new Date(interview.starts_at).toLocaleString()} · {interview.status}</p></div>
                <div className="flex gap-2"><a className="text-sm font-semibold underline" href={"/interviews/" + interview.id + "/ics"}>Calendar</a>{interview.status === "scheduled" && <button className={secondary} onClick={() => cancel(interview.id)}>Cancel</button>}</div>
              </div>
              <div className="mt-4 grid gap-4 lg:grid-cols-2">
                <div className="rounded-lg bg-[#fafaf8] p-4">
                  <p className="text-xs font-semibold uppercase text-ink-500">Interview panel</p>
                  <div className="mt-3 flex flex-wrap gap-2">{panel.map((person) => <span key={person.user_id} className="inline-flex items-center gap-1 rounded-full bg-blue-50 px-3 py-1 text-xs font-semibold text-blue-800">{person.full_name} <button type="button" className="font-bold" onClick={() => removeParticipant(interview.id, person.user_id)}>×</button></span>)}{!panel.length && <span className="text-xs text-ink-500">No additional panel members.</span>}</div>
                  <div className="mt-3 flex gap-2"><select className={input} value={selectedUser[interview.id] || ""} onChange={(e) => setSelectedUser({...selectedUser,[interview.id]:e.target.value})}><option value="">Add interviewer…</option>{users.filter((person) => !panel.some((item) => item.user_id === person.id)).map((person) => <option key={person.id} value={person.id}>{person.full_name} · {person.role}</option>)}</select><button className={primary} onClick={() => addParticipant(interview.id)}>Add</button></div>
                </div>
                {interview.status === "scheduled" && (
                  <div className="rounded-lg bg-[#fafaf8] p-4">
                    <p className="text-xs font-semibold uppercase text-ink-500">Reschedule</p>
                    <div className="mt-3 grid gap-2 sm:grid-cols-2">
                      <input className={input} type="datetime-local" value={form.starts_at} onChange={(e) => update(interview.id,{starts_at:e.target.value})} />
                      <input className={input} type="number" min="15" max="480" value={form.duration_minutes} onChange={(e) => update(interview.id,{duration_minutes:e.target.value})} />
                      <select className={input} value={form.mode} onChange={(e) => update(interview.id,{mode:e.target.value,location:"",meeting_url:""})}><option value="online">Online</option><option value="offline">Offline</option></select>
                      <input className={input} value={form.round_name} onChange={(e) => update(interview.id,{round_name:e.target.value})} placeholder="Round name" />
                      {form.mode === "online" ? <input className={input + " sm:col-span-2"} value={form.meeting_url} onChange={(e) => update(interview.id,{meeting_url:e.target.value})} placeholder="Meeting link" /> : <input className={input + " sm:col-span-2"} value={form.location} onChange={(e) => update(interview.id,{location:e.target.value})} placeholder="Location" />}
                    </div>
                    <button className={primary + " mt-3"} onClick={() => saveReschedule(interview)}>Save reschedule</button>
                  </div>
                )}
              </div>
            </article>
          );
        })}
        {!loading && !interviews.length && <p className="rounded-xl border border-dashed border-ink-100 bg-white p-8 text-center text-sm text-ink-500">No interview rounds are scheduled for this application.</p>}
      </div>
    </section>
  );
}
