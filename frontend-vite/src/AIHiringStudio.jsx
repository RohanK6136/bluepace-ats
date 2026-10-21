import { useEffect, useState } from "react";

const DEFAULT_MODEL = "openrouter/free";
const MAX_FILE_BYTES = 5 * 1024 * 1024;
const PROVIDER_OPTIONS = [
  { id: "openrouter", label: "OpenRouter", defaultModel: "openrouter/free", keyPlaceholder: "sk-or-v1-…", keyEnvVar: "OPENROUTER_API_KEY" },
  { id: "openai", label: "OpenAI / ChatGPT API", defaultModel: "gpt-5.4", keyPlaceholder: "OpenAI API key", keyEnvVar: "OPENAI_API_KEY" },
  { id: "claude", label: "Claude (Anthropic)", defaultModel: "claude-sonnet-4-6", keyPlaceholder: "Anthropic API key", keyEnvVar: "ANTHROPIC_API_KEY (or CLAUDE_API_KEY)" },
  { id: "deepseek", label: "DeepSeek", defaultModel: "deepseek-flash", keyPlaceholder: "DeepSeek API key", keyEnvVar: "DEEPSEEK_API_KEY" },
  { id: "cloudflare", label: "Cloudflare Workers AI", defaultModel: "@cf/qwen/qwen3.8-27b", keyPlaceholder: "Cloudflare API token", keyEnvVar: "CLOUDFLARE_API_TOKEN" },
  { id: "ollama", label: "Local Ollama · Qwen 3.5", defaultModel: "qwen3.5:4b", keyPlaceholder: "", baseUrl: "http://localhost:11434/v1" },
];
const PROVIDER_BY_ID = Object.fromEntries(PROVIDER_OPTIONS.map((item) => [item.id, item]));
function readSessionValue(key) {
  try { return sessionStorage.getItem(key) || ""; } catch { return ""; }
}
function storedProvider() {
  const saved = readSessionValue("bluepace_ai_provider");
  return PROVIDER_BY_ID[saved] ? saved : "openrouter";
}
const tabs = [
  { id: "generate", label: "Generate JD" },
  { id: "rubric", label: "Assessment rubric" },
  { id: "resume", label: "Resume analysis" },
  { id: "history", label: "Run history" },
  { id: "settings", label: "Settings" },
];

function explainError(error) {
  const detail = error?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (detail?.message) return detail.message;
  if (typeof error?.message === "string") return error.message;
  return "The request failed. Review the configuration and try again.";
}

function buildLocalJDFallback(sourceText, overrides = {}, mode = "detailed") {
  const source = String(sourceText || "").trim();
  const lines = source.split(/\r?\n/).map((line) => line.trim().replace(/^(?:#{1,6}\s+|[-*•]|\d+[.)])\s*/, "")).filter(Boolean);
  const titleMatch = source.match(/(?:job\s*title|position(?:\s*title)?|role)\s*[:\-]\s*([^\r\n]{3,100})/i);
  const genericHeading = /^(?:job description|job details|position details|role description|role overview|about the role|recruiter notes|hiring notes)$/i;
  const candidateLine = lines.find((line) => line.length <= 70 && !genericHeading.test(line) && !/^(?:location|work\s*mode|employment(?:\s*type)?|experience|minimum\s*experience|salary|department|job\s*title|title)\s*[:\-]/i.test(line) && !/\b(?:years?\s+(?:of\s+)?experience|salary|compensation)\b/i.test(line) && !/[.!?]$/.test(line) && !/^(?:we|hiring|seeking|looking|need|responsible|must|should)\b/i.test(line));
  const explicitTitle = String(overrides.job_title || (titleMatch ? titleMatch[1] : "")).trim();
  const title = explicitTitle || candidateLine || "Role title to be confirmed";
  const labelValue = (labelPattern) => {
    const match = source.match(labelPattern);
    return match ? String(match[1] || "").trim().replace(/[.;,]+$/, "") : "";
  };
  const employmentMatch = source.match(/\b(full[- ]time|part[- ]time|contract(?:or)?|permanent|temporary|internship|freelance)\b/i);
  const workModeMatch = source.match(/\b(remote|hybrid|on[- ]site|onsite)\b/i);
  const experienceMatch = source.match(/(\d+(?:\.\d+)?)\s*(?:-|to)\s*\d+(?:\.\d+)?\s*(?:years?|yrs?)|(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)\s+(?:of\s+)?experience/i);
  const inferredExperience = experienceMatch ? Number(experienceMatch[1] || experienceMatch[2]) : null;
  const hasExplicitExperience = overrides.minimum_experience_years !== undefined && overrides.minimum_experience_years !== null && overrides.minimum_experience_years !== "";
  const minExperience = hasExplicitExperience ? Number(overrides.minimum_experience_years) : inferredExperience;
  const locationFromLabel = labelValue(/(?:work\s*location|job\s*location|location)\s*[:\-]\s*([^\r\n]+)/i);
  const location = String(overrides.location || locationFromLabel).trim();
  const employmentType = String(overrides.employment_type || (employmentMatch ? employmentMatch[1].replace(/\s+/g, "-").toLowerCase() : "")).trim();
  const rawWorkMode = String(overrides.work_mode || (workModeMatch ? workModeMatch[1] : "")).trim().toLowerCase();
  const workMode = rawWorkMode.includes("remote") ? "Remote" : rawWorkMode.includes("hybrid") ? "Hybrid" : rawWorkMode ? "On-site" : "";
  const fresherAllowed = Boolean(overrides.fresher_allowed || /\b(freshers?|entry[- ]level|graduates?\s+welcome|no experience required)\b/i.test(source));
  const detailRows = [
    "- Employment type: " + (employmentType || "Not specified in the supplied notes"),
    "- Work mode: " + (workMode || "Not specified in the supplied notes"),
    "- Location: " + (location || "Not specified in the supplied notes"),
    "- Minimum experience: " + (Number.isFinite(minExperience) && minExperience !== null ? String(minExperience) + (minExperience === 1 ? " year" : " years") : "Not specified in the supplied notes"),
  ];
  const reviewItems = [
    "- Confirm the role title and reporting line.",
    "- Confirm the essential responsibilities and required versus preferred qualifications.",
    "- Confirm compensation, benefits, employment terms, and application instructions before publication.",
  ];
  const jobDescription = [
    "# " + title,
    "",
    "## Draft status",
    mode === "concise" ? "Local template draft from the supplied notes; AI provider key is not configured. Not AI-rewritten. Verify details before publishing." : "This is a local template draft assembled from the supplied notes because an AI provider key is not configured. It has not been AI-rewritten. Review and complete all details before saving or publishing.",
    "",
    "## Role details",
    ...detailRows,
    "",
    "## Recruiter-provided brief",
    source,
    "",
    "## Before publishing",
    ...reviewItems,
  ].join("\n");
  return {
    job_description: jobDescription,
    details: {
      job_title: explicitTitle || candidateLine || "",
      employment_type: employmentType,
      work_mode: workMode,
      location,
      minimum_experience_years: Number.isFinite(minExperience) ? minExperience : null,
      fresher_allowed: fresherAllowed,
    },
    missing_fields: [],
    notes: ["Local template fallback used; no AI provider was called."],
  };
}

function displayDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}

function MetaPill({ children, tone = "neutral" }) {
  const styles = {
    neutral: "bg-slate-100 text-slate-700",
    good: "bg-emerald-50 text-emerald-700",
    warn: "bg-amber-50 text-amber-800",
    bad: "bg-rose-50 text-rose-700",
    blue: "bg-blue-50 text-blue-700",
  };
  return <span className={"inline-flex items-center rounded-full px-2.5 py-1 text-xs font-semibold " + (styles[tone] || styles.neutral)}>{children}</span>;
}

function Metric({ label, value }) {
  return <div className="rounded-xl border border-slate-200 bg-white px-4 py-3"><p className="text-xs font-medium text-slate-500">{label}</p><p className="mt-1 text-xl font-semibold text-slate-900">{value}</p></div>;
}

export default function AIHiringStudio({ token, apiRequest, jobs = [], onSaved }) {
  const [tab, setTab] = useState("generate");
  const [provider, setProvider] = useState(() => storedProvider());
  const [apiKey, setApiKey] = useState(() => {
    const current = storedProvider();
    return readSessionValue("bluepace_ai_" + current + "_key")
      || (current === "openrouter" ? readSessionValue("bluepace_openrouter_key") : "");
  });
  const [model, setModel] = useState(() => {
    const current = storedProvider();
    const saved = readSessionValue("bluepace_ai_" + current + "_model")
      || (current === "openrouter" ? readSessionValue("bluepace_openrouter_model") : "");
    return !saved || saved === "openai/gpt-4o-mini" ? PROVIDER_BY_ID[current].defaultModel : saved;
  });
  const [baseUrl, setBaseUrl] = useState(() => readSessionValue("bluepace_ai_ollama_base_url") || "http://localhost:11434/v1");
  const [accountId, setAccountId] = useState(() => readSessionValue("bluepace_ai_cloudflare_account_id"));
  const [connection, setConnection] = useState(null);
  const [serverKeyConfigured, setServerKeyConfigured] = useState(null);
  const [serverAccountIdConfigured, setServerAccountIdConfigured] = useState(null);
  const [sourceText, setSourceText] = useState("");
  const [selectedJobId, setSelectedJobId] = useState("");
  const [mode, setMode] = useState("detailed");
  const [jobDescription, setJobDescription] = useState("");
  const [jobDetails, setJobDetails] = useState({
    job_title: "", employment_type: "", work_mode: "", location: "",
    minimum_experience_years: "", fresher_allowed: false,
  });
  const [suggestions, setSuggestions] = useState([]);
  const [generationMeta, setGenerationMeta] = useState(null);
  const [jdFileName, setJdFileName] = useState("");
  const [rubric, setRubric] = useState(null);
  const [rubricMeta, setRubricMeta] = useState(null);
  const [savedRubrics, setSavedRubrics] = useState([]);
  const [savedRubricId, setSavedRubricId] = useState("");
  const [rubricVersionBaseId, setRubricVersionBaseId] = useState("");
  const [rubricTitle, setRubricTitle] = useState("");
  const [rubricListBusy, setRubricListBusy] = useState(false);
  const [resumeBatch, setResumeBatch] = useState([]);
  const [resumeSort, setResumeSort] = useState("score");
  const [expandedResumeId, setExpandedResumeId] = useState("");
  const [history, setHistory] = useState([]);
  const [historyDetail, setHistoryDetail] = useState(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const selectedRubricSnapshot = savedRubrics.find((item) => item.rubric_id === savedRubricId) || null;

  const selectedProvider = PROVIDER_BY_ID[provider] || PROVIDER_BY_ID.openrouter;
  const credentials = () => ({
    provider,
    model: model.trim() || selectedProvider.defaultModel,
    ...(provider !== "ollama" && apiKey.trim() ? { api_key: apiKey.trim() } : {}),
    ...(provider === "ollama" ? { base_url: baseUrl.trim() || selectedProvider.baseUrl } : {}),
    ...(provider === "cloudflare" && accountId.trim() ? { account_id: accountId.trim() } : {}),
  });

  async function ensureProviderConfigured() {
    if (provider === "ollama" || apiKey.trim()) return true;

    let keyConfigured = serverKeyConfigured;
    if (keyConfigured === null) {
      try {
        const statusResponse = await apiRequest(
          token,
          "get",
          "/ai-hiring/status?provider=" + encodeURIComponent(provider)
        );
        const value = statusResponse.data?.server_key_configured;
        keyConfigured = typeof value === "boolean" ? value : null;
        setServerKeyConfigured(keyConfigured);
      } catch {
        setError("Could not check the AI provider configuration. No AI request was sent. Check the connection and try again.");
        setNotice("");
        return false;
      }
    }

    if (keyConfigured !== true) {
      setError(keyConfigured === false
        ? selectedProvider.label + " is not configured. Add its API key in Settings to use AI rubric generation and resume assessment."
        : "The AI provider configuration is unavailable. No AI request was sent; check the connection and try again.");
      setNotice("No AI request was sent, so this attempt will not create a failed AI run-history record.");
      return false;
    }
    return true;
  }

  function persistSettings() {
    sessionStorage.setItem("bluepace_ai_provider", provider);
    const keyName = "bluepace_ai_" + provider + "_key";
    if (apiKey.trim()) sessionStorage.setItem(keyName, apiKey.trim());
    else sessionStorage.removeItem(keyName);
    sessionStorage.setItem("bluepace_ai_" + provider + "_model", model.trim() || selectedProvider.defaultModel);
    if (provider === "ollama") sessionStorage.setItem("bluepace_ai_ollama_base_url", baseUrl.trim() || selectedProvider.baseUrl);
    if (provider === "cloudflare") sessionStorage.setItem("bluepace_ai_cloudflare_account_id", accountId.trim());
    if (provider === "openrouter") {
      if (apiKey.trim()) sessionStorage.setItem("bluepace_openrouter_key", apiKey.trim());
      else sessionStorage.removeItem("bluepace_openrouter_key");
      sessionStorage.setItem("bluepace_openrouter_model", model.trim() || DEFAULT_MODEL);
    }
  }

  function changeProvider(nextProvider) {
    const next = PROVIDER_BY_ID[nextProvider];
    if (!next) return;
    setProvider(nextProvider);
    setApiKey(readSessionValue("bluepace_ai_" + nextProvider + "_key")
      || (nextProvider === "openrouter" ? readSessionValue("bluepace_openrouter_key") : ""));
    setModel(readSessionValue("bluepace_ai_" + nextProvider + "_model")
      || (nextProvider === "openrouter" && readSessionValue("bluepace_openrouter_model")
        ? readSessionValue("bluepace_openrouter_model") : next.defaultModel));
    if (nextProvider === "ollama") setBaseUrl(readSessionValue("bluepace_ai_ollama_base_url") || next.baseUrl);
    if (nextProvider === "cloudflare") setAccountId(readSessionValue("bluepace_ai_cloudflare_account_id"));
    setServerKeyConfigured(null); setServerAccountIdConfigured(null);
    setConnection(null); setError(""); setNotice("");
  }

  function saveSettings() {
    try {
      persistSettings();
      setNotice("Provider settings saved for this browser tab session. Keys are not written to AI run history.");
      setError("");
    } catch {
      setError("Browser session storage is unavailable. Settings will remain in memory until this page is closed.");
    }
  }

  async function testConnection() {
    setBusy("test"); setError(""); setNotice(""); setConnection(null);
    try {
      const response = await apiRequest(token, "post", "/ai-hiring/test", { data: credentials(), timeout: 45000 });
      setConnection(response.data);
      try { persistSettings(); } catch {}
      setNotice(response.data?.message || (selectedProvider.label + " connection checked."));
    } catch (requestError) {
      setError(explainError(requestError));
    } finally { setBusy(""); }
  }

  async function importJDFile(event) {
    const input = event.currentTarget;
    const file = input.files && input.files[0];
    setError("");
    setNotice("");
    if (!file) return;
    if (!/\.(pdf|docx)$/i.test(file.name)) {
      input.value = "";
      setError("Choose a PDF or DOCX job description.");
      return;
    }
    if (file.size === 0 || file.size > MAX_FILE_BYTES) {
      input.value = "";
      setError(file.size === 0 ? "The selected file is empty." : "Job description files must be 5 MB or smaller.");
      return;
    }
    setBusy("jd-upload");
    try {
      const body = new FormData();
      body.append("file", file);
      const response = await apiRequest(token, "post", "/resume-processing/job-description", { data: body });
      const extracted = String(response.data?.description || "").trim();
      if (!extracted) throw new Error("No text could be extracted from that document.");
      setSourceText(extracted);
      setJdFileName(file.name);
      setNotice("Text extracted from " + file.name + ". Review it, then generate the job description.");
    } catch (requestError) {
      setError(explainError(requestError));
    } finally {
      setBusy("");
      input.value = "";
    }
  }

  function applyLocalJDFallback(chosenDetails) {
    const fallback = buildLocalJDFallback(sourceText, chosenDetails, mode);
    const details = fallback.details || {};
    setJobDescription(String(fallback.job_description || ""));
    setJobDetails({
      job_title: String(details.job_title || chosenDetails.job_title || ""),
      employment_type: String(details.employment_type || chosenDetails.employment_type || ""),
      work_mode: String(details.work_mode || chosenDetails.work_mode || ""),
      location: String(details.location || chosenDetails.location || ""),
      minimum_experience_years: details.minimum_experience_years ?? chosenDetails.minimum_experience_years ?? "",
      fresher_allowed: Boolean(details.fresher_allowed ?? chosenDetails.fresher_allowed),
    });
    setSuggestions([]);
    setGenerationMeta({
      model: "local-template-fallback",
      latency_ms: 0,
      token_usage: null,
      model_call_count: 0,
      generation_mode: "template_fallback",
    });
    setRubric(null);
    setRubricTitle("");
    setSavedRubricId("");
    setResumeBatch((previous) => previous.map((item) => ({
      ...item, analysis: null, meta: null,
      status: item.resumeData ? "ready" : item.status, error: "",
    })));
    setError("");
    setNotice("No AI provider key is configured. A local template draft was created from your notes; this is not AI-generated. Add a provider key in Settings to enable AI rewriting.");
  }

  async function generateJD(overrides = null) {
    if (sourceText.trim().length < 5) {
      setError("Paste recruiter notes or import a job description before generating.");
      setTab("generate");
      return;
    }
    const chosenDetails = overrides || jobDetails;
    setBusy("generate");
    setError("");
    setNotice("");
    // Resolve an unknown server-key state before calling generation. This avoids
    // recording a failed AI run if the user clicks before the status check completes.
    let providerKeyConfigured = serverKeyConfigured;
    if (provider !== "ollama" && !apiKey.trim() && providerKeyConfigured === null) {
      try {
        const statusResponse = await apiRequest(
          token,
          "get",
          "/ai-hiring/status?provider=" + encodeURIComponent(provider)
        );
        const keyStatus = statusResponse.data?.server_key_configured;
        providerKeyConfigured = typeof keyStatus === "boolean" ? keyStatus : null;
        setServerKeyConfigured(providerKeyConfigured);
      } catch {
        setError("Could not verify the AI provider configuration. Check the connection and try again.");
        setBusy("");
        return;
      }
    }
    if (provider !== "ollama" && !apiKey.trim() && providerKeyConfigured === false) {
      applyLocalJDFallback(chosenDetails);
      setBusy("");
      return;
    }
    try {
      const cleanOverrides = {};
      Object.entries(chosenDetails).forEach(([key, value]) => {
        if (value !== "" && value !== null && value !== undefined) {
          cleanOverrides[key] = key === "minimum_experience_years" ? Number(value) : value;
        }
      });
      const response = await apiRequest(token, "post", "/ai-hiring/generate-jd", {
        data: { ...credentials(), source_text: sourceText.trim(), mode, overrides: cleanOverrides },
        timeout: 90000,
      });
      const result = response.data?.result || {};
      const details = result.details || {};
      setJobDescription(String(result.job_description || ""));
      setJobDetails({
        job_title: String(details.job_title || chosenDetails.job_title || ""),
        employment_type: String(details.employment_type || chosenDetails.employment_type || ""),
        work_mode: String(details.work_mode || chosenDetails.work_mode || ""),
        location: String(details.location || chosenDetails.location || ""),
        minimum_experience_years: details.minimum_experience_years ?? chosenDetails.minimum_experience_years ?? "",
        fresher_allowed: Boolean(details.fresher_allowed ?? chosenDetails.fresher_allowed),
      });
      setSuggestions(Array.isArray(result.missing_fields) ? result.missing_fields : []);
      setGenerationMeta(response.data);
      setNotice("Draft generated. Review the fields and job description before saving it as an ATS draft.");
      setRubric(null);
      setRubricTitle("");
      setSavedRubricId("");
      setResumeBatch((previous) => previous.map((item) => ({ ...item, analysis: null, meta: null, status: item.resumeData ? "ready" : item.status, error: "" })));
    } catch (requestError) {
      const message = explainError(requestError);
      const missingProviderKey = /^Add an? .+ API key in settings\b/i.test(message)
        || /API key is not configured/i.test(message);
      if (missingProviderKey) {
        applyLocalJDFallback(chosenDetails);
      } else {
        setError(message);
      }
    } finally {
      setBusy("");
    }
  }

  function useSuggestion(suggestion) {
    const aliases = {
      title: "job_title", job_title: "job_title", employment: "employment_type",
      employment_type: "employment_type", work_mode: "work_mode", location: "location",
      experience: "minimum_experience_years", minimum_experience_years: "minimum_experience_years",
      fresher_allowed: "fresher_allowed",
    };
    const key = aliases[String(suggestion?.field || "").toLowerCase().replaceAll(" ", "_")];
    if (!key || suggestion.suggested_value === undefined) return;
    setJobDetails((previous) => ({
      ...previous,
      [key]: key === "minimum_experience_years" ? String(suggestion.suggested_value) : key === "fresher_allowed" ? Boolean(suggestion.suggested_value) : String(suggestion.suggested_value),
    }));
  }

  async function saveDraftJob() {
    if (!jobDescription.trim()) {
      setError("Generate or edit a job description first.");
      return;
    }
    const title = jobDetails.job_title.trim() || jobDescription.split(/\r?\n/).map((line) => line.replace(/^#+\s*/, "").trim()).find(Boolean)?.slice(0, 200) || "New role";
    const exp = jobDetails.minimum_experience_years === "" ? null : Number(jobDetails.minimum_experience_years);
    if (exp !== null && (!Number.isFinite(exp) || exp < 0 || exp > 60)) {
      setError("Minimum experience must be between 0 and 60 years.");
      return;
    }
    const modeValue = String(jobDetails.work_mode || "").toLowerCase();
    const workMode = modeValue.includes("remote") ? "remote" : modeValue.includes("hybrid") ? "hybrid" : "onsite";
    setBusy("save-job");
    setError("");
    try {
      const response = await apiRequest(token, "post", "/jobs", {
        data: {
          title, description: jobDescription.trim(), department: null,
          location: jobDetails.location.trim() || null,
          employment_type: jobDetails.employment_type || null,
          work_mode: workMode, status: "draft", required_skills: [],
          minimum_experience_years: exp, fresher_allowed: Boolean(jobDetails.fresher_allowed),
        },
      });
      setNotice("Saved as draft ATS job: " + (response.data?.title || title) + ". It has not been published.");
      if (onSaved) await onSaved();
    } catch (requestError) {
      setError(explainError(requestError));
    } finally {
      setBusy("");
    }
  }

  async function buildRubric() {
    if (jobDescription.trim().length < 10) {
      setError("Generate or paste a job description before building the rubric.");
      return;
    }
    setBusy("rubric");
    setError("");
    setNotice("");
    if (!(await ensureProviderConfigured())) {
      setBusy("");
      return;
    }
    try {
      const response = await apiRequest(token, "post", "/ai-hiring/rubric", {
        data: { ...credentials(), job_description: jobDescription.trim() },
        timeout: 90000,
      });
      const rawRubric = response.data?.rubric || null;
      const generatedRubric = rawRubric ? {
        ...rawRubric,
        minimum_years_overall: rawRubric.minimum_years_overall ?? (jobDetails.minimum_experience_years === "" ? null : Number(jobDetails.minimum_experience_years)),
        education_minimum: rawRubric.education_minimum || "",
        equivalent_experience_accepted: Boolean(rawRubric.equivalent_experience_accepted),
      } : null;
      setRubric(generatedRubric);
      setRubricTitle(String(generatedRubric?.title || jobDetails.job_title || "Assessment rubric"));
      setSavedRubricId("");
      setRubricVersionBaseId("");
      setRubricMeta(response.data);
      setResumeBatch((previous) => previous.map((item) => ({ ...item, analysis: null, meta: null, status: item.resumeData ? "ready" : item.status, error: "" })));
      setNotice("Rubric created. Edit the criteria, then save the version before assessing resumes.");
    } catch (requestError) {
      setError(explainError(requestError));
    } finally {
      setBusy("");
    }
  }

  function updateResumeRow(id, patch) {
    setResumeBatch((previous) => previous.map((item) => item.id === id ? { ...item, ...patch } : item));
  }

  async function extractResumes(event) {
    const input = event.currentTarget;
    const selectedFiles = Array.from(input.files || []);
    input.value = "";
    if (!selectedFiles.length) return;

    const validFiles = [];
    const rejected = [];
    selectedFiles.forEach((file) => {
      const supported = file.name.toLowerCase().endsWith(".pdf") || file.name.toLowerCase().endsWith(".docx");
      if (!supported) rejected.push(file.name + " (only PDF/DOCX files are supported)");
      else if (file.size === 0) rejected.push(file.name + " (empty file)");
      else if (file.size > MAX_FILE_BYTES) rejected.push(file.name + " (over 5 MB)");
      else validFiles.push(file);
    });
    const acceptedFiles = validFiles.slice(0, 25);
    if (validFiles.length > 25) rejected.push((validFiles.length - 25) + " additional file(s) (maximum 25 resumes per assessment batch)");
    if (!acceptedFiles.length) {
      setError(rejected.join("; ") || "Choose one or more PDF or DOCX resumes.");
      return;
    }

    const rows = acceptedFiles.map((file, index) => ({
      id: String(Date.now()) + "-" + String(index) + "-" + String(file.lastModified),
      file,
      resumeData: null,
      analysis: null,
      meta: null,
      status: "queued",
      error: "",
    }));
    setResumeBatch(rows);
    setExpandedResumeId("");
    setError(rejected.length ? "Skipped: " + rejected.join("; ") : "");
    setNotice("");
    setBusy("resume-extract");

    let nextIndex = 0;
    const workers = Array.from({ length: Math.min(3, rows.length) }, async () => {
      while (true) {
        const index = nextIndex++;
        if (index >= rows.length) return;
        const row = rows[index];
        updateResumeRow(row.id, { status: "extracting", error: "" });
        try {
          const body = new FormData();
          body.append("file", row.file);
          const response = await apiRequest(token, "post", "/extract/", { data: body, timeout: 90000 });
          const data = response.data?.data || response.data?.resume_json || null;
          if (!data || typeof data !== "object") throw new Error("No structured resume data was returned.");
          updateResumeRow(row.id, { resumeData: data, status: "ready", error: "" });
        } catch (requestError) {
          updateResumeRow(row.id, { status: "failed", error: explainError(requestError) });
        }
      }
    });
    await Promise.all(workers);
    setBusy("");
    setNotice("Resume extraction finished. Review the files below, then assess the ready resumes against the saved rubric.");
  }

  async function analyzeResumes() {
    if (!rubric?.criteria?.length) {
      setError("Build an assessment rubric first.");
      setTab("rubric");
      return;
    }
    if (!savedRubricId) {
      setError("Save the rubric version first so every resume is scored against a consistent, reusable framework.");
      setTab("rubric");
      return;
    }
    const pending = resumeBatch.filter((item) => item.resumeData && !item.analysis);
    if (!pending.length) {
      setError("Upload resumes first, or clear the current results to assess them again.");
      return;
    }
    setBusy("batch-analysis");
    setError("");
    setNotice("");
    if (!(await ensureProviderConfigured())) {
      setBusy("");
      return;
    }
    let nextIndex = 0;
    let successes = 0;
    let failures = 0;
    const workers = Array.from({ length: Math.min(2, pending.length) }, async () => {
      while (true) {
        const index = nextIndex++;
        if (index >= pending.length) return;
        const item = pending[index];
        updateResumeRow(item.id, { status: "analyzing", error: "" });
        try {
          const response = await apiRequest(token, "post", "/ai-hiring/analyze-resume", {
            data: { ...credentials(), resume_data: item.resumeData, rubric_id: savedRubricId, rubric },
            timeout: 90000,
          });
          updateResumeRow(item.id, { analysis: response.data?.analysis || null, meta: response.data, status: "complete", error: "" });
          successes += 1;
        } catch (requestError) {
          updateResumeRow(item.id, { status: "failed", error: explainError(requestError) });
          failures += 1;
        }
      }
    });
    await Promise.all(workers);
    setBusy("");
    setNotice("Assessment finished: " + successes + " completed, " + failures + " failed. Scores are decision support only and need human review.");
  }

  async function loadSavedRubric(id) {
    if (!id) {
      setSavedRubricId("");
      setRubricVersionBaseId("");
      return;
    }
    setBusy("load-rubric");
    setError("");
    setNotice("");
    try {
      const response = await apiRequest(token, "get", "/ai-hiring/rubrics/" + encodeURIComponent(id));
      const saved = response.data;
      setRubric(saved?.rubric || null);
      setRubricTitle(String(saved?.title || "Assessment rubric"));
      setSavedRubricId(String(saved?.rubric_id || id));
      setRubricVersionBaseId(String(saved?.rubric_id || id));
      setJobDetails((previous) => ({ ...previous, job_title: String(saved?.job_title || previous.job_title) }));
      setRubricMeta(null);
      setResumeBatch((previous) => previous.map((item) => ({ ...item, analysis: null, meta: null, status: item.resumeData ? "ready" : item.status, error: "" })));
      setNotice("Saved rubric loaded. Existing scores were cleared so resumes are assessed against the selected version.");
    } catch (requestError) {
      setError(explainError(requestError));
    } finally {
      setBusy("");
    }
  }

  async function saveRubric() {
    if (!rubric?.criteria?.length) {
      setError("Generate a rubric or add at least one criterion before saving.");
      return;
    }
    const title = rubricTitle.trim() || String(rubric.title || jobDetails.job_title || "Assessment rubric").trim();
    if (!title) {
      setError("Enter a name for this assessment rubric.");
      return;
    }
    setBusy("save-rubric");
    setError("");
    setNotice("");
    try {
      const route = rubricVersionBaseId ? "/ai-hiring/rubrics/" + encodeURIComponent(rubricVersionBaseId) : "/ai-hiring/rubrics";
      const method = rubricVersionBaseId ? "put" : "post";
      const response = await apiRequest(token, method, route, {
        data: { title, job_title: String(jobDetails.job_title || ""), rubric },
      });
      const saved = response.data;
      setRubric(saved?.rubric || rubric);
      setRubricTitle(String(saved?.title || title));
      setSavedRubricId(String(saved?.rubric_id || ""));
      setRubricVersionBaseId(String(saved?.rubric_id || ""));
      setSavedRubrics((previous) => [saved, ...previous.filter((item) => item.rubric_id !== saved?.rubric_id)]);
      setResumeBatch((previous) => previous.map((item) => ({ ...item, analysis: null, meta: null, status: item.resumeData ? "ready" : item.status, error: "" })));
      setNotice("Immutable rubric version saved. Previous versions remain available for audit and comparison; resume results were cleared.");
    } catch (requestError) {
      setError(explainError(requestError));
    } finally {
      setBusy("");
    }
  }

  function updateRubricCriterion(index, field, value) {
    setRubric((previous) => {
      if (!previous) return previous;
      return { ...previous, criteria: previous.criteria.map((item, itemIndex) => itemIndex === index ? { ...item, [field]: value } : item) };
    });
    setSavedRubricId("");
  }

  function updateRubricField(field, value) {
    setRubric((previous) => previous ? { ...previous, [field]: value } : previous);
    setSavedRubricId("");
  }

  function addRubricCriterion() {
    setRubric((previous) => ({
      ...(previous || {}),
      title: rubricTitle || previous?.title || "Assessment rubric",
      rubric_summary: previous?.rubric_summary || "",
      criteria: [...(previous?.criteria || []), {
        name: "New requirement",
        category: "Skill",
        required: false,
        weight: 5,
        minimum_years: null,
        keywords: [],
        description: "Describe the job-related evidence to look for.",
        scoring_guide: { missing: "No evidence found", partial: "Some relevant evidence", strong: "Clear, specific evidence" },
      }],
    }));
    setSavedRubricId("");
  }

  function removeRubricCriterion(index) {
    setRubric((previous) => previous ? { ...previous, criteria: previous.criteria.filter((_, itemIndex) => itemIndex !== index) } : previous);
    setSavedRubricId("");
  }

  async function loadHistory() {
    setBusy("history");
    setError("");
    try {
      const response = await apiRequest(token, "get", "/ai-hiring/history", { params: { limit: 50 } });
      setHistory(Array.isArray(response.data?.runs) ? response.data.runs : []);
    } catch (requestError) {
      setError(explainError(requestError));
    } finally {
      setBusy("");
    }
  }

  async function openHistoryDetail(id) {
    setBusy("history-detail");
    setError("");
    try {
      const response = await apiRequest(token, "get", "/ai-hiring/history/" + encodeURIComponent(id));
      setHistoryDetail(response.data);
    } catch (requestError) {
      setError(explainError(requestError));
    } finally {
      setBusy("");
    }
  }

  useEffect(() => {
    if (tab === "history") void loadHistory();
  }, [tab]);

  useEffect(() => {
    if (tab !== "rubric") return undefined;
    let active = true;
    setRubricListBusy(true);
    apiRequest(token, "get", "/ai-hiring/rubrics")
      .then((response) => {
        if (active) setSavedRubrics(Array.isArray(response.data?.rubrics) ? response.data.rubrics : []);
      })
      .catch((requestError) => {
        if (active) setError(explainError(requestError));
      })
      .finally(() => {
        if (active) setRubricListBusy(false);
      });
    return () => { active = false; };
  }, [tab, token, apiRequest]);

  useEffect(() => {
    let active = true;
    apiRequest(token, "get", "/ai-hiring/status?provider=" + encodeURIComponent(provider))
      .then((response) => {
        if (!active) return;
        const keyStatus = response.data?.server_key_configured;
        setServerKeyConfigured(typeof keyStatus === "boolean" ? keyStatus : null);
        const accountStatus = response.data?.account_id_configured;
        setServerAccountIdConfigured(typeof accountStatus === "boolean" ? accountStatus : null);
      })
      .catch(() => {
        if (active) {
          setServerKeyConfigured(null);
          setServerAccountIdConfigured(null);
        }
      });
    return () => { active = false; };
  }, [provider, token, apiRequest]);

  function updateJobDetail(field, value) {
    setJobDetails((previous) => ({ ...previous, [field]: value }));
  }

  const fieldClass = "w-full rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-900 outline-none transition focus:border-amber-500 focus:ring-2 focus:ring-amber-100";
  const btnPrimary = "inline-flex items-center justify-center rounded-lg bg-slate-950 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50";
  const btnSecondary = "inline-flex items-center justify-center rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm font-semibold text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50";
  const totalRubricWeight = (rubric?.criteria || []).reduce((total, item) => total + (Number(item.weight) || 0), 0);
  const sortedResumeBatch = [...resumeBatch].sort((a, b) => {
    if (resumeSort === "name") {
      const aName = String(a.resumeData?.name || a.resumeData?.full_name || a.file.name).toLowerCase();
      const bName = String(b.resumeData?.name || b.resumeData?.full_name || b.file.name).toLowerCase();
      return aName.localeCompare(bName);
    }
    const aScore = a.analysis ? Number(a.analysis.overall_score) : -1;
    const bScore = b.analysis ? Number(b.analysis.overall_score) : -1;
    return bScore - aScore;
  });
  const readyResumeCount = resumeBatch.filter((item) => item.resumeData && !item.analysis && item.status !== "analyzing").length;
  const cloudflareAccountMissing = provider === "cloudflare" && serverAccountIdConfigured === false && !accountId.trim();
  const providerSetupMissing = cloudflareAccountMissing;

  return (
    <div className="space-y-5 pb-10">
      <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="border-b border-slate-200 bg-slate-950 px-5 py-6 text-white sm:px-7">
          <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-amber-300">BluePace · AI-assisted recruitment</p>
          <div className="mt-2 flex flex-wrap items-end justify-between gap-4">
            <div><h2 className="text-2xl font-semibold tracking-tight">AI Hiring Studio</h2><p className="mt-1 max-w-2xl text-sm text-slate-300">Turn job notes into editable job descriptions, build a transparent rubric, and inspect resume evidence.</p></div>
            <MetaPill tone={connection?.status === "connected" && connection?.model_listed !== false ? "good" : "neutral"}>{connection?.status === "connected" ? (connection.provider_label || selectedProvider.label) + " checked" : "Human review required"}</MetaPill>
          </div>
        </div>
        <div className="flex gap-1 overflow-x-auto border-b border-slate-200 px-3 py-2 sm:px-5" role="tablist" aria-label="AI Hiring Studio sections">
          {tabs.map((item) => <button key={item.id} type="button" role="tab" aria-selected={tab === item.id} onClick={() => { setTab(item.id); setError(""); }} className={"whitespace-nowrap rounded-lg px-3 py-2 text-sm font-semibold transition " + (tab === item.id ? "bg-slate-950 text-white" : "text-slate-600 hover:bg-slate-100")}>{item.label}</button>)}
        </div>
        {(error || notice) && <div className="px-5 pt-4 sm:px-7">{error ? <div role="alert" className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">{error}</div> : <div role="status" className={"rounded-lg border px-4 py-3 text-sm " + (notice.startsWith("No AI provider key is configured") ? "border-amber-200 bg-amber-50 text-amber-900" : "border-emerald-200 bg-emerald-50 text-emerald-800")}>{notice}</div>}</div>}
        {providerSetupMissing && <div className="px-5 pt-4 sm:px-7"><div role="status" className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900"><p><strong>AI connection needs setup.</strong>{" "}{cloudflareAccountMissing && <>Cloudflare Workers AI requires an Account ID. Enter it in AI settings or configure <code>CLOUDFLARE_ACCOUNT_ID</code> on the backend.</>}</p><button type="button" className="shrink-0 font-semibold underline underline-offset-2" onClick={() => setTab("settings")}>Open AI settings</button></div></div>}

        <div className="p-5 sm:p-7">
          {tab === "generate" && <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
            <div className="space-y-4">
              <div><p className="text-xs font-semibold uppercase tracking-wide text-amber-700">01 · Source</p><h3 className="mt-1 text-lg font-semibold text-slate-900">Start from recruiter notes or an existing job</h3><p className="mt-1 text-sm text-slate-500">Upload a PDF/DOCX (5 MB max), paste content, or use an existing ATS job as the starting point.</p></div>
              <label className="block text-sm font-semibold text-slate-700">Use an existing ATS job
                <select className={fieldClass + " mt-1.5"} value={selectedJobId} onChange={(event) => { const id = event.target.value; setSelectedJobId(id); const job = jobs.find((item) => String(item.id) === id); if (job) { setSourceText(String(job.description || "")); setJobDetails((previous) => ({ ...previous, job_title: job.title || previous.job_title, employment_type: job.employment_type || previous.employment_type, location: job.location || previous.location })); } }}>
                  <option value="">Choose an existing job (optional)</option>
                  {jobs.filter((job) => job.status !== "archived").map((job) => <option key={job.id} value={String(job.id)}>{job.title}</option>)}
                </select>
              </label>
              <label className="block text-sm font-semibold text-slate-700">Import job description file
                <input type="file" accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" className="mt-1.5 block w-full rounded-lg border border-slate-200 bg-white p-3 text-sm font-normal" onChange={importJDFile} disabled={Boolean(busy)} />
                <span className="mt-1 block text-xs font-normal text-slate-500">{jdFileName ? "Extracted from " + jdFileName : "PDF or DOCX only. Text is extracted by the ATS backend."}</span>
              </label>
              <label className="block text-sm font-semibold text-slate-700">Paste notes or current description
                <textarea className={fieldClass + " mt-1.5 min-h-56 resize-y leading-6"} placeholder="Example: Python developer, APIs, PostgreSQL, 2+ years, Edinburgh, full-time. Include the responsibilities and requirements you know." value={sourceText} onChange={(event) => setSourceText(event.target.value)} />
              </label>
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs font-semibold text-slate-600">Output style</span>
                <button type="button" onClick={() => setMode("concise")} aria-pressed={mode === "concise"} className={mode === "concise" ? btnPrimary : btnSecondary}>Concise</button>
                <button type="button" onClick={() => setMode("detailed")} aria-pressed={mode === "detailed"} className={mode === "detailed" ? btnPrimary : btnSecondary}>Detailed</button>
                <button type="button" onClick={() => void generateJD()} disabled={Boolean(busy)} className={btnPrimary}>{busy === "generate" ? "Generating…" : "Generate job description"}</button>
              </div>
            </div>

            <div className="space-y-4">
              <div><p className="text-xs font-semibold uppercase tracking-wide text-amber-700">02 · Review</p><h3 className="mt-1 text-lg font-semibold text-slate-900">Editable job description</h3><p className="mt-1 text-sm text-slate-500">Review the generated text and correct the role details before saving a draft.</p></div>
              {generationMeta && <div className="flex flex-wrap gap-2"><MetaPill tone={generationMeta.generation_mode === "template_fallback" ? "warn" : "good"}>{generationMeta.generation_mode === "template_fallback" ? "Template draft" : "Generated"}</MetaPill><MetaPill>{generationMeta.model}</MetaPill><MetaPill>{generationMeta.latency_ms ?? "—"} ms</MetaPill><MetaPill>{generationMeta.token_usage?.total_tokens ?? "Tokens n/a"} tokens</MetaPill></div>}
              <label className="block text-sm font-semibold text-slate-700">Job description
                <textarea className={fieldClass + " mt-1.5 min-h-64 resize-y leading-6"} placeholder="Your generated job description will appear here." value={jobDescription} onChange={(event) => setJobDescription(event.target.value)} />
              </label>
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="text-sm font-semibold text-slate-700">Job title<input className={fieldClass + " mt-1.5"} value={jobDetails.job_title} onChange={(event) => updateJobDetail("job_title", event.target.value)} placeholder="Role title" /></label>
                <label className="text-sm font-semibold text-slate-700">Employment type
                  <select className={fieldClass + " mt-1.5"} value={jobDetails.employment_type} onChange={(event) => updateJobDetail("employment_type", event.target.value)}><option value="">Not specified</option><option>Full-time</option><option>Part-time</option><option>Contract</option><option>Freelance</option><option>Temporary</option><option>Internship</option></select>
                </label>
                <label className="text-sm font-semibold text-slate-700">Work mode
                  <select className={fieldClass + " mt-1.5"} value={jobDetails.work_mode} onChange={(event) => updateJobDetail("work_mode", event.target.value)}><option value="">Not specified</option><option>On-site</option><option>Hybrid</option><option>Remote</option></select>
                </label>
                <label className="text-sm font-semibold text-slate-700">Location<input className={fieldClass + " mt-1.5"} value={jobDetails.location} onChange={(event) => updateJobDetail("location", event.target.value)} placeholder="City or remote" /></label>
                <label className="text-sm font-semibold text-slate-700">Minimum experience (years)<input type="number" min="0" max="60" step="0.5" className={fieldClass + " mt-1.5"} value={jobDetails.minimum_experience_years} onChange={(event) => updateJobDetail("minimum_experience_years", event.target.value)} placeholder="e.g. 1.5" /></label>
                <label className="flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-3 text-sm font-semibold text-slate-700"><input type="checkbox" checked={jobDetails.fresher_allowed} onChange={(event) => updateJobDetail("fresher_allowed", event.target.checked)} className="h-4 w-4 accent-amber-600" />Freshers are eligible</label>
              </div>
              {suggestions.length > 0 && <div className="rounded-xl border border-amber-200 bg-amber-50/60 p-4"><h4 className="text-sm font-semibold text-slate-900">Suggested missing details</h4><p className="mt-1 text-xs text-slate-600">Suggestions are not facts. Apply only the values that the hiring team confirms.</p><div className="mt-3 grid gap-2">{suggestions.map((item, index) => <div key={String(item.field || index) + "-" + index} className="rounded-lg border border-amber-100 bg-white p-3"><div className="flex flex-wrap items-center justify-between gap-2"><p className="text-sm font-semibold text-slate-800">{String(item.field || "Missing field").replaceAll("_", " ")}</p><button type="button" onClick={() => useSuggestion(item)} className="text-xs font-semibold text-amber-800 underline underline-offset-2">Use suggestion</button></div><p className="mt-1 text-sm text-slate-700">{String(item.suggested_value ?? "No suggestion")}</p><p className="mt-1 text-xs leading-5 text-slate-500">{String(item.reason || "Review with the hiring team.")}</p></div>)}</div><button type="button" onClick={() => void generateJD(jobDetails)} disabled={Boolean(busy)} className={btnSecondary + " mt-3"}>Regenerate using edited fields</button></div>}
              <div className="flex flex-wrap gap-2"><button type="button" className={btnSecondary} onClick={() => { setSourceText(jobDescription); setTab("rubric"); }}>Use this JD for rubric</button><button type="button" className={btnPrimary} disabled={Boolean(busy) || !jobDescription.trim()} onClick={() => void saveDraftJob()}>{busy === "save-job" ? "Saving…" : "Save as ATS draft"}</button></div>
              <p className="text-xs leading-5 text-slate-500">Saving creates a draft only. It does not publish the role. Fractional experience values are supported and saved to the ATS job record.</p>
            </div>
          </div>}

          {tab === "settings" && <div className="mx-auto max-w-2xl space-y-5">
            <div><p className="text-xs font-semibold uppercase tracking-wide text-amber-700">Configuration</p><h3 className="mt-1 text-lg font-semibold text-slate-900">AI provider connection</h3><p className="mt-1 text-sm leading-6 text-slate-500">Choose a provider for JD generation, rubric building and resume assessment. Keys stay in this browser tab session and are sent to the backend over HTTPS; they are excluded from AI run history.</p><div className="mt-3 flex flex-wrap items-center gap-2">{null}{provider === "cloudflare" && <MetaPill tone={accountId.trim() || serverAccountIdConfigured === true ? "good" : "warn"}>Account ID: {accountId.trim() ? "entered" : serverAccountIdConfigured === true ? "configured on backend" : "required"}</MetaPill>}<MetaPill>{selectedProvider.label}</MetaPill><MetaPill>{model.trim() || selectedProvider.defaultModel}</MetaPill></div></div>
            <label className="block text-sm font-semibold text-slate-700">AI provider<select value={provider} onChange={(event) => changeProvider(event.target.value)} className={fieldClass + " mt-1.5"}>{PROVIDER_OPTIONS.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}</select></label>
            {provider !== "ollama" && <label className="block text-sm font-semibold text-slate-700">{provider === "claude" ? "Anthropic API key" : provider === "cloudflare" ? "Cloudflare API token" : selectedProvider.label + " API key"}<input type="password" autoComplete="new-password" className={fieldClass + " mt-1.5 font-mono"} value={apiKey} onChange={(event) => { setApiKey(event.target.value); setConnection(null); }} placeholder={selectedProvider.keyPlaceholder}/><span className="mt-1 block text-xs font-normal text-slate-500">Leave empty to use the matching backend environment variable.</span></label>}
            {provider === "cloudflare" && <label className="block text-sm font-semibold text-slate-700">Cloudflare Account ID<input className={fieldClass + " mt-1.5 font-mono"} value={accountId} onChange={(event) => { setAccountId(event.target.value); setConnection(null); }} placeholder="Cloudflare account ID" autoComplete="off"/><span className="mt-1 block text-xs font-normal text-slate-500">Required for the Workers AI account endpoint.</span></label>}
            {provider === "ollama" && <label className="block text-sm font-semibold text-slate-700">Local Ollama base URL<input className={fieldClass + " mt-1.5 font-mono"} value={baseUrl} onChange={(event) => { setBaseUrl(event.target.value); setConnection(null); }} placeholder="http://localhost:11434/v1" autoComplete="url"/><span className="mt-1 block text-xs font-normal text-slate-500">Only loopback URLs are accepted; remote host URLs are rejected.</span></label>}
            <label className="block text-sm font-semibold text-slate-700">Model identifier<input className={fieldClass + " mt-1.5 font-mono"} value={model} onChange={(event) => { setModel(event.target.value); setConnection(null); }} placeholder={selectedProvider.defaultModel}/><span className="mt-1 block text-xs font-normal text-slate-500">Default: {selectedProvider.defaultModel}. Enter another model ID if your provider supports it. Qwen is a model family, not a separate API provider.</span></label>
            <div className="flex flex-wrap gap-2"><button type="button" onClick={saveSettings} className={btnSecondary}>Save for this tab session</button><button type="button" onClick={() => void testConnection()} disabled={Boolean(busy)} className={btnPrimary}>{busy === "test" ? "Testing…" : "Test " + selectedProvider.label + " connection"}</button></div>
            {connection && <div className={"rounded-xl border p-4 " + (connection.status === "connected" && connection.model_listed !== false ? "border-emerald-200 bg-emerald-50" : "border-amber-200 bg-amber-50")}><div className="flex flex-wrap items-center gap-2"><MetaPill tone={connection.status === "connected" && connection.model_listed !== false ? "good" : "warn"}>{connection.status === "connected" && connection.model_listed !== false ? "Connection successful" : "Check the selected model"}</MetaPill><MetaPill>{connection.latency_ms} ms</MetaPill></div><p className="mt-2 text-sm text-slate-800">{connection.message}</p><p className="mt-1 text-xs text-slate-600">Selected model: {connection.model} · Provider: {connection.provider_label || selectedProvider.label} · Key source: {connection.key_source}</p></div>}
            <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm leading-6 text-slate-600"><p><strong className="text-slate-800">Hosted providers:</strong> OpenAI/ChatGPT, Claude, DeepSeek, OpenRouter and Cloudflare send prompts to the selected provider. Confirm your organisation's data-use terms before processing candidate data. Requests may incur charges.</p><p className="mt-2"><strong className="text-slate-800">Local Ollama / Qwen 3.5:</strong> Install Ollama where the backend runs and execute <code>ollama pull qwen3.5:4b</code>. Keep the URL at <code>http://localhost:11434/v1</code>.</p><p className="mt-2"><strong className="text-slate-800">Hosted deployment limitation:</strong> On Railway, localhost means the Railway container, not your PC. The production ATS cannot reach Ollama on your computer using localhost. For local inference run the backend and Ollama on the same computer, or build a separately secured local bridge. Never put API keys in Vite environment variables or commit them to GitHub.</p><p className="mt-2">“Qwen 3.4.5” did not identify a model tag that I could verify; the model field defaults to the published Qwen 3.5 family and remains editable.</p></div>
          </div>}

          {tab === "rubric" && <div className="space-y-5">
            <div className="flex flex-wrap items-end justify-between gap-3">
              <div><p className="text-xs font-semibold uppercase tracking-wide text-amber-700">Assessment framework</p><h3 className="mt-1 text-lg font-semibold text-slate-900">Build, edit and save a weighted rubric</h3><p className="mt-1 text-sm text-slate-500">Use job-related criteria, must-have vs nice-to-have requirements and transparent evidence guidance. Rubrics are saved within your organisation.</p></div>
              <div className="flex flex-wrap gap-2">
                <button type="button" className={btnSecondary} disabled={Boolean(busy) || !jobDescription.trim()} onClick={() => void buildRubric()}>{busy === "rubric" ? "Building…" : "Generate from job description"}</button>
                <button type="button" className={btnPrimary} disabled={Boolean(busy) || !rubric?.criteria?.length} onClick={() => void saveRubric()}>{busy === "save-rubric" ? "Saving…" : savedRubricId ? "Save rubric changes" : "Save rubric version"}</button>
              </div>
            </div>
            <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)]">
              <label className="block text-sm font-semibold text-slate-700">Load a saved rubric
                <select className={fieldClass + " mt-1.5"} value={savedRubricId} onChange={(event) => void loadSavedRubric(event.target.value)} disabled={Boolean(busy)}>
                  <option value="">Current unsaved rubric</option>
                  {savedRubrics.map((item) => <option key={item.rubric_id} value={item.rubric_id}>{item.title}{item.job_title ? " · " + item.job_title : ""}{" · v" + (item.version || 1)}{item.content_hash ? " · SHA256 " + item.content_hash.slice(0, 8) : ""}</option>)}
                </select>
                <span className="mt-1 block text-xs font-normal text-slate-500">{rubricListBusy ? "Refreshing saved rubrics…" : String(savedRubrics.length) + " saved rubric(s) available"}</span>
              </label>
              <label className="block text-sm font-semibold text-slate-700">Job title<input className={fieldClass + " mt-1.5"} value={jobDetails.job_title} onChange={(event) => { updateJobDetail("job_title", event.target.value); setSavedRubricId(""); }} placeholder="e.g. Implementation Specialist" /></label>
              <label className="block text-sm font-semibold text-slate-700">Rubric name<input className={fieldClass + " mt-1.5"} value={rubricTitle} onChange={(event) => { setRubricTitle(event.target.value); setSavedRubricId(""); }} placeholder="e.g. Implementation Specialist — v1" /></label>
            </div>
            <label className="block text-sm font-semibold text-slate-700">Job description used for scoring<textarea className={fieldClass + " mt-1.5 min-h-40 leading-6"} value={jobDescription} onChange={(event) => { setJobDescription(event.target.value); setSavedRubricId(""); }} placeholder="Generate a job description in the first tab or paste the approved job description here." /></label>
            {rubricMeta && <div className="flex flex-wrap gap-2"><MetaPill tone="good">Rubric generated</MetaPill><MetaPill>{rubricMeta.model}</MetaPill><MetaPill>{rubricMeta.latency_ms} ms</MetaPill></div>}
            {rubric && <div className="space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-slate-50 p-4">
                <div><p className="font-semibold text-slate-900">{rubric.title || rubricTitle || "Assessment rubric"}</p><p className="mt-1 text-sm text-slate-600">{rubric.rubric_summary || "A transparent set of job-related criteria."}</p></div>
                <div className="text-right"><p className="text-2xl font-semibold text-slate-900">{totalRubricWeight.toFixed(1)}%</p><p className="text-xs text-slate-500">Current weight total · saved version normalizes to 100%</p></div>
              </div>
              <div className="grid gap-3 rounded-xl border border-slate-200 p-4 sm:grid-cols-3">
                <label className="block text-sm font-semibold text-slate-700">Required experience overall (years)<input type="number" min="0" max="60" step="0.5" className={fieldClass + " mt-1.5"} value={rubric.minimum_years_overall ?? ""} onChange={(event) => updateRubricField("minimum_years_overall", event.target.value === "" ? null : Number(event.target.value))} /><span className="mt-1 block text-xs font-normal text-slate-500">Use only an approved, job-related requirement.</span></label>
                <label className="block text-sm font-semibold text-slate-700">Minimum education<input className={fieldClass + " mt-1.5"} value={String(rubric.education_minimum || "")} onChange={(event) => updateRubricField("education_minimum", event.target.value)} placeholder="e.g. Not required; relevant degree preferred" /><span className="mt-1 block text-xs font-normal text-slate-500">Keep equivalent practical experience in mind.</span></label>
                <label className="flex items-start gap-2 rounded-lg border border-slate-200 px-3 py-3 text-sm font-semibold text-slate-700"><input type="checkbox" className="mt-1 h-4 w-4 accent-amber-600" checked={Boolean(rubric.equivalent_experience_accepted)} onChange={(event) => updateRubricField("equivalent_experience_accepted", event.target.checked)} /><span>Equivalent experience accepted<span className="mt-1 block text-xs font-normal text-slate-500">Do not treat a degree as the only path when equivalent experience is accepted.</span></span></label>
              </div>
              <div className="overflow-hidden rounded-xl border border-slate-200">
                <div className="hidden grid-cols-[minmax(0,1fr)_140px_100px_100px_42px] gap-3 border-b border-slate-200 bg-slate-50 px-4 py-3 text-xs font-semibold uppercase tracking-wide text-slate-500 lg:grid"><span>Requirement</span><span>Category</span><span>Importance</span><span>Weight %</span><span /></div>
                <div className="divide-y divide-slate-100">
                  {rubric.criteria.map((item, index) => <div key={String(item.name || index) + "-" + index} className="grid gap-3 p-4 lg:grid-cols-[minmax(0,1fr)_140px_100px_100px_42px] lg:items-start">
                    <div className="space-y-2">
                      <label className="block text-xs font-semibold text-slate-500">Requirement name<input className={fieldClass + " mt-1"} value={String(item.name || "")} onChange={(event) => updateRubricCriterion(index, "name", event.target.value)} /></label>
                      <label className="block text-xs font-semibold text-slate-500">Description / evidence to look for<textarea className={fieldClass + " mt-1 min-h-16"} value={String(item.description || "")} onChange={(event) => updateRubricCriterion(index, "description", event.target.value)} /></label>
                      <label className="block text-xs font-semibold text-slate-500">Search terms / aliases, comma separated<input className={fieldClass + " mt-1"} value={(item.keywords || []).join(", ")} onChange={(event) => updateRubricCriterion(index, "keywords", event.target.value.split(",").map((value) => value.trim()).filter(Boolean))} /></label>
                    </div>
                    <label className="block text-xs font-semibold text-slate-500">Category<select className={fieldClass + " mt-1"} value={String(item.category || "Skill")} onChange={(event) => updateRubricCriterion(index, "category", event.target.value)}><option>Skill</option><option>Cloud & tools</option><option>Coding</option><option>Experience</option><option>Education</option><option>Certification</option><option>Communication</option><option>Soft skill</option><option>Other</option></select></label>
                    <label className="block text-xs font-semibold text-slate-500">Importance<select className={fieldClass + " mt-1"} value={item.required ? "required" : "optional"} onChange={(event) => updateRubricCriterion(index, "required", event.target.value === "required")}><option value="required">Must-have</option><option value="optional">Nice-to-have</option></select></label>
                    <label className="block text-xs font-semibold text-slate-500">Weight %<input type="number" min="0" max="100" step="0.5" className={fieldClass + " mt-1"} value={Number(item.weight ?? 0)} onChange={(event) => updateRubricCriterion(index, "weight", Number(event.target.value))} /></label>
                    <button type="button" className={btnSecondary + " self-start"} aria-label={"Remove " + String(item.name || "criterion")} onClick={() => removeRubricCriterion(index)}>×</button>
                    <label className="block text-xs font-semibold text-slate-500 lg:col-start-1">Minimum years (optional)<input type="number" min="0" max="60" step="0.5" className={fieldClass + " mt-1 max-w-40"} value={item.minimum_years ?? ""} onChange={(event) => updateRubricCriterion(index, "minimum_years", event.target.value === "" ? null : Number(event.target.value))} /></label>
                  </div>)}
                  {!rubric.criteria.length && <div className="p-6 text-sm text-slate-500">No criteria yet. Add a criterion to continue.</div>}
                </div>
                <div className="flex flex-wrap justify-between gap-2 border-t border-slate-200 bg-slate-50 p-4"><button type="button" className={btnSecondary} onClick={addRubricCriterion}>Add requirement</button><span className="text-xs leading-5 text-slate-500">{rubric.criteria.length} criteria · saved weights are normalized to 100% · recruiter approval required</span></div>
              </div>
              {savedRubricId && <div className="flex flex-wrap items-center gap-2"><MetaPill tone="good">Immutable version selected · v{selectedRubricSnapshot?.version || 1}</MetaPill><MetaPill>SHA-256 {String(selectedRubricSnapshot?.content_hash || "").slice(0, 12) || "pending"}</MetaPill><button type="button" className={btnSecondary} onClick={() => setTab("resume")}>Assess resumes against this version</button></div>}
            </div>}
            {!rubric && <div className="rounded-xl border border-dashed border-slate-300 p-8 text-center"><p className="font-semibold text-slate-800">No rubric loaded yet</p><p className="mt-1 text-sm text-slate-500">Paste or generate a job description, then create a rubric or load a saved version.</p></div>}
          </div>}

          {tab === "resume" && <div className="space-y-5">
            <div><p className="text-xs font-semibold uppercase tracking-wide text-amber-700">Evidence-based review</p><h3 className="mt-1 text-lg font-semibold text-slate-900">Assess multiple resumes against one saved rubric</h3><p className="mt-1 text-sm text-slate-500">Upload up to 25 PDF/DOCX files per batch (5 MB each). Extraction runs with limited concurrency; assessments are scored against the same saved rubric version.</p></div>
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-slate-50 p-4">
              <div>{savedRubricId && rubric ? <><p className="font-semibold text-slate-900">{rubricTitle || rubric.title || "Assessment rubric"}</p><p className="mt-1 text-xs text-slate-500">{rubric.criteria.length} criteria · version {selectedRubricSnapshot?.version || 1} · SHA-256 {String(selectedRubricSnapshot?.content_hash || "").slice(0, 12) || "pending"}</p></> : <><p className="font-semibold text-slate-900">A saved rubric is required</p><p className="mt-1 text-xs text-slate-500">Create or load a rubric and save the version before scoring resumes.</p></>}</div>
              <button type="button" className={btnSecondary} onClick={() => setTab("rubric")}>Manage rubrics</button>
            </div>
            <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 p-5">
              <label className="block text-sm font-semibold text-slate-800">Resume files (PDF/DOCX, 5 MB maximum per file)
                <input type="file" multiple accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" className="mt-2 block w-full rounded-lg border border-slate-200 bg-white p-3 text-sm font-normal" onChange={extractResumes} disabled={Boolean(busy)} />
              </label>
              <div className="mt-4 flex flex-wrap items-center gap-2">
                <button type="button" className={btnPrimary} disabled={Boolean(busy) || !savedRubricId || readyResumeCount === 0} onClick={() => void analyzeResumes()}>{busy === "batch-analysis" ? "Assessing resumes…" : "Assess ready resumes"}</button>
                <button type="button" className={btnSecondary} disabled={Boolean(busy) || !resumeBatch.length} onClick={() => { setResumeBatch([]); setExpandedResumeId(""); setNotice(""); }}>Clear batch</button>
                <span className="text-xs text-slate-500">{resumeBatch.length} file(s) · {resumeBatch.filter((item) => item.analysis).length} assessed · {resumeBatch.filter((item) => item.status === "failed").length} failed</span>
              </div>
            </div>
            {resumeBatch.length > 0 && <div className="space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-3"><h4 className="font-semibold text-slate-900">Applicant assessments</h4><label className="flex items-center gap-2 text-sm text-slate-600">Sort by<select className={fieldClass + " w-auto min-w-36"} value={resumeSort} onChange={(event) => setResumeSort(event.target.value)}><option value="score">Match score</option><option value="name">Name</option></select></label></div>
              {sortedResumeBatch.map((item) => {
                const resumeName = String(item.resumeData?.name || item.resumeData?.full_name || item.resumeData?.personal_information?.name || item.file.name.split(".").slice(0, -1).join(".") || item.file.name);
                const score = item.analysis ? Math.max(0, Math.min(100, Math.round(Number(item.analysis.overall_score || 0)))) : null;
                const expanded = expandedResumeId === item.id;
                return <article key={item.id} className="overflow-hidden rounded-xl border border-slate-200 bg-white">
                  <div className="flex flex-wrap items-center justify-between gap-3 p-4">
                    <div className="min-w-0"><h5 className="break-words font-semibold text-slate-900">{resumeName}</h5><p className="mt-1 break-all text-xs text-slate-500">{item.file.name} · {(item.file.size / 1024).toFixed(0)} KB</p><div className="mt-2 flex flex-wrap items-center gap-2"><MetaPill tone={item.status === "complete" ? "good" : item.status === "failed" ? "bad" : item.status === "analyzing" || item.status === "extracting" ? "warn" : "neutral"}>{item.status}</MetaPill>{item.analysis && <MetaPill tone="blue">{score}% match</MetaPill>}{item.analysis?.recommendation && <MetaPill>{item.analysis.recommendation}</MetaPill>}</div></div>
                    {item.analysis && <div className="text-right"><p className="text-2xl font-semibold text-slate-900">{score}%</p><p className="text-xs text-slate-500">Evidence alignment</p></div>}
                    {item.resumeData && <button type="button" className={btnSecondary} onClick={() => setExpandedResumeId(expanded ? "" : item.id)}>{expanded ? "Hide evidence" : "View evidence"}</button>}
                  </div>
                  {item.error && <div className="border-t border-rose-100 bg-rose-50 px-4 py-3 text-sm text-rose-800">{item.error}</div>}
                  {item.analysis && expanded && <div className="space-y-4 border-t border-slate-200 bg-slate-50 p-4">
                    <div><h6 className="font-semibold text-slate-900">Assessment summary</h6><p className="mt-1 text-sm leading-6 text-slate-600">{item.analysis.summary || "Review the criterion evidence below."}</p><p className="mt-1 text-xs text-slate-500">Decision support only. Do not use this score as the sole basis for hiring decisions.</p></div>
                    <div className="space-y-3">{(item.analysis.criteria || []).map((criterion, criterionIndex) => <div key={String(criterion.name || criterionIndex)} className="rounded-lg border border-slate-200 bg-white p-3"><div className="flex flex-wrap items-start justify-between gap-2"><div><p className="font-semibold text-slate-900">{criterion.name || "Criterion"}</p><p className="mt-1 text-sm text-slate-600">{criterion.assessment || "Review evidence."}</p></div><p className="font-semibold text-slate-900">{Math.round(Number(criterion.score || 0))}% <span className="text-xs font-normal text-slate-500">· {criterion.weight ?? 0}% weight</span></p></div><div className="mt-3 grid gap-3 sm:grid-cols-2"><div><p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Evidence</p>{criterion.evidence?.length ? <ul className="mt-1 list-disc space-y-1 pl-4 text-sm text-slate-700">{criterion.evidence.map((evidence, evidenceIndex) => <li key={evidenceIndex}>{String(evidence)}</li>)}</ul> : <p className="mt-1 text-sm text-slate-500">No explicit evidence returned.</p>}</div><div><p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Gap / follow-up</p><p className="mt-1 text-sm leading-5 text-slate-700">{criterion.gap || "No gap specified."}</p></div></div></div>)}</div>
                    <div className="grid gap-3 md:grid-cols-3"><div className="rounded-lg border border-slate-200 bg-white p-3"><h6 className="font-semibold text-slate-900">Strengths</h6><ul className="mt-2 list-disc space-y-1 pl-4 text-sm text-slate-600">{(item.analysis.strengths || []).map((value, valueIndex) => <li key={valueIndex}>{String(value)}</li>)}</ul></div><div className="rounded-lg border border-slate-200 bg-white p-3"><h6 className="font-semibold text-slate-900">Concerns</h6><ul className="mt-2 list-disc space-y-1 pl-4 text-sm text-slate-600">{(item.analysis.concerns || []).map((value, valueIndex) => <li key={valueIndex}>{String(value)}</li>)}</ul></div><div className="rounded-lg border border-slate-200 bg-white p-3"><h6 className="font-semibold text-slate-900">Missing requirements</h6><ul className="mt-2 list-disc space-y-1 pl-4 text-sm text-slate-600">{(item.analysis.missing_requirements || []).map((value, valueIndex) => <li key={valueIndex}>{String(value)}</li>)}</ul></div></div>
                  </div>}
                </article>;
              })}
            </div>}
            <p className="text-xs leading-5 text-slate-500">Human review is mandatory. The system highlights evidence and gaps; it must not automatically reject or rank candidates as a hiring decision. Confirm local policy and provider data-use terms before uploading candidate information.</p>
          </div>}

          {tab === "history" && <div className="space-y-4">
            <div className="flex flex-wrap items-end justify-between gap-3"><div><p className="text-xs font-semibold uppercase tracking-wide text-amber-700">Observability</p><h3 className="mt-1 text-lg font-semibold text-slate-900">AI run history</h3><p className="mt-1 text-sm text-slate-500">Inspect model calls, prompts, output, latency, available token usage and failures.</p></div><button type="button" onClick={() => void loadHistory()} disabled={Boolean(busy)} className={btnSecondary}>{busy === "history" ? "Refreshing…" : "Refresh history"}</button></div>
            {history.length === 0 ? <div className="rounded-xl border border-dashed border-slate-300 p-8 text-center"><p className="font-semibold text-slate-800">No AI runs recorded yet</p><p className="mt-1 text-sm text-slate-500">Generate a JD, build a rubric, or analyze a resume to create a run record.</p></div> : <div className="overflow-x-auto rounded-xl border border-slate-200"><table className="w-full min-w-[760px] border-collapse text-left text-sm"><thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500"><tr><th className="px-4 py-3">Task</th><th className="px-4 py-3">Status</th><th className="px-4 py-3">Model</th><th className="px-4 py-3">Latency</th><th className="px-4 py-3">Tokens</th><th className="px-4 py-3">Calls</th><th className="px-4 py-3">Created</th><th className="px-4 py-3">Details</th></tr></thead><tbody className="divide-y divide-slate-100">{history.map((run) => <tr key={run.request_id} className="align-top"><td className="px-4 py-3 font-medium text-slate-800">{String(run.task_type).replaceAll("_", " ")}</td><td className="px-4 py-3">{(() => { const missingKey = /Add an? .+ API key in settings|API key is not configured/i.test(String(run.error_message || "")); return <><MetaPill tone={run.status === "success" ? "good" : missingKey ? "warn" : run.status === "failed" ? "bad" : "warn"}>{missingKey ? "setup required" : run.status}</MetaPill>{run.error_message && <p className={"mt-1 max-w-48 text-xs " + (missingKey ? "text-amber-800" : "text-rose-700")}>{missingKey ? "Provider key was missing at the time of this saved attempt. " : ""}{run.error_message}</p>}</>; })()}</td><td className="max-w-44 break-words px-4 py-3 text-xs text-slate-600">{run.model}</td><td className="px-4 py-3 text-slate-700">{run.latency_ms == null ? "—" : run.latency_ms + " ms"}</td><td className="px-4 py-3 text-slate-700">{run.token_usage?.total_tokens ?? "—"}</td><td className="px-4 py-3 text-slate-700">{run.model_call_count ?? 0}</td><td className="px-4 py-3 text-xs text-slate-500">{displayDate(run.created_at)}</td><td className="px-4 py-3"><button type="button" className="font-semibold text-amber-800 underline underline-offset-2" onClick={() => void openHistoryDetail(run.request_id)}>Open</button></td></tr>)}</tbody></table></div>}
            {historyDetail && <section className="space-y-3 rounded-xl border border-slate-200 bg-slate-50 p-4"><div className="flex flex-wrap items-center justify-between gap-2"><div><h4 className="font-semibold text-slate-900">Run details</h4><p className="break-all font-mono text-xs text-slate-500">{historyDetail.request_id}</p></div><button type="button" className={btnSecondary} onClick={() => setHistoryDetail(null)}>Close details</button></div><div className="grid gap-2 sm:grid-cols-4"><MetaPill>{historyDetail.task_type}</MetaPill><MetaPill>{historyDetail.model}</MetaPill><MetaPill>{historyDetail.latency_ms ?? "—"} ms</MetaPill><MetaPill>{historyDetail.model_call_count ?? 0} model call(s)</MetaPill></div><details><summary className="cursor-pointer py-2 text-sm font-semibold text-slate-800">System prompt</summary><pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded-lg bg-white p-3 text-xs leading-5 text-slate-700">{historyDetail.system_prompt}</pre></details><details><summary className="cursor-pointer py-2 text-sm font-semibold text-slate-800">User prompt and input data</summary><pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-lg bg-white p-3 text-xs leading-5 text-slate-700">{historyDetail.user_prompt}</pre><pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap rounded-lg bg-white p-3 text-xs leading-5 text-slate-700">{JSON.stringify(historyDetail.input_data, null, 2)}</pre></details><details><summary className="cursor-pointer py-2 text-sm font-semibold text-slate-800">Structured result</summary><pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-lg bg-white p-3 text-xs leading-5 text-slate-700">{JSON.stringify(historyDetail.output_data, null, 2)}</pre></details><details><summary className="cursor-pointer py-2 text-sm font-semibold text-slate-800">Raw model output</summary><pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-lg bg-white p-3 text-xs leading-5 text-slate-700">{historyDetail.raw_model_output || historyDetail.error_message || "No raw model output."}</pre></details></section>}
          </div>}
        </div>
      </section>
      <p className="px-1 text-xs leading-5 text-slate-500">Recruiter review is required. AI scores can be incomplete or incorrect and must not be used as the sole basis for hiring decisions. Candidate data and prompts are stored in organisation-scoped run history for troubleshooting; only upload data your organisation is authorised to process.</p>
    </div>
  );
}
