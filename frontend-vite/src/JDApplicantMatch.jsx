import { useCallback, useEffect, useId, useRef, useState } from "react";
import { buildBulkMatchCsv, getBulkMatchConcurrency, getBulkBatchStopReason, getBulkResultStopReason, MAX_BULK_RESUMES, runWithConcurrency, validateBulkResume } from "./bulkMatchUtils.mjs";
import { deleteBulkQueue, loadBulkQueue, moveBulkQueue, saveBulkQueue } from "./bulkQueueStorage.mjs";
import { extractJdTextFromResult, getJdUploadError, normalizeJdText, normalizeJdPublicationGate, getUnsupportedJdOptionFields, formatJdValidationErrors, removeUnsupportedRubricMetadata, getUnsupportedFormFields } from "./jdUploadUtils.mjs";
import { getLoopbackNetworkPermission, localAiPermissionHelp, localAiServiceHelp } from "./localNetworkAccess.mjs";
import { readSavedRubrics, writeSavedRubrics } from "./savedRubricStorage.mjs";
import { unwrapRubricDraft } from "./matchRubricUtils.mjs";
import { buildSourceGroundedRubric } from "./rubricFallback.mjs";
import { SAMPLE_JOB_DESCRIPTION, SAMPLE_MANUAL_REFERENCE, SAMPLE_RESUME_TEXT } from "./sampleApplicantMatchScenario.mjs";
import MatchAssessmentInsights from "./MatchAssessmentInsights.jsx";

const primaryButton = "inline-flex items-center justify-center gap-2 rounded-md bg-[#c49a4a] px-4 py-2.5 text-sm font-semibold text-[#11141c] transition hover:bg-[#d4b06a] disabled:cursor-not-allowed disabled:opacity-50";
const secondaryButton = "inline-flex items-center justify-center gap-2 rounded-md border border-ink-200 bg-white px-3 py-2 text-sm font-semibold text-ink-800 transition hover:bg-ink-50 disabled:cursor-not-allowed disabled:opacity-50";
const fieldClass = "w-full rounded-md border border-ink-200 bg-white px-3 py-2.5 text-sm text-ink-900 outline-none placeholder:text-ink-400 focus:border-gold-500 focus:ring-2 focus:ring-gold-100";
const MAX_FILE_BYTES = 5 * 1024 * 1024;
const REVIEW_STAGES = [
  ["new", "New"],
  ["reviewing", "Reviewing"],
  ["interview", "Interview"],
  ["decision", "Decision"],
];
const WORKSPACE_STORAGE_KEY = "bluepace_jd_match_workspaces_v1";
const ACTIVE_WORKSPACE_KEY = "bluepace_jd_match_active_workspace_v1";
const UNSAVED_BULK_QUEUE_ID = "__unsaved_workspace__";
const LOCAL_AI_API_STORAGE_KEY = "bluepace_jd_match_local_ai_api_v1";
const DEFAULT_LOCAL_AI_API_URL = "http://127.0.0.1:8000";

function normalizeLocalAiApiUrl(value) {
  let parsed;
  try {
    parsed = new URL(String(value || "").trim());
  } catch {
    throw new Error("This is the optional local Ollama API URL, not your work email. Enter http://127.0.0.1:8000 only after starting the local AI service, or use hosted AI instead.");
  }
  const host = parsed.hostname.replace(/^\[|\]$/g, "").toLowerCase();
  if (parsed.protocol !== "http:" || !["localhost", "127.0.0.1", "::1"].includes(host)
      || parsed.username || parsed.password || parsed.search || parsed.hash || !["", "/"].includes(parsed.pathname)) {
    throw new Error("For safety, the local AI URL must be an HTTP loopback address such as http://127.0.0.1:8000.");
  }
  return parsed.origin;
}

function readSavedLocalAiApiUrl() {
  try {
    const value = localStorage.getItem(LOCAL_AI_API_STORAGE_KEY) || "";
    return value ? normalizeLocalAiApiUrl(value) : "";
  } catch {
    return "";
  }
}

function readWorkspaces() {
  try {
    const value = JSON.parse(localStorage.getItem(WORKSPACE_STORAGE_KEY) || "[]");
    return Array.isArray(value) ? value : [];
  } catch { return []; }
}
function readActiveWorkspace() {
  try {
    const id = localStorage.getItem(ACTIVE_WORKSPACE_KEY);
    return readWorkspaces().find((workspace) => workspace.id === id) || null;
  } catch { return null; }
}

function workspaceJdDetail(workspace) {
  // Workspaces created before the concise-default release stored "detailed"
  // even when the recruiter never changed the old default. Migrate them once.
  return workspace?.jdDetailVersion === 1 && workspace.jdDetail === "detailed"
    ? "detailed"
    : "concise";
}
function writeWorkspaces(rows) {
  try {
    localStorage.setItem(WORKSPACE_STORAGE_KEY, JSON.stringify(rows.slice(0, 40)));
    return true;
  } catch { return false; }
}
function newWorkspaceId() {
  return globalThis.crypto?.randomUUID?.() || `workspace-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}
function savedApplicantRows(batchRows) {
  return batchRows
    .filter((row) => (row.status !== "queued" && row.status !== "processing") || row.followUpAt)
    .map((row) => ({
      id: row.id,
      fileName: row.file?.name || row.fileName || "Applicant resume",
      fileSize: Number(row.file?.size || row.fileSize || 0),
      status: row.status,
      result: row.result || null,
      error: row.error || "",
      reviewStage: row.reviewStage || "new",
      reviewHistory: Array.isArray(row.reviewHistory) ? row.reviewHistory : [],
      followUpAt: row.followUpAt || "",
      followUpNote: row.followUpNote || "",
    }));
}
function workspaceProgress(workspace) {
  const hasJD = Boolean(normalizeJdText(workspace.jdText).trim() || workspace.jdResult);
  const hasRubric = Boolean(workspace.rubric?.items?.length);
  const applicantCount = (workspace.applicants || []).filter((row) => row.result).length + (workspace.candidateCard ? 1 : 0);
  return `${hasJD ? "JD ✓" : "JD —"} · ${hasRubric ? "Rubric ✓" : "Rubric —"} · ${applicantCount} applicant${applicantCount === 1 ? "" : "s"}`;
}
function appendReviewEvent(history, event) {
  return [...(Array.isArray(history) ? history : []), { ...event, at: new Date().toISOString() }].slice(-200);
}
function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character]);
}
function reportAnchor(value) {
  return String(value || "item").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "item";
}
function latestReviewerRatings(item) {
  const latest = new Map();
  for (const rating of Array.isArray(item?.reviewer_ratings) ? item.reviewer_ratings : []) {
    const name = String(rating.reviewer || "").trim();
    if (name) latest.set(name.toLowerCase(), { ...rating, reviewer: name });
  }
  return Array.from(latest.values());
}
function hasReviewerDisagreement(item) {
  return new Set(latestReviewerRatings(item).map((rating) => rating.status)).size > 1;
}
function localDateValue(date = new Date()) {
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}
function followUpState(date) {
  if (!date) return "none";
  const today = localDateValue();
  if (date < today) return "overdue";
  if (date === today) return "today";
  const week = localDateValue(new Date(Date.now() + 7 * 24 * 60 * 60 * 1000));
  return date <= week ? "upcoming" : "later";
}
function formatLocalDate(date) {
  if (!date) return "";
  const parsed = new Date(`${date}T00:00:00`);
  return Number.isNaN(parsed.getTime()) ? date : parsed.toLocaleDateString();
}

function savedRubricOption(row) {
  return {
    rubric_id: row.rubric_id,
    title: row.title || null,
    items: Array.isArray(row.items) ? row.items.length : Math.max(0, Number(row.items) || 0),
    created_at: row.created_at || null,
  };
}
function sessionProviderKey(provider) {
  try {
    const key = sessionStorage.getItem("bluepace_ai_" + provider + "_key");
    if (key) return key.trim();
    if (provider === "openrouter") return (sessionStorage.getItem("bluepace_openrouter_key") || "").trim();
  } catch { /* session storage is optional */ }
  return "";
}

function explainError(error) {
  const status = error?.response?.status;
  const requestedPath = error?.config?.url || "";
  const detail = error?.response?.data?.detail;
  if (status === 404) {
    const routeDetail = typeof detail === "string" ? detail : "";
    const routeLabel = requestedPath || "The requested AI feature endpoint";
    return routeDetail
      ? `${routeLabel} returned HTTP 404: ${routeDetail}`
      : `${routeLabel} is not available on this deployment. Check the deployed AI API function and route configuration.`;
  }
  if (status === 503) {
    return typeof detail === "string" ? detail : "The backend is reachable, but its AI feature platform or model registry is unavailable. Check backend startup configuration.";
  }
  if (typeof detail === "string") return detail;
  if (detail?.message) return detail.message;
  if (detail?.detail) return String(detail.detail);
  if (Array.isArray(detail)) return formatJdValidationErrors(error) || detail.map((item) => item.msg || String(item)).join("; ");
  if (status === 401 || status === 403) return "The backend rejected this request. Check the optional X-API-Key in API access settings.";
  if (error?.response) return `AI Feature API returned HTTP ${status}.`;
  if (error?.request) return "The backend could not be reached. Confirm the API service is running and configured for this frontend.";
  return error?.message || "The request failed. Review the configuration and try again.";
}

function Pill({ children, tone = "neutral" }) {
  const tones = {
    neutral: "border-ink-200 bg-ink-50 text-ink-600",
    good: "border-emerald-200 bg-emerald-50 text-emerald-800",
    warn: "border-amber-200 bg-amber-50 text-amber-800",
    bad: "border-rose-200 bg-rose-50 text-rose-800",
    gold: "border-[#e5d2a6] bg-[#fbf6e9] text-[#72541d]",
  };
  return <span className={`inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-semibold ${tones[tone] || tones.neutral}`}>{children}</span>;
}

function SectionHeading({ eyebrow, title, detail, action }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div>
        {eyebrow && <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-500">{eyebrow}</p>}
        <h2 className="mt-1 text-lg font-semibold tracking-tight text-ink-950">{title}</h2>
        {detail && <p className="mt-1 max-w-3xl text-sm leading-6 text-ink-500">{detail}</p>}
      </div>
      {action}
    </div>
  );
}

function Field({ label, children, hint }) {
  return <label className="grid gap-1.5 text-xs font-semibold text-ink-700"><span>{label}</span>{children}{hint && <span className="font-normal leading-5 text-ink-500">{hint}</span>}</label>;
}

function ScoreMetric({ label, value, detail }) {
  return <div className="rounded-lg border border-ink-100 bg-white p-4"><p className="text-[11px] font-semibold uppercase tracking-wide text-ink-500">{label}</p><p className="mt-2 text-2xl font-semibold tabular-nums text-ink-950">{value ?? "—"}</p>{detail && <p className="mt-1 text-xs text-ink-500">{detail}</p>}</div>;
}

function EvidenceRatingCard({ item, onOverride, reviewerName, onRecordRating, onResolve }) {
  const fieldId = useId();
  const [ratingDraft, setRatingDraft] = useState(item.review_override || item.status || "unclear");
  const [resolutionDraft, setResolutionDraft] = useState(item.calibration_resolution?.status || "");
  const [resolutionNoteDraft, setResolutionNoteDraft] = useState(item.calibration_resolution?.note || "");
  const ratingOptions = [
    ["met", "Met"],
    ["partial", "Partial"],
    ["unclear", "Unclear"],
    ["not_evidenced", "Not evidenced"],
  ];
  const reviewerRatings = latestReviewerRatings(item);
  function saveResolution() {
    onResolve(resolutionDraft, resolutionNoteDraft.trim());
  }
  return (
    <div className="rounded-lg border border-ink-100 bg-white p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div><p className="text-sm font-semibold text-ink-900">{item.label}</p><p className="mt-1 text-xs text-ink-500">{item.importance === "must" ? "Must-have" : "Preferred"} · {item.group}</p></div>
        <div className="flex flex-wrap items-center gap-2"><span className="text-[11px] text-ink-500">AI rating</span><Pill tone={item.status === "met" ? "good" : item.status === "partial" ? "warn" : "neutral"}>{String(item.status || "unclear").replaceAll("_", " ")}</Pill></div>
      </div>
      {item.note && <p className="mt-2 text-sm leading-6 text-ink-700">{item.note}</p>}
      {item.lines?.length > 0 ? <ul className="mt-3 space-y-2">{item.lines.map((line) => <li key={line.id} className="border-l-2 border-gold-400 pl-3 text-sm leading-6 text-ink-600"><span className="mr-2 text-xs font-semibold text-ink-400">{line.id}</span>{line.text}</li>)}</ul> : <p className="mt-3 rounded-md bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-900">No exact resume excerpt was returned for this criterion. Check the original resume before confirming a rating.</p>}
      <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-ink-100 pt-3">
        <label className="text-xs font-semibold text-ink-700" htmlFor={fieldId}>Reviewer override</label>
        <select id={fieldId} value={item.review_override || ""} onChange={(event) => onOverride(event.target.value)} className="rounded-md border border-ink-200 bg-white px-2.5 py-2 text-xs text-ink-800">
          <option value="">Use AI rating</option>
          {ratingOptions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
        {item.review_override && <Pill tone="gold">Reviewer: {String(item.review_override).replaceAll("_", " ")}</Pill>}
      </div>
      <p className="mt-2 text-[11px] leading-5 text-ink-500">This records your review separately; it does not change the AI rating or match score.</p>
      <div className="mt-4 border-t border-ink-100 pt-3">
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-xs font-semibold text-ink-800">Reviewer calibration</p>
          {hasReviewerDisagreement(item) && !item.calibration_resolution && <Pill tone="warn">Disagreement to resolve</Pill>}
          {item.calibration_resolution && <Pill tone="good">Resolved · {String(item.calibration_resolution.status).replaceAll("_", " ")}</Pill>}
        </div>
        {reviewerRatings.length > 0 ? <div className="mt-2 flex flex-wrap gap-1.5">{reviewerRatings.map((rating) => <Pill key={rating.reviewer} tone="neutral">{rating.reviewer}: {String(rating.status).replaceAll("_", " ")}</Pill>)}</div> : <p className="mt-1 text-[11px] text-ink-500">No independent reviewer ratings recorded yet.</p>}
        <div className="mt-3 flex flex-wrap items-end gap-2">
          <label className="text-[11px] font-semibold text-ink-700" htmlFor={`${fieldId}-rating`}>Your independent rating
            <select id={`${fieldId}-rating`} value={ratingDraft} onChange={(event) => setRatingDraft(event.target.value)} className="mt-1 block rounded-md border border-ink-200 bg-white px-2.5 py-2 text-xs text-ink-800">
              {ratingOptions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
          <button type="button" className={secondaryButton} onClick={() => onRecordRating(ratingDraft, reviewerName)} disabled={!reviewerName?.trim()}>Record rating</button>
          {!reviewerName?.trim() && <span className="text-[11px] text-amber-800">Enter reviewer name above first.</span>}
        </div>
        {(hasReviewerDisagreement(item) || item.calibration_resolution) && <div className="mt-3 grid gap-2 border-t border-ink-100 pt-3 sm:grid-cols-[minmax(140px,0.7fr)_minmax(0,1fr)_auto] sm:items-end">
          <label className="text-[11px] font-semibold text-ink-700" htmlFor={`${fieldId}-resolution`}>Agreed rating
            <select id={`${fieldId}-resolution`} value={resolutionDraft} onChange={(event) => setResolutionDraft(event.target.value)} className="mt-1 block w-full rounded-md border border-ink-200 bg-white px-2.5 py-2 text-xs text-ink-800">
              <option value="">Choose resolution…</option>
              {ratingOptions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
          <label className="text-[11px] font-semibold text-ink-700" htmlFor={`${fieldId}-rationale`}>Resolution rationale
            <input id={`${fieldId}-rationale`} value={resolutionNoteDraft} onChange={(event) => setResolutionNoteDraft(event.target.value)} maxLength={1000} placeholder="Why did reviewers agree on this rating?" className="mt-1 block w-full rounded-md border border-ink-200 px-2.5 py-2 text-xs" />
          </label>
          <button type="button" className={primaryButton} onClick={saveResolution} disabled={!resolutionDraft || !reviewerName?.trim()}>Save resolution</button>
          {item.calibration_resolution && <p className="text-[11px] leading-5 text-ink-500 sm:col-span-3">Resolved by {item.calibration_resolution.reviewer} · {item.calibration_resolution.at ? new Date(item.calibration_resolution.at).toLocaleString() : "time not recorded"}{item.calibration_resolution.note ? ` · ${item.calibration_resolution.note}` : ""}</p>}
        </div>}
      </div>
    </div>
  );
}

function ApplicantWorkflowControls({ review, onStageChange, onAddNote, onFollowUpChange }) {
  const [noteDraft, setNoteDraft] = useState("");
  const history = Array.isArray(review?.history) ? review.history : [];
  const reminderState = followUpState(review?.followUpAt);
  function submitNote(event) {
    event.preventDefault();
    const note = noteDraft.trim();
    if (!note) return;
    onAddNote(note);
    setNoteDraft("");
  }
  return (
    <div className="min-w-[240px] space-y-2">
      <label className="block text-[11px] font-semibold text-ink-600">Review stage
        <select value={review?.stage || "new"} onChange={(event) => onStageChange(event.target.value)} className="mt-1 w-full rounded-md border border-ink-200 bg-white px-2 py-1.5 text-xs text-ink-800">
          {REVIEW_STAGES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
      </label>
      <form onSubmit={submitNote} className="flex gap-1.5">
        <input value={noteDraft} onChange={(event) => setNoteDraft(event.target.value)} maxLength={1000} placeholder="Add reviewer note…" aria-label="Reviewer note" className="min-w-0 flex-1 rounded-md border border-ink-200 px-2 py-1.5 text-xs" />
        <button type="submit" disabled={!noteDraft.trim()} className="rounded-md border border-ink-200 px-2 py-1.5 text-xs font-semibold text-ink-700 disabled:opacity-50">Add</button>
      </form>
      <div className="grid gap-1.5 border-t border-ink-100 pt-2">
        <label className="text-[11px] font-semibold text-ink-600">Follow-up date
          <input type="date" value={review?.followUpAt || ""} onChange={(event) => onFollowUpChange({ followUpAt: event.target.value, followUpNote: review?.followUpNote || "" })} className="mt-1 block w-full rounded-md border border-ink-200 bg-white px-2 py-1.5 text-xs text-ink-800" />
        </label>
        <label className="text-[11px] font-semibold text-ink-600">Reminder note
          <input value={review?.followUpNote || ""} onChange={(event) => onFollowUpChange({ followUpAt: review?.followUpAt || "", followUpNote: event.target.value })} maxLength={300} placeholder="e.g. Send interview feedback" className="mt-1 block w-full rounded-md border border-ink-200 px-2 py-1.5 text-xs" />
        </label>
        <div className="flex items-center justify-between gap-2">
          {review?.followUpAt ? <Pill tone={reminderState === "overdue" ? "bad" : reminderState === "today" ? "warn" : "neutral"}>{reminderState === "overdue" ? "Overdue" : reminderState === "today" ? "Due today" : reminderState === "upcoming" ? "Due within 7 days" : "Scheduled"}</Pill> : <span className="text-[11px] text-ink-400">No reminder scheduled</span>}
          {review?.followUpAt && <button type="button" className="text-[11px] font-semibold text-ink-500 underline" onClick={() => onFollowUpChange({ followUpAt: "", followUpNote: "" })}>Clear</button>}
        </div>
      </div>
      <details>
        <summary className="cursor-pointer text-[11px] font-semibold text-blue-700 underline">Activity history ({history.length})</summary>
        {history.length ? <ol className="mt-2 max-h-48 space-y-2 overflow-auto border-l border-ink-200 pl-3">
          {[...history].reverse().map((entry, index) => <li key={`${entry.at || "event"}-${index}`} className="text-[11px] leading-5 text-ink-600">
            <span className="font-semibold text-ink-800">{entry.type === "stage" ? `Stage: ${REVIEW_STAGES.find(([value]) => value === entry.to)?.[1] || entry.to}` : entry.type === "followup" ? `Follow-up ${entry.date ? "scheduled" : "cleared"}` : "Reviewer note"}</span>
            {entry.type === "stage" && <span> · from {REVIEW_STAGES.find(([value]) => value === entry.from)?.[1] || entry.from}</span>}
            {entry.type === "note" && <span>: {entry.text}</span>}
            {entry.type === "followup" && <span>{entry.date ? ` · ${formatLocalDate(entry.date)}` : ""}{entry.text ? ` · ${entry.text}` : ""}</span>}
            <time className="block text-ink-400">{entry.at ? new Date(entry.at).toLocaleString() : "Time not recorded"}</time>
          </li>)}
        </ol> : <p className="mt-2 text-[11px] text-ink-500">No stage changes or notes yet.</p>}
      </details>
    </div>
  );
}

function withEvidenceOverride(result, itemId, override) {
  if (!result || !Array.isArray(result.evidence)) return result;
  return {
    ...result,
    evidence: result.evidence.map((item) => {
      if (item.item_id !== itemId) return item;
      const next = { ...item };
      if (override) {
        next.review_override = override;
        next.reviewed_at = new Date().toISOString();
      } else {
        delete next.review_override;
        delete next.reviewed_at;
      }
      return next;
    }),
  };
}

function withReviewerRating(result, itemId, reviewer, status) {
  if (!result || !Array.isArray(result.evidence) || !reviewer?.trim()) return result;
  return {
    ...result,
    evidence: result.evidence.map((item) => {
      if (item.item_id !== itemId) return item;
      const next = { ...item, reviewer_ratings: [...(Array.isArray(item.reviewer_ratings) ? item.reviewer_ratings : []), { reviewer: reviewer.trim(), status, at: new Date().toISOString() }].slice(-100) };
      delete next.calibration_resolution;
      return next;
    }),
  };
}

function withCalibrationResolution(result, itemId, reviewer, status, note) {
  if (!result || !Array.isArray(result.evidence)) return result;
  return {
    ...result,
    evidence: result.evidence.map((item) => {
      if (item.item_id !== itemId) return item;
      if (!status) {
        const next = { ...item };
        delete next.calibration_resolution;
        return next;
      }
      return { ...item, calibration_resolution: { reviewer: reviewer.trim(), status, note: note || "", at: new Date().toISOString() } };
    }),
  };
}

function ErrorNotice({ children }) {
  if (!children) return null;
  return <div role="alert" className="rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm leading-6 text-rose-900">{children}</div>;
}

function EmptyPanel({ title, detail }) {
  return <div className="rounded-lg border border-dashed border-ink-200 bg-white px-5 py-9 text-center"><p className="text-sm font-semibold text-ink-800">{title}</p><p className="mx-auto mt-1 max-w-lg text-sm leading-6 text-ink-500">{detail}</p></div>;
}

export default function JDApplicantMatch({ token, apiRequest, jobs = [], applications = [] }) {
  const initialWorkspace = readActiveWorkspace();
  const [workspaces, setWorkspaces] = useState(readWorkspaces);
  const [teamWorkspaceBusy, setTeamWorkspaceBusy] = useState(false);
  const [activeWorkspaceId, setActiveWorkspaceId] = useState(() => initialWorkspace?.id || "");
  const [workspaceName, setWorkspaceName] = useState(() => initialWorkspace?.title || "");
  const [workspaceNotes, setWorkspaceNotes] = useState(() => initialWorkspace?.notes || "");
  const [calibrationReviewerName, setCalibrationReviewerName] = useState(() => initialWorkspace?.calibrationReviewerName || "");
  const [savedApplicants, setSavedApplicants] = useState(() => initialWorkspace?.applicants || []);
  const [workspaceStorageError, setWorkspaceStorageError] = useState(false);
  const [activeTab, setActiveTab] = useState("jd");
  const [atsJobId, setAtsJobId] = useState("");
  const [atsApplicationId, setAtsApplicationId] = useState("");
  const [assessmentSaving, setAssessmentSaving] = useState(false);
  const [atsResumeMatchLoading, setAtsResumeMatchLoading] = useState(false);
  const [assessmentSaveMessage, setAssessmentSaveMessage] = useState("");
  const [savedAtsAssessments, setSavedAtsAssessments] = useState([]);
  const [savedAtsAssessmentsLoading, setSavedAtsAssessmentsLoading] = useState(false);
  const [savedAtsAssessmentsError, setSavedAtsAssessmentsError] = useState("");
  const [apiKey, setApiKey] = useState(() => {
    try { return sessionStorage.getItem("bluepace_feature_api_key") || ""; } catch { return ""; }
  });
  const [apiKeyDraft, setApiKeyDraft] = useState(() => {
    try { return sessionStorage.getItem("bluepace_feature_api_key") || ""; } catch { return ""; }
  });
  const [openRouterKey, setOpenRouterKey] = useState(() => sessionProviderKey("openrouter"));
  const [openRouterKeyDraft, setOpenRouterKeyDraft] = useState(() => sessionProviderKey("openrouter"));
  const [inferenceTest, setInferenceTest] = useState({ status: "", message: "" });
  const [localAiApiUrl, setLocalAiApiUrl] = useState(readSavedLocalAiApiUrl);
  const [localAiApiDraft, setLocalAiApiDraft] = useState(() => readSavedLocalAiApiUrl() || DEFAULT_LOCAL_AI_API_URL);
  const [localAiApiTest, setLocalAiApiTest] = useState({ status: "", message: "" });
  const [localAiApiVerified, setLocalAiApiVerified] = useState(false);
  const [models, setModels] = useState([]);
  const [selectedProfile, setSelectedProfile] = useState(() => initialWorkspace?.selectedProfile || "");
  const [connection, setConnection] = useState("checking");
  const [connectionMessage, setConnectionMessage] = useState("Checking the AI Feature API…");
  const [jdText, setJdText] = useState(() => normalizeJdText(initialWorkspace?.jdText));
  const [jdSourceJobId, setJdSourceJobId] = useState("");
  const [jdSourceMessage, setJdSourceMessage] = useState("");
  const [jdUploadBusy, setJdUploadBusy] = useState(false);
  const [jdLink, setJdLink] = useState("");
  const [jdLinkBusy, setJdLinkBusy] = useState(false);
  const [jdAssistantOpen, setJdAssistantOpen] = useState(false);
  const [jdAssistantInput, setJdAssistantInput] = useState("");
  const [jdAssistantMessages, setJdAssistantMessages] = useState([{ role: "assistant", text: "Hi! I can guide you through importing a JD, standardizing it, building a match rubric, and reviewing applicant evidence. What would you like help with?" }]);
  const [jdAssistantBusy, setJdAssistantBusy] = useState(false);
  const [jdMode, setJdMode] = useState(() => initialWorkspace?.jdMode || "light");
  const [jdDetail, setJdDetail] = useState(() => workspaceJdDetail(initialWorkspace));
  const [jdResult, setJdResult] = useState(() => initialWorkspace?.jdResult || null);
  const [jdLoading, setJdLoading] = useState(false);
  const [jdPrepareLoading, setJdPrepareLoading] = useState(false);
  const [jdError, setJdError] = useState("");
  const [rubric, setRubric] = useState(() => initialWorkspace?.rubric || null);
  const [rubricNotes, setRubricNotes] = useState(() => initialWorkspace?.rubricNotes || []);
  const [savedRubrics, setSavedRubrics] = useState(() => readSavedRubrics().map(savedRubricOption));
  const [selectedRubricId, setSelectedRubricId] = useState(() => initialWorkspace?.selectedRubricId || "");
  const [rubricLoading, setRubricLoading] = useState(false);
  const [rubricError, setRubricError] = useState("");
  const [resumeFile, setResumeFile] = useState(null);
  const [resumeText, setResumeText] = useState("");
  const [candidateCard, setCandidateCard] = useState(() => initialWorkspace?.candidateCard || null);
  const [candidateReview, setCandidateReview] = useState(() => initialWorkspace?.candidateReview || { stage: "new", history: [] });
  const [matchLoading, setMatchLoading] = useState(false);
  const [sampleAssessmentLoading, setSampleAssessmentLoading] = useState(false);
  const [matchError, setMatchError] = useState("");
  const [batchFiles, setBatchFiles] = useState([]);
  const [batchQueueHydrated, setBatchQueueHydrated] = useState(false);
  const [batchQueueMessage, setBatchQueueMessage] = useState("");
  const batchQueueScopeRef = useRef({ scope: "", ready: false });
  const [batchRunning, setBatchRunning] = useState(false);
  const [batchCurrentName, setBatchCurrentName] = useState("");
  const [batchProgress, setBatchProgress] = useState({ done: 0, total: 0 });
  const [batchError, setBatchError] = useState("");
  const [notice, setNotice] = useState("");

  // Bulk resume binaries and queue state are kept in IndexedDB per workspace.
  // An unsaved workspace uses a separate local-device queue key until it is saved.
  useEffect(() => {
    const scope = activeWorkspaceId || UNSAVED_BULK_QUEUE_ID;
    let active = true;
    batchQueueScopeRef.current = { scope, ready: false };
    setBatchQueueHydrated(false);
    loadBulkQueue(scope).then(({ rows, interrupted }) => {
      if (!active || batchQueueScopeRef.current.scope !== scope) return;
      setBatchFiles(rows);
      batchQueueScopeRef.current = { scope, ready: true };
      setBatchQueueHydrated(true);
      if (interrupted) {
        setBatchQueueMessage(`${interrupted} resume(s) were in progress when the previous session ended. They have been returned to the queue; rerun them to verify completion.`);
      } else if (rows.length) {
        setBatchQueueMessage(`Restored ${rows.length} queued resume(s) and their saved results from this browser. Files are stored on this device only.`);
      } else {
        setBatchQueueMessage("");
      }
    }).catch((error) => {
      if (!active || batchQueueScopeRef.current.scope !== scope) return;
      batchQueueScopeRef.current = { scope, ready: true };
      setBatchQueueHydrated(true);
      setBatchQueueMessage(`Local queue recovery is unavailable: ${String(error?.message || error)}. The current queue will remain in memory only.`);
    });
    return () => { active = false; };
  }, [activeWorkspaceId]);

  useEffect(() => {
    const scope = activeWorkspaceId || UNSAVED_BULK_QUEUE_ID;
    if (!batchQueueHydrated || !batchQueueScopeRef.current.ready || batchQueueScopeRef.current.scope !== scope) return;
    const timer = window.setTimeout(() => {
      saveBulkQueue(scope, batchFiles).then(() => {
        if (batchQueueScopeRef.current.scope !== scope) return;
        setBatchQueueMessage((current) => current.startsWith("Local queue recovery is unavailable") || current.startsWith("Could not persist")
          ? current
          : batchFiles.length
            ? `Queue recovery is on. ${batchFiles.length} file(s) and progress are saved in this browser only.`
            : "");
      }).catch((error) => {
        if (batchQueueScopeRef.current.scope !== scope) return;
        setBatchQueueMessage(`Could not persist the bulk queue: ${String(error?.message || error)}. Keep this tab open until the batch finishes or export your results.`);
      });
    }, 250);
    return () => window.clearTimeout(timer);
  }, [activeWorkspaceId, batchFiles, batchQueueHydrated]);

  useEffect(() => {
    if (!jdSourceJobId) return;
    const selectedJob = jobs.find((job) => String(job?.id) === String(jdSourceJobId));
    if (!selectedJob) {
      setJdSourceMessage("The selected ATS job is no longer available. Refresh the jobs list and try again.");
      return;
    }
    const description = [
      selectedJob.description,
      selectedJob.description_text,
      selectedJob.description_markdown,
      selectedJob.job_description,
      selectedJob.jobDescription,
      selectedJob.jd,
      selectedJob.responsibilities,
      selectedJob.requirements,
      selectedJob.qualifications,
    ].filter((value) => typeof value === "string" && value.trim()).join("\\n\\n");
    if (!description.trim()) {
      setJdSourceMessage("This ATS job has no saved description yet. Add a description to the job record or use the manual field below.");
      return;
    }
    setJdText(description.trim());
    setAtsJobId(String(selectedJob.id));
    setAtsApplicationId((currentId) => applications.some((application) => String(application.id) === String(currentId) && Number(application.job_id) === Number(selectedJob.id)) ? currentId : "");
    setJdResult(null);
    setJdError("");
    setRubricError("");
    setJdSourceMessage(`Loaded the description from ${selectedJob.title || selectedJob.job_title || `Job #${selectedJob.id}`}. Run Standardize JD to prepare the structured version.`);
    setActiveTab("jd");
  }, [jdSourceJobId, jobs, applications]);

  useEffect(() => {
    if (!activeWorkspaceId) return;
    const existingRows = readWorkspaces();
    const existing = existingRows.find((workspace) => workspace.id === activeWorkspaceId);
    if (!existing) return;
    const applicantsById = new Map();
    for (const applicant of [...savedApplicants, ...savedApplicantRows(batchFiles)]) {
      applicantsById.set(applicant.id, applicant);
    }
    const updated = {
      ...existing,
      title: workspaceName.trim() || "Untitled workspace",
      jdText,
      jdMode,
      jdDetail,
      jdDetailVersion: 1,
      jdResult,
      rubric,
      rubricNotes,
      selectedRubricId,
      selectedProfile,
      candidateCard,
      candidateReview,
      applicants: Array.from(applicantsById.values()).slice(-MAX_BULK_RESUMES),
      notes: workspaceNotes,
      calibrationReviewerName,
      updatedAt: new Date().toISOString(),
    };
    const next = [updated, ...existingRows.filter((workspace) => workspace.id !== activeWorkspaceId)].slice(0, 40);
    const saved = writeWorkspaces(next);
    setWorkspaceStorageError(!saved);
    if (saved) setWorkspaces(next);
  }, [activeWorkspaceId, workspaceName, workspaceNotes, calibrationReviewerName, jdText, jdMode, jdDetail, jdResult, rubric, rubricNotes, selectedRubricId, selectedProfile, candidateCard, candidateReview, savedApplicants, batchFiles]);

  function activateWorkspace(workspace) {
    if (!workspace) return;
    setActiveWorkspaceId(workspace.id);
    setWorkspaceName(workspace.title || "Untitled workspace");
    setWorkspaceNotes(workspace.notes || "");
    setCalibrationReviewerName(workspace.calibrationReviewerName || "");
    setJdText(normalizeJdText(workspace.jdText));
    setJdMode(workspace.jdMode || "light");
    setJdDetail(workspaceJdDetail(workspace));
    setJdResult(workspace.jdResult || null);
    setRubric(workspace.rubric || null);
    setRubricNotes(workspace.rubricNotes || []);
    setSelectedRubricId(workspace.selectedRubricId || "");
    setSelectedProfile(workspace.selectedProfile || "");
    setCandidateCard(workspace.candidateCard || null);
    setCandidateReview(workspace.candidateReview || { stage: "new", history: [] });
    setSavedApplicants(workspace.applicants || []);
    setResumeFile(null);
    setResumeText("");
    setBatchFiles([]);
    setMatchError("");
    setBatchError("");
    setJdError("");
    setRubricError("");
    setNotice(`Opened “${workspace.title || "Untitled workspace"}”.`);
    try { localStorage.setItem(ACTIVE_WORKSPACE_KEY, workspace.id); } catch { /* Workspace can still be used in memory. */ }
  }

  async function saveWorkspace() {
    const existingRows = readWorkspaces();
    const existing = existingRows.find((workspace) => workspace.id === activeWorkspaceId);
    const id = existing?.id || newWorkspaceId();
    const title = workspaceName.trim() || jdTitle || "Untitled workspace";
    if (!activeWorkspaceId && batchFiles.length && id !== UNSAVED_BULK_QUEUE_ID) {
      try {
        await moveBulkQueue(UNSAVED_BULK_QUEUE_ID, id);
      } catch (error) {
        setBatchQueueMessage(`Cannot move the unsaved queue into a workspace yet: ${String(error?.message || error)}. Keep this tab open or clear the queue before saving a new workspace.`);
        return existing || { id, title };
      }
    }
    const applicantsById = new Map();
    for (const applicant of [...savedApplicants, ...savedApplicantRows(batchFiles)]) applicantsById.set(applicant.id, applicant);
    const workspace = {
      ...existing,
      id,
      title,
      createdAt: existing?.createdAt || new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      jdText,
      jdMode,
      jdDetail,
      jdDetailVersion: 1,
      jdResult,
      rubric,
      rubricNotes,
      selectedRubricId,
      selectedProfile,
      candidateCard,
      candidateReview,
      applicants: Array.from(applicantsById.values()).slice(-MAX_BULK_RESUMES),
      notes: workspaceNotes,
      calibrationReviewerName,
    };
    const next = [workspace, ...existingRows.filter((row) => row.id !== id)].slice(0, 40);
    const saved = writeWorkspaces(next);
    setWorkspaceStorageError(!saved);
    setWorkspaces(next);
    setActiveWorkspaceId(id);
    setWorkspaceName(title);
    try { localStorage.setItem(ACTIVE_WORKSPACE_KEY, id); } catch { /* Workspace remains open in memory. */ }
    setNotice(saved ? `Workspace “${title}” saved on this device.` : "Could not save this workspace. Browser storage may be full or unavailable.");
    return workspace;
  }

  async function syncWorkspaceToTeam() {
    if (!token) {
      setNotice("Sign in to sync workspaces with your organization.");
      return;
    }
    setTeamWorkspaceBusy(true);
    try {
      const workspace = await saveWorkspace();
      await request("put", `/ai-hiring/workspaces/${encodeURIComponent(workspace.id)}`, { workspace });
      setNotice(`Workspace “${workspace.title}” synced with your organization.`);
    } catch (error) {
      setNotice(`Team sync failed: ${explainError(error)}`);
    } finally {
      setTeamWorkspaceBusy(false);
    }
  }

  async function loadTeamWorkspaces() {
    if (!token) {
      setNotice("Sign in to load workspaces shared by your organization.");
      return;
    }
    setTeamWorkspaceBusy(true);
    try {
      const response = await request("get", "/ai-hiring/workspaces", undefined, { timeout: 15000 });
      const remoteRows = Array.isArray(response.data?.workspaces) ? response.data.workspaces : [];
      const localRows = readWorkspaces();
      const byId = new Map(localRows.map((workspace) => [workspace.id, workspace]));
      for (const remote of remoteRows) {
        if (!remote?.id) continue;
        const local = byId.get(remote.id);
        const localTime = Date.parse(local?.updatedAt || local?.createdAt || "") || 0;
        const remoteTime = Date.parse(remote.updatedAt || remote.createdAt || "") || 0;
        if (!local || remoteTime >= localTime) byId.set(remote.id, remote);
      }
      const merged = Array.from(byId.values())
        .sort((a, b) => (Date.parse(b.updatedAt || b.createdAt || "") || 0) - (Date.parse(a.updatedAt || a.createdAt || "") || 0))
        .slice(0, 40);
      writeWorkspaces(merged);
      setWorkspaces(merged);
      setNotice(`Loaded ${remoteRows.length} team workspace${remoteRows.length === 1 ? "" : "s"}. Choose one from the workspace list.`);
    } catch (error) {
      setNotice(`Could not load team workspaces: ${explainError(error)}`);
    } finally {
      setTeamWorkspaceBusy(false);
    }
  }

  async function createWorkspace() {
    if (activeWorkspaceId || jdText.trim() || jdResult || rubric || candidateCard || batchFiles.length || workspaceNotes.trim()) await saveWorkspace();
    const now = new Date().toISOString();
    const workspace = {
      id: newWorkspaceId(),
      title: "Untitled workspace",
      createdAt: now,
      updatedAt: now,
      jdText: "",
      jdMode: "light",
      jdDetail: "concise",
      jdResult: null,
      rubric: null,
      rubricNotes: [],
      selectedRubricId: "",
      selectedProfile: "",
      candidateCard: null,
      candidateReview: { stage: "new", history: [] },
      applicants: [],
      notes: "",
      calibrationReviewerName: "",
    };
    const next = [workspace, ...readWorkspaces()].slice(0, 40);
    writeWorkspaces(next);
    setWorkspaces(next);
    activateWorkspace(workspace);
  }

  function deleteWorkspace() {
    if (!activeWorkspaceId) return;
    const current = workspaces.find((workspace) => workspace.id === activeWorkspaceId);
    if (!window.confirm(`Delete “${current?.title || "Untitled workspace"}” and its saved review data from this device?`)) return;
    const next = workspaces.filter((workspace) => workspace.id !== activeWorkspaceId);
    void deleteBulkQueue(activeWorkspaceId).catch((error) => setBatchQueueMessage(`Could not delete the saved local queue: ${String(error?.message || error)}`));
    const saved = writeWorkspaces(next);
    setWorkspaces(next);
    if (next.length) activateWorkspace(next[0]);
    else {
      setActiveWorkspaceId("");
      setWorkspaceName("");
      setWorkspaceNotes("");
      setCalibrationReviewerName("");
      setJdText("");
      setJdMode("light");
      setJdDetail("concise");
      setJdResult(null);
      setRubric(null);
      setRubricNotes([]);
      setSelectedRubricId("");
      setSelectedProfile("");
      setCandidateCard(null);
      setCandidateReview({ stage: "new", history: [] });
      setSavedApplicants([]);
      setResumeFile(null);
      setResumeText("");
      setBatchFiles([]);
      try { localStorage.removeItem(ACTIVE_WORKSPACE_KEY); } catch { /* Ignore unavailable local storage. */ }
    }
    setWorkspaceStorageError(!saved);
    setNotice(saved ? "Workspace deleted from this device." : "Could not update browser storage.");
  }

  const request = useCallback((method, path, data, options = {}) => {
    const headers = { ...(options.headers || {}) };
    const isFeatureRoute = String(path || "").startsWith("/v1/");
    const explicitBaseURL = options.baseURL ? String(options.baseURL).replace(/\/$/, "") : "";
    const usingLocalAi = Boolean(
      localAiApiUrl && isFeatureRoute
      && (explicitBaseURL === localAiApiUrl || (!explicitBaseURL && selectedProfile === "local-ollama"))
    );
    const featureApiBase = explicitBaseURL || (usingLocalAi ? localAiApiUrl : window.location.origin);
    const usingHostedModelProxy = isFeatureRoute && featureApiBase === window.location.origin;

    if (apiKey.trim() && !usingLocalAi) headers["X-API-Key"] = apiKey.trim();
    // Hosted provider keys are sent only to this app's same-origin model proxy.
    // They are never sent to the local Ollama endpoint or another custom API host.
    const keys = [
      ["openrouter", "X-OpenRouter-Api-Key"],
      ["gemini", "X-Google-Api-Key"],
      ["deepseek", "X-DeepSeek-Api-Key"],
      ["xai", "X-XAI-Api-Key"],
      ["openai", "X-OpenAI-Api-Key"],
    ];
    if (usingHostedModelProxy) {
      for (const [provider, header] of keys) {
        const value = provider === "openrouter"
          ? (sessionProviderKey(provider) || openRouterKey)
          : sessionProviderKey(provider);
        if (value) headers[header] = value;
      }
    }
    const requestOptions = {
      ...options,
      ...(usingLocalAi ? { timeout: Math.max(Number(options.timeout) || 0, 300000), skipAuth: true } : {}),
      headers,
      ...(isFeatureRoute ? { baseURL: featureApiBase } : {}),
    };
    if (data !== undefined) requestOptions.data = data;
    // Vercel rewrites have not been consistently applied on every deployed
    // BluePace hostname. Address the serverless function path directly for
    // hosted feature requests; local Ollama exposes the original /v1 path.
    const isVercelAppHostname = window.location.hostname.toLowerCase().endsWith(".vercel.app");
    const featureRequestPath = isFeatureRoute && !usingLocalAi && isVercelAppHostname ? `/api${path}` : path;
    return apiRequest(token, method, featureRequestPath, requestOptions);
  }, [apiKey, apiRequest, localAiApiUrl, openRouterKey, selectedProfile, token]);

  useEffect(() => {
    if (!atsApplicationId || !token) {
      setSavedAtsAssessments([]);
      setSavedAtsAssessmentsError("");
      return undefined;
    }
    let active = true;
    setSavedAtsAssessmentsLoading(true);
    setSavedAtsAssessmentsError("");
    request("get", `/ai-hiring/applications/${Number(atsApplicationId)}/applicant-match-assessments`, undefined, { timeout: 15000 })
      .then((response) => {
        if (active) setSavedAtsAssessments(Array.isArray(response.data) ? response.data : []);
      })
      .catch((error) => {
        if (active) {
          setSavedAtsAssessments([]);
          setSavedAtsAssessmentsError(explainError(error));
        }
      })
      .finally(() => { if (active) setSavedAtsAssessmentsLoading(false); });
    return () => { active = false; };
  }, [atsApplicationId, token, request]);

  const refreshConnection = useCallback(async (baseURLOverride = null) => {
    setConnection("checking");
    const usingLocal = Boolean(localAiApiUrl && localAiApiVerified && !baseURLOverride);
    setConnectionMessage(usingLocal ? "Checking the local AI service and hosted model options…" : "Checking the AI Feature API…");
    try {
      const connectionBase = usingLocal ? localAiApiUrl : (baseURLOverride || window.location.origin);
      const response = await request("get", "/v1/models", undefined, {
        timeout: 10000,
        baseURL: connectionBase,
      });
      const primaryRows = Array.isArray(response.data) ? response.data : [];
      let rows = primaryRows;
      let localModel = primaryRows.find((model) => model.id === "local-ollama");

      if (usingLocal) {
        if (!localModel || !localModel.enabled) {
          throw new Error(localModel?.disabled_reason || "The local AI service does not expose an enabled local-ollama profile.");
        }
        const health = await request("get", "/v1/models/local-ollama/health", undefined, {
          timeout: 30000, baseURL: localAiApiUrl,
        });
        if (!health.data?.ok) throw new Error(health.data?.detail || "Ollama did not respond to the local inference check.");
        setLocalAiApiTest({ status: "success", message: `Local inference verified · ${localModel.model}` });

        // Local registry returns only local profiles. Fetch the hosted Vercel catalogue separately
        // so recruiters can switch between local Ollama and OpenRouter free/paid models.
        try {
          const hostedResponse = await request("get", "/v1/models", undefined, {
            timeout: 10000, baseURL: window.location.origin,
          });
          const hostedRows = Array.isArray(hostedResponse.data) ? hostedResponse.data : [];
          rows = [
            ...primaryRows.filter((model) => model.local),
            ...hostedRows.filter((model) => !model.local),
          ];
        } catch {
          rows = primaryRows;
        }
      } else if (baseURLOverride) {
        setLocalAiApiTest({ status: "", message: "" });
      }

      setModels(rows);
      setConnection("connected");
      const readyCount = rows.filter((model) => model.enabled).length;
      const freeCount = rows.filter((model) => model.free_endpoint).length;
      setConnectionMessage(usingLocal
        ? `Local inference ready · ${localModel.model}. ${freeCount} hosted free model option(s) also listed.`
        : rows.length ? (readyCount ? `${readyCount} model profile(s) ready` : "API is reachable, but no provider key is configured. Add one in AI Hiring Studio Settings.") : "API reachable; no model profiles were returned");
      setSelectedProfile((current) => (
        rows.find((model) => model.id === current && model.enabled)?.id
        || (usingLocal ? rows.find((model) => model.id === "local-ollama" && model.enabled)?.id : null)
        || rows.find((model) => model.enabled && model.is_default)?.id
        || rows.find((model) => model.enabled)?.id
        || ""
      ));
      setJdError("");
      setRubricError((current) => current.includes("does not expose") ? "" : current);
    } catch (error) {
      setModels([]);
      setConnection("unavailable");
      setConnectionMessage(explainError(error));
      if (localAiApiUrl && !baseURLOverride) {
        setLocalAiApiTest({ status: "error", message: explainError(error) });
      }
    }
  }, [localAiApiUrl, localAiApiVerified, request]);

  async function connectLocalAiApi() {
    let baseURL;
    try {
      baseURL = normalizeLocalAiApiUrl(localAiApiDraft);
    } catch (error) {
      setLocalAiApiTest({ status: "error", message: error.message });
      return;
    }
    setLocalAiApiTest({ status: "checking", message: "Checking browser permission, the local API and Ollama…" });
    try {
      // Query permission state only from this explicit button action. If the
      // browser is in "prompt" state, the health request below triggers its
      // native permission prompt while the user gesture is active.
      const permission = await getLoopbackNetworkPermission();
      if (permission.state === "denied") {
        throw Object.assign(new Error(localAiPermissionHelp(window.location.origin)), { code: "LOCAL_NETWORK_PERMISSION_DENIED" });
      }

      // Check the companion process before checking its model registry. This
      // separates a stopped PowerShell/Uvicorn process from model health errors.
      const serviceHealth = await apiRequest(null, "get", "/healthz", {
        baseURL, timeout: 6000, skipAuth: true,
      });
      if (serviceHealth.data?.status !== "ok" || serviceHealth.data?.service !== "bluepace-local-ai") {
        throw Object.assign(new Error("A service answered on this address, but it is not the BluePace local AI API. Check that the URL is http://127.0.0.1:8000."), { code: "LOCAL_AI_WRONG_SERVICE" });
      }

      const response = await apiRequest(null, "get", "/v1/models", { baseURL, timeout: 10000, skipAuth: true });
      const rows = Array.isArray(response.data) ? response.data : [];
      const profile = rows.find((model) => model.id === "local-ollama");
      if (!profile || !profile.enabled) {
        throw new Error(profile?.disabled_reason || "The BluePace local API is online, but its local-ollama profile is not enabled. Restart backend/start-local-ai.ps1 and check Ollama.");
      }
      const health = await apiRequest(null, "get", "/v1/models/local-ollama/health", { baseURL, timeout: 200000, skipAuth: true });
      if (!health.data?.ok) throw new Error(health.data?.detail || "The local API is online, but Ollama did not answer the model health check.");
      try { localStorage.setItem(LOCAL_AI_API_STORAGE_KEY, baseURL); } catch { /* Keep the selected URL in memory. */ }
      setLocalAiApiUrl(baseURL);
      setLocalAiApiDraft(baseURL);
      setLocalAiApiVerified(true);
      setLocalAiApiTest({ status: "success", message: `Local inference verified · ${profile.model}` });
      setInferenceTest({ status: "", message: "" });
      let combinedRows = rows.filter((model) => model.local);
      try {
        const hostedResponse = await request("get", "/v1/models", undefined, {
          timeout: 10000, baseURL: window.location.origin,
        });
        const hostedRows = Array.isArray(hostedResponse.data) ? hostedResponse.data : [];
        combinedRows = [
          ...combinedRows,
          ...hostedRows.filter((model) => !model.local),
        ];
      } catch {
        // Keep local inference working even when the hosted model proxy is unavailable.
      }
      setModels(combinedRows);
      setSelectedProfile("local-ollama");
      setConnection("connected");
      const freeCount = combinedRows.filter((model) => model.free_endpoint).length;
      setConnectionMessage(`Local inference ready · ${profile.model}. ${freeCount} hosted free model option(s) also listed.`);
      setNotice("Local Ollama connected. Choose Local Ollama for on-device inference or a free OpenRouter model for hosted inference.");
    } catch (error) {
      setLocalAiApiVerified(false);
      let detail = explainError(error);
      if (error?.code === "LOCAL_NETWORK_PERMISSION_DENIED" || error?.code === "LOCAL_AI_WRONG_SERVICE") {
        detail = error.message;
      } else {
        const permissionAfterFailure = await getLoopbackNetworkPermission();
        if (permissionAfterFailure.state === "denied") {
          detail = localAiPermissionHelp(window.location.origin);
        } else if (error?.request || /failed to fetch|load failed|networkerror|network error/i.test(String(error?.message || ""))) {
          detail = localAiServiceHelp();
        }
      }
      setLocalAiApiTest({ status: "error", message: detail });
    }
  }
  function useHostedAiApi() {
    const hadLocalAiConnection = Boolean(localAiApiUrl);
    try { localStorage.removeItem(LOCAL_AI_API_STORAGE_KEY); } catch { /* Ignore unavailable storage. */ }
    setLocalAiApiUrl("");
    setLocalAiApiDraft("");
    setLocalAiApiVerified(false);
    setLocalAiApiTest({ status: "", message: "" });
    setSelectedProfile("");
    setConnection("checking");
    setConnectionMessage("Switching JD & Applicant Match back to the hosted AI API…");
    // A connected local URL change triggers the effect. If local mode was never
    // active, refresh explicitly because the URL state itself did not change.
    if (!hadLocalAiConnection) void refreshConnection();
  }

  const refreshSavedRubrics = useCallback(async () => {
    const localRows = readSavedRubrics();
    const merged = localRows.map(savedRubricOption);
    setSavedRubrics(merged);
    try {
      const response = await request("get", "/v1/match/rubrics", undefined, { params: { limit: 50 }, timeout: 10000 });
      const remoteRows = Array.isArray(response.data) ? response.data : [];
      const byId = new Map(merged.map((row) => [row.rubric_id, row]));
      for (const row of remoteRows) {
        if (row?.rubric_id && !byId.has(row.rubric_id)) byId.set(row.rubric_id, savedRubricOption(row));
      }
      setSavedRubrics(Array.from(byId.values()).slice(0, 50));
    } catch {
      // The Vercel feature API is stateless; the durable browser copy remains authoritative there.
      setSavedRubrics(merged);
    }
  }, [request]);

  useEffect(() => {
    let active = true;
    if (localAiApiUrl) {
      if (!localAiApiVerified) {
        // If the local loopback service has not been re-authorized yet, keep hosted
        // models usable instead of hiding the selector or blocking the whole panel.
        const headers = {};
        const providerHeaders = [
          ["openrouter", "X-OpenRouter-Api-Key"],
          ["gemini", "X-Google-Api-Key"],
          ["deepseek", "X-DeepSeek-Api-Key"],
          ["xai", "X-XAI-Api-Key"],
          ["openai", "X-OpenAI-Api-Key"],
        ];
        for (const [provider, header] of providerHeaders) {
          const value = provider === "openrouter"
            ? (sessionProviderKey(provider) || openRouterKey)
            : sessionProviderKey(provider);
          if (value) headers[header] = value;
        }
        apiRequest(null, "get", "/v1/models", {
          baseURL: window.location.origin, headers, timeout: 10000, skipAuth: true,
        }).then((response) => {
          if (!active) return;
          const hostedRows = Array.isArray(response.data) ? response.data : [];
          const visibleRows = hostedRows.filter((model) => !model.local);
          setModels(visibleRows);
          setConnection("connected");
          setConnectionMessage(
            `Hosted AI API is available · ${visibleRows.filter((model) => model.free_endpoint).length} free OpenRouter choices listed. Reconnect local Ollama to enable on-device inference.`
          );
        }).catch((error) => {
          if (!active) return;
          setModels([]);
          setConnection("unavailable");
          setConnectionMessage(explainError(error));
        });
      }
      return () => { active = false; };
    }
    refreshConnection();
    return () => { active = false; };
  }, [localAiApiUrl, localAiApiVerified, refreshConnection, apiRequest, openRouterKey]);

  useEffect(() => {
    if (activeTab === "match" && connection === "connected") refreshSavedRubrics();
  }, [activeTab, connection, refreshSavedRubrics]);


  async function matchExistingAtsResume() {
    if (localAiApiUrl) {
      setAssessmentSaveMessage("Local mode does not route the private stored-resume endpoint through Ollama yet. To avoid hosted provider usage, upload the resume in Applicant Match and run the local analysis there.");
      return;
    }
    const applicationId = Number(atsApplicationId);
    if (!applicationId || !selectedRubricId) {
      setAssessmentSaveMessage("Choose an ATS application and a saved rubric first.");
      return;
    }
    setAtsResumeMatchLoading(true);
    setAssessmentSaveMessage("");
    setMatchError("");
    try {
      await request("post", `/ai-hiring/jobs/${Number(atsJobId)}/applicant-match-rubrics`, { rubric_id: selectedRubricId }, { timeout: 20000 });
      const response = await request("post", `/ai-hiring/applications/${applicationId}/applicant-match`, {}, { timeout: 120000 });
      const card = response.data;
      if (!card || !(card.request_id || card.run_id)) {
        throw new Error("The API returned no verifiable match run. Please retry.");
      }
      setCandidateCard(card);
      setAssessmentSaveMessage("Existing ATS resume analysed successfully. Review the evidence, gaps and score, then save the assessment.");
      setActiveTab("match");
    } catch (error) {
      setAssessmentSaveMessage(explainError(error));
    } finally {
      setAtsResumeMatchLoading(false);
    }
  }

  async function saveAssessmentToATS() {
    if (localAiApiUrl) {
      setAssessmentSaveMessage("This result was created by the local AI service. The hosted ATS cannot yet verify that local run for shared application storage. The assessment remains in your local JD & Applicant Match workspace.");
      return;
    }
    const jobId = Number(atsJobId);
    const applicationId = Number(atsApplicationId);
    const requestId = String(candidateCard?.request_id || candidateCard?.run_id || "").trim();
    if (!jobId || !applicationId) { setAssessmentSaveMessage("Choose an ATS job and its application first."); return; }
    if (!selectedRubricId) { setAssessmentSaveMessage("Select or create a saved rubric before linking this assessment."); return; }
    if (!requestId) { setAssessmentSaveMessage("This result has no verifiable run ID. Run Applicant Match again before saving."); return; }
    setAssessmentSaving(true); setAssessmentSaveMessage("");
    try {
      await request("post", `/ai-hiring/jobs/${jobId}/applicant-match-rubrics`, { rubric_id: selectedRubricId }, { timeout: 20000 });
      await request("post", "/ai-hiring/applicant-match/assessments", { application_id: applicationId, job_id: jobId, request_id: requestId }, { timeout: 20000 });
      setAssessmentSaveMessage("Verified assessment saved to the ATS application. Only minimised scores, criteria states, and review flags are retained.");
    } catch (error) {
      setAssessmentSaveMessage(explainError(error));
    } finally { setAssessmentSaving(false); }
  }

  function applyApiKey() {
    const value = apiKeyDraft.trim();
    setApiKey(value);
    try {
      if (value) sessionStorage.setItem("bluepace_feature_api_key", value);
      else sessionStorage.removeItem("bluepace_feature_api_key");
    } catch {
      // Continue with an in-memory key if session storage is disabled.
    }
    setNotice(value ? "API key kept for this browser session only." : "Optional API key cleared.");
    if (value === apiKey) refreshConnection();
  }

  function storeOpenRouterKey(value) {
    setOpenRouterKey(value);
    try {
      if (value) {
        sessionStorage.setItem("bluepace_ai_openrouter_key", value);
        sessionStorage.setItem("bluepace_openrouter_key", value);
      } else {
        sessionStorage.removeItem("bluepace_ai_openrouter_key");
        sessionStorage.removeItem("bluepace_openrouter_key");
      }
    } catch {
      // The in-memory state keeps the key usable if session storage is unavailable.
    }
  }

  function saveOpenRouterKey() {
    const value = openRouterKeyDraft.trim();
    storeOpenRouterKey(value);
    setInferenceTest({ status: "", message: "" });
    setNotice(value
      ? "OpenRouter key saved for this browser tab session."
      : "OpenRouter key cleared from this browser tab session.");
    void refreshConnection();
  }

  async function testOpenRouterInference() {
    const value = openRouterKeyDraft.trim();
    storeOpenRouterKey(value);
    setInferenceTest({ status: "checking", message: "Sending a short test prompt to OpenRouter. Provider usage charges may apply." });
    setNotice("");
    try {
      const response = await request("post", "/api/v1/test", {}, {
        timeout: 60000,
        baseURL: window.location.origin,
        skipAuth: true,
        ...(value ? { headers: { "X-OpenRouter-Api-Key": value } } : {}),
      });
      const result = response.data || {};
      setInferenceTest({
        status: "success",
        message: "Inference verified: " + String(result.model || "OpenRouter model")
          + " responded in " + String(Number(result.latency_ms) || 0) + " ms."
          + " Token usage: " + String(Number(result.prompt_tokens) || 0) + " prompt, "
          + String(Number(result.completion_tokens) || 0) + " completion.",
      });
      await refreshConnection();
    } catch (error) {
      setInferenceTest({ status: "error", message: explainError(error) });
    }
  }

  async function requestWithOptionsCompatibility(path, payload, requestOptions = {}) {
    try {
      return await request("post", path, payload, requestOptions);
    } catch (error) {
      const unsupported = getUnsupportedJdOptionFields(error);
      if (!unsupported.length || !payload?.options || typeof payload.options !== "object") throw error;
      const compatibleOptions = { ...payload.options };
      unsupported.forEach((field) => { delete compatibleOptions[field]; });
      setNotice(
        `The connected AI API does not support the optional ${unsupported.join(", ")} setting(s). Retrying with its default values.`,
      );
      return request("post", path, { ...payload, options: compatibleOptions }, requestOptions);
    }
  }

  async function requestJdUploadWithCompatibility(path, form, requestOptions = {}) {
    try {
      return await request("post", path, form, requestOptions);
    } catch (error) {
      const unsupported = getUnsupportedJdOptionFields(error);
      if (!unsupported.length) throw error;
      let compatibleOptions;
      try {
        compatibleOptions = JSON.parse(String(form.get("options") || "{}"));
      } catch {
        throw error;
      }
      unsupported.forEach((field) => { delete compatibleOptions[field]; });
      const retryForm = new FormData();
      for (const [key, value] of form.entries()) {
        if (key !== "options") retryForm.append(key, value);
      }
      retryForm.append("options", JSON.stringify(compatibleOptions));
      setNotice(
        `The connected AI API does not support the optional ${unsupported.join(", ")} setting(s). Retrying with its default values.`,
      );
      return request("post", path, retryForm, requestOptions);
    }
  }

  async function saveRubricWithCompatibility(rubric, requestOptions = {}) {
    try {
      return await request("post", "/v1/match/rubrics", { rubric }, requestOptions);
    } catch (error) {
      const compatible = removeUnsupportedRubricMetadata(rubric, error);
      if (!compatible) throw error;
      setNotice(
        `The connected AI API uses an older rubric schema. Retrying without ${compatible.removed} optional source-trace field(s); match criteria are unchanged.`,
      );
      return request("post", "/v1/match/rubrics", { rubric: compatible.rubric }, requestOptions);
    }
  }


  async function requestFormWithCompatibility(path, form, requestOptions = {}) {
    try {
      return await request("post", path, form, requestOptions);
    } catch (error) {
      // A selected profile is optional: older companions can use their
      // configured default profile when this field is not in their schema.
      const unsupported = getUnsupportedFormFields(error, ["profile"]);
      if (!unsupported.length) throw error;
      const retryForm = new FormData();
      for (const [key, value] of form.entries()) {
        if (!unsupported.includes(key)) retryForm.append(key, value);
      }
      setNotice(
        "The connected AI API does not support the selected profile field. Retrying with its configured default model.",
      );
      return request("post", path, retryForm, requestOptions);
    }
  }

  async function runJD(mode) {
    if (!jdText.trim()) {
      setJdError("Paste a job description or a role brief before running the standardizer.");
      return;
    }
    setJdLoading(true);
    setJdError("");
    setNotice("");
    setJdResult(null);
    try {
      const payload = {
        text: jdText.trim(),
        options: { mode: jdMode, detail: jdDetail, ...(selectedProfile ? { profile: selectedProfile } : {}) },
        overrides: {},
      };
      const response = await requestWithOptionsCompatibility(mode === "fast" ? "/v1/jd/generate" : "/v1/jd/standardize", payload, { timeout: 120000 });
      setJdResult(response.data);
      if (response.data?.request_id) setNotice(`Run completed · ${response.data.request_id}`);
    } catch (error) {
      setJdError(explainError(error));
    } finally {
      setJdLoading(false);
    }
  }


  async function uploadJobDescription(file) {
    if (!file) return;
    if (!/\.(pdf|docx|txt|md)$/i.test(file.name)) { setJdError("Upload a searchable PDF, DOCX, TXT, or Markdown job description."); return; }
    if (file.size > 5 * 1024 * 1024) { setJdError("The JD file must be 5 MB or smaller."); return; }
    setJdUploadBusy(true); setJdError(""); setJdSourceMessage("");
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("options", JSON.stringify({ mode: jdMode, detail: jdDetail, ...(selectedProfile ? { profile: selectedProfile } : {}) }));
      form.append("overrides", JSON.stringify({}));
      const response = await requestJdUploadWithCompatibility("/v1/jd/generate/upload", form, { timeout: 120000 });
      const result = response.data || {};
      const uploadError = getJdUploadError(result);
      if (uploadError) throw new Error(uploadError);
      setJdResult(result);
      const extracted = extractJdTextFromResult(result);
      setJdText(normalizeJdText(extracted || result.long_description_text || ""));
      setJdSourceMessage(`Imported ${file.name}. Review the extracted content and standardized output.`);
      setNotice("JD file uploaded and processed. Review the output, then generate and link the match rubric.");
    } catch (error) { setJdError(explainError(error)); }
    finally { setJdUploadBusy(false); }
  }

  async function importJobLink() {
    const value = jdLink.trim();
    if (!/^https?:\/\//i.test(value)) { setJdError("Enter a complete public job-posting URL starting with https://."); return; }
    setJdLinkBusy(true); setJdError(""); setJdSourceMessage("");
    try {
      const form = new FormData(); form.append("url", value);
      const response = await request("post", "/jobs/preview-url", form, { timeout: 30000 });
      const data = response.data || {};
      const importedDescription = normalizeJdText(data.description);
      if (!importedDescription.trim()) throw new Error("No usable job description was found at that link. Upload the JD document or paste the text instead.");
      setJdText(importedDescription); setJdResult(null); setJdSourceJobId("");
      setJdSourceMessage(`Imported ${data.title || "job posting"} from ${data.source_url || value}. Preview only; no ATS job was created.`);
      setNotice("Job description imported from link. Standardize it and choose the ATS job to attach the match rubric to.");
    } catch (error) { setJdError(explainError(error)); }
    finally { setJdLinkBusy(false); }
  }

  async function sendJdAssistant(value = jdAssistantInput) {
    const question = String(value || "").trim();
    if (!question || jdAssistantBusy) return;
    const context = [
      "You are the BluePace JD & Applicant Match workflow assistant. Give concise practical recruiter guidance.",
      "Help import job descriptions, standardize requirements, create match rubrics, and interpret evidence-based applicant matches.",
      "Never make hiring or rejection decisions. A recruiter must decide. Do not invent missing JD details; flag them for recruiter confirmation.",
      "Current JD text: " + (normalizeJdText(jdText).slice(0, 7000) || "Not provided yet."),
      "Workflow: JD result " + (jdResult ? "available" : "not generated") + "; rubric " + (selectedRubricId ? "selected" : "not selected") + ".",
      "Question: " + question,
    ].join("\\n");
    setJdAssistantInput("");
    setJdAssistantMessages((rows) => [...rows, { role: "user", text: question }]);
    setJdAssistantBusy(true);
    try {
      const response = localAiApiUrl
        ? await request("post", "/v1/assistant", { message: context }, { timeout: 300000 })
        : await apiRequest(token, "post", "/chatbot", { data: { message: context } });
      setJdAssistantMessages((rows) => [...rows, { role: "assistant", text: response.data?.answer || "I could not generate a reply. Please try again." }]);
    } catch (error) {
      const fallback = localAiApiUrl
        ? `Local Ollama assistant request failed: ${explainError(error)}`
        : "The ATS assistant service is unavailable right now. Retry in a moment; JD upload and standardization remain available.";
      setJdAssistantMessages((rows) => [...rows, { role: "assistant", text: fallback }]);
    } finally { setJdAssistantBusy(false); }
  }

  async function prepareSelectedJobForMatching() {
    const jobId = Number(jdSourceJobId) || null;
    const sourceJD = String(jdText || "").trim();
    if (!sourceJD) {
      setJdError("The selected ATS job does not contain a description. Add one to the job record first.");
      return;
    }
    setJdPrepareLoading(true);
    setRubricLoading(true);
    setJdError("");
    setRubricError("");
    setNotice("");
    setCandidateCard(null);

    // The rubric is source-grounded and deterministic by default. Start JD
    // standardization in parallel, but do not make recruiters wait for a model
    // generation call before receiving the reviewable rubric.
    const options = {
      mode: jdMode === "verbatim" ? "verbatim" : jdMode === "rewrite" ? "rewrite" : "light",
      detail: "concise",
    };
    setJdResult(null);
    setJdLoading(true);
    setJdSourceMessage("Building the rubric from the original JD while concise standardization runs in the background…");
    const standardizationTask = requestWithOptionsCompatibility("/v1/jd/generate", {
      text: sourceJD,
      options,
    }, { timeout: 120000 })
      .then((jdResponse) => {
        const standardized = jdResponse.data;
        if (standardized && Array.isArray(standardized.sections) && standardized.sections.length) {
          setJdResult(standardized);
          setJdError("");
          setJdSourceMessage("JD standardization completed. The rubric was built separately from your original JD text.");
        } else {
          const message = "JD Standardizer returned no structured sections. The original job description and saved rubric remain available for review.";
          setJdError(message);
          setJdSourceMessage(message);
        }
        return standardized;
      })
      .catch((error) => {
        const message = "JD standardization could not complete: " + explainError(error);
        setJdError(message + " The original job description and rubric remain available.");
        setJdSourceMessage("The rubric is available from the original JD. " + message);
        return null;
      })
      .finally(() => setJdLoading(false));

    let localDraft = null;
    const localDraftNotes = [{
      code: "fast_rules",
      message: "Instant source-grounded draft created directly from the original JD. No model call was used. Review item boundaries, importance and weights before relying on this rubric.",
    }];
    try {
      // Parse the JD synchronously in the browser. The previous flow made one
      // network call to compile the draft and a second to freeze it; that first
      // round trip duplicated deterministic work and made Step 03 feel slow.
      localDraft = buildSourceGroundedRubric(sourceJD);
      setRubric(localDraft);
      setSelectedRubricId("");
      setRubricNotes(localDraftNotes);
      setNotice("Rubric draft built locally. Saving its immutable version now; JD standardization continues separately.");
      setActiveTab("match");

      // Only the immutable save requires the API. This is one request instead
      // of compile → save, and the editable draft stays visible if saving fails.
      const saveResponse = await saveRubricWithCompatibility(localDraft, { timeout: 30000 });
      const saved = saveResponse.data?.rubric || saveResponse.data;
      if (!saved?.rubric_id || !Array.isArray(saved.items)) {
        throw new Error("The draft is ready to review, but the API did not confirm the immutable save. Use Save rubric version to retry.");
      }
      const existing = readSavedRubrics().filter((item) => item.rubric_id !== saved.rubric_id);
      const storage = writeSavedRubrics([saved, ...existing]);
      if (!storage.ok) {
        throw new Error("The API saved the rubric, but this browser could not store its local copy. Allow site storage or clear browser storage, then retry.");
      }
      setSavedRubrics([saved, ...existing].map(savedRubricOption));
      setRubric(saved);
      setSelectedRubricId(saved.rubric_id);

      if (jobId && !localAiApiUrl) {
        // Linking is secondary to the reviewable rubric.
        void request("post", `/ai-hiring/jobs/${jobId}/applicant-match-rubrics`, { rubric_id: saved.rubric_id }, { timeout: 20000 })
          .then(() => setJdSourceMessage("Rubric saved and linked to the ATS job. JD standardization is running independently."))
          .catch((error) => setJdSourceMessage("Rubric saved on this device, but ATS job linking failed: " + explainError(error)));
      }

      setNotice("Rubric created and saved. Review its requirements now; concise JD standardization is continuing in the background.");
      // Keep the promise observed; its own handlers update the JD result/status.
      void standardizationTask;
    } catch (error) {
      const message = explainError(error);
      if (localDraft) {
        setRubric(localDraft);
        setSelectedRubricId("");
        setRubricNotes(localDraftNotes);
        setRubricError("The draft is ready to review, but its immutable save did not complete: " + message);
      } else {
        setJdError(message);
        setRubricError(message);
      }
    } finally {
      setJdPrepareLoading(false);
      setRubricLoading(false);
    }
  }

  async function compileRubric() {
    // Always compile from the text currently visible in the JD editor. A
    // previously standardized result can be stale or belong to another job,
    // and must never override the recruiter's latest pasted description.
    const currentJD = String(jdText ?? "").trim();
    if (currentJD.length < 15) {
      setRubricError("Paste a job description with at least 15 characters to build a rubric.");
      return;
    }
    setRubricLoading(true);
    setRubricError("");
    setNotice("");
    setCandidateCard(null);
    try {
      // Step 03 draft creation is deterministic and source-grounded. Do it in
      // the browser so the recruiter sees the requirements immediately rather
      // than waiting for a remote API round trip just to split JD text.
      const nextRubric = buildSourceGroundedRubric(currentJD);
      const notes = [{
        code: "fast_rules",
        message: "Instant source-grounded draft created directly from the current JD. No model call or API request was needed. Review item boundaries, importance and weights before saving.",
      }];
      setRubric(nextRubric);
      setSelectedRubricId("");
      setRubricNotes(notes);
      setNotice("Draft created instantly from the current JD. Review the requirements, then save an immutable rubric version.");
    } catch (error) {
      setRubricError(explainError(error));
    } finally {
      setRubricLoading(false);
    }
  }

  async function loadRubric(id) {
    setSelectedRubricId(id);
    setRubricError("");
    if (!id) {
      setRubric(null);
      setCandidateCard(null);
      return;
    }
    setRubricLoading(true);
    try {
      const local = readSavedRubrics().find((item) => item.rubric_id === id);
      if (local) {
        setRubric(local);
        setCandidateCard(null);
        setNotice(`Loaded rubric ${id} from this browser session.`);
      } else {
        const response = await request("get", `/v1/match/rubrics/${encodeURIComponent(id)}`, undefined, { timeout: 10000 });
        setRubric(response.data);
        setCandidateCard(null);
        setNotice(`Loaded rubric ${id}.`);
      }
    } catch (error) {
      setRubricError(explainError(error));
    } finally {
      setRubricLoading(false);
    }
  }

  async function saveRubric() {
    if (!rubric) return;
    setRubricLoading(true);
    setRubricError("");
    setNotice("");
    try {
      const response = await saveRubricWithCompatibility(rubric, { timeout: 30000 });
      const saved = response.data;
      if (!saved?.rubric_id || !Array.isArray(saved.items)) {
        throw new Error("The save service returned no complete rubric version. Your draft is still open; please retry.");
      }
      const existing = readSavedRubrics().filter((item) => item.rubric_id !== saved.rubric_id);
      const nextRows = [saved, ...existing].slice(0, 50);
      const storage = writeSavedRubrics(nextRows);
      if (!storage.ok) {
        throw new Error("The AI service accepted the rubric, but this browser could not store it. Allow site storage or clear browser storage, then retry.");
      }
      setSavedRubrics(nextRows.map(savedRubricOption));
      setRubric(saved);
      setSelectedRubricId(saved.rubric_id);
      setNotice(storage.persistent
        ? `Rubric version saved on this device · ${saved.rubric_id}`
        : `Rubric saved for this tab only because persistent browser storage is unavailable · ${saved.rubric_id}`);
      // Saving is complete; refresh the picker in the background rather than
      // making the save button wait for a second network request.
      void refreshSavedRubrics();
    } catch (error) {
      setRubricError(explainError(error));
    } finally {
      setRubricLoading(false);
    }
  }

  async function analyzeResume() {
    if (!selectedRubricId) {
      setMatchError("Select a saved rubric or save the draft rubric first.");
      return;
    }
    if (!resumeFile && !resumeText.trim()) {
      setMatchError("Upload a resume (PDF, DOCX or TXT up to 5 MB) or paste resume text.");
      return;
    }
    if (resumeFile && resumeFile.size > MAX_FILE_BYTES) {
      setMatchError("Resume must be 5 MB or smaller.");
      return;
    }
    setMatchLoading(true);
    setMatchError("");
    setCandidateCard(null);
    setCandidateReview({ stage: "new", history: [] });
    setNotice("");
    try {
      const body = new FormData();
      body.append("rubric_id", selectedRubricId);
      if (resumeFile) body.append("file", resumeFile);
      else body.append("text", resumeText.trim());
      if (selectedProfile) body.append("profile", selectedProfile);
      const requestStartedAt = Date.now();
      const response = await requestFormWithCompatibility("/v1/match/analyze", body, { timeout: 120000 });
      const result = {
        ...response.data,
        performance: {
          ...(response.data?.performance || {}),
          client_round_trip_ms: Date.now() - requestStartedAt,
        },
      };
      setCandidateCard(result);
      setNotice("Analysis complete. Review the evidence before making any recruiting decision.");
    } catch (error) {
      setMatchError(explainError(error));
    } finally {
      setMatchLoading(false);
    }
  }



  async function runSampleAssessment() {
    if (connection !== "connected") {
      setMatchError("Connect to a working AI profile before running the sample assessment.");
      setActiveTab("match");
      return;
    }
    if (localAiApiUrl && !localAiApiVerified) {
      setMatchError("Reconnect and verify the local BluePace AI service before running the sample assessment.");
      setActiveTab("match");
      return;
    }

    setSampleAssessmentLoading(true);
    setMatchError("");
    setRubricError("");
    setNotice("Building the sample rubric and assessing the sample resume with the selected AI profile…");
    setCandidateCard(null);
    setCandidateReview({ stage: "new", history: [] });
    try {
      const draftResponse = await request("post", "/v1/match/rubrics", {
        jd_text: SAMPLE_JOB_DESCRIPTION,
      }, { timeout: 30000 });
      const draft = unwrapRubricDraft(draftResponse.data);
      const saveResponse = await saveRubricWithCompatibility(draft, { timeout: 30000 });
      const savedRubric = saveResponse.data?.rubric || saveResponse.data;
      if (!savedRubric?.rubric_id || !Array.isArray(savedRubric.items)) {
        throw new Error("The sample rubric was generated, but the API did not confirm that it was saved.");
      }

      const existing = readSavedRubrics().filter((item) => item.rubric_id !== savedRubric.rubric_id);
      const savedRows = [savedRubric, ...existing].slice(0, 50);
      const storage = writeSavedRubrics(savedRows);
      if (!storage.ok) {
        throw new Error("The sample rubric was saved by the API, but this browser could not save its local copy. Allow site storage and retry.");
      }

      const body = new FormData();
      body.append("rubric_id", savedRubric.rubric_id);
      const sampleFile = typeof File === "function"
        ? new File([SAMPLE_RESUME_TEXT], "Aarav_Sharma_Sample_Resume.txt", { type: "text/plain" })
        : null;
      if (sampleFile) body.append("file", sampleFile);
      else body.append("text", SAMPLE_RESUME_TEXT);
      if (selectedProfile) body.append("profile", selectedProfile);

      const analysisStartedAt = Date.now();
      const analysisResponse = await requestFormWithCompatibility("/v1/match/analyze", body, { timeout: 120000 });
      const result = {
        ...analysisResponse.data,
        performance: {
          ...(analysisResponse.data?.performance || {}),
          client_round_trip_ms: Date.now() - analysisStartedAt,
        },
        sampleScenario: "aarav-sharma",
      };

      setJdText(SAMPLE_JOB_DESCRIPTION);
      setJdResult(null);
      setRubric(savedRubric);
      setRubricNotes(draftResponse.data?.notes || []);
      setSavedRubrics(savedRows.map(savedRubricOption));
      setSelectedRubricId(savedRubric.rubric_id);
      setResumeFile(sampleFile);
      setResumeText(sampleFile ? "" : SAMPLE_RESUME_TEXT);
      setCandidateCard(result);
      setActiveTab("match");
      setNotice(`Sample assessment completed using ${selectedProfile || "the default AI profile"}. Actual match: ${result.scores?.match == null ? "manual review required" : result.scores.match + "%"}.`);
    } catch (error) {
      setMatchError(explainError(error));
      setNotice("The sample assessment did not complete. Review the error and keep the local AI terminal open.");
      setActiveTab("match");
    } finally {
      setSampleAssessmentLoading(false);
    }
  }

  function handleBatchFileSelection(event) {
    const selected = Array.from(event.target.files || []);
    event.target.value = "";
    if (!selected.length) return;

    const nextRows = [...batchFiles];
    const issues = [];
    for (const file of selected) {
      if (nextRows.length >= MAX_BULK_RESUMES) {
        issues.push(`The queue is limited to ${MAX_BULK_RESUMES} resumes. Remove files before adding more.`);
        break;
      }
      const validation = validateBulkResume(file, nextRows.map((row) => row.file));
      if (!validation.valid) {
        issues.push(`${file.name}: ${validation.reason}`);
        continue;
      }
      nextRows.push({
        id: `${Date.now()}-${nextRows.length}-${file.name}`,
        file,
        status: "queued",
        result: null,
        error: "",
      });
    }
    setBatchFiles(nextRows);
    setBatchError(issues.slice(0, 4).join(" "));
    setBatchProgress({ done: 0, total: 0 });
  }

  function updateBatchRow(id, patch) {
    setBatchFiles((current) => current.map((row) => row.id === id ? { ...row, ...patch } : row));
  }

  function overrideBatchEvidence(rowId, itemId, status) {
    setBatchFiles((current) => current.map((row) => row.id === rowId ? { ...row, result: withEvidenceOverride(row.result, itemId, status) } : row));
  }

  function overrideSavedApplicantEvidence(applicantId, itemId, status) {
    setSavedApplicants((current) => current.map((applicant) => applicant.id === applicantId ? { ...applicant, result: withEvidenceOverride(applicant.result, itemId, status) } : applicant));
  }

  function overrideCandidateEvidence(itemId, status) {
    setCandidateCard((current) => withEvidenceOverride(current, itemId, status));
  }

  function recordBatchCalibrationRating(rowId, itemId, status, reviewer) {
    setBatchFiles((current) => current.map((row) => row.id === rowId ? { ...row, result: withReviewerRating(row.result, itemId, reviewer, status) } : row));
  }

  function resolveBatchCalibration(rowId, itemId, status, note) {
    setBatchFiles((current) => current.map((row) => row.id === rowId ? { ...row, result: withCalibrationResolution(row.result, itemId, calibrationReviewerName, status, note) } : row));
  }

  function recordSavedCalibrationRating(applicantId, itemId, status, reviewer) {
    setSavedApplicants((current) => current.map((applicant) => applicant.id === applicantId ? { ...applicant, result: withReviewerRating(applicant.result, itemId, reviewer, status) } : applicant));
  }

  function resolveSavedCalibration(applicantId, itemId, status, note) {
    setSavedApplicants((current) => current.map((applicant) => applicant.id === applicantId ? { ...applicant, result: withCalibrationResolution(applicant.result, itemId, calibrationReviewerName, status, note) } : applicant));
  }

  function recordCandidateCalibrationRating(itemId, status, reviewer) {
    setCandidateCard((current) => withReviewerRating(current, itemId, reviewer, status));
  }

  function resolveCandidateCalibration(itemId, status, note) {
    setCandidateCard((current) => withCalibrationResolution(current, itemId, calibrationReviewerName, status, note));
  }

  function updateBatchReviewStage(rowId, stage) {
    const row = batchFiles.find((item) => item.id === rowId);
    if (!row || (row.reviewStage || "new") === stage) return;
    updateBatchRow(rowId, {
      reviewStage: stage,
      reviewHistory: appendReviewEvent(row.reviewHistory, { type: "stage", from: row.reviewStage || "new", to: stage }),
    });
  }

  function addBatchReviewNote(rowId, text) {
    const row = batchFiles.find((item) => item.id === rowId);
    if (!row) return;
    updateBatchRow(rowId, { reviewHistory: appendReviewEvent(row.reviewHistory, { type: "note", text }) });
  }

  function updateSavedReviewStage(applicantId, stage) {
    setSavedApplicants((current) => current.map((applicant) => {
      const from = applicant.reviewStage || "new";
      return applicant.id === applicantId && from !== stage
        ? { ...applicant, reviewStage: stage, reviewHistory: appendReviewEvent(applicant.reviewHistory, { type: "stage", from, to: stage }) }
        : applicant;
    }));
  }

  function addSavedReviewNote(applicantId, text) {
    setSavedApplicants((current) => current.map((applicant) => applicant.id === applicantId
      ? { ...applicant, reviewHistory: appendReviewEvent(applicant.reviewHistory, { type: "note", text }) }
      : applicant));
  }

  function updateBatchFollowUp(rowId, followUp) {
    const row = batchFiles.find((item) => item.id === rowId);
    if (!row) return;
    const followUpAt = followUp.followUpAt || "";
    const followUpNote = followUp.followUpNote || "";
    const changedDate = (row.followUpAt || "") !== followUpAt;
    updateBatchRow(rowId, {
      followUpAt,
      followUpNote,
      ...(changedDate ? { reviewHistory: appendReviewEvent(row.reviewHistory, { type: "followup", date: followUpAt, text: followUpNote }) } : {}),
    });
  }

  function updateSavedFollowUp(applicantId, followUp) {
    setSavedApplicants((current) => current.map((applicant) => {
      if (applicant.id !== applicantId) return applicant;
      const followUpAt = followUp.followUpAt || "";
      const followUpNote = followUp.followUpNote || "";
      const changedDate = (applicant.followUpAt || "") !== followUpAt;
      return {
        ...applicant,
        followUpAt,
        followUpNote,
        ...(changedDate ? { reviewHistory: appendReviewEvent(applicant.reviewHistory, { type: "followup", date: followUpAt, text: followUpNote }) } : {}),
      };
    }));
  }

  function updateCandidateFollowUp(followUp) {
    setCandidateReview((current) => {
      const followUpAt = followUp.followUpAt || "";
      const followUpNote = followUp.followUpNote || "";
      const changedDate = (current.followUpAt || "") !== followUpAt;
      return {
        ...current,
        followUpAt,
        followUpNote,
        ...(changedDate ? { history: appendReviewEvent(current.history, { type: "followup", date: followUpAt, text: followUpNote }) } : {}),
      };
    });
  }

  function updateCandidateReviewStage(stage) {
    setCandidateReview((current) => (current.stage || "new") === stage ? current : {
      stage,
      history: appendReviewEvent(current.history, { type: "stage", from: current.stage || "new", to: stage }),
    });
  }

  function addCandidateReviewNote(text) {
    setCandidateReview((current) => ({ ...current, history: appendReviewEvent(current.history, { type: "note", text }) }));
  }

  function removeBatchRow(id) {
    if (batchRunning) return;
    setBatchFiles((current) => current.filter((row) => row.id !== id));
    setBatchError("");
  }

  function clearBatchQueue() {
    if (batchRunning) return;
    setBatchFiles([]);
    setBatchCurrentName("");
    setBatchProgress({ done: 0, total: 0 });
    setBatchError("");
  }

  function downloadBulkCsv() {
    if (!batchFiles.length) return;
    const blob = new Blob([buildBulkMatchCsv(batchFiles)], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `bluepace-applicant-match-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  function downloadWorkspaceReport() {
    if (!activeWorkspaceId) return;
    const applicantsById = new Map();
    for (const applicant of [...savedApplicants, ...savedApplicantRows(batchFiles)]) applicantsById.set(applicant.id, applicant);
    const applicants = Array.from(applicantsById.values());
    if (candidateCard) applicants.unshift({ id: "individual-applicant", fileName: "Individual applicant assessment", status: "complete", result: candidateCard, reviewStage: candidateReview.stage, reviewHistory: candidateReview.history, followUpAt: candidateReview.followUpAt, followUpNote: candidateReview.followUpNote });
    const criteria = Array.isArray(rubric?.items) ? rubric.items : [];
    const criterionAnchor = (itemId, label) => {
      const index = criteria.findIndex((item) => item.id === itemId || item.label === label);
      return index >= 0 ? `criterion-${index + 1}` : "";
    };
    const applicantAnchor = (applicant, index) => `applicant-${index + 1}-${reportAnchor(applicant.id || applicant.fileName)}`;
    const criterionHtml = criteria.length
      ? `<ol class="criteria">${criteria.map((item, index) => `<li id="criterion-${index + 1}"><strong>${escapeHtml(item.label)}</strong> <span>${escapeHtml(item.importance || "")}${item.weight ? ` · weight ${escapeHtml(item.weight)}` : ""}</span>${item.source_text ? `<p>${escapeHtml(item.source_text)}</p>` : ""}</li>`).join("")}</ol>`
      : "<p>No rubric is saved in this workspace.</p>";
    const overviewRows = applicants.map((applicant, index) => {
      const result = applicant.result || {};
      const stage = REVIEW_STAGES.find(([value]) => value === applicant.reviewStage)?.[1] || "New";
      return `<tr><td><a href="#${applicantAnchor(applicant, index)}">${escapeHtml(applicant.fileName || "Applicant")}</a></td><td>${escapeHtml(stage)}</td><td>${applicant.followUpAt ? escapeHtml(formatLocalDate(applicant.followUpAt)) : "—"}</td><td>${result.scores?.match == null ? "—" : `${escapeHtml(result.scores.match)}%`}</td><td>${escapeHtml(result.applicant_id || "—")}</td></tr>`;
    }).join("");
    const applicantHtml = applicants.length
      ? applicants.map((applicant, index) => {
        const result = applicant.result || {};
        const stage = REVIEW_STAGES.find(([value]) => value === applicant.reviewStage)?.[1] || "New";
        const evidence = Array.isArray(result.evidence) ? result.evidence : [];
        const evidenceHtml = evidence.length ? evidence.map((item) => {
          const anchor = criterionAnchor(item.item_id, item.label);
          const reviewerRatings = latestReviewerRatings(item);
          const ratingsHtml = reviewerRatings.length ? `<p><strong>Independent reviewer ratings:</strong> ${reviewerRatings.map((rating) => `${escapeHtml(rating.reviewer)}: ${escapeHtml(rating.status)}`).join(" · ")}</p>` : "";
          const resolutionHtml = item.calibration_resolution ? `<p><strong>Agreed rating:</strong> ${escapeHtml(item.calibration_resolution.status)} · Resolved by ${escapeHtml(item.calibration_resolution.reviewer)}${item.calibration_resolution.note ? ` · ${escapeHtml(item.calibration_resolution.note)}` : ""}${item.calibration_resolution.at ? ` · ${escapeHtml(new Date(item.calibration_resolution.at).toLocaleString())}` : ""}</p>` : (hasReviewerDisagreement(item) ? '<p class="alert">Reviewer disagreement remains unresolved.</p>' : "");
          const excerpts = item.lines?.length ? `<ul>${item.lines.map((line) => `<li><strong>${escapeHtml(line.id || "Excerpt")}</strong> ${escapeHtml(line.text)}</li>`).join("")}</ul>` : '<p class="muted">No exact excerpt returned; inspect the original resume.</p>';
          return `<article class="evidence"><h4>${anchor ? `<a href="#${anchor}">${escapeHtml(item.label)}</a>` : escapeHtml(item.label)}</h4><p><strong>AI rating:</strong> ${escapeHtml(item.status || "unclear")} · <strong>Reviewer override:</strong> ${escapeHtml(item.review_override || "None")}</p>${ratingsHtml}${resolutionHtml}${item.note ? `<p>${escapeHtml(item.note)}</p>` : ""}${excerpts}</article>`;
        }).join("") : "<p>No criterion-level evidence is available for this applicant.</p>";
        const history = Array.isArray(applicant.reviewHistory) ? applicant.reviewHistory : [];
        const historyHtml = history.length ? `<ol class="history">${history.map((entry) => {
          const event = entry.type === "stage"
            ? `Stage changed from ${REVIEW_STAGES.find(([value]) => value === entry.from)?.[1] || entry.from} to ${REVIEW_STAGES.find(([value]) => value === entry.to)?.[1] || entry.to}`
            : entry.type === "followup"
              ? `Follow-up ${entry.date ? `scheduled for ${formatLocalDate(entry.date)}` : "cleared"}${entry.text ? `: ${entry.text}` : ""}`
              : `Reviewer note: ${entry.text || ""}`;
          return `<li><span>${escapeHtml(event)}</span><time>${escapeHtml(entry.at ? new Date(entry.at).toLocaleString() : "Time not recorded")}</time></li>`;
        }).join("")}</ol>` : "<p>No stage changes or reviewer notes.</p>";
        const flags = Array.isArray(result.flags) && result.flags.length ? `<ul>${result.flags.map((flag) => `<li>${escapeHtml(flag)}</li>`).join("")}</ul>` : "<p>None returned.</p>";
        const rawSummary = result.summary?.value || result.summary || "";
        const summary = typeof rawSummary === "string" ? rawSummary : "";
        return `<section class="applicant" id="${applicantAnchor(applicant, index)}"><h3>${escapeHtml(applicant.fileName || "Applicant")}</h3><p class="meta">Stage: ${escapeHtml(stage)} · Match: ${result.scores?.match == null ? "—" : `${escapeHtml(result.scores.match)}%`} · Candidate ref: ${escapeHtml(result.applicant_id || "—")}</p>${applicant.followUpAt ? `<p><strong>Follow-up:</strong> ${escapeHtml(formatLocalDate(applicant.followUpAt))}${applicant.followUpNote ? ` · ${escapeHtml(applicant.followUpNote)}` : ""}</p>` : ""}${applicant.error ? `<p class="alert">${escapeHtml(applicant.error)}</p>` : ""}${summary ? `<p>${escapeHtml(summary)}</p>` : ""}<h4>Evidence and reviewer ratings</h4>${evidenceHtml}<h4>Review activity</h4>${historyHtml}<h4>Flags to review</h4>${flags}</section>`;
      }).join("")
      : "<p>No applicant assessments are saved in this workspace yet.</p>";
    const workspaceNotesHtml = workspaceNotes.trim() ? `<section><h2>Workspace notes</h2><p class="pre">${escapeHtml(workspaceNotes)}</p></section>` : "";
    const jobDescriptionHtml = jdText.trim() ? `<section><h2>Source job description</h2><p class="pre">${escapeHtml(jdText)}</p></section>` : "";
    const standardizedHtml = descriptionOutput ? `<section><h2>Standardized job description</h2><p class="pre">${escapeHtml(descriptionOutput)}</p></section>` : "";
    const report = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${escapeHtml(workspaceName || jdTitle)} · Applicant review</title><style>
      :root{color-scheme:light;font-family:Arial,Helvetica,sans-serif;color:#172033}body{max-width:980px;margin:32px auto;padding:0 24px;line-height:1.55}h1{font-size:28px;margin-bottom:4px}h2{font-size:20px;margin-top:28px;border-bottom:1px solid #d7dce4;padding-bottom:7px}h3{font-size:18px;margin-bottom:4px}h4{font-size:14px;margin:20px 0 8px}p{white-space:normal}a{color:#1557a0}table{width:100%;border-collapse:collapse;margin:14px 0}th,td{text-align:left;vertical-align:top;border:1px solid #d7dce4;padding:8px;font-size:13px}.muted,.meta,time{color:#596579;font-size:12px}.criteria{padding-left:24px}.criteria li{padding:8px 4px}.criteria span{color:#596579;font-size:12px}.criteria p{margin:4px 0 0;color:#596579;font-size:12px}.applicant{border:1px solid #d7dce4;border-radius:8px;padding:16px;margin:22px 0;break-inside:avoid}.evidence{padding:10px 12px;margin:10px 0;border-left:3px solid #c49a4a;background:#fafaf8}.evidence h4{margin-top:2px}.evidence ul{padding-left:22px}.evidence li{margin:6px 0}.history{padding-left:22px}.history li{margin:8px 0}.history time{display:block}.alert{color:#8b1d1d;background:#fff2f2;padding:8px}.pre{white-space:pre-wrap;background:#fafaf8;border:1px solid #e3e7ed;padding:12px;border-radius:6px;font-size:13px}.notice{border:1px solid #ead9b1;background:#fbf6e9;padding:12px;border-radius:6px;font-size:12px}@media print{body{margin:0 auto;padding:0 8mm}a{color:inherit;text-decoration:none}.applicant{break-inside:avoid}}
      </style></head><body><h1>${escapeHtml(workspaceName || jdTitle)}</h1><p class="meta">Applicant review summary · Generated ${escapeHtml(new Date().toLocaleString())}</p><p class="notice">Hiring decision support only. Verify source evidence and apply consistent criteria; this report does not make hiring recommendations. Review applicant information carefully before sharing.</p>${workspaceNotesHtml}<section><h2>Job and rubric</h2><p><strong>Role:</strong> ${escapeHtml(jdTitle)}</p>${jobDescriptionHtml}${standardizedHtml}<h3>Review criteria</h3>${criterionHtml}</section><section><h2>Applicant overview</h2>${applicants.length ? `<table><thead><tr><th>Applicant</th><th>Stage</th><th>Follow-up date</th><th>Match</th><th>Candidate ref</th></tr></thead><tbody>${overviewRows}</tbody></table>` : "<p>No applicants are saved in this workspace yet.</p>"}</section><section><h2>Applicant evidence and activity</h2>${applicantHtml}</section></body></html>`;
    const fileName = (workspaceName || jdTitle || "job-review").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "job-review";
    const url = URL.createObjectURL(new Blob([report], { type: "text/html;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `${fileName}-review-summary.html`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    setNotice("Review summary exported as a standalone HTML file. Open it in a browser to print or save as PDF.");
  }

  async function runBatchMatches(retryOnly = false, onlyIds = null) {
    if (!selectedRubricId) {
      setBatchError("Select a saved rubric or save the draft rubric before running bulk matching.");
      return;
    }
    if (connection !== "connected") {
      setBatchError("The AI API is not connected. Restore the feature API connection before processing resumes.");
      return;
    }
    const queue = batchFiles.filter((row) => {
      if (!row.file) return false;
      if (onlyIds?.length) return onlyIds.includes(row.id) && ["queued", "failed"].includes(row.status);
      return retryOnly ? row.status === "failed" : row.status === "queued";
    });
    if (!queue.length) {
      setBatchError(retryOnly ? "There are no failed resumes to retry." : "Add at least one queued resume first.");
      return;
    }

    setBatchRunning(true);
    setBatchError("");
    setNotice("");
    setBatchCurrentName("");
    setBatchProgress({ done: 0, total: queue.length });
    let complete = 0;
    let manual = 0;
    let rulesOnly = 0;
    let failed = 0;
    let processed = 0;
    let stopQueue = false;
    let fatalMessage = "";
    const activeNames = new Set();
    const syncActiveNames = () => setBatchCurrentName(Array.from(activeNames).join(" · ").slice(0, 180));

    const concurrency = getBulkMatchConcurrency(selectedProfile);
    await runWithConcurrency(queue, concurrency, async (row) => {
      activeNames.add(row.file.name);
      syncActiveNames();
      updateBatchRow(row.id, { status: "processing", error: "" });

      const body = new FormData();
      body.append("rubric_id", selectedRubricId);
      body.append("file", row.file);
      if (selectedProfile) body.append("profile", selectedProfile);

      try {
        const requestStartedAt = Date.now();
        const response = await request("post", "/v1/match/analyze", body, { timeout: 120000 });
        const result = {
          ...response.data,
          performance: {
            ...(response.data?.performance || {}),
            client_round_trip_ms: Date.now() - requestStartedAt,
          },
        };
        const rulesOnlyResult = result?.versions?.assessment_mode === "rules_only"
          || result?.versions?.profile === "rules"
          || result?.flags?.includes("rules_only_assessment")
          || Number(result?.usage?.llm_calls) === 0;
        const status = rulesOnlyResult ? "rules_only" : result?.status === "manual" ? "manual" : "complete";
        updateBatchRow(row.id, { status, result, error: "" });
        if (status === "rules_only") rulesOnly += 1;
        else if (status === "manual") manual += 1;
        else complete += 1;

        // A 402 may be converted by the backend into HTTP 200 with an explicit
        // rules-only fallback. Keep that result, then stop claiming new resumes.
        const resultStopReason = getBulkResultStopReason(result);
        if (resultStopReason) {
          stopQueue = true;
          fatalMessage = fatalMessage || resultStopReason;
        }
      } catch (error) {
        const message = explainError(error);
        updateBatchRow(row.id, { status: "failed", error: message, result: null });
        failed += 1;

        // Stop claiming new files after a shared provider/API failure.
        // In particular, 402 and 429 must not be repeated for every resume.
        // Requests already in flight finish; all unstarted rows stay queued.
        const stopReason = getBulkBatchStopReason(error);
        if (stopReason) {
          stopQueue = true;
          fatalMessage = fatalMessage || stopReason;
        }
      } finally {
        activeNames.delete(row.file.name);
        syncActiveNames();
        processed += 1;
        setBatchProgress({ done: processed, total: queue.length });
      }
    }, () => stopQueue);

    setBatchCurrentName("");
    setBatchRunning(false);
    setNotice(`Bulk match finished: ${complete} complete, ${rulesOnly} rules-only, ${manual} requiring manual review, ${failed} failed. ${processed} of ${queue.length} queued resumes processed with up to ${concurrency} running at once. Rules-only results use direct text evidence and do not assess experience dates or fuzzy criteria. Review every result before making a recruiting decision.`);
    if (fatalMessage) {
      const unstarted = queue.length - processed;
      setBatchError(`${fatalMessage} ${unstarted} unstarted resume(s) remain queued. Resolve the shared provider/API issue, then use Run queued to continue.`);
    }
  }

  function updateRubricItem(index, patch) {
    setRubric((current) => current ? {
      ...current,
      rubric_id: null,
      rubric_hash: null,
      created_at: null,
      items: current.items.map((item, itemIndex) => itemIndex === index ? { ...item, ...patch } : item),
    } : current);
    setSelectedRubricId("");
    setCandidateCard(null);
  }

  function updateRubricWeight(key, value) {
    setRubric((current) => current ? {
      ...current,
      rubric_id: null,
      rubric_hash: null,
      created_at: null,
      weights: { ...current.weights, [key]: Number(value) },
    } : current);
    setSelectedRubricId("");
    setCandidateCard(null);
  }

  const jdTitle = jdResult?.fields?.title?.value || jdResult?.fields?.title?.raw || jdResult?.title?.text || "Job description review";
  const descriptionOutput = jdResult?.description_markdown || jdResult?.long_description || jdResult?.long_description_annotated || jdResult?.long_description_text || "";
  // Older local AI companions incorrectly returned provider availability as a blocker.
  // Normalize only that diagnostic; genuine content blockers remain visible.
  const jdPublicationResult = normalizeJdPublicationGate(jdResult);
  const matchScore = candidateCard?.scores?.match;
  const workspaceProgressState = { jdText, jdResult, rubric, applicants: [...savedApplicants, ...savedApplicantRows(batchFiles)], candidateCard };
  const batchQueuedCount = batchFiles.filter((row) => row.status === "queued").length;
  const batchFailedCount = batchFiles.filter((row) => row.status === "failed").length;
  const batchTerminalCount = batchFiles.filter((row) => ["complete", "rules_only", "manual", "failed", "file_missing"].includes(row.status)).length;
  const calibrationEvidence = [
    ...[...savedApplicants, ...savedApplicantRows(batchFiles)].flatMap((applicant) => (applicant.result?.evidence || []).map((item) => ({ item, applicant: applicant.fileName || "Applicant" }))),
    ...(candidateCard?.evidence || []).map((item) => ({ item, applicant: "Individual applicant" })),
  ];
  const unresolvedCalibrationCount = calibrationEvidence.filter(({ item }) => hasReviewerDisagreement(item) && !item.calibration_resolution).length;
  const resolvedCalibrationCount = calibrationEvidence.filter(({ item }) => Boolean(item.calibration_resolution)).length;
  const calibrationReviewers = new Set(calibrationEvidence.flatMap(({ item }) => latestReviewerRatings(item).map((rating) => rating.reviewer))).size;
  const followUpsById = new Map();
  for (const applicant of [...savedApplicants, ...savedApplicantRows(batchFiles)]) {
    if (applicant.followUpAt) followUpsById.set(applicant.id, applicant);
  }
  if (candidateCard && candidateReview.followUpAt) followUpsById.set("individual-applicant", { id: "individual-applicant", fileName: "Individual applicant assessment", reviewStage: candidateReview.stage, followUpAt: candidateReview.followUpAt, followUpNote: candidateReview.followUpNote });
  const followUpEntries = Array.from(followUpsById.values()).map((applicant) => ({ ...applicant, reminderState: followUpState(applicant.followUpAt) })).sort((a, b) => a.followUpAt.localeCompare(b.followUpAt));
  const overdueFollowUpCount = followUpEntries.filter((applicant) => applicant.reminderState === "overdue").length;
  const todayFollowUpCount = followUpEntries.filter((applicant) => applicant.reminderState === "today").length;

  return (
    <div className="space-y-6">
      <section className="overflow-hidden rounded-xl border border-ink-200 bg-white shadow-sm">
        <div className="bg-ink-950 px-5 py-6 text-white sm:px-7">
          <div className="flex flex-wrap items-start justify-between gap-5">
            <div className="max-w-3xl">
              <div className="flex flex-wrap items-center gap-2">
                <Pill tone="gold">NEW WORKSPACE</Pill>
                <span className="text-xs font-medium text-ink-300">JD Standardizer · Applicant Match</span>
              </div>
              <h1 className="mt-3 text-2xl font-semibold tracking-tight sm:text-3xl">From job brief to evidence-based candidate review</h1>
              <p className="mt-2 max-w-2xl text-sm leading-6 text-ink-200">Standardize a job description, turn its requirements into a reviewable rubric, then analyze resumes against job-related evidence. Recruiters remain responsible for decisions.</p>
            </div>
            <div className="min-w-[210px] rounded-lg border border-white/15 bg-white/5 p-4">
              <p className="text-[10px] font-semibold uppercase tracking-[0.13em] text-ink-300">AI service status</p>
              <div className="mt-2 flex items-center gap-2">
                <span className={`h-2.5 w-2.5 rounded-full ${connection === "connected" ? "bg-emerald-400" : connection === "checking" ? "animate-pulse bg-amber-300" : "bg-rose-400"}`} />
                <span className="text-sm font-semibold">{connection === "connected" ? "Connected" : connection === "checking" ? "Checking" : "Not connected"}</span>
              </div>
              <p className="mt-2 text-xs leading-5 text-ink-300">{connectionMessage}</p>
              <button type="button" onClick={refreshConnection} disabled={connection === "checking"} className="mt-3 text-xs font-semibold text-gold-300 underline underline-offset-4 disabled:opacity-50">Retry connection</button>
            </div>
          </div>
        </div>
        <div className="space-y-3 border-b border-ink-100 bg-white px-4 py-4 sm:px-6">
          <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(180px,0.65fr)_auto] xl:items-end">
            <Field label="Saved job workspace" hint="Keep the JD, rubric, applicant results and notes together.">
              <select value={activeWorkspaceId} onChange={(event) => activateWorkspace(workspaces.find((workspace) => workspace.id === event.target.value))} className={fieldClass}>
                <option value="">Current session · not saved</option>
                {workspaces.map((workspace) => <option key={workspace.id} value={workspace.id}>{workspace.title} · {workspaceProgress(workspace)}</option>)}
              </select>
            </Field>
            <Field label="Workspace name">
              <input value={workspaceName} onChange={(event) => setWorkspaceName(event.target.value)} placeholder={jdTitle || "e.g. Senior Data Engineer · Hyderabad"} className={fieldClass} maxLength={120} />
            </Field>
            <Field label="Calibration reviewer" hint="Name or initials required to record ratings.">
              <input value={calibrationReviewerName} onChange={(event) => setCalibrationReviewerName(event.target.value)} placeholder="Reviewer name" className={fieldClass} maxLength={80} />
            </Field>
            <div className="flex flex-wrap gap-2">
              <button type="button" className={secondaryButton} onClick={createWorkspace}>New workspace</button>
              <button type="button" className={primaryButton} onClick={() => { void saveWorkspace(); }}>Save workspace</button>
              <button type="button" className={secondaryButton} onClick={syncWorkspaceToTeam} disabled={!token || teamWorkspaceBusy} title="Share this saved workspace with authenticated members of your organization">{teamWorkspaceBusy ? "Syncing…" : "Sync with team"}</button>
              <button type="button" className={secondaryButton} onClick={loadTeamWorkspaces} disabled={!token || teamWorkspaceBusy}>{teamWorkspaceBusy ? "Loading…" : "Load team workspaces"}</button>
              <button type="button" className={secondaryButton} onClick={downloadWorkspaceReport} disabled={!activeWorkspaceId} title="Export a standalone HTML report you can print or save as PDF">Export summary</button>
              <button type="button" className={secondaryButton} onClick={deleteWorkspace} disabled={!activeWorkspaceId}>Delete</button>
            </div>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-ink-500">
            <span>{activeWorkspaceId ? `Progress: ${workspaceProgress(workspaceProgressState)}` : "Create or save a workspace to preserve this review."}</span>
            <span>Workspaces save on this device; use team sync to share them with your organization. Resume files and pasted resume text are not stored.</span>
          </div>
          {workspaceStorageError && <p role="alert" className="text-xs text-rose-700">Browser storage could not save this workspace. Check available device storage.</p>}
          <details>
            <summary className="cursor-pointer text-xs font-semibold text-ink-600">Workspace notes</summary>
            <textarea value={workspaceNotes} onChange={(event) => setWorkspaceNotes(event.target.value)} rows={3} maxLength={10000} placeholder="Add recruiter context, review reminders, or decisions to revisit." className={`${fieldClass} mt-2 resize-y leading-6`} />
          </details>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-ink-100 bg-white px-4 py-3 sm:px-6">
          <div>
            <p className="text-xs font-semibold text-ink-900">One-click JD preparation</p>
            <p className="mt-1 text-[11px] leading-5 text-ink-500">Standardize the current job description first, then automatically build, save and select its source-grounded match rubric. No extra inputs are required.</p>
          </div>
          <button type="button" className={primaryButton} onClick={prepareSelectedJobForMatching} disabled={jdPrepareLoading || jdLoading || rubricLoading || connection !== "connected" || !jdText.trim()}>
            {jdPrepareLoading ? "Saving rubric…" : jdLoading ? "JD standardizing in background…" : "Standardize JD + auto setup"}
          </button>
        </div>
        <div className="flex flex-wrap gap-2 border-b border-ink-100 bg-[#fafaf8] px-4 py-3 sm:px-6" role="tablist" aria-label="AI feature workflows">
          <button type="button" role="tab" aria-selected={activeTab === "jd"} onClick={() => setActiveTab("jd")} className={`rounded-md px-4 py-2 text-sm font-semibold ${activeTab === "jd" ? "bg-ink-950 text-white" : "text-ink-600 hover:bg-ink-100"}`}>1 · JD Standardizer</button>
          <button type="button" role="tab" aria-selected={activeTab === "match"} onClick={() => setActiveTab("match")} className={`rounded-md px-4 py-2 text-sm font-semibold ${activeTab === "match" ? "bg-ink-950 text-white" : "text-ink-600 hover:bg-ink-100"}`}>2 · Applicant Match</button>
          <div className="ml-auto flex flex-wrap items-center justify-end gap-2">
            <span className="hidden text-xs text-ink-500 sm:inline">Model</span>
            <select aria-label="AI model profile" value={selectedProfile} onChange={(event) => setSelectedProfile(event.target.value)} className="max-w-[230px] rounded-md border border-ink-200 bg-white px-2.5 py-2 text-xs text-ink-700">
              <option value="">Backend default</option>
              {models.some((model) => model.free_endpoint) && (
                <optgroup label="Free OpenRouter models">
                  {models.filter((model) => model.free_endpoint).map((model) => <option key={model.id} value={model.id} disabled={!model.enabled}>{model.label}{model.enabled ? "" : ` · ${model.disabled_reason || "setup required"}`}</option>)}
                </optgroup>
              )}
              <optgroup label="Other models">
                {models.filter((model) => !model.free_endpoint).map((model) => <option key={model.id} value={model.id} disabled={!model.enabled}>{model.label}{model.enabled ? "" : ` · ${model.disabled_reason || "setup required"}`}</option>)}
              </optgroup>
            </select>
            {connection === "connected" && models.length > 0 && !models.some((model) => model.enabled && model.id !== "rules") && (
              <p role="status" className="basis-full max-w-[620px] text-right text-[11px] leading-4 text-amber-800">
                Only the Built-in Rules Engine is enabled right now. To use Qwen3 locally without hosted credits, connect Local Ollama below. Hosted models become selectable after their provider API key is configured and the model list is refreshed.
              </p>
            )}
            {models.some((model) => model.id === selectedProfile && model.free_endpoint) && (
              <p role="note" className="basis-full max-w-[620px] text-right text-[11px] leading-4 text-amber-800">
                Free shared inference is rate-limited and provider data policies vary. Use synthetic or anonymised demo data only; do not send identifiable candidate resumes or confidential hiring data unless your organisation has approved that provider.
              </p>
            )}
          </div>
        </div>
        <div className="border-b border-ink-100 px-5 py-4 sm:px-6">
          <div className="rounded-lg border border-emerald-200 bg-emerald-50/60 p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <p className="text-sm font-semibold text-emerald-950">Local Ollama connection</p>
                <p className="mt-1 text-xs leading-5 text-emerald-900">Run Qwen3 8B on this computer for JD Standardizer and Applicant Match. No provider key, OpenRouter credits or cloud inference charges.</p>
              </div>
              {localAiApiUrl && <Pill tone="good">Local mode active</Pill>}
            </div>
            <div className="mt-3 grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto_auto] sm:items-end">
              <Field label="Local AI API URL (optional)" hint="Only for Ollama running on this computer. Leave blank to use BluePace's hosted AI API. To connect locally, start backend/start-local-ai.ps1 first.">
                <input
                  type="url"
                  name="bluepace_local_ai_api_url"
                  autoComplete="off"
                  autoCapitalize="none"
                  spellCheck={false}
                  inputMode="url"
                  value={localAiApiDraft}
                  onChange={(event) => setLocalAiApiDraft(event.target.value)}
                  placeholder="http://127.0.0.1:8000"
                  className={fieldClass}
                />
              </Field>
              <button type="button" className={primaryButton} onClick={() => void connectLocalAiApi()} disabled={localAiApiTest.status === "checking"}>
                {localAiApiTest.status === "checking" ? "Connecting…" : localAiApiUrl ? "Reconnect local model" : "Connect local model"}
              </button>
              <button type="button" className={secondaryButton} onClick={useHostedAiApi}>Use hosted AI</button>
            </div>
            {localAiApiTest.message && <p role="status" className={`mt-3 rounded-md border px-3 py-2 text-xs leading-5 ${localAiApiTest.status === "error" ? "border-rose-200 bg-rose-50 text-rose-900" : localAiApiTest.status === "success" ? "border-emerald-200 bg-white text-emerald-900" : "border-amber-200 bg-amber-50 text-amber-900"}`}>{localAiApiTest.message}</p>}
            <p className="mt-2 text-[11px] leading-5 text-emerald-900">Only JD & Applicant Match AI calls switch to the local computer. ATS login, jobs and applications continue using the hosted ATS API. Edge or Chrome may request Local Network Access on your first click; choose Allow. If blocked, open the browser site permissions and allow Local network access for this BluePace site. Keep the local service running while using local inference.</p>
          </div>
        </div>
        <div className="border-b border-ink-100 px-5 py-4 sm:px-6">
          <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
            <Field label="OpenRouter API key (provider credential)" hint="Required for hosted OpenRouter models, including the free options. This is different from X-API-Key and is kept only in this browser tab session. Local Ollama does not use this key.">
              <input type="password" autoComplete="off" value={openRouterKeyDraft} onChange={(event) => setOpenRouterKeyDraft(event.target.value)} placeholder="sk-or-v1-…" className={fieldClass} />
            </Field>
            <div className="flex flex-wrap gap-2">
              <button type="button" className={secondaryButton} onClick={saveOpenRouterKey}>Save key & refresh</button>
              <button type="button" className={primaryButton} onClick={() => void testOpenRouterInference()} disabled={inferenceTest.status === "checking"}>{inferenceTest.status === "checking" ? "Testing…" : "Test real inference"}</button>
            </div>
          </div>
          <p className="mt-2 text-[11px] leading-5 text-ink-500">The inference test sends a tiny prompt to the selected OpenRouter model and can incur a small provider charge. The key is not displayed in test results or logged by this UI.</p>
          {inferenceTest.message && <div role="status" className={"mt-3 rounded-md border px-3 py-2 text-xs leading-5 " + (inferenceTest.status === "error" ? "border-rose-200 bg-rose-50 text-rose-900" : inferenceTest.status === "success" ? "border-emerald-200 bg-emerald-50 text-emerald-900" : "border-amber-200 bg-amber-50 text-amber-900")}>{inferenceTest.message}</div>}
        </div>
        <details className="border-b border-ink-100 px-5 py-3 sm:px-6">
          <summary className="cursor-pointer text-xs font-semibold text-ink-600">API access settings (optional)</summary>
          <div className="mt-3 grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
            <Field label="X-API-Key" hint="Kept in session storage for this browser tab session. Never sent to GitHub or stored by this UI. Leave blank if the backend does not require API-key authentication.">
              <input type="password" autoComplete="off" value={apiKeyDraft} onChange={(event) => setApiKeyDraft(event.target.value)} placeholder="Paste API key only if your backend requires one" className={fieldClass} />
            </Field>
            <button type="button" className={secondaryButton} onClick={applyApiKey}>Apply key & test connection</button>
          </div>
        </details>
        <div className="px-5 py-5 sm:px-7 sm:py-6">
          {connection === "connected" && models.some((model) => model.id === "rules" && model.enabled) && models.filter((model) => model.id !== "rules").every((model) => !model.enabled) && (
            <div role="status" className="mb-4 rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm leading-6 text-amber-950">
              <p className="font-semibold">Built-in Rules Engine is enabled; hosted AI keys are not configured.</p>
              <p className="mt-1">You can standardize a JD, build a rubric and compare resumes using explicit keyword evidence now. This is deterministic text matching, not generative AI; it can miss synonyms and context. To use hosted AI, save a valid provider API key above. To avoid provider credits, connect the local Ollama model above.</p>
            </div>
          )}
          {connection === "connected" && models.length > 0 && models.every((model) => !model.enabled) && (
            <div role="status" className="mb-4 rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm leading-6 text-amber-950">
              <p className="font-semibold">Model API is online; no model profile is enabled.</p>
              <p className="mt-1">Retry the connection. Hosted AI models require a valid provider key; local models must run on a computer reachable by the API.</p>
            </div>
          )}
          {notice && <div role="status" className="mb-4 rounded-md border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-900">{notice}</div>}
          {connection === "unavailable" && (
            <div className="mb-5 rounded-md border border-amber-200 bg-amber-50 px-4 py-3">
              <p className="text-sm font-semibold text-amber-950">The interface is deployed; the AI API is not confirmed available.</p>
              <p className="mt-1 text-sm leading-6 text-amber-900">{connectionMessage}</p>
              <p className="mt-2 text-xs leading-5 text-amber-900">The front end and AI backend deploy separately. This panel will not fabricate results or silently switch to local mock output.</p>
            </div>
          )}

          {activeTab === "jd" && (
            <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(330px,0.9fr)]">
              <div className="space-y-4">
                <SectionHeading eyebrow="Step 01" title="Job description input" detail="Load the description from an existing ATS job, or use the manual field for an external role." action={<button type="button" className={secondaryButton} onClick={runSampleAssessment} disabled={sampleAssessmentLoading || matchLoading || connection !== "connected"}>{sampleAssessmentLoading ? "Running sample…" : "Run end-to-end sample"}</button>} />
                <Field label="Import from existing ATS job" hint="Selecting a job automatically loads its saved description below.">
                  <select value={jdSourceJobId} onChange={(event) => { setJdSourceJobId(event.target.value); setJdSourceMessage(""); }} className={fieldClass}>
                    <option value="">Choose an ATS job to import…</option>
                    {jobs.filter((job) => job && job.id != null).map((job) => <option key={job.id} value={job.id}>{job.title || job.job_title || `Job #${job.id}`}</option>)}
                  </select>
                </Field>
                {jdSourceMessage && <p role="status" className="rounded-md border border-ink-100 bg-ink-50 px-3 py-2 text-xs leading-5 text-ink-700">{jdSourceMessage}</p>}
                <div className="grid gap-3 rounded-lg border border-ink-100 bg-[#fafaf8] p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2"><p className="text-xs font-semibold text-ink-800">Import a job description</p><Pill>PDF · DOCX · TXT · MD · URL</Pill></div>
                  <Field label="Upload JD file" hint="Maximum 5 MB. Text-based PDF and DOCX files work best.">
                    <input type="file" accept=".pdf,.docx,.txt,.md,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" onChange={(event) => { const file = event.target.files?.[0]; if (file) uploadJobDescription(file); event.target.value = ""; }} className={fieldClass} disabled={jdUploadBusy || jdLinkBusy} />
                  </Field>
                  {jdUploadBusy && <p className="text-xs text-ink-500">Uploading and extracting JD content…</p>}
                  <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto]">
                    <Field label="Import from public job link" hint="Preview only; this does not create an ATS job."><input type="url" value={jdLink} onChange={(event) => setJdLink(event.target.value)} placeholder="https://company.com/careers/job-title" className={fieldClass} /></Field>
                    <button type="button" className={secondaryButton} onClick={importJobLink} disabled={jdLinkBusy || jdUploadBusy || !jdLink.trim()}>{jdLinkBusy ? "Importing…" : "Import link"}</button>
                  </div>
                </div>
                <Field label="Job description or brief" hint={`${jdText.length.toLocaleString()} characters · API input limit is deployment-configured`}>
                  <textarea value={jdText} onChange={(event) => { setJdText(event.target.value); setJdResult(null); setJdError(""); setRubricError(""); }} rows={13} maxLength={60000} placeholder={"Example: Senior Data Engineer\nLocation: Hyderabad / Hybrid\nRequired: Python, SQL, Airflow, cloud data platforms\nResponsibilities: Build reliable data pipelines, own data quality, and partner with analytics teams."} className={`${fieldClass} resize-y leading-6`} />
                </Field>
                <div className="grid gap-3 sm:grid-cols-2">
                  <Field label="Writing mode">
                    <select value={jdMode} onChange={(event) => setJdMode(event.target.value)} className={fieldClass}>
                      <option value="verbatim">Verbatim · preserve source</option>
                      <option value="light">Light edit · improve clarity</option>
                      <option value="rewrite">Rewrite · restructure language</option>
                    </select>
                  </Field>
                  <Field label="Output detail" hint="Concise is faster. Detailed adds more AI-generated content.">
                    <select value={jdDetail} onChange={(event) => setJdDetail(event.target.value)} className={fieldClass}>
                      <option value="detailed">Detailed</option>
                      <option value="concise">Concise · faster</option>
                    </select>
                  </Field>
                </div>
                <ErrorNotice>{jdError}</ErrorNotice>
                <div className="flex flex-wrap gap-2">
                  <button type="button" className={primaryButton} onClick={() => runJD("fast")} disabled={jdLoading || connection !== "connected" || !jdText.trim()} title="Fast path: rule-based parsing plus one model call.">{jdLoading ? "Standardizing…" : "Standardize JD"}</button>
                  <button type="button" className={secondaryButton} onClick={prepareSelectedJobForMatching} disabled={jdPrepareLoading || jdLoading || rubricLoading || !jdText.trim()} title={!jdText.trim() ? "Add or import a job description to enable setup" : "Prepare the JD and source-grounded match rubric together"}>{jdPrepareLoading ? "Saving rubric…" : jdLoading ? "JD standardizing in background…" : "Standardize JD + auto setup"}</button>
                  <button type="button" className={secondaryButton} onClick={() => runJD("strict")} disabled={jdLoading || connection !== "connected" || !jdText.trim()} title="Full 12-stage validation; takes longer than the fast standardization path.">{jdLoading ? "Processing…" : "Full validation (slower)"}</button>
                  <button type="button" className={secondaryButton} onClick={() => { setJdText(""); setJdResult(null); setJdError(""); setNotice(""); }}>Clear</button>
                </div>
              </div>
              <div className="space-y-4">
                <div className="rounded-lg border border-ink-200 bg-white p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2"><div><p className="text-xs font-semibold text-ink-900">JD workflow AI assistant</p><p className="mt-1 text-[11px] text-ink-500">Guidance for importing, standardizing and matching</p></div><button type="button" className={secondaryButton} onClick={() => setJdAssistantOpen((open) => !open)}>{jdAssistantOpen ? "Hide assistant" : "Ask AI assistant"}</button></div>
                  {jdAssistantOpen && <div className="mt-3 space-y-3">
                    <div className="max-h-56 space-y-2 overflow-y-auto rounded-md bg-[#fafaf8] p-3" aria-live="polite">{jdAssistantMessages.map((item, index) => <div key={index} className={item.role === "user" ? "ml-6 rounded-lg bg-blue-50 p-2.5 text-xs leading-5 text-blue-950" : "mr-4 rounded-lg border border-ink-100 bg-white p-2.5 text-xs leading-5 text-ink-700"}><p className="whitespace-pre-wrap">{item.text}</p></div>)}{jdAssistantBusy && <p className="text-xs text-ink-500">Assistant is thinking…</p>}</div>
                    <div className="flex flex-wrap gap-1.5">{["What is missing from this JD?", "How do I create a fair match rubric?", "Explain an applicant match result"].map((prompt) => <button key={prompt} type="button" className="rounded-full border border-ink-200 px-2.5 py-1.5 text-[11px] text-ink-600 hover:bg-ink-50" disabled={jdAssistantBusy} onClick={() => sendJdAssistant(prompt)}>{prompt}</button>)}</div>
                    <form className="flex gap-2" onSubmit={(event) => { event.preventDefault(); sendJdAssistant(); }}><input value={jdAssistantInput} onChange={(event) => setJdAssistantInput(event.target.value)} placeholder="Ask how to complete this step…" className={fieldClass} disabled={jdAssistantBusy} /><button type="submit" className={primaryButton} disabled={jdAssistantBusy || !jdAssistantInput.trim()}>Send</button></form>
                    <p className="text-[10px] leading-4 text-ink-500">AI provides guidance only. Recruiters verify requirements and make every hiring decision.</p>
                  </div>}
                </div>
                <SectionHeading eyebrow="Step 02" title="Standardized output" detail="Review flags and missing details before using the content in a live requisition." />
                {!jdResult && <EmptyPanel title="Your result will appear here" detail="Run either workflow to see the pipeline status, publication blockers, extracted facts, and standardized description." />}
                {jdResult && (
                  <div className="space-y-4">
                    <div className="flex flex-wrap items-center gap-2">
                      <Pill tone={jdPublicationResult?.publishable ? "good" : jdResult.status === "ok" ? "warn" : "neutral"}>{jdResult.status || "complete"}</Pill>
                      <Pill tone={jdPublicationResult?.publishable ? "good" : "warn"}>{jdPublicationResult?.publishable ? "Ready for recruiter review" : "Review required"}</Pill>
                      {jdResult.meta?.latency_ms != null && <Pill>{(jdResult.meta.latency_ms / 1000).toFixed(1)}s</Pill>}
                      {jdResult.meta?.llm_calls != null && <Pill>{jdResult.meta.llm_calls} model calls</Pill>}
                    </div>
                    {Array.isArray(jdPublicationResult?.publish_blockers) && jdPublicationResult.publish_blockers.length > 0 && <div className="rounded-md border border-rose-200 bg-rose-50 p-3"><p className="text-xs font-semibold uppercase tracking-wide text-rose-900">Publication blockers</p><ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-rose-900">{jdPublicationResult.publish_blockers.map((item, index) => <li key={index}>{item}</li>)}</ul></div>}
                    {Array.isArray(jdResult.flags) && jdResult.flags.length > 0 && <div className="rounded-md border border-amber-200 bg-amber-50 p-3"><p className="text-xs font-semibold uppercase tracking-wide text-amber-900">Review flags</p><ul className="mt-2 space-y-2 text-sm text-amber-950">{jdResult.flags.map((flag, index) => <li key={index}><span className="font-semibold">{flag.severity || "info"}:</span> {flag.message || flag.code}</li>)}</ul></div>}
                    <div className="rounded-lg border border-ink-100 bg-white p-4">
                      <p className="text-sm font-semibold text-ink-900">{jdTitle}</p>
                      <p className="mt-1 text-xs text-ink-500">Request ID: {jdResult.request_id || "not supplied"}</p>
                      <div className="mt-4 grid grid-cols-2 gap-3">
                        <ScoreMetric label="Status" value={jdResult.status || "—"} detail="Pipeline outcome" />
                        <ScoreMetric label="Est. model cost" value={jdResult.meta?.cost_usd != null ? `$${Number(jdResult.meta.cost_usd).toFixed(4)}` : "—"} detail="Provider-reported / configured estimate" />
                      </div>
                    </div>
                    {(jdResult.needs_input || []).length > 0 && <div className="rounded-md border border-amber-200 bg-amber-50 p-3"><p className="text-sm font-semibold text-amber-950">Details to confirm</p><ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-amber-900">{jdResult.needs_input.map((item, index) => <li key={index}>{item.field}: {item.reason}</li>)}</ul></div>}
                    {(jdResult.sections || []).map((section) => <div key={section.id} className="rounded-lg border border-ink-100 bg-white p-4"><div className="flex flex-wrap items-center justify-between gap-2"><h3 className="text-sm font-semibold">{section.heading}</h3><Pill>{section.status}</Pill></div><ul className="mt-3 list-disc space-y-1.5 pl-5 text-sm leading-6 text-ink-700">{(section.items || []).map((item, index) => <li key={index}>{item.text}{item.origin === "ai_draft" && <span className="ml-2 text-[10px] font-semibold uppercase text-amber-700">AI draft</span>}</li>)}</ul></div>)}
                    {descriptionOutput && <details open className="rounded-lg border border-ink-100 bg-white p-4"><summary className="cursor-pointer text-sm font-semibold">Full job description</summary><pre className="mt-3 max-h-[520px] overflow-auto whitespace-pre-wrap text-sm leading-6 text-ink-700">{descriptionOutput}</pre></details>}
                    <button type="button" className={primaryButton} onClick={() => { setActiveTab("match"); setRubricError(""); }} disabled={!descriptionOutput && !jdText.trim()}>Continue to Applicant Match</button>
                  </div>
                )}
              </div>
            </div>
          )}

          {activeTab === "match" && (
            <div className="space-y-7">
              <section className="rounded-lg border border-ink-100 bg-[#fafaf8] p-4">
                <SectionHeading eyebrow="Rubric calibration" title="Reviewer alignment" detail="Record independent ratings beside the same resume evidence. Resolve differences with an agreed rating and rationale before making a decision." action={<Pill tone={unresolvedCalibrationCount ? "warn" : "good"}>{unresolvedCalibrationCount ? `${unresolvedCalibrationCount} disagreement${unresolvedCalibrationCount === 1 ? "" : "s"} to resolve` : "No unresolved disagreements"}</Pill>} />
                <p className="mt-2 text-xs leading-5 text-ink-600">{calibrationReviewers} reviewer{calibrationReviewers === 1 ? "" : "s"} have recorded ratings · {resolvedCalibrationCount} criterion resolution{resolvedCalibrationCount === 1 ? "" : "s"} saved in this workspace. Reviewer ratings are local to this browser and appear in exported summaries.</p>
                {!calibrationReviewerName.trim() && <p className="mt-2 text-xs font-medium text-amber-800">Enter a calibration reviewer name above to record ratings or resolutions.</p>}
              </section>
              <section className="rounded-lg border border-ink-100 bg-white p-4">
                <SectionHeading eyebrow="Follow-up reminders" title="Applicants to follow up" detail="Set a due date and reminder note in an applicant’s workflow controls. Reminders are saved with this workspace on this device." action={<Pill tone={overdueFollowUpCount ? "bad" : todayFollowUpCount ? "warn" : "neutral"}>{overdueFollowUpCount ? `${overdueFollowUpCount} overdue` : todayFollowUpCount ? `${todayFollowUpCount} due today` : `${followUpEntries.length} scheduled`}</Pill>} />
                {followUpEntries.length ? <ul className="mt-3 grid gap-2 md:grid-cols-2">{followUpEntries.map((applicant) => <li key={applicant.id} className="flex items-start justify-between gap-3 rounded-md border border-ink-100 bg-[#fafaf8] p-3">
                  <div><a href={`#follow-up-${reportAnchor(applicant.id)}`} className="text-sm font-semibold text-blue-700 underline">{applicant.fileName || "Applicant"}</a><p className="mt-1 text-xs text-ink-600">{REVIEW_STAGES.find(([value]) => value === applicant.reviewStage)?.[1] || "New"} · {formatLocalDate(applicant.followUpAt)}</p>{applicant.followUpNote && <p className="mt-1 text-xs leading-5 text-ink-500">{applicant.followUpNote}</p>}</div>
                  <Pill tone={applicant.reminderState === "overdue" ? "bad" : applicant.reminderState === "today" ? "warn" : "neutral"}>{applicant.reminderState === "overdue" ? "Overdue" : applicant.reminderState === "today" ? "Today" : applicant.reminderState === "upcoming" ? "Next 7 days" : "Scheduled"}</Pill>
                </li>)}</ul> : <p className="mt-3 text-sm text-ink-500">No follow-ups scheduled. Add a due date from an applicant’s workflow controls.</p>}
              </section>
              <div className="grid gap-5 xl:grid-cols-2">
                <div className="space-y-4">
                  <SectionHeading eyebrow="Step 03" title="Build a reviewable rubric" detail="Create a draft from the job description, check the requirements, then save an immutable rubric version before assessing resumes." />
                  <Field label="Saved rubric version" hint="Saved on this device and retained after refresh. It is not yet shared across different devices or recruiter accounts.">
                    <select value={selectedRubricId} onChange={(event) => loadRubric(event.target.value)} className={fieldClass} disabled={rubricLoading}>
                      <option value="">Choose a saved rubric…</option>
                      {savedRubrics.map((item) => <option key={item.rubric_id} value={item.rubric_id}>{item.title || "Untitled role"} · {item.items} requirements · {item.rubric_id}</option>)}
                    </select>
                  </Field>
                  <div className="flex flex-wrap gap-2">
                    <button type="button" className={primaryButton} onClick={prepareSelectedJobForMatching} disabled={jdPrepareLoading || jdLoading || rubricLoading || connection !== "connected" || !jdText.trim()}>{jdPrepareLoading ? "Saving rubric…" : jdLoading ? "JD standardizing in background…" : "Standardize JD + auto setup"}</button>
                    <button type="button" className={secondaryButton} onClick={compileRubric} disabled={rubricLoading || !jdText.trim()}>{rubricLoading ? "Building…" : "Build rubric from current JD"}</button>
                    <button type="button" className={secondaryButton} onClick={refreshSavedRubrics} disabled={connection !== "connected" || rubricLoading}>Refresh saved rubrics</button>
                  </div>
                  <p className="text-[11px] leading-5 text-ink-500">Build a source-grounded draft instantly from the current JD without a model call. Review the requirements and weights before saving an immutable version. Auto setup saves the version in one API request while JD standardization runs separately.</p>
                  <ErrorNotice>{rubricError}</ErrorNotice>
                  {rubricNotes.length > 0 && <div className="rounded-md border border-amber-200 bg-amber-50 p-3"><p className="text-xs font-semibold uppercase tracking-wide text-amber-900">Compiler notes</p><ul className="mt-2 space-y-1 text-sm text-amber-950">{rubricNotes.map((note, index) => <li key={index}>{typeof note === "string" ? note : note.message || note.code}</li>)}</ul></div>}
                  {rubric && (
                    <div className="space-y-4 rounded-lg border border-ink-100 bg-[#fafaf8] p-4">
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div><p className="text-sm font-semibold text-ink-950">{rubric.title || "Job assessment rubric"}</p><p className="mt-1 text-xs text-ink-500">Review and adjust importance / weight before saving.</p></div>
                        <Pill tone={rubric.rubric_id ? "good" : "gold"}>{rubric.rubric_id ? `Saved · ${rubric.rubric_id}` : "Draft · not saved"}</Pill>
                      </div>
                      <div className="grid gap-3 sm:grid-cols-2">
                        <Field label="Minimum years of experience">
                          <input className={fieldClass} type="number" min="0" max="40" step="0.5" value={rubric.required_years ?? ""} onChange={(event) => { setRubric({ ...rubric, rubric_id: null, rubric_hash: null, required_years: event.target.value === "" ? null : Number(event.target.value), created_at: null }); setSelectedRubricId(""); setCandidateCard(null); }} />
                        </Field>
                        <Field label="Education minimum">
                          <select className={fieldClass} value={rubric.education?.min_level || "none"} onChange={(event) => { setRubric({ ...rubric, rubric_id: null, rubric_hash: null, education: { ...(rubric.education || {}), min_level: event.target.value }, created_at: null }); setSelectedRubricId(""); setCandidateCard(null); }}>
                            {["none", "high_school", "diploma", "associate", "bachelor", "master", "phd"].map((level) => <option key={level} value={level}>{level.replaceAll("_", " ")}</option>)}
                          </select>
                        </Field>
                      </div>
                      <div className="grid gap-3 sm:grid-cols-2">
                        {[
                          ["required_skills", "Required skills"],
                          ["experience", "Experience"],
                          ["preferred_skills", "Preferred skills"],
                          ["education", "Education"],
                        ].map(([key, label]) => <Field key={key} label={`${label} weight · ${rubric.weights?.[key] ?? 0}`}>
                          <input className="w-full accent-[#c49a4a]" type="range" min="0" max="100" value={rubric.weights?.[key] ?? 0} onChange={(event) => updateRubricWeight(key, event.target.value)} />
                        </Field>)}
                      </div>
                      <div className="space-y-2">
                        {(rubric.items || []).map((item, index) => <div key={item.id || index} className="grid gap-3 rounded-md border border-ink-100 bg-white p-3 sm:grid-cols-[minmax(0,1fr)_130px_100px] sm:items-center">
                          <div className="min-w-0">
                            <Field label="Requirement">
                              <input className={fieldClass} maxLength={120} value={item.label} onChange={(event) => updateRubricItem(index, { label: event.target.value })} />
                            </Field>
                            <p className="mt-1 text-xs text-ink-500">{item.type} · {item.group} · Source {item.source_line || "not linked"}</p>
                            {item.source_text && <p className="mt-1 text-xs leading-5 text-ink-400">JD: {item.source_text}</p>}
                          </div>
                          <Field label="Importance"><select className={fieldClass} value={item.importance} onChange={(event) => updateRubricItem(index, { importance: event.target.value })}><option value="must">Must-have</option><option value="nice">Preferred</option></select></Field>
                          <Field label="Weight"><select className={fieldClass} value={item.weight || 1} onChange={(event) => updateRubricItem(index, { weight: Number(event.target.value) })}><option value="1">1 · Base</option><option value="2">2 · High</option><option value="3">3 · Critical</option></select></Field>
                        </div>)}
                        {!rubric.items?.length && <p className="text-sm text-ink-500">No rubric items were returned. Review the JD and build the rubric again.</p>}
                      </div>
                      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-ink-200 pt-4">
                        <span className="text-xs text-ink-500">{rubric.items?.length || 0} requirements · immutable versions after saving</span>
                        <button type="button" className={primaryButton} onClick={saveRubric} disabled={rubricLoading || !rubric.items?.length}>{rubricLoading ? "Saving…" : "Save rubric version"}</button>
                      </div>
                    </div>
                  )}
                </div>

                <div className="space-y-4">
                  <SectionHeading eyebrow="Step 04" title="Analyze a resume" detail="Use a saved rubric to compare a resume with job-related criteria. The API is designed to keep personal identifiers out of model inputs." />
                  <div className="rounded-lg border border-ink-100 bg-white p-4">
                    <Field label="Resume file" hint="PDF, DOCX or TXT · maximum 5 MB">
                      <input className={fieldClass} type="file" accept=".pdf,.docx,.txt,.md" onChange={(event) => { const file = event.target.files?.[0] || null; setResumeFile(file); setMatchError(file && file.size > MAX_FILE_BYTES ? "Resume must be 5 MB or smaller." : ""); if (file && file.size > MAX_FILE_BYTES) setResumeFile(null); }} />
                    </Field>
                    <div className="my-4 flex items-center gap-3 text-xs text-ink-400"><span className="h-px flex-1 bg-ink-100" />OR PASTE TEXT<span className="h-px flex-1 bg-ink-100" /></div>
                    <Field label="Resume text">
                      <textarea rows={7} value={resumeText} onChange={(event) => setResumeText(event.target.value)} placeholder="Paste resume content here when you do not have a file to upload." className={`${fieldClass} resize-y leading-6`} />
                    </Field>
                    {resumeFile && <p className="mt-2 text-xs text-ink-500">{resumeFile.name} · {(resumeFile.size / (1024 * 1024)).toFixed(2)} MB</p>}
                    <ErrorNotice>{matchError}</ErrorNotice>
                    <button type="button" className={primaryButton + " mt-4 w-full"} onClick={analyzeResume} disabled={matchLoading || connection !== "connected" || !selectedRubricId || (!resumeFile && !resumeText.trim())}>{matchLoading ? "Analyzing evidence…" : "Analyze resume against rubric"}</button>
                    <p className="mt-3 text-xs leading-5 text-ink-500">AI output is decision support only. It does not accept, reject, or shortlist a candidate automatically.</p>
                  </div>
                </div>
              </div>


              <section className="space-y-4 border-t border-ink-200 pt-6">
                <SectionHeading
                  eyebrow="Step 05"
                  title="Bulk resume comparison"
                  detail={`Match up to ${MAX_BULK_RESUMES} resumes against the selected saved rubric. Files and progress are recoverable on this browser after a refresh; processing uses bounded parallelism and failures do not discard successful results.`}
                  action={<button type="button" className={secondaryButton} onClick={downloadBulkCsv} disabled={!batchFiles.length}>Export CSV</button>}
                />
                <div className="rounded-lg border border-ink-100 bg-white p-4">
                  <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
                    <Field label="Resume files" hint="PDF, DOCX, TXT or MD · each file up to 5 MB · maximum 50 files in the queue">
                      <input
                        className={fieldClass}
                        type="file"
                        accept=".pdf,.docx,.txt,.md"
                        multiple
                        disabled={batchRunning || batchFiles.length >= MAX_BULK_RESUMES}
                        onChange={handleBatchFileSelection}
                      />
                    </Field>
                    <div className="flex flex-wrap gap-2">
                      <button type="button" className={primaryButton} onClick={() => runBatchMatches(false)} disabled={batchRunning || connection !== "connected" || !selectedRubricId || !batchQueuedCount}>
                        {batchRunning ? "Matching…" : `Run queued (${batchQueuedCount})`}
                      </button>
                      <button type="button" className={secondaryButton} onClick={() => runBatchMatches(true)} disabled={batchRunning || connection !== "connected" || !selectedRubricId || !batchFailedCount}>
                        Retry failed ({batchFailedCount})
                      </button>
                      <button type="button" className={secondaryButton} onClick={clearBatchQueue} disabled={batchRunning || !batchFiles.length}>Clear</button>
                    </div>
                  </div>
                  {!selectedRubricId && <p className="mt-3 text-xs leading-5 text-amber-800">Choose a saved rubric above or save the reviewed draft before starting a batch.</p>}
                  <p className="mt-2 text-[11px] leading-5 text-ink-500">If the shared AI service reports insufficient credits, rate limiting, or an API outage, new files stop being claimed. Completed results are kept and unstarted resumes remain queued for when service is restored.</p>
                  {batchQueueMessage && <p className="mt-2 rounded-md border border-ink-100 bg-[#fafaf8] px-3 py-2 text-xs leading-5 text-ink-600" role="status">{batchQueueMessage}</p>}
                  {batchError && <ErrorNotice>{batchError}</ErrorNotice>}
                  {batchRunning && (
                    <div className="mt-4" aria-live="polite">
                      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-ink-600">
                        <span>Processing {batchProgress.done} of {batchProgress.total}</span>
                        <span className="max-w-full truncate">{batchCurrentName}</span>
                      </div>
                      <div className="mt-2 h-2 overflow-hidden rounded-full bg-ink-100" role="progressbar" aria-valuemin={0} aria-valuemax={batchProgress.total || 1} aria-valuenow={batchProgress.done} aria-label="Bulk resume analysis progress">
                        <div className="h-full rounded-full bg-[#c49a4a] transition-all" style={{ width: `${batchProgress.total ? Math.round(batchProgress.done / batchProgress.total * 100) : 0}%` }} />
                      </div>
                    </div>
                  )}
                  {batchFiles.length > 0 && (
                    <div className="mt-4 flex flex-wrap gap-2 text-xs">
                      <Pill>{batchFiles.length}/{MAX_BULK_RESUMES} queued</Pill>
                      <Pill tone="good">{batchFiles.filter((row) => row.status === "complete").length} complete</Pill>
                      <Pill tone="warn">{batchFiles.filter((row) => row.status === "rules_only").length} rules-only</Pill>
                      <Pill tone="warn">{batchFiles.filter((row) => row.status === "manual").length} manual review</Pill>
                      <Pill tone="bad">{batchFailedCount} failed</Pill>
                      {batchTerminalCount > 0 && <span className="self-center text-ink-500">{batchTerminalCount} attempted</span>}
                    </div>
                  )}
                </div>

                {batchFiles.length === 0 ? (
                  <EmptyPanel title="No resumes in this batch" detail="Select multiple resume files to compare them against the same saved rubric. You can export the results when processing finishes." />
                ) : (
                  <div className="overflow-x-auto rounded-lg border border-ink-100 bg-white">
                    <table className="w-full min-w-[1040px] border-collapse text-left text-sm">
                      <thead className="bg-[#fafaf8] text-[11px] uppercase tracking-wide text-ink-500">
                        <tr>
                          <th className="px-3 py-3 font-semibold">Resume</th>
                          <th className="px-3 py-3 font-semibold">Status</th>
                          <th className="px-3 py-3 font-semibold">Candidate ref</th>
                          <th className="px-3 py-3 font-semibold">Match</th>
                          <th className="px-3 py-3 font-semibold">Required skills</th>
                          <th className="px-3 py-3 font-semibold">Experience</th>
                          <th className="px-3 py-3 font-semibold">Gaps to review</th>
                          <th className="px-3 py-3 font-semibold">Action</th>
                        </tr>
                      </thead>
                      <tbody>
                        {batchFiles.map((row) => {
                          const result = row.result;
                          const statusLabel = {
                            queued: "Queued",
                            processing: "Processing",
                            complete: "Complete",
                            rules_only: "Rules-only review",
                            manual: "Manual review",
                            failed: "Failed",
                            file_missing: "File unavailable",
                          }[row.status] || row.status;
                          const tone = row.status === "complete" ? "good" : row.status === "rules_only" || row.status === "manual" || row.status === "failed" || row.status === "file_missing" ? "warn" : "neutral";
                          const gaps = (result?.gaps || []).filter((gap) => gap.importance === "must" || gap.status !== "met");
                          return (
                            <tr id={`follow-up-${reportAnchor(row.id)}`} key={row.id} className="border-t border-ink-100 align-top">
                              <td className="max-w-[240px] px-3 py-3">
                                <p className="break-all text-xs font-semibold text-ink-800">{row.file.name}</p>
                                <p className="mt-1 text-[11px] text-ink-500">{(row.file.size / 1024).toFixed(0)} KB</p>
                              </td>
                              <td className="px-3 py-3">
                                <Pill tone={tone}>{statusLabel}</Pill>
                                {row.error && <p className="mt-2 max-w-[260px] text-xs leading-5 text-rose-700">{row.error}</p>}
                                {(row.status === "rules_only" || result?.status === "manual") && <p className="mt-2 max-w-[260px] text-xs leading-5 text-amber-800">{result.reason || "Review the resume manually."}</p>}
                              </td>
                              <td className="px-3 py-3 font-mono text-xs text-ink-600">{result?.applicant_id || "—"}</td>
                              <td className="px-3 py-3 font-semibold tabular-nums">{result?.scores?.match == null ? "—" : `${result.scores.match}%`}</td>
                              <td className="px-3 py-3 tabular-nums">{result?.scores?.required_skills?.pct == null ? "—" : `${result.scores.required_skills.pct}%`}</td>
                              <td className="px-3 py-3 tabular-nums">{result?.scores?.experience?.pct == null ? "—" : `${result.scores.experience.pct}%`}</td>
                              <td className="max-w-[240px] px-3 py-3 text-xs leading-5 text-ink-600">{gaps.length ? gaps.map((gap) => gap.label).join(", ") : result ? "No unverified gaps returned" : "—"}</td>
                              <td className="px-3 py-3">
                                <div className="flex flex-wrap gap-2">
                                  {row.status === "failed" && !batchRunning && <button type="button" className="text-xs font-semibold text-blue-700 underline" onClick={() => runBatchMatches(false, [row.id])} disabled={connection !== "connected" || !selectedRubricId}>Retry</button>}
                                  {!batchRunning && <button type="button" className="text-xs font-semibold text-ink-500 underline" onClick={() => removeBatchRow(row.id)}>Remove</button>}
                                </div>
                                <ApplicantWorkflowControls
                                  review={{ stage: row.reviewStage || "new", history: row.reviewHistory || [], followUpAt: row.followUpAt || "", followUpNote: row.followUpNote || "" }}
                                  onStageChange={(stage) => updateBatchReviewStage(row.id, stage)}
                                  onAddNote={(note) => addBatchReviewNote(row.id, note)}
                                  onFollowUpChange={(followUp) => updateBatchFollowUp(row.id, followUp)}
                                />
                                {result?.evidence?.length > 0 && <details className="mt-2 min-w-[300px]">
                                  <summary className="cursor-pointer text-xs font-semibold text-blue-700 underline">Review evidence & ratings</summary>
                                  <div className="mt-2 space-y-2">{result.evidence.map((item) => <EvidenceRatingCard key={`${row.id}:${item.item_id}`} item={item} reviewerName={calibrationReviewerName} onOverride={(status) => overrideBatchEvidence(row.id, item.item_id, status)} onRecordRating={(status, reviewer) => recordBatchCalibrationRating(row.id, item.item_id, status, reviewer)} onResolve={(status, note) => resolveBatchCalibration(row.id, item.item_id, status, note)} />)}</div>
                                </details>}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                    <p className="border-t border-ink-100 bg-[#fafaf8] px-3 py-3 text-xs leading-5 text-ink-500">
                      Match scores summarize evidence against this rubric; they do not rank candidates for automatic rejection or hiring. Verify the cited evidence and review flags before deciding.
                    </p>
                  </div>
                )}
              </section>

              {savedApplicants.length > 0 && (
                <section className="space-y-3 border-t border-ink-200 pt-6">
                  <SectionHeading eyebrow="Saved in this workspace" title="Applicant review history" detail="Completed batch results are kept with this job on this device. Reopen the workspace to review these summaries; resume files are not retained." />
                  <div className="overflow-x-auto rounded-lg border border-ink-100 bg-white">
                    <table className="w-full min-w-[1160px] border-collapse text-left text-sm">
                      <thead className="bg-[#fafaf8] text-[11px] uppercase tracking-wide text-ink-500"><tr><th className="px-3 py-3 font-semibold">Resume</th><th className="px-3 py-3 font-semibold">Status</th><th className="px-3 py-3 font-semibold">Match</th><th className="px-3 py-3 font-semibold">Candidate ref</th><th className="px-3 py-3 font-semibold">Evidence review</th><th className="px-3 py-3 font-semibold">Workflow</th></tr></thead>
                      <tbody>{savedApplicants.map((applicant) => <tr id={`follow-up-${reportAnchor(applicant.id)}`} key={applicant.id} className="border-t border-ink-100"><td className="break-all px-3 py-3 text-xs font-medium text-ink-800">{applicant.fileName || "Applicant resume"}</td><td className="px-3 py-3"><Pill tone={applicant.status === "complete" ? "good" : applicant.status === "manual" || applicant.status === "failed" ? "warn" : "neutral"}>{applicant.status || "Saved"}</Pill>{applicant.error && <p className="mt-1 max-w-sm text-xs text-rose-700">{applicant.error}</p>}</td><td className="px-3 py-3 font-semibold tabular-nums">{applicant.result?.scores?.match == null ? "—" : `${applicant.result.scores.match}%`}</td><td className="px-3 py-3 font-mono text-xs text-ink-600">{applicant.result?.applicant_id || "—"}</td><td className="px-3 py-3">{applicant.result?.evidence?.length ? <details><summary className="cursor-pointer text-xs font-semibold text-blue-700 underline">Review {applicant.result.evidence.length} criteria</summary><div className="mt-2 min-w-[320px] space-y-2">{applicant.result.evidence.map((item) => <EvidenceRatingCard key={`${applicant.id}:${item.item_id}`} item={item} reviewerName={calibrationReviewerName} onOverride={(status) => overrideSavedApplicantEvidence(applicant.id, item.item_id, status)} onRecordRating={(status, reviewer) => recordSavedCalibrationRating(applicant.id, item.item_id, status, reviewer)} onResolve={(status, note) => resolveSavedCalibration(applicant.id, item.item_id, status, note)} />)}</div></details> : <span className="text-xs text-ink-400">No evidence details</span>}</td><td className="px-3 py-3"><ApplicantWorkflowControls review={{ stage: applicant.reviewStage || "new", history: applicant.reviewHistory || [], followUpAt: applicant.followUpAt || "", followUpNote: applicant.followUpNote || "" }} onStageChange={(stage) => updateSavedReviewStage(applicant.id, stage)} onAddNote={(note) => addSavedReviewNote(applicant.id, note)} onFollowUpChange={(followUp) => updateSavedFollowUp(applicant.id, followUp)} /></td></tr>)}</tbody>
                    </table>
                  </div>
                </section>
              )}

              {candidateCard && (
                <section id="follow-up-individual-applicant" className="space-y-4 border-t border-ink-200 pt-6">
                  <SectionHeading eyebrow="Evidence review" title="Applicant assessment" detail="Review source evidence and missing or unclear information. An absent detail is not proof of a candidate's ability." />
                  <div className="rounded-lg border border-ink-100 bg-[#fafaf8] p-4"><ApplicantWorkflowControls review={candidateReview} onStageChange={updateCandidateReviewStage} onAddNote={addCandidateReviewNote} onFollowUpChange={updateCandidateFollowUp} /></div>
                  <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                    <ScoreMetric label="Job match" value={matchScore == null ? "Manual review" : `${matchScore}%`} detail="Evidence-weighted result, not a hiring decision" />
                    <ScoreMetric label="Experience" value={candidateCard.scores?.experience?.pct == null ? "—" : `${candidateCard.scores.experience.pct}%`} detail={candidateCard.profile?.relevant_years == null ? "Relevant years not established" : `${candidateCard.profile.relevant_years} relevant years`} />
                    <ScoreMetric label="Required skills" value={candidateCard.scores?.required_skills?.pct == null ? "—" : `${candidateCard.scores.required_skills.pct}%`} detail={`${candidateCard.scores?.required_skills?.met ?? 0} of ${candidateCard.scores?.required_skills?.total ?? 0} evidenced`} />
                    <ScoreMetric label="Education" value={candidateCard.scores?.education?.pct == null ? "—" : `${candidateCard.scores.education.pct}%`} detail={candidateCard.profile?.education_level || "Not established"} />
                  </div>
                  {candidateCard.performance && <div className="rounded-lg border border-ink-100 bg-white px-4 py-3">
                    <p className="text-xs font-semibold uppercase tracking-wide text-ink-500">Processing diagnostics</p>
                    <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-2 text-xs sm:grid-cols-3 xl:grid-cols-6">
                      <div><p className="text-ink-500">Resume extraction</p><p className="mt-0.5 font-semibold text-ink-900">{Number(candidateCard.performance.resume_extraction_ms ?? 0).toLocaleString()} ms</p></div>
                      <div><p className="text-ink-500">Preprocessing</p><p className="mt-0.5 font-semibold text-ink-900">{Number(candidateCard.performance.preprocessing_ms ?? 0).toLocaleString()} ms</p></div>
                      <div><p className="text-ink-500">Provider round trip</p><p className="mt-0.5 font-semibold text-ink-900">{Number(candidateCard.performance.provider_round_trip_ms ?? 0).toLocaleString()} ms</p></div>
                      <div><p className="text-ink-500">Sum of model calls</p><p className="mt-0.5 font-semibold text-ink-900">{candidateCard.performance.model_call_time_ms == null ? "Not run" : `${Number(candidateCard.performance.model_call_time_ms).toLocaleString()} ms`}</p></div>
                      <div><p className="text-ink-500">Server total</p><p className="mt-0.5 font-semibold text-ink-900">{Number(candidateCard.performance.total_ms ?? 0).toLocaleString()} ms</p></div>
                      <div><p className="text-ink-500">Browser round trip</p><p className="mt-0.5 font-semibold text-ink-900">{Number(candidateCard.performance.client_round_trip_ms ?? 0).toLocaleString()} ms</p></div>
                    </div>
                    <p className="mt-2 text-[11px] text-ink-500">Server timings exclude file upload transfer. Provider round trip is wall-clock time for the parallel model stage. Sum of model calls adds individual request durations and can exceed wall-clock time; neither value measures provider-internal compute time.</p>
                  </div>}
                  <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm leading-6 text-amber-950"><strong>Recruiter review required.</strong> This assessment is based on resume-derived evidence; verify any important claim directly and apply the same criteria consistently across applicants.</div>
                  <div className="rounded-lg border border-ink-200 bg-white p-4 sm:p-5">
                    <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-500">Evidence-first workflow</p><h3 className="mt-1 text-sm font-semibold text-ink-950">Save verified assessment to ATS</h3><p className="mt-1 max-w-2xl text-xs leading-5 text-ink-500">Attach this recorded run to the matching application. Rubric versions are linked to the job first; the server verifies the run and stores a privacy-minimised snapshot.</p></div><Pill tone="gold">Human decision required</Pill></div>
                    <div className="mt-4 grid gap-3 sm:grid-cols-2">
                      <label className="grid gap-1.5 text-xs font-semibold text-ink-700">ATS job<select className={fieldClass} value={atsJobId} onChange={(event) => { setAtsJobId(event.target.value); setAtsApplicationId(""); setAssessmentSaveMessage(""); }}><option value="">Choose a job</option>{jobs.filter((job) => job && job.id != null).map((job) => <option key={job.id} value={job.id}>{job.title || job.job_title || `Job #${job.id}`}</option>)}</select></label>
                      <label className="grid gap-1.5 text-xs font-semibold text-ink-700">Application<select className={fieldClass} value={atsApplicationId} onChange={(event) => { setAtsApplicationId(event.target.value); setAssessmentSaveMessage(""); }} disabled={!atsJobId}><option value="">Choose an application</option>{applications.filter((application) => Number(application.job_id) === Number(atsJobId)).map((application) => <option key={application.id} value={application.id}>{application.candidate_name || application.name || `Candidate #${application.candidate_id || application.id}`} · {application.stage_name || application.status || "Application"}</option>)}</select></label>
                    </div>
                    {!selectedRubricId && <p className="mt-2 text-xs text-amber-700">A saved rubric is required. Save a rubric in Applicant Match before linking.</p>}
                    {assessmentSaveMessage && <p className={`mt-3 rounded-md px-3 py-2 text-xs leading-5 ${assessmentSaveMessage.includes("saved to the ATS") ? "bg-emerald-50 text-emerald-800" : "bg-amber-50 text-amber-900"}`} role="status">{assessmentSaveMessage}</p>}
                    {atsApplicationId && <div className="mt-3 rounded-md border border-ink-100 bg-[#fafaf8] p-3">
                      <div className="flex flex-wrap items-center justify-between gap-2"><p className="text-xs font-semibold text-ink-800">Saved assessments for this application</p><span className="text-[11px] text-ink-500">{savedAtsAssessments.length} record(s)</span></div>
                      {savedAtsAssessmentsLoading ? <p className="mt-2 text-xs text-ink-500">Loading assessment history…</p>
                        : savedAtsAssessmentsError ? <p className="mt-2 text-xs text-amber-800">{savedAtsAssessmentsError}</p>
                          : savedAtsAssessments.length ? <div className="mt-2 space-y-2">{savedAtsAssessments.map((item) => <div key={item.id || item.request_id} className="flex flex-wrap items-center justify-between gap-2 border-t border-ink-100 pt-2"><div><p className="text-xs font-semibold text-ink-800">{item.rubric_title || "Applicant Match assessment"}</p><p className="text-[11px] text-ink-500">{item.created_at ? new Date(item.created_at).toLocaleString() : "Date unavailable"} · {item.status || "recorded"}</p></div><Pill tone={item.match_score == null ? "warn" : item.match_score >= 75 ? "good" : "neutral"}>{item.match_score == null ? "Manual review" : `${item.match_score}% match`}</Pill></div>)}</div>
                            : <p className="mt-2 text-xs text-ink-500">No saved Applicant Match assessments for this application yet.</p>}
                    </div>}
                    <div className="mt-3 flex flex-wrap items-center gap-2"><button type="button" className={secondaryButton} disabled={localAiApiUrl || atsResumeMatchLoading || !atsApplicationId || !selectedRubricId} title={localAiApiUrl ? "Upload the resume in Applicant Match to use local Ollama. This private ATS-resume endpoint remains hosted." : "Use the resume already stored on the ATS candidate profile."} onClick={matchExistingAtsResume}>{atsResumeMatchLoading ? "Matching stored resume…" : "Match existing ATS resume"}</button><button type="button" className={primaryButton} disabled={localAiApiUrl || assessmentSaving || !atsJobId || !atsApplicationId || !selectedRubricId || !(candidateCard?.request_id || candidateCard?.run_id)} title={localAiApiUrl ? "Local AI run IDs cannot yet be verified by the hosted ATS assessment store." : "Save the verified assessment to the ATS application."} onClick={saveAssessmentToATS}>{assessmentSaving ? "Saving verified assessment…" : "Save assessment to application"}</button><span className="text-[11px] text-ink-500">Uses the private resume already stored on the candidate profile. No email is sent.</span></div>
                  </div>
                  {candidateCard.versions?.assessment_mode === "rules_only" && <div className="rounded-lg border border-amber-200 bg-amber-50 p-4"><p className="text-sm font-semibold text-amber-950">Rules-only assessment</p><p className="mt-1 text-xs leading-5 text-amber-900">{candidateCard.reason || "AI is unavailable. Only direct resume text matches are scored; experience dates and fuzzy criteria need recruiter review."}</p></div>}
                  <MatchAssessmentInsights result={candidateCard} sampleReference={candidateCard.sampleScenario ? SAMPLE_MANUAL_REFERENCE : null} />
                  {(candidateCard.evidence || []).map((item) => <EvidenceRatingCard key={`${activeWorkspaceId}:${item.item_id}`} item={item} reviewerName={calibrationReviewerName} onOverride={(status) => overrideCandidateEvidence(item.item_id, status)} onRecordRating={(status, reviewer) => recordCandidateCalibrationRating(item.item_id, status, reviewer)} onResolve={(status, note) => resolveCandidateCalibration(item.item_id, status, note)} />)}
                  
                  {candidateCard.flags?.length > 0 && <div className="rounded-lg border border-amber-200 bg-amber-50 p-4"><h3 className="text-sm font-semibold text-amber-950">Review flags</h3><ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-amber-900">{candidateCard.flags.map((flag, index) => <li key={index}>{flag}</li>)}</ul></div>}
                </section>
              )}
            </div>
          )}
        </div>
      </section>
      <p className="text-xs leading-5 text-ink-500">Privacy and audit note: AI calls use the selected hosted provider or the connected local Ollama service. Candidate assessments remain recruiter decision support; confirm evidence and do not use the score alone to make hiring decisions.</p>
    </div>
  );
}

