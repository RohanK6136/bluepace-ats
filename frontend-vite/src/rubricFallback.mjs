const SECTION_HEADINGS = /^(?:required\s+(?:qualifications?|skills?)|minimum\s+qualifications?|requirements?|qualifications?|must[- ]haves?|key\s+responsibilities|responsibilities|preferred(?:\s+(?:skills?|qualifications?))?|nice to have(?:\s+skills?)?|bonus|benefits|what we offer|about the role|experience|skills)\s*:?\s*$/i;
const PREFERRED_HEADINGS = /^(?:preferred(?:\s+(?:skills?|qualifications?))?|nice to have(?:\s+skills?)?|bonus)\s*:?\s*$/i;
const EXCLUDED_PREFIX = /^(?:location|based in|work mode|employment type|job type|salary|compensation|benefits|equal opportunity|about us|company overview|apply now|how to apply|visa sponsorship|work authorization)\b/i;
const EXPERIENCE_YEARS = /\b(\d+(?:\.\d+)?)\s*(?:\+|plus)?\s*(?:years?|yrs?)\s*(?:of\s+)?(?:relevant\s+)?experience\b/i;

const SKILL_GROUPS = [
  { group: "coding", terms: ["TypeScript", "JavaScript", "Python", "Java", "Kotlin", "Swift", "C++", "C#", ".NET", "React", "Next.js", "Node.js", "FastAPI", "Django", "Flask", "Spring Boot", "REST API", "GraphQL", "SQL", "PostgreSQL", "MySQL", "MongoDB", "HTML", "CSS", "PHP", "Ruby", "Go", "Rust"] },
  { group: "cloud_tools", terms: ["GitHub Actions", "CI/CD", "Kubernetes", "Terraform", "Databricks", "Snowflake", "Airflow", "dbt", "Kafka", "Spark", "Docker", "Jenkins", "AWS", "Azure", "GCP", "Google Cloud", "Linux", "Git", "Power BI", "Tableau", "Excel", "Salesforce", "SAP"] },
  { group: "domain", terms: ["data engineering", "machine learning", "artificial intelligence", "cybersecurity", "financial services", "banking", "healthcare", "insurance", "e-commerce", "logistics", "supply chain", "data analytics", "business analysis", "recruitment", "talent acquisition", "customer support", "project management", "product management"] },
  { group: "soft", terms: ["stakeholder management", "stakeholder communication", "problem solving", "analytical thinking", "critical thinking", "time management", "presentation skills", "communication", "leadership", "teamwork", "collaboration", "mentoring", "negotiation"] },
];
const EDUCATION_LEVELS = ["none", "high_school", "diploma", "associate", "bachelor", "master", "phd"];

function splitSourceLines(text) {
  const rows = [];
  let section = "must";
  for (const raw of String(text || "").split(/\r?\n/)) {
    const line = raw.replace(/^\s*[-*•]\s*/, "").trim();
    if (!line) continue;
    if (PREFERRED_HEADINGS.test(line)) { section = "nice"; continue; }
    if (SECTION_HEADINGS.test(line)) { section = "must"; continue; }
    if (line.length < 5) continue;
    rows.push({ id: "J" + String(rows.length + 1).padStart(2, "0"), section, text: line.slice(0, 400), origin: "source" });
    if (rows.length >= 80) break;
  }
  if (!rows.length) {
    for (const part of String(text || "").split(/[.!?]\s+/).slice(0, 60)) {
      if (part.trim().length >= 8) rows.push({ id: "J" + String(rows.length + 1).padStart(2, "0"), section: "must", text: part.trim().slice(0, 400), origin: "source" });
    }
  }
  return rows;
}

function inferTitle(text) {
  const lines = String(text || "").split(/\r?\n/).map((line) => line.replace(/^\s*[-*•#]+\s*/, "").trim()).filter(Boolean);
  for (const line of lines.slice(0, 5)) {
    const labelled = /^(?:job\s*)?title\s*[:-]\s*(.+)$/i.exec(line);
    if (labelled) return labelled[1].slice(0, 120);
    if (line.length >= 4 && line.length <= 90 && !/^(job description|about the role|responsibilities|requirements|qualifications|what you'll do|what you need)$/i.test(line)) return line;
  }
  return null;
}

function inferEducationLevel(text) {
  if (/\b(?:ph\.?d\.?|doctorate|doctoral degree)\b/i.test(text)) return "phd";
  if (/\b(?:master'?s?|M\.?Sc|M\.?Tech|MBA|MCA|postgraduate)\b/i.test(text)) return "master";
  if (/\b(?:bachelor'?s?|B\.?Sc|B\.?Tech|B\.?E\.?|BCA|B\.?Com|undergraduate degree)\b/i.test(text)) return "bachelor";
  if (/\b(?:associate'?s? degree)\b/i.test(text)) return "associate";
  if (/\b(?:diploma|higher national diploma)\b/i.test(text)) return "diploma";
  if (/\b(?:high school|secondary school|12th grade|class XII|A-levels|GCSE)\b/i.test(text)) return "high_school";
  return "none";
}

function includesRuleToken(haystack, token) {
  const value = String(haystack || "").toLowerCase();
  const term = String(token || "").toLowerCase();
  if (!term) return false;
  if (term.length <= 3 && /^[a-z0-9+#]+$/.test(term)) {
    const normalized = " " + value.replace(/[^a-z0-9+#]+/g, " ") + " ";
    return normalized.includes(" " + term + " ");
  }
  return value.includes(term);
}

function classifyRubricLine(text) {
  const value = String(text || "");
  if (/\b(?:certification|certified|licen[cs]e|PMP|CISSP|CISA|CPA|CFA|ITIL|CompTIA)\b/i.test(value)) {
    return [{ label: value.slice(0, 120), type: "certification", group: "other" }];
  }
  const found = [];
  const seen = new Set();
  for (const entry of SKILL_GROUPS) {
    for (const term of entry.terms) {
      if (includesRuleToken(value, term) && !seen.has(term.toLowerCase())) {
        found.push({ label: term, type: "skill", group: entry.group });
        seen.add(term.toLowerCase());
      }
    }
  }
  return found;
}

/**
 * Deterministic compatibility fallback for older local AI APIs whose model
 * schema cannot compile a rubric. Every criterion is copied from a source JD
 * line; no AI-generated requirement is invented.
 */
export function buildSourceGroundedRubric(jdText) {
  const text = String(jdText || "").trim();
  if (text.length < 15) throw new Error("Paste a job description with at least 15 characters to build a rubric.");
  if (text.length > 60000) throw new Error("Job description exceeds the 60,000 character limit.");

  const lines = splitSourceLines(text);
  const title = inferTitle(text);
  const candidates = [];
  const seen = new Set();
  let educationLevel = "none";
  let educationSource = null;
  const rank = Object.fromEntries(EDUCATION_LEVELS.map((level, index) => [level, index]));

  for (const line of lines) {
    const value = line.text.trim();
    if ((title && value.toLowerCase() === title.toLowerCase()) || EXCLUDED_PREFIX.test(value)) continue;
    if (line.section !== "nice") {
      const level = inferEducationLevel(value);
      if (rank[level] > rank[educationLevel]) {
        educationLevel = level;
        educationSource = line.id;
      }
      if (level !== "none") continue;
    }
    if (EXPERIENCE_YEARS.test(value)) continue;

    const classified = classifyRubricLine(value);
    if (classified.length) {
      for (const item of classified) {
        const key = item.label.toLowerCase();
        if (seen.has(key)) continue;
        seen.add(key);
        candidates.push({
          label: item.label.slice(0, 120),
          source_line: line.id,
          type: item.type,
          group: item.group,
          importance: line.section === "nice" ? "nice" : "must",
          weight: line.section === "nice" ? 1 : /\b(?:critical|mandatory|must[- ]have|essential)\b/i.test(value) ? 3 : 2,
          aliases: [],
        });
      }
      continue;
    }

    const actionable = /\b(?:experience|knowledge|ability|proficien|familiar|responsible|build|develop|design|implement|manage|lead|maintain|support|deliver|coordinate|analy[sz]e|create|optimi[sz]e|ensure|oversee|degree|diploma|communication|leadership|teamwork|collaborat)\b/i.test(value);
    if (!actionable || value.length < 8) continue;
    const key = value.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
    if (!key || seen.has(key)) continue;
    seen.add(key);
    const type = /\b(?:certification|certified|licen[cs]e)\b/i.test(value) ? "certification"
      : /\b(?:communication|leadership|teamwork|collaborat|stakeholder|problem.solving)\b/i.test(value) ? "skill" : "other";
    candidates.push({
      label: value.slice(0, 120),
      source_line: line.id,
      type,
      group: type === "skill" ? "soft" : "other",
      importance: line.section === "nice" ? "nice" : "must",
      weight: line.section === "nice" ? 1 : /\b(?:critical|mandatory|must[- ]have|essential)\b/i.test(value) ? 3 : 2,
      aliases: [],
    });
  }

  const yearsMatch = text.match(EXPERIENCE_YEARS);
  const items = candidates.slice(0, 40).map((item, index) => ({
    id: "R" + String(index + 1).padStart(2, "0"),
    ...item,
    min_years: null,
    source_text: lines.find((line) => line.id === item.source_line)?.text || null,
  }));
  const hasExperience = Boolean(yearsMatch);
  const hasEducation = educationLevel !== "none";
  if (!items.length && !hasExperience && !hasEducation) {
    throw new Error("The JD did not contain clear job-related requirements. Add required skills, responsibilities, experience or education and retry.");
  }

  return {
    rubric_id: null,
    rubric_hash: null,
    job_ref: null,
    title,
    weights: { required_skills: 50, experience: 25, preferred_skills: 15, education: 10 },
    required_years: yearsMatch ? Math.max(0, Math.min(40, Number(yearsMatch[1]))) : null,
    education: {
      min_level: educationLevel,
      equivalent_experience_ok: /equivalent experience|or equivalent/i.test(text),
      source_line: educationSource,
    },
    items,
    job_lines: lines,
    created_at: null,
  };
}

export function isExtraInputValidationError(error) {
  const detail = error?.response?.data?.detail;
  if (Array.isArray(detail)) {
    return detail.some((item) => (
      item?.type === "extra_forbidden"
      || /extra inputs are not permitted/i.test(String(item?.msg || ""))
    ));
  }
  const message = typeof detail === "string"
    ? detail
    : detail && typeof detail === "object"
      ? JSON.stringify(detail)
      : String(error?.message || "");
  return /extra inputs are not permitted/i.test(message);
}
