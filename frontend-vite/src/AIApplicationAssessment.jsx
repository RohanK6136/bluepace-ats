import { useEffect, useMemo, useState } from "react";

const MAX_BYTES = 5 * 1024 * 1024;
const MAX_BATCH = 50;
const SAVE_KEY = "bluepace_saved_assessment_rubric_v1";
const DEFAULT_MODEL = "openrouter/free";

function errorText(error) {
  const detail = error?.response?.data?.detail;
  return (typeof detail === "string" && detail) || detail?.message || error?.message || "Request failed. Check the configuration and retry.";
}

function normalize(source) {
  if (!Array.isArray(source?.criteria) || !source.criteria.length) return null;
  const criteria = source.criteria.map((item, index) => ({
    ...item,
    name: String(item?.name || ("Criterion " + (index + 1))).trim(),
    type: String(item?.type || "skill"),
    category: String(item?.category || "Technical"),
    required: Boolean(item?.required),
    weight: Math.max(0, Math.min(100, Number(item?.weight) || 0)),
    minimum_years: item?.minimum_years === "" || item?.minimum_years == null ? null : Number(item.minimum_years),
    keywords: Array.isArray(item?.keywords) ? item.keywords.map(String).filter(Boolean) : [],
  }));
  const total = criteria.reduce((sum, item) => sum + item.weight, 0);
  if (!Number.isFinite(total) || total <= 0) return null;
  let used = 0;
  const fixed = criteria.map((item, index) => {
    const weight = index === criteria.length - 1 ? Number((100 - used).toFixed(2)) : Number((item.weight * 100 / total).toFixed(2));
    used += weight;
    return { ...item, weight };
  });
  return { ...source, criteria: fixed, total_weight: 100 };
}

function label(index) {
  return "Candidate " + String(index + 1).padStart(2, "0");
}

function stableSerialize(value) {
  if (Array.isArray(value)) return "[" + value.map(stableSerialize).join(",") + "]";
  if (value && typeof value === "object") {
    return "{" + Object.keys(value).sort().map((key) => JSON.stringify(key) + ":" + stableSerialize(value[key])).join(",") + "}";
  }
  return JSON.stringify(value);
}

export default function AIApplicationAssessment({ token, apiRequest, jobs = [], model = DEFAULT_MODEL, apiKey = "", initialRubric = null, initialJobDescription = "", initialJobTitle = "", onRubricChange }) {
  const [jobDescription, setJobDescription] = useState(String(initialJobDescription || ""));
  const [jobId, setJobId] = useState("");
  const [sourceMode, setSourceMode] = useState(initialJobDescription ? "standardizer" : "paste");
  const [jobTitle, setJobTitle] = useState(String(initialJobTitle || ""));
  const [requiredYears, setRequiredYears] = useState("");
  const [education, setEducation] = useState("Not required");
  const [equivalentExperience, setEquivalentExperience] = useState(true);
  const [rubric, setRubric] = useState(initialRubric);
  const [rubricMeta, setRubricMeta] = useState(null);
  const [savedRubrics, setSavedRubrics] = useState([]);
  const [selectedSavedRubricId, setSelectedSavedRubricId] = useState("");
  const [categoryWeightDrafts, setCategoryWeightDrafts] = useState({});
  const [candidates, setCandidates] = useState([]);
  const [busy, setBusy] = useState("");
  const [progress, setProgress] = useState({ completed: 0, total: 0, message: "" });
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const usableJobs = useMemo(() => jobs.filter((item) => item.status !== "archived"), [jobs]);
  const selectedSavedRubric = useMemo(
    () => savedRubrics.find((item) => String(item.rubric_id) === String(selectedSavedRubricId)) || null,
    [savedRubrics, selectedSavedRubricId],
  );
  const categoryWeights = useMemo(() => {
    if (!rubric?.criteria?.length) return [];
    const totals = new Map();
    for (const criterion of rubric.criteria) {
      const category = String(criterion.category || "Other").trim() || "Other";
      totals.set(category, (totals.get(category) || 0) + (Number(criterion.weight) || 0));
    }
    const sum = [...totals.values()].reduce((total, value) => total + value, 0);
    return [...totals.entries()].map(([category, weight]) => ({
      category,
      weight: sum > 0 ? weight * 100 / sum : 0,
    }));
  }, [rubric]);
  useEffect(() => {
    const drafts = {};
    categoryWeights.forEach((item) => { drafts[item.category] = String(Math.round(item.weight)); });
    setCategoryWeightDrafts(drafts);
  }, [categoryWeights]);

  const hasUnsavedRubricChanges = useMemo(() => {
    if (!selectedSavedRubric) return false;
    const normalized = normalize(rubric);
    if (!normalized) return true;
    const current = {
      ...normalized,
      role_profile: {
        job_title: jobTitle.trim() || normalized.title || "Assessment rubric",
        required_years_overall: requiredYears === "" ? null : Number(requiredYears),
        education_minimum: education,
        equivalent_experience_accepted: equivalentExperience,
      },
    };
    return stableSerialize(current) !== stableSerialize(selectedSavedRubric.rubric);
  }, [selectedSavedRubric, rubric, jobTitle, requiredYears, education, equivalentExperience]);
  const assessmentReady = Boolean(rubric && selectedSavedRubric && !hasUnsavedRubricChanges);
  const ranked = useMemo(() => [...candidates].filter((item) => item.analysis).sort((a, b) => Number(b.analysis.overall_score || 0) - Number(a.analysis.overall_score || 0)), [candidates]);
  const readyCount = candidates.filter((item) => item.resumeData && item.status !== "scored").length;

  useEffect(() => {
    try {
      const saved = JSON.parse(sessionStorage.getItem(SAVE_KEY) || "null");
      if (saved) {
        if (!String(initialJobDescription || "").trim()) setJobDescription(String(saved.jobDescription || ""));
        if (!String(initialJobTitle || "").trim()) setJobTitle(String(saved.jobTitle || ""));
        setRequiredYears(saved.requiredYears == null ? "" : String(saved.requiredYears));
        setEducation(saved.education || "Not required");
        setEquivalentExperience(typeof saved.equivalentExperience === "boolean" ? saved.equivalentExperience : true);
        if (!initialRubric && saved.rubric?.criteria?.length) setRubric(saved.rubric);
      }
    } catch { /* Ignore invalid session data. */ }
    if (initialRubric?.criteria?.length) setRubric(initialRubric);
  }, [initialRubric]);

  function credentials() {
    return { model: String(model || DEFAULT_MODEL).trim() || DEFAULT_MODEL, ...(String(apiKey || "").trim() ? { api_key: String(apiKey).trim() } : {}) };
  }

  function loadFromStandardizer() {
    if (!String(initialJobDescription || "").trim()) {
      setSourceMode("standardizer");
      setNotice("Generate a job description in the JD Standardizer first, or choose Paste a JD.");
      return;
    }
    setSourceMode("standardizer");
    setJobDescription(String(initialJobDescription));
    if (String(initialJobTitle || "").trim()) setJobTitle(String(initialJobTitle));
    setNotice("Loaded the current job description from JD Standardizer. Review it before building the rubric.");
    setError("");
  }

  function applySavedRubric(saved) {
    if (!saved?.rubric?.criteria?.length) return false;
    setSelectedSavedRubricId(String(saved.rubric_id || ""));
    setJobDescription(String(saved.job_description || saved.jobDescription || ""));
    setJobTitle(String(saved.job_title || saved.jobTitle || ""));
    const profile = saved.rubric?.role_profile || {};
    setRequiredYears(
      profile.required_years_overall != null
        ? String(profile.required_years_overall)
        : (saved.requiredYears == null ? "" : String(saved.requiredYears))
    );
    setEducation(String(profile.education_minimum || saved.education || "Not required"));
    setEquivalentExperience(
      typeof profile.equivalent_experience_accepted === "boolean"
        ? profile.equivalent_experience_accepted
        : (typeof saved.equivalentExperience === "boolean" ? saved.equivalentExperience : true)
    );
    setRubric(saved.rubric);
    setRubricMeta(null);
    onRubricChange?.(saved.rubric);
    setNotice("Saved rubric loaded. Review the requirements before assessing a batch.");
    setError("");
    return true;
  }

  async function loadSavedRubric() {
    setSourceMode("saved");
    setBusy("saved-rubrics");
    setError("");
    setNotice("");
    try {
      const response = await apiRequest(token, "get", "/ai-hiring/rubrics");
      const items = Array.isArray(response.data?.rubrics) ? response.data.rubrics : [];
      setSavedRubrics(items);
      if (items.length) {
        applySavedRubric(items[0]);
      } else {
        const local = JSON.parse(sessionStorage.getItem(SAVE_KEY) || "null");
        if (local?.rubric?.criteria?.length) {
          applySavedRubric(local);
          setNotice("Loaded the browser-session draft. No organisation-saved rubrics exist yet; save this one to make it available to your team.");
        } else {
          setNotice("No saved rubrics yet. Build a rubric and choose Save rubric to create the first one.");
        }
      }
    } catch (requestError) {
      setError(errorText(requestError));
      try {
        const local = JSON.parse(sessionStorage.getItem(SAVE_KEY) || "null");
        if (local?.rubric?.criteria?.length) applySavedRubric(local);
      } catch { /* Ignore stale session data. */ }
    } finally {
      setBusy("");
    }
  }

  function chooseSavedRubric(value) {
    setSelectedSavedRubricId(value);
    const saved = savedRubrics.find((item) => String(item.rubric_id) === String(value));
    if (saved) applySavedRubric(saved);
  }

  function loadJob(value) {
    setJobId(value);
    const job = usableJobs.find((item) => String(item.id) === String(value));
    if (!job) return;
    setJobDescription(String(job.description || ""));
    setJobTitle(String(job.title || ""));
    setRequiredYears(job.minimum_experience_years == null ? "" : String(job.minimum_experience_years));
    setError("");
    setNotice("Loaded the job from the ATS. Review the description before building the rubric.");
  }

  async function buildRubric() {
    if (jobDescription.trim().length < 10) { setError("Select a job or enter a job description first."); return; }
    setBusy("rubric"); setError(""); setNotice("");
    try {
      const response = await apiRequest(token, "post", "/ai-hiring/rubric", { data: { ...credentials(), job_description: jobDescription.trim() }, timeout: 90000 });
      const next = normalize(response.data?.rubric);
      if (!next) throw new Error("The generated rubric has no positive criterion weights.");
      setRubric(next); setRubricMeta(response.data); setSelectedSavedRubricId(""); onRubricChange?.(next);
      setNotice("Rubric generated. Edit the criteria below, then save it before scoring resumes.");
    } catch (failure) { setError(errorText(failure)); }
    finally { setBusy(""); }
  }

  function editCriterion(index, field, value) {
    setRubric((old) => {
      if (!old?.criteria) return old;
      const criteria = old.criteria.map((item, i) => {
        if (i !== index) return item;
        if (field === "keywords") return { ...item, keywords: value.split(",").map((part) => part.trim()).filter(Boolean) };
        if (field === "weight") return { ...item, weight: Math.max(0, Math.min(100, Number(value) || 0)) };
        if (field === "minimum_years") return { ...item, minimum_years: value === "" ? null : Math.max(0, Number(value) || 0) };
        return { ...item, [field]: value };
      });
      return { ...old, criteria };
    });
  }

  function setCategoryWeight(category, requestedWeight) {
    const desired = Math.max(0, Math.min(100, Number(requestedWeight) || 0));
    setRubric((previous) => {
      const base = normalize(previous);
      if (!base) return previous;
      const categories = [...new Set(base.criteria.map((item) => String(item.category || "Other").trim() || "Other"))];
      if (!categories.includes(category)) return previous;
      if (categories.length === 1) {
        return { ...base, criteria: base.criteria.map((item) => ({ ...item, weight: 100 })), total_weight: 100 };
      }

      const oldTotals = new Map(categories.map((name) => [name, 0]));
      for (const item of base.criteria) {
        const name = String(item.category || "Other").trim() || "Other";
        oldTotals.set(name, (oldTotals.get(name) || 0) + item.weight);
      }
      const others = categories.filter((name) => name !== category);
      const otherTotal = others.reduce((sum, name) => sum + (oldTotals.get(name) || 0), 0);
      const groupTargets = new Map([[category, desired]]);
      let allocated = 0;
      others.forEach((name, index) => {
        const target = index === others.length - 1
          ? Math.max(0, 100 - desired - allocated)
          : Number(((100 - desired) * ((oldTotals.get(name) || 0) > 0 ? oldTotals.get(name) : 1) /
              (otherTotal > 0 ? otherTotal : others.length)).toFixed(2));
        groupTargets.set(name, target);
        allocated += target;
      });

      const updated = base.criteria.map((item) => {
        const name = String(item.category || "Other").trim() || "Other";
        const groupRows = base.criteria.filter((row) => (String(row.category || "Other").trim() || "Other") === name);
        const groupSum = groupRows.reduce((sum, row) => sum + row.weight, 0);
        const indexInGroup = groupRows.indexOf(item);
        const priorInGroup = groupRows.slice(0, indexInGroup).reduce((sum, row) => {
          const proportion = groupSum > 0 ? row.weight / groupSum : 1 / groupRows.length;
          return sum + Number((groupTargets.get(name) * proportion).toFixed(2));
        }, 0);
        const target = groupTargets.get(name) || 0;
        const nextWeight = indexInGroup === groupRows.length - 1
          ? Math.max(0, Number((target - priorInGroup).toFixed(2)))
          : Number((target * (groupSum > 0 ? item.weight / groupSum : 1 / groupRows.length)).toFixed(2));
        return { ...item, weight: nextWeight };
      });
      return { ...base, criteria: updated, total_weight: Number(updated.reduce((sum, item) => sum + item.weight, 0).toFixed(2)) };
    });
  }

  async function saveRubric() {
    const saved = normalize(rubric);
    if (!saved) { setError("Enter positive criterion weights before saving the rubric."); return; }
    if (saved.criteria.some((item) => !item.name.trim())) { setError("Every criterion needs a requirement name."); return; }
    if (jobDescription.trim().length < 10) { setError("A job description is required to save a reusable rubric."); return; }
    if (requiredYears !== "" && (!Number.isFinite(Number(requiredYears)) || Number(requiredYears) < 0 || Number(requiredYears) > 60)) {
      setError("Required experience must be between 0 and 60 years."); return;
    }
    const finalRubric = { ...saved, role_profile: {
      job_title: jobTitle.trim() || saved.title || "Assessment rubric",
      required_years_overall: requiredYears === "" ? null : Number(requiredYears),
      education_minimum: education,
      equivalent_experience_accepted: equivalentExperience,
    } };
    const body = {
      title: jobTitle.trim() || finalRubric.title || "Assessment rubric",
      job_title: jobTitle.trim() || finalRubric.title || "Assessment rubric",
      job_description: jobDescription.trim(),
      rubric: finalRubric,
    };
    setBusy("save-rubric");
    setError("");
    try {
      const response = selectedSavedRubricId
        ? await apiRequest(token, "put", "/ai-hiring/rubrics/" + encodeURIComponent(selectedSavedRubricId), { data: body })
        : await apiRequest(token, "post", "/ai-hiring/rubrics", { data: body });
      const stored = response.data;
      setSelectedSavedRubricId(String(stored.rubric_id));
      setSavedRubrics((old) => [stored, ...old.filter((item) => String(item.rubric_id) !== String(stored.rubric_id))]);
      setRubric(stored.rubric || finalRubric);
      onRubricChange?.(stored.rubric || finalRubric);
      try {
        sessionStorage.setItem(SAVE_KEY, JSON.stringify({
          jobDescription, jobTitle, requiredYears, education, equivalentExperience, rubric: stored.rubric || finalRubric,
        }));
      } catch { /* The backend save succeeded, so browser storage is only a convenience. */ }
      setSourceMode("saved");
      setNotice("Saved as immutable version v" + String(stored.version || 1) + ". This version is frozen; later edits create a new version.");
    } catch (requestError) {
      setError(errorText(requestError));
    } finally {
      setBusy("");
    }
  }

  function addCriterion() {
    setRubric((old) => old ? { ...old, criteria: [...old.criteria, {
      name: "New requirement", type: "skill", category: "Technical", required: false,
      weight: 10, minimum_years: null, keywords: [], description: "Edit this requirement.",
      scoring_guide: { missing: "Not evidenced", partial: "Some evidence", strong: "Clear evidence" },
    }] } : old);
  }

  function removeCriterion(index) {
    setRubric((old) => old ? { ...old, criteria: old.criteria.filter((_, i) => i !== index) } : old);
  }

  function selectFiles(event) {
    const input = event.currentTarget;
    const files = Array.from(input.files || []);
    setError(""); setNotice(""); setCandidates([]);
    if (!files.length) return;
    if (files.length > MAX_BATCH) {
      setError("Select at most " + MAX_BATCH + " resumes per batch. Split larger batches into separate runs.");
      input.value = ""; return;
    }
    const valid = files.filter((file) => /\.(pdf|docx)$/i.test(file.name) && file.size > 0 && file.size <= MAX_BYTES);
    if (valid.length !== files.length) setError("Invalid files were skipped. Every resume must be a non-empty PDF/DOCX file no larger than 5 MB.");
    setCandidates(valid.map((file, index) => ({
      id: String(file.size) + "-" + String(file.lastModified) + "-" + index,
      file, index, resumeData: null, analysis: null, status: "queued", error: "", latencyMs: null,
    })));
    input.value = "";
  }

  async function extractBatch() {
    if (!candidates.length) { setError("Select one or more PDF/DOCX resumes first."); return; }
    const queue = candidates.map((item) => ({ ...item }));
    setBusy("extract"); setError(""); setNotice("");
    setProgress({ completed: 0, total: queue.length, message: "Starting resume extraction…" });
    for (let i = 0; i < queue.length; i += 1) {
      const item = queue[i];
      setProgress({ completed: i, total: queue.length, message: "Extracting " + label(item.index) + "…" });
      try {
        const form = new FormData(); form.append("file", item.file);
        const response = await apiRequest(token, "post", "/extract/", { data: form, timeout: 90000 });
        const data = response.data?.data || response.data?.resume_json;
        if (!data || typeof data !== "object") throw new Error("No structured resume data was returned.");
        queue[i] = { ...item, resumeData: data, status: "ready", error: "" };
      } catch (failure) { queue[i] = { ...item, status: "extract_error", error: errorText(failure) }; }
      setCandidates([...queue]);
      setProgress({ completed: i + 1, total: queue.length, message: (i + 1) + " of " + queue.length + " resumes extracted." });
    }
    setBusy("");
    const succeeded = queue.filter((item) => item.resumeData).length;
    setNotice(succeeded + " of " + queue.length + " resumes extracted. " + (succeeded ? "You can now run the assessment." : "Review file errors and retry."));
  }

  async function assessBatch() {
    const final = normalize(rubric);
    if (!final) { setError("Build or load a rubric with positive weights before assessing."); return; }
    if (!selectedSavedRubric) { setError("Save the reviewed rubric first. Each batch must use a frozen, versioned rubric."); return; }
    if (hasUnsavedRubricChanges) { setError("This saved version is frozen. Save a new rubric version before assessment so every result uses an exact, auditable rubric."); return; }
    const eligible = candidates.filter((item) => item.resumeData && item.status !== "scored");
    if (!eligible.length) { setError("Extract at least one resume before assessing the batch."); return; }
    final.role_profile = {
      job_title: jobTitle.trim() || final.title || "Assessment rubric",
      required_years_overall: requiredYears === "" ? null : Number(requiredYears),
      education_minimum: education,
      equivalent_experience_accepted: equivalentExperience,
    };
    setRubric(final); onRubricChange?.(final);
    const queue = candidates.map((item) => ({ ...item }));
    const indices = queue.map((item, i) => item.resumeData && item.status !== "scored" ? i : -1).filter((i) => i >= 0);
    setBusy("assess"); setError(""); setNotice("");
    setProgress({ completed: 0, total: indices.length, message: "Assessing resumes against the rubric…" });
    for (let ordinal = 0; ordinal < indices.length; ordinal += 1) {
      const i = indices[ordinal];
      const item = queue[i];
      setProgress({ completed: ordinal, total: indices.length, message: "Assessing " + label(item.index) + "…" });
      try {
        const response = await apiRequest(token, "post", "/ai-hiring/analyze-resume", {
          data: {
            ...credentials(),
            resume_data: item.resumeData,
            rubric: final,
            saved_rubric_id: selectedSavedRubric.rubric_id,
            saved_rubric_version: selectedSavedRubric.version,
            saved_rubric_sha256: selectedSavedRubric.content_sha256,
          }, timeout: 90000,
        });
        const result = response.data || {};
        queue[i] = { ...item, analysis: result.analysis || null, savedRubric: result.saved_rubric || null, status: result.analysis ? "scored" : "score_error", error: result.analysis ? "" : "No assessment result returned.", latencyMs: result.latency_ms ?? null };
      } catch (failure) { queue[i] = { ...item, status: "score_error", error: errorText(failure) }; }
      setCandidates([...queue]);
      setProgress({ completed: ordinal + 1, total: indices.length, message: (ordinal + 1) + " of " + indices.length + " assessments completed." });
    }
    setBusy("");
    setNotice(queue.filter((item) => item.analysis).length + " of " + indices.length + " resumes assessed. Results are evidence-ranked for recruiter review; no one was automatically shortlisted or rejected.");
  }

  const field = "mt-1.5 w-full rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-900 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-100";
  const primary = "inline-flex items-center justify-center rounded-lg bg-blue-700 px-4 py-2.5 text-sm font-semibold text-white hover:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-50";
  const secondary = "inline-flex items-center justify-center rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50";
  const display = ranked.length ? [...ranked, ...candidates.filter((item) => !item.analysis)] : candidates;

  return <div className="space-y-5">
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div><p className="text-xs font-semibold uppercase tracking-[0.16em] text-blue-700">Structured evaluation</p><h3 className="mt-1 text-xl font-semibold text-slate-950">Application assessment</h3><p className="mt-1 max-w-3xl text-sm leading-6 text-slate-600">Build a job-specific rubric, process a batch of resumes, and compare evidence consistently.</p></div>
        <span className="rounded-full bg-blue-50 px-3 py-1 text-xs font-semibold text-blue-800">Human review required</span>
      </div>
      <div className="mt-4 rounded-lg border border-blue-100 bg-blue-50/70 p-3 text-sm leading-5 text-blue-950"><strong>Decision support only.</strong> Match scores reflect job-related evidence found in resumes. They do not predict hiring success and do not automatically shortlist or reject anyone.</div>
    </section>
    {(error || notice) && <div role={error ? "alert" : "status"} className={"rounded-lg border px-4 py-3 text-sm " + (error ? "border-rose-200 bg-rose-50 text-rose-800" : "border-emerald-200 bg-emerald-50 text-emerald-800")}>{error || notice}</div>}

    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3"><div><p className="text-xs font-semibold uppercase tracking-wide text-blue-700">01 · Job and rubric</p><h4 className="mt-1 text-lg font-semibold text-slate-900">Define assessment requirements</h4></div>{rubric && <div className="flex flex-wrap items-center gap-2"><span className="rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-700">{rubric.criteria?.length || 0} criteria · {rubric.total_weight ?? 100}% total</span>{selectedSavedRubric ? <span className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-xs font-semibold text-slate-600">Frozen v{selectedSavedRubric.version} · SHA-256 {String(selectedSavedRubric.content_sha256 || "").slice(0, 12)}</span> : <span className="rounded-full bg-amber-50 px-2.5 py-1 text-xs font-semibold text-amber-800">Draft — review, then save</span>}</div>}</div>
      <div className="mt-4 flex flex-wrap gap-2 border-b border-slate-200 pb-4" role="tablist" aria-label="Job description source">
        <button type="button" role="tab" aria-selected={sourceMode === "standardizer"} className={sourceMode === "standardizer" ? primary : secondary} onClick={loadFromStandardizer}>From JD Standardizer</button>
        <button type="button" role="tab" aria-selected={sourceMode === "paste"} className={sourceMode === "paste" ? primary : secondary} onClick={() => { setSourceMode("paste"); setNotice("Paste or edit a job description below."); setError(""); }}>Paste a JD</button>
        <button type="button" role="tab" aria-selected={sourceMode === "saved"} className={sourceMode === "saved" ? primary : secondary} onClick={loadSavedRubric}>Saved rubric</button>
      </div>
      {sourceMode === "standardizer" && <p className="mt-3 text-xs leading-5 text-slate-500">{String(initialJobDescription || "").trim() ? "Using the current JD Standardizer output. You can edit the description below before generating the rubric." : "No generated JD is currently available from JD Standardizer. Generate one there, or switch to Paste a JD."}</p>}
      {sourceMode === "saved" && <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50 p-3">
        <label className="block text-sm font-semibold text-slate-700">Saved rubric
          <select className={field} value={selectedSavedRubricId} onChange={(event) => chooseSavedRubric(event.target.value)} disabled={!savedRubrics.length || Boolean(busy)}>
            <option value="">{savedRubrics.length ? "Choose a saved rubric" : "No organisation rubrics saved yet"}</option>
            {savedRubrics.map((item) => <option key={item.rubric_id} value={String(item.rubric_id)}>{item.title} · v{item.version} · {item.job_title}</option>)}
          </select>
        </label>
        <p className="mt-2 text-xs text-slate-500">{busy === "saved-rubrics" ? "Loading saved rubrics…" : savedRubrics.length + " organisation-saved rubric(s) available. Saving again updates the selected rubric."}</p>
      </div>}
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <label className="text-sm font-semibold text-slate-700">Use an existing ATS job<select className={field} value={jobId} onChange={(event) => loadJob(event.target.value)}><option value="">Choose a role or paste a JD</option>{usableJobs.map((job) => <option key={job.id} value={String(job.id)}>{job.title}</option>)}</select></label>
        <label className="text-sm font-semibold text-slate-700">Job title<input className={field} value={jobTitle} onChange={(event) => setJobTitle(event.target.value)} placeholder="Implementation Specialist" /></label>
      </div>
      <label className="mt-4 block text-sm font-semibold text-slate-700">Job description<textarea className={field + " min-h-32 leading-6"} value={jobDescription} onChange={(event) => setJobDescription(event.target.value)} placeholder="Select an existing ATS role or paste a job description." /></label>
      <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <label className="text-sm font-semibold text-slate-700">Required years overall<input className={field} type="number" min="0" max="60" step="0.5" value={requiredYears} onChange={(event) => setRequiredYears(event.target.value)} placeholder="Not specified" /></label>
        <label className="text-sm font-semibold text-slate-700">Education minimum<select className={field} value={education} onChange={(event) => setEducation(event.target.value)}><option>Not required</option><option>Secondary</option><option>Diploma</option><option>Bachelor's</option><option>Master's</option><option>Doctorate</option><option>Equivalent experience</option></select></label>
        <label className="sm:col-span-2 flex items-center gap-2 self-end rounded-lg border border-slate-200 px-3 py-3 text-sm font-medium text-slate-700"><input type="checkbox" className="h-4 w-4 accent-blue-700" checked={equivalentExperience} onChange={(event) => setEquivalentExperience(event.target.checked)} />Equivalent experience accepted</label>
      </div>
      <div className="mt-4 flex flex-wrap gap-2"><button className={primary} type="button" disabled={Boolean(busy)} onClick={() => void buildRubric()}>{busy === "rubric" ? "Building rubric…" : "Generate rubric from JD"}</button><button className={secondary} type="button" disabled={Boolean(busy) || !rubric} onClick={() => void saveRubric()}>{busy === "save-rubric" ? "Saving rubric…" : selectedSavedRubricId ? "Save new version" : "Save rubric"}</button><button className={secondary} type="button" disabled={Boolean(busy) || !rubric} onClick={addCriterion}>Add requirement</button><button className={secondary} type="button" disabled={Boolean(busy) || !rubric} onClick={() => { setRubric(null); setRubricMeta(null); setSelectedSavedRubricId(""); setNotice("Build a new rubric from the job description."); }}>Reset rubric</button></div>
      {rubricMeta && <p className="mt-3 text-xs text-slate-500">Generated by {rubricMeta.model || model} · {rubricMeta.latency_ms ?? "—"} ms. Review and edit every criterion before use.</p>}
      {selectedSavedRubric && hasUnsavedRubricChanges && <div role="status" className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm leading-5 text-amber-900">You are editing frozen rubric v{selectedSavedRubric.version}. Save new version to preserve this change before assessing. Existing versions are not overwritten.</div>}
      {rubric && categoryWeights.length > 0 && <details className="mt-4 rounded-lg border border-slate-200 px-4 py-3">
        <summary className="cursor-pointer text-sm font-semibold text-slate-800">Category weights</summary>
        <p className="mt-2 text-xs leading-5 text-slate-500">Adjust the total emphasis for each group. Criterion weights within each group are rescaled proportionally; the complete rubric remains at 100%.</p>
        <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {categoryWeights.map((item) => <label key={item.category} className="flex items-center gap-3 rounded-md border border-slate-100 p-3 text-sm">
            <span className="min-w-0 flex-1 font-medium text-slate-700">{item.category}</span>
            <input type="number" min="0" max="100" step="1" className="w-24 rounded-md border border-slate-200 px-2 py-2 text-right text-sm" value={categoryWeightDrafts[item.category] ?? String(Math.round(item.weight))} onChange={(event) => setCategoryWeightDrafts((old) => ({ ...old, [item.category]: event.target.value }))} onBlur={(event) => setCategoryWeight(item.category, event.target.value)} aria-label={"Category weight for " + item.category} />
            <span className="text-xs text-slate-500">%</span>
          </label>)}
        </div>
      </details>}
      {rubric && <div className="mt-5 overflow-x-auto rounded-lg border border-slate-200"><table className="w-full min-w-[1050px] border-collapse text-left text-sm"><thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500"><tr><th className="px-3 py-3">Requirement</th><th className="px-3 py-3">Type</th><th className="px-3 py-3">Group</th><th className="px-3 py-3">Importance</th><th className="px-3 py-3">Weight</th><th className="px-3 py-3">Min years</th><th className="px-3 py-3">Aliases / searched</th><th className="px-3 py-3">Remove</th></tr></thead><tbody className="divide-y divide-slate-100">
        {rubric.criteria.map((item, index) => <tr key={String(item.name || "criterion") + index} className="align-top">
          <td className="min-w-52 px-3 py-3"><p className="mb-1 text-[10px] font-bold tracking-wide text-slate-400">R{String(index + 1).padStart(2, "0")}</p><input className={field} value={item.name || ""} onChange={(event) => editCriterion(index, "name", event.target.value)} aria-label={"Requirement " + (index + 1)} /><p className="mt-1 max-w-xs text-xs text-slate-500">{item.description || ""}</p></td>
          <td className="px-3 py-3"><select className={field} value={item.type || "skill"} onChange={(event) => editCriterion(index, "type", event.target.value)}><option value="skill">Skill</option><option value="experience">Experience</option><option value="education">Education</option><option value="certification">Certification</option><option value="language">Language</option><option value="responsibility">Responsibility</option><option value="other">Other</option></select></td>
          <td className="px-3 py-3"><input className={field} value={item.category || ""} onChange={(event) => editCriterion(index, "category", event.target.value)} aria-label={"Group for " + item.name} /></td>
          <td className="px-3 py-3"><select className={field} value={item.required ? "must" : "preferred"} onChange={(event) => editCriterion(index, "required", event.target.value === "must")}><option value="must">Must-have</option><option value="preferred">Preferred</option></select></td>
          <td className="w-28 px-3 py-3"><input className={field} type="number" min="0" max="100" step="0.5" value={item.weight ?? 0} onChange={(event) => editCriterion(index, "weight", event.target.value)} aria-label={"Weight for " + item.name} /></td>
          <td className="w-28 px-3 py-3"><input className={field} type="number" min="0" max="60" step="0.5" value={item.minimum_years ?? ""} onChange={(event) => editCriterion(index, "minimum_years", event.target.value)} aria-label={"Minimum years for " + item.name} /></td>
          <td className="min-w-56 px-3 py-3"><input className={field} value={(item.keywords || []).join(", ")} onChange={(event) => editCriterion(index, "keywords", event.target.value)} placeholder="none — judged by evidence" aria-label={"Aliases for " + item.name} /></td>
          <td className="px-3 py-3"><button className={secondary} type="button" disabled={rubric.criteria.length < 2 || Boolean(busy)} onClick={() => removeCriterion(index)}>Remove</button></td>
        </tr>)}
      </tbody></table></div>}
      <p className="mt-3 text-xs leading-5 text-slate-500">Importance separates required from preferred criteria. Aliases are passed to the assessment model as evidence-search cues; they are not additional requirements. Review cited evidence, and treat missing evidence as unverified rather than as proof of a missing skill.</p>
    </section>

    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
      <p className="text-xs font-semibold uppercase tracking-wide text-blue-700">02 · Resumes</p><h4 className="mt-1 text-lg font-semibold text-slate-900">Upload a batch of resumes</h4><p className="mt-1 text-sm leading-6 text-slate-600">Select up to {MAX_BATCH} PDF/DOCX resumes, each no larger than 5 MB. Extraction and AI calls are processed sequentially to limit resource spikes.</p>
      <label className="mt-4 block rounded-lg border border-dashed border-slate-300 bg-slate-50 p-4 text-sm font-semibold text-slate-800">Resume files<input className="mt-2 block w-full rounded-lg border border-slate-200 bg-white p-3 text-sm font-normal" type="file" multiple accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" disabled={Boolean(busy)} onChange={selectFiles} /><span className="mt-2 block text-xs font-normal text-slate-500">{candidates.length ? candidates.length + " valid resumes selected" : "Files are labelled anonymously during assessment; filenames remain in this browser UI."}</span></label>
      <div className="mt-4 flex flex-wrap gap-2"><button className={secondary} type="button" disabled={Boolean(busy) || !candidates.length} onClick={() => void extractBatch()}>{busy === "extract" ? "Extracting…" : "Extract selected resumes"}</button><button className={primary} type="button" disabled={Boolean(busy) || !rubric || readyCount === 0} onClick={() => void assessBatch()}>{busy === "assess" ? "Assessing batch…" : "Assess " + readyCount + " ready resume(s)"}</button><button className={secondary} type="button" disabled={Boolean(busy) || !candidates.length} onClick={() => { setCandidates([]); setProgress({ completed: 0, total: 0, message: "" }); setError(""); setNotice(""); }}>Clear batch</button></div>
      {busy && progress.total > 0 && <div className="mt-4" aria-live="polite"><div className="flex justify-between gap-2 text-xs text-slate-600"><span>{progress.message}</span><span>{progress.completed}/{progress.total}</span></div><div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-100"><div className="h-full bg-blue-700" style={{ width: String(progress.completed / progress.total * 100) + "%" }} /></div></div>}
      <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50/70 p-3 text-xs leading-5 text-amber-950">Privacy: the backend removes structured contact/protected-attribute fields and redacts common identifiers before model analysis. Free-text identifiers may not all be detected. Only process documents you are authorized to use; AI run history receives sanitized assessment input.</div>
      {candidates.length > 0 && <div className="mt-4 overflow-x-auto rounded-lg border border-slate-200"><table className="w-full min-w-[540px] text-left text-sm"><thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500"><tr><th className="px-3 py-3">Candidate</th><th className="px-3 py-3">File name (local only)</th><th className="px-3 py-3">Status</th><th className="px-3 py-3">Size</th></tr></thead><tbody className="divide-y divide-slate-100">{candidates.map((item) => <tr key={item.id}><td className="px-3 py-2.5 font-semibold text-slate-800">{label(item.index)}</td><td className="px-3 py-2.5 text-slate-600">{item.file.name}</td><td className="px-3 py-2.5 text-slate-600">{item.status.replaceAll("_", " ")}{item.error && <p className="mt-1 text-xs text-rose-700">{item.error}</p>}</td><td className="px-3 py-2.5 text-slate-600">{(item.file.size / 1024).toFixed(0)} KB</td></tr>)}</tbody></table></div>}
    </section>

    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6"><div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-xs font-semibold uppercase tracking-wide text-blue-700">03 · Applicant cards</p><h4 className="mt-1 text-lg font-semibold text-slate-900">Evidence-ranked results</h4><p className="mt-1 text-sm text-slate-600">Sorted by rubric alignment for recruiter review, not an automated shortlist.</p></div><span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-700">{ranked.length} assessed</span></div>
      {display.length === 0 ? <div className="mt-4 rounded-lg border border-dashed border-slate-300 p-8 text-center"><p className="font-semibold text-slate-800">No applicants assessed yet</p><p className="mt-1 text-sm text-slate-500">Generate a rubric, extract resumes, then assess the batch to populate these cards.</p></div>
        : <div className="mt-4 grid gap-3 xl:grid-cols-2">{display.map((item) => {
          const score = item.analysis ? Math.max(0, Math.min(100, Number(item.analysis.overall_score || 0))) : null;
          return <article key={item.id} className="rounded-lg border border-slate-200 p-4"><div className="flex items-start justify-between gap-3"><div><h5 className="font-semibold text-slate-900">{label(item.index)}</h5><p className="mt-1 text-xs text-slate-500">{item.status === "scored" ? "Assessed · " + (item.latencyMs ?? "—") + " ms" : item.status.replaceAll("_", " ")}</p>{item.savedRubric && <p className="mt-1 break-all text-[11px] text-slate-500">Rubric v{item.savedRubric.version} · SHA-256 {String(item.savedRubric.content_sha256 || "").slice(0, 16)}</p>}</div>{score !== null && <div className="text-right"><p className="text-2xl font-semibold tabular-nums text-slate-950">{Math.round(score)}%</p><p className="text-xs text-slate-500">Evidence alignment</p></div>}</div>
            {item.analysis && <><p className="mt-3 text-sm leading-6 text-slate-600">{item.analysis.summary || "Review the criterion evidence below."}</p><div className="mt-3 grid gap-3 sm:grid-cols-2"><div><p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Strengths</p><ul className="mt-1 list-disc space-y-1 pl-4 text-sm text-slate-700">{(item.analysis.strengths || []).slice(0, 3).map((entry, index) => <li key={index}>{String(entry)}</li>)}</ul></div><div><p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Evidence gaps / follow-up</p><ul className="mt-1 list-disc space-y-1 pl-4 text-sm text-slate-700">{[...(item.analysis.concerns || []), ...(item.analysis.missing_requirements || [])].slice(0, 3).map((entry, index) => <li key={index}>{String(entry)}</li>)}</ul></div></div><details className="mt-3 border-t border-slate-100 pt-3"><summary className="cursor-pointer text-sm font-semibold text-blue-800">Review all criteria and evidence</summary><div className="mt-3 space-y-3">{(item.analysis.criteria || []).map((criterion, index) => <div key={String(criterion.name || "criterion") + index} className="rounded-md bg-slate-50 p-3"><div className="flex justify-between gap-2"><p className="font-medium text-slate-800">{criterion.name || "Criterion"}</p><span className="text-sm font-semibold text-slate-900">{Math.round(Number(criterion.score || 0))}% · {criterion.weight ?? 0}%</span></div><p className="mt-1 text-sm text-slate-600">{criterion.assessment || "Review evidence."}</p>{criterion.evidence?.length > 0 && <ul className="mt-2 list-disc pl-4 text-sm text-slate-700">{criterion.evidence.map((entry, j) => <li key={j}>{String(entry)}</li>)}</ul>}<p className="mt-2 text-xs text-slate-500">Follow-up: {criterion.gap || "No specific gap returned."}</p></div>)}</div></details></>}
            {item.error && <p className="mt-3 text-sm text-rose-700">{item.error}</p>}
          </article>;
        })}</div>}
    </section>
  </div>;
}
