import { useState } from "react";
import axios from "axios";

const configuredApiUrl = import.meta.env.VITE_API_URL?.trim();
const API_URL = (
  configuredApiUrl ||
  (import.meta.env.PROD ? "https://bluepace-ats-11.onrender.com" : "http://localhost:8000")
).replace(/\/+$/, "");

const EMPTY = {
  title: "",
  description: "",
  department: "",
  location: "",
  employment_type: "full-time",
  work_mode: "hybrid",
  required_skills: "",
  minimum_experience_years: "",
  fresher_allowed: false,
  contact_email: "",
  posted_by_name: "",
};

/** Public careers form: posts an open role without recruiter login. */
export default function PublicJobPostForm({ onCreated }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(EMPTY);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  function update(field, value) {
    setForm((current) => ({ ...current, [field]: value }));
  }

  async function submit(event) {
    event.preventDefault();
    setError("");
    setSuccess("");
    const title = form.title.trim();
    const description = form.description.trim();
    if (title.length < 3) {
      setError("Enter a job title (at least 3 characters).");
      return;
    }
    if (description.length < 40) {
      setError("Add a fuller role description (at least 40 characters).");
      return;
    }
    setBusy(true);
    try {
      const skills = form.required_skills
        .split(/[,;\n]/)
        .map((item) => item.trim())
        .filter(Boolean)
        .slice(0, 40);
      const body = {
        title,
        description,
        department: form.department.trim() || null,
        location: form.location.trim() || null,
        employment_type: form.employment_type.trim() || null,
        work_mode: form.work_mode,
        required_skills: skills,
        minimum_experience_years: form.minimum_experience_years === "" ? null : Number(form.minimum_experience_years),
        fresher_allowed: Boolean(form.fresher_allowed),
        contact_email: form.contact_email.trim() || null,
        posted_by_name: form.posted_by_name.trim() || null,
      };
      const response = await axios.post(`${API_URL}/public/jobs`, body, { timeout: 60000 });
      const job = response.data;
      setSuccess(`Published “${job.title}”. It now appears under Open roles.`);
      setForm(EMPTY);
      if (typeof onCreated === "function") onCreated(job);
      else window.setTimeout(() => window.location.reload(), 900);
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setError(typeof detail === "string" ? detail : err?.message || "Could not publish this role.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="mx-auto max-w-7xl px-5 pb-10" aria-labelledby="public-post-role-title">
      <div className="rounded-2xl border border-ink-100 bg-white p-5 shadow-sm sm:p-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-ink-500">Hiring team</p>
            <h2 id="public-post-role-title" className="mt-1 text-xl font-semibold text-ink-900">
              Post an open role
            </h2>
            <p className="mt-1 max-w-2xl text-sm leading-6 text-ink-600">
              Publish a role on this careers page without signing in to the ATS. The listing goes live immediately
              under Open roles.
            </p>
          </div>
          <button
            type="button"
            className="rounded-xl border border-ink-200 bg-ink-950 px-4 py-2 text-sm font-semibold text-white"
            onClick={() => setOpen((value) => !value)}
            aria-expanded={open}
          >
            {open ? "Hide form" : "Add open role"}
          </button>
        </div>

        {open && (
          <form className="mt-5 grid gap-4 sm:grid-cols-2" onSubmit={submit}>
            <label className="block text-sm sm:col-span-2">
              <span className="font-medium text-ink-800">Job title *</span>
              <input
                className="mt-1 w-full rounded-xl border border-ink-200 px-3 py-2 text-sm"
                value={form.title}
                onChange={(e) => update("title", e.target.value)}
                required
                maxLength={200}
                placeholder="e.g. Senior Full Stack Engineer"
              />
            </label>
            <label className="block text-sm sm:col-span-2">
              <span className="font-medium text-ink-800">Role description *</span>
              <textarea
                className="mt-1 min-h-32 w-full rounded-xl border border-ink-200 px-3 py-2 text-sm"
                value={form.description}
                onChange={(e) => update("description", e.target.value)}
                required
                maxLength={20000}
                placeholder="Responsibilities, requirements, and what success looks like…"
              />
            </label>
            <label className="block text-sm">
              <span className="font-medium text-ink-800">Department</span>
              <input
                className="mt-1 w-full rounded-xl border border-ink-200 px-3 py-2 text-sm"
                value={form.department}
                onChange={(e) => update("department", e.target.value)}
                placeholder="Engineering"
              />
            </label>
            <label className="block text-sm">
              <span className="font-medium text-ink-800">Location</span>
              <input
                className="mt-1 w-full rounded-xl border border-ink-200 px-3 py-2 text-sm"
                value={form.location}
                onChange={(e) => update("location", e.target.value)}
                placeholder="Hyderabad, India"
              />
            </label>
            <label className="block text-sm">
              <span className="font-medium text-ink-800">Employment type</span>
              <input
                className="mt-1 w-full rounded-xl border border-ink-200 px-3 py-2 text-sm"
                value={form.employment_type}
                onChange={(e) => update("employment_type", e.target.value)}
                placeholder="full-time"
              />
            </label>
            <label className="block text-sm">
              <span className="font-medium text-ink-800">Work mode</span>
              <select
                className="mt-1 w-full rounded-xl border border-ink-200 px-3 py-2 text-sm"
                value={form.work_mode}
                onChange={(e) => update("work_mode", e.target.value)}
              >
                <option value="hybrid">Hybrid</option>
                <option value="remote">Remote</option>
                <option value="onsite">On-site</option>
              </select>
            </label>
            <label className="block text-sm sm:col-span-2">
              <span className="font-medium text-ink-800">Required skills</span>
              <input
                className="mt-1 w-full rounded-xl border border-ink-200 px-3 py-2 text-sm"
                value={form.required_skills}
                onChange={(e) => update("required_skills", e.target.value)}
                placeholder="Python, React, SQL (comma-separated)"
              />
            </label>
            <label className="block text-sm">
              <span className="font-medium text-ink-800">Minimum experience (years)</span>
              <input
                type="number"
                min="0"
                max="60"
                step="0.5"
                className="mt-1 w-full rounded-xl border border-ink-200 px-3 py-2 text-sm"
                value={form.minimum_experience_years}
                onChange={(e) => update("minimum_experience_years", e.target.value)}
              />
            </label>
            <label className="mt-7 flex items-center gap-2 text-sm text-ink-800">
              <input
                type="checkbox"
                checked={form.fresher_allowed}
                onChange={(e) => update("fresher_allowed", e.target.checked)}
              />
              Freshers may apply
            </label>
            <label className="block text-sm">
              <span className="font-medium text-ink-800">Your name</span>
              <input
                className="mt-1 w-full rounded-xl border border-ink-200 px-3 py-2 text-sm"
                value={form.posted_by_name}
                onChange={(e) => update("posted_by_name", e.target.value)}
                placeholder="Hiring manager or recruiter"
              />
            </label>
            <label className="block text-sm">
              <span className="font-medium text-ink-800">Contact email</span>
              <input
                type="email"
                className="mt-1 w-full rounded-xl border border-ink-200 px-3 py-2 text-sm"
                value={form.contact_email}
                onChange={(e) => update("contact_email", e.target.value)}
                placeholder="you@company.com"
              />
            </label>
            {error && (
              <p role="alert" className="sm:col-span-2 text-sm text-rose-700">{error}</p>
            )}
            {success && (
              <p role="status" className="sm:col-span-2 text-sm text-emerald-700">{success}</p>
            )}
            <div className="sm:col-span-2 flex flex-wrap gap-2">
              <button
                type="submit"
                disabled={busy}
                className="rounded-xl bg-ink-950 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
              >
                {busy ? "Publishing…" : "Publish open role"}
              </button>
              <button
                type="button"
                className="rounded-xl border border-ink-200 px-4 py-2 text-sm font-semibold text-ink-800"
                onClick={() => {
                  setOpen(false);
                  setError("");
                  setSuccess("");
                }}
              >
                Cancel
              </button>
            </div>
          </form>
        )}
      </div>
    </section>
  );
}
