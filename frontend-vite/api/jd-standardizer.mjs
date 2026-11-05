/**
 * Deterministic JD standardization for BluePace ATS.
 * Source-grounded NLP/rules only. No model calls and no invented facts.
 */
const SECTION_RULES = [
  ["responsibilities", /^(?:(?:key\s+)?responsibilities|what\s+you(?:'|’)ll\s+do|duties|role\s+responsibilities)$/i],
  ["requirements", /^(?:(?:required\s+)?(?:qualifications?|skills?|requirements?)|must[- ]haves?|what\s+you(?:'|’)ll\s+need|what\s+you\s+bring|experience|technical\s+requirements)$/i],
  ["nice_to_have", /^(?:preferred\s+(?:skills?|qualifications?)|nice[- ]to[- ]have|bonus|desirable|preferred)$/i],
  ["offer", /^(?:what\s+we\s+offer|benefits|compensation|perks|our\s+offer)$/i],
  ["about_role", /^(?:about\s+(?:the\s+)?role|role\s+overview|job\s+summary|position\s+summary|overview)$/i],
  ["additional_info", /^(?:additional\s+information|other\s+details|schedule|working\s+arrangement)$/i],
];
const FIELD_LABELS = [
  ["title", /^(?:job\s+title|position(?:\s+title)?|role\s+title|title)$/i],
  ["role_type", /^(?:employment\s+type|job\s+type|contract\s+type|employment)$/i],
  ["location", /^(?:location|job\s+location|work\s+location|primary\s+location|based\s+in)$/i],
  ["country", /^country(?:\/region)?$/i], ["state", /^(?:state|province|region)$/i],
  ["city", /^city$/i], ["work_mode", /^(?:work\s+mode|work\s+model|work\s+arrangement|work\s+location\s+type)$/i],
  ["experience", /^(?:experience|required\s+experience|years\s+of\s+experience|experience\s+required)$/i],
  ["duration", /^(?:duration|contract\s+duration|term)$/i],
  ["salary", /^(?:salary|compensation|pay\s+range|remuneration)$/i],
  ["education", /^(?:education|educational\s+qualification|degree)$/i],
];
const SKILL_TAXONOMY = [
  ["Python", ["python", "python 3", "python3"]], ["Java", ["java"]],
  ["JavaScript", ["javascript", "js"]], ["TypeScript", ["typescript", "ts"]],
  ["C++", ["c++"]], ["C#", ["c sharp", "c#"]], ["Go", ["golang", "go language"]],
  ["Rust", ["rust"]], ["React", ["react", "react.js", "reactjs"]],
  ["Node.js", ["node.js", "nodejs", "node js"]], ["FastAPI", ["fastapi", "fast api"]],
  ["Django", ["django"]], ["Flask", ["flask"]], ["Spring Boot", ["spring boot"]],
  ["SQL", ["sql", "structured query language"]], ["PostgreSQL", ["postgresql", "postgres"]],
  ["MySQL", ["mysql"]], ["MongoDB", ["mongodb", "mongo db"]], ["Redis", ["redis"]],
  ["REST APIs", ["rest api", "rest apis", "restful api", "restful apis"]], ["GraphQL", ["graphql"]],
  ["AWS", ["aws", "amazon web services"]], ["Microsoft Azure", ["azure", "microsoft azure"]],
  ["Google Cloud", ["google cloud", "gcp", "google cloud platform"]], ["Docker", ["docker"]],
  ["Kubernetes", ["kubernetes", "k8s"]], ["Terraform", ["terraform"]], ["Linux", ["linux"]],
  ["Git", ["git"]], ["CI/CD", ["ci/cd", "continuous integration", "continuous delivery"]],
  ["Power BI", ["power bi", "powerbi"]], ["Tableau", ["tableau"]], ["Microsoft Excel", ["excel", "microsoft excel"]],
  ["Pandas", ["pandas"]], ["NumPy", ["numpy"]], ["Machine Learning", ["machine learning", "ml"]],
  ["Data Analysis", ["data analysis", "data analytics"]], ["Data Engineering", ["data engineering", "data pipelines"]],
  ["Quality Assurance", ["quality assurance", "qa testing"]], ["Selenium", ["selenium"]],
  ["Playwright", ["playwright"]], ["Jest", ["jest"]], ["pytest", ["pytest"]], ["Figma", ["figma"]],
  ["Product Design", ["product design", "ux design", "ui design"]], ["SEO", ["seo", "search engine optimization"]],
  ["Salesforce", ["salesforce"]], ["Zoho Recruit", ["zoho recruit"]],
  ["Recruitment", ["recruitment", "talent acquisition", "technical recruiting"]],
  ["Project Management", ["project management"]], ["Agile", ["agile"]], ["Scrum", ["scrum"]],
  ["Stakeholder Management", ["stakeholder management"]], ["Financial Analysis", ["financial analysis"]],
  ["Risk Management", ["risk management"]], ["Cybersecurity", ["cybersecurity", "information security"]],
  ["Networking", ["networking", "network administration"]], ["Customer Service", ["customer service", "customer support"]],
];
const JOB_FAMILIES = [
  ["software_engineering", ["software engineer", "software developer", "backend engineer", "frontend engineer", "full stack", "full-stack", "application developer", "web developer"]],
  ["data_analytics", ["data analyst", "business intelligence", "analytics", "data scientist", "data engineer", "reporting analyst"]],
  ["devops_cloud", ["devops", "platform engineer", "site reliability", "cloud engineer", "infrastructure engineer", "systems administrator"]],
  ["quality_assurance", ["qa engineer", "quality assurance", "test engineer", "automation tester", "software tester"]],
  ["product_design", ["product designer", "ux designer", "ui designer", "interaction designer", "visual designer"]],
  ["product_management", ["product manager", "product owner"]], ["project_management", ["project manager", "program manager", "delivery manager"]],
  ["human_resources", ["human resources", "hr generalist", "hr business partner", "technical recruiter", "recruiter", "talent acquisition", "learning and development"]],
  ["finance", ["accountant", "finance analyst", "financial analyst", "accounting", "payroll"]],
  ["sales", ["sales executive", "account executive", "business development", "sales manager"]],
  ["marketing", ["marketing", "content strategist", "seo specialist", "brand manager"]],
  ["customer_support", ["customer support", "customer success", "service desk", "help desk"]],
];
const STOP_TITLES = new Set(["job description", "job posting", "job vacancy", "about the company", "about blupace tech", "company profile", "untitled", "untitled role", "careers"]);
const COUNTRIES = [
  ["IN", "India", ["india"]], ["US", "United States", ["united states", "usa", "us"]],
  ["GB", "United Kingdom", ["united kingdom", "uk", "great britain"]], ["CA", "Canada", ["canada"]],
  ["AU", "Australia", ["australia"]], ["SG", "Singapore", ["singapore"]],
  ["AE", "United Arab Emirates", ["united arab emirates", "uae"]], ["DE", "Germany", ["germany"]],
  ["FR", "France", ["france"]], ["IE", "Ireland", ["ireland"]], ["NL", "Netherlands", ["netherlands", "holland"]],
  ["NZ", "New Zealand", ["new zealand"]], ["JP", "Japan", ["japan"]], ["BR", "Brazil", ["brazil"]],
];
const ROLE_TYPES = [
  ["Full-Time", /\bfull[\s-]?time\b/i], ["Part-Time", /\bpart[\s-]?time\b/i],
  ["Contract", /\bcontract(?:or)?\b|\bfixed[\s-]?term\b/i], ["Internship", /\bintern(?:ship)?\b/i],
  ["Temporary", /\btemporary\b|\btemp role\b/i], ["Freelance", /\bfreelance\b|\bindependent contractor\b/i],
];
const WORK_MODES = [
  ["remote", /\bremote\b|\bwork from home\b|\bwfh\b/i],
  ["hybrid", /\bhybrid\b/i], ["onsite", /\bon[\s-]?site\b|\bin[\s-]?office\b|\boffice[\s-]?based\b/i],
];
const SECTION_IDS = ["about_role", "responsibilities", "requirements", "nice_to_have", "offer", "additional_info"];

function norm(value) {
  return String(value ?? "").replace(/\u00a0/g, " ").replace(/[ \t]+/g, " ").trim();
}
function stripBullet(value) {
  return norm(value).replace(/^#{1,6}\s*/, "").replace(/^(?:[-*•●▪◦]+|\d+[.)])\s*/, "").trim();
}
function dedupe(values) {
  const seen = new Set();
  return values.filter((value) => {
    const key = norm(value).toLocaleLowerCase();
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}
function esc(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
function includesTerm(text, term) {
  const escaped = esc(term).replace(/\s+/g, "\\s+");
  return new RegExp("(^|[^a-z0-9])" + escaped + "(?=$|[^a-z0-9])", "i").test(String(text ?? ""));
}
function pushCandidate(map, field, value, line) {
  const normalized = norm(value);
  if (!normalized) return;
  const values = map[field] || (map[field] = []);
  if (!values.some((item) => norm(item.value).toLocaleLowerCase() === normalized.toLocaleLowerCase())) {
    values.push({ value: normalized, line: line?.id || null, quote: line?.text || normalized });
  }
}
function labelled(raw) {
  const match = /^([^:：]{2,50})\s*[:：]\s*(.*?)\s*$/.exec(raw);
  if (!match) return null;
  const label = norm(match[1]);
  const field = FIELD_LABELS.find(([, pattern]) => pattern.test(label));
  return field ? { field: field[0], value: norm(match[2]) } : null;
}
function heading(raw) {
  const value = stripBullet(raw).replace(/:$/, "").trim();
  if (!value || value.length > 65) return null;
  return SECTION_RULES.find((item) => item[1].test(value))?.[0] || null;
}
function inlineHeading(raw) {
  const cleaned = stripBullet(raw);
  const colon = cleaned.indexOf(":");
  if (colon <= 0 || colon > 50) return null;
  const section = heading(cleaned.slice(0, colon));
  const value = norm(cleaned.slice(colon + 1));
  return section ? { section, value } : null;
}
function inferSection(text) {
  if (/\b(preferred|nice to have|bonus|desirable)\b/i.test(text)) return "nice_to_have";
  if (/\b(benefits|salary|compensation|paid leave|insurance|equity|what we offer)\b/i.test(text)) return "offer";
  if (/\b(responsibilit|you will|you'll|duties|accountable for|responsible for)\b/i.test(text)) return "responsibilities";
  if (/\b(required|qualification|must have|minimum requirement|years? of experience|proficien|degree|certification)\b/i.test(text)) return "requirements";
  if (/^(build|develop|design|implement|maintain|lead|manage|deliver|support|coordinate|create|own|operate|test|monitor|review|analy[sz]e|collaborate|ensure|drive|improve)\b/i.test(text)) return "responsibilities";
  return "about_role";
}
function parseExperience(value) {
  const text = norm(value);
  const range = /(\d+(?:\.\d+)?)\s*(?:-|–|to)\s*(\d+(?:\.\d+)?)\s*(?:\+?\s*)?(?:years?|yrs?)(?:\s+of\s+(?:relevant\s+)?experience)?/i.exec(text);
  if (range) {
    const min = Number(range[1]), max = Number(range[2]);
    if (min >= 0 && max >= min && max <= 60) return { min_years: min, max_years: max, scope: /relevant/i.test(text) ? "relevant" : "unspecified" };
  }
  const minimum = /(?:minimum|min(?:imum)?\s+of|at\s+least)?\s*(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)(?:\s+of\s+(?:relevant\s+)?experience)?/i.exec(text);
  if (minimum) {
    const years = Number(minimum[1]);
    if (years >= 0 && years <= 60) return { min_years: years, max_years: null, scope: /relevant/i.test(text) ? "relevant" : "unspecified" };
  }
  return null;
}
function parseDuration(value) {
  const text = norm(value);
  const month = /(\d{1,2})\s*(?:months?|mos?)\b/i.exec(text);
  if (month && Number(month[1]) > 0 && Number(month[1]) <= 120) return Number(month[1]);
  const year = /(\d{1,2})\s*(?:years?|yrs?)\b/i.exec(text);
  if (year && Number(year[1]) > 0 && Number(year[1]) <= 10) return Number(year[1]) * 12;
  return null;
}
function matching(values, text) {
  return values.filter(([, pattern]) => pattern.test(text)).map(([value]) => value);
}
function parseLocation(value) {
  // Retain parenthetical location details such as "Bengaluru (India)".
  let text = norm(value).replace(/[()]/g, ",").replace(/[|;]/g, ",");
  const modes = matching(WORK_MODES, value);
  text = norm(text.replace(/\b(remote|hybrid|on[\s-]?site|in[\s-]?office|office[\s-]?based|work from home|wfh)\b/ig, " ")).replace(/^[,/\-]+|[,/\-]+$/g, "");
  const pieces = text.split(/\s*,\s*|\s+\/\s+|\s+\|\s+/).map(norm).filter(Boolean);
  let country = null, countryIndex = -1;
  for (let index = 0; index < pieces.length; index += 1) {
    const found = COUNTRIES.find(([, , aliases]) => aliases.includes(pieces[index].toLocaleLowerCase()));
    if (found) { country = { iso2: found[0], name: found[1] }; countryIndex = index; break; }
  }
  let city = null, state = null;
  if (pieces.length >= 2) {
    city = countryIndex === 0 ? null : pieces[0];
    if (countryIndex > 1) state = pieces[1];
  } else if (pieces.length === 1 && !country) city = pieces[0];
  return { country, city, state, work_mode: modes };
}
function roleFamily(title, text) {
  const haystack = (String(title || "") + "\n" + String(text || "")).toLocaleLowerCase();
  const matches = JOB_FAMILIES.filter(([, terms]) => terms.some((term) => haystack.includes(term)));
  if (!matches.length) return null;
  const titleMatches = JOB_FAMILIES.filter(([, terms]) => terms.some((term) => title && String(title).toLocaleLowerCase().includes(term)));
  return (titleMatches[0] || matches[0])[0];
}
function skillMatches(text) {
  return dedupe(SKILL_TAXONOMY.filter(([, aliases]) => aliases.some((alias) => includesTerm(text, alias))).map(([name]) => name));
}
function fact(candidates, transform = (value) => value) {
  const values = candidates || [];
  if (!values.length) return { value: null, status: "missing", source: null, line: null, quote: null, candidates: [] };
  if (values.length > 1) return {
    value: null, status: "conflict", source: "rules", line: null, quote: null,
    candidates: values.map((item) => ({ value: transform(item.value), line: item.line, quote: item.quote })),
  };
  const item = values[0];
  return { value: transform(item.value), status: "verified", source: "rules", line: item.line, quote: item.quote, candidates: [] };
}
function titleIsGeneric(value) {
  const text = norm(value).toLocaleLowerCase().replace(/^#+\s*/, "");
  return STOP_TITLES.has(text) || text.startsWith("about ");
}
function inferTitle(lines) {
  for (const line of lines.slice(0, 8)) {
    const item = labelled(line.raw);
    if (item?.field === "title" && item.value && !titleIsGeneric(item.value)) return { value: item.value.slice(0, 120), line: line.id, quote: line.text };
    if (line.section === "heading" || line.section === "metadata") continue;
    const candidate = stripBullet(line.text).replace(/^#{1,6}\s*/, "");
    if (candidate.length >= 4 && candidate.length <= 90 && !titleIsGeneric(candidate) && !/[.!?]$/.test(candidate)) {
      return { value: candidate.slice(0, 120), line: line.id, quote: line.text };
    }
  }
  return null;
}
function fieldCandidatesFromLocation(map, items, field) {
  for (const item of items || []) {
    const parsed = parseLocation(item.value);
    if (field === "country" && parsed.country) pushCandidate(map, field, parsed.country.name, { id: item.line, text: item.quote });
    if (field === "city" && parsed.city) pushCandidate(map, field, parsed.city, { id: item.line, text: item.quote });
    if (field === "state" && parsed.state) pushCandidate(map, field, parsed.state, { id: item.line, text: item.quote });
    if (field === "work_mode") for (const mode of parsed.work_mode) pushCandidate(map, field, mode, { id: item.line, text: item.quote });
  }
}
export function standardizeJD(input) {
  const source = String(input ?? "").replace(/\r\n?/g, "\n");
  if (source.trim().length < 15) throw Object.assign(new Error("Paste a job description with at least 15 characters."), { statusCode: 422 });
  if (source.length > 60000) throw Object.assign(new Error("Job description exceeds the 60,000 character limit."), { statusCode: 413 });

  const lines = [], candidates = {}, sectionLineRefs = Object.fromEntries(SECTION_IDS.map((key) => [key, []]));
  const content = Object.fromEntries(SECTION_IDS.map((key) => [key, []]));
  const duplicates = [];
  let activeSection = "about_role", companyIntro = false;

  const rawLines = source.split("\n");
  for (let index = 0; index < rawLines.length; index += 1) {
    const raw = norm(rawLines[index]);
    if (!raw) continue;
    const item = { id: "J" + String(lines.length + 1).padStart(2, "0"), n: index + 1, raw, text: stripBullet(raw), section: activeSection };
    const inline = inlineHeading(raw);
    const sectionHeading = inline?.section || heading(raw);
    if (sectionHeading) {
      activeSection = sectionHeading;
      lines.push({ ...item, text: raw, section: "heading" });
      if (inline?.value) {
        const inlineItem = { ...item, text: inline.value, section: activeSection };
        content[activeSection].push({ text: inlineItem.text, lines: [inlineItem.id] });
        sectionLineRefs[activeSection].push(inlineItem.id);
      }
      continue;
    }

    const label = labelled(raw);
    if (label) {
      if (["title", "role_type", "location", "country", "state", "city", "work_mode", "experience", "duration"].includes(label.field) && label.value) {
        if (label.field === "location") pushCandidate(candidates, "location", label.value, item);
        else pushCandidate(candidates, label.field, label.value, item);
      }
      if (label.field === "salary" && label.value) {
        content.offer.push({ text: item.text, lines: [item.id] });
        sectionLineRefs.offer.push(item.id);
      } else if (label.field === "education" && label.value) {
        content.requirements.push({ text: item.text, lines: [item.id] });
        sectionLineRefs.requirements.push(item.id);
      }
      const modes = label.field === "location" ? matching(WORK_MODES, label.value) : [];
      for (const mode of modes) pushCandidate(candidates, "work_mode", mode, item);
      lines.push({ ...item, section: "metadata", field: label.field });
      continue;
    }

    if (/\babout\s+(?:blupace\s+tech|the company|us)\b/i.test(raw)) companyIntro = true;
    let section = activeSection;
    if (section === "about_role") {
      const inferred = inferSection(item.text);
      if (inferred !== "about_role") section = inferred;
    }
    item.section = section;
    lines.push(item);
    if (!content[section]) continue;
    const normalized = item.text.replace(/[.!?]+$/, "").toLocaleLowerCase();
    const duplicate = content[section].find((existing) => existing.text.replace(/[.!?]+$/, "").toLocaleLowerCase() === normalized);
    if (duplicate) { duplicates.push({ section, line: item.id, duplicate_of: duplicate.lines[0], text: item.text }); continue; }
    content[section].push({ text: item.text, lines: [item.id] });
    sectionLineRefs[section].push(item.id);
    if (/\b(remote|hybrid|on[\s-]?site|in[\s-]?office|office[\s-]?based|work from home|wfh)\b/i.test(item.text)) {
      for (const mode of matching(WORK_MODES, item.text)) pushCandidate(candidates, "work_mode", mode, item);
    }
  }

  // A company overview must not be mistaken for a job title. Only an explicit
  // title field can identify a role when the source is company-profile-only.
  const title = companyIntro ? null : inferTitle(lines);
  if (title && !(candidates.title || []).length) pushCandidate(candidates, "title", title.value, title);
  const fullText = lines.map((line) => line.text).join("\n");

  if (!(candidates.role_type || []).length) {
    for (const [canonical, pattern] of ROLE_TYPES) {
      const foundLine = lines.find((line) => line.section !== "metadata" && pattern.test(line.text));
      if (foundLine) pushCandidate(candidates, "role_type", canonical, foundLine);
    }
  } else {
    candidates.role_type = candidates.role_type.map((item) => ({ ...item, value: ROLE_TYPES.find(([name, pattern]) => name.toLowerCase() === item.value.toLowerCase() || pattern.test(item.value))?.[0] || item.value }));
  }

  if (!(candidates.experience || []).length) {
    for (const line of lines) {
      // A labelled contract duration is not a candidate experience requirement.
      if (line.section === "metadata" || !/experience|years?|yrs?/i.test(line.text)) continue;
      const parsed = parseExperience(line.text);
      if (parsed) pushCandidate(candidates, "experience", String(parsed.min_years) + (parsed.max_years == null ? "+" : "-" + parsed.max_years) + " years", line);
    }
  }
  candidates.experience = (candidates.experience || []).map((item) => ({ ...item, value: parseExperience(typeof item.value === "object" ? JSON.stringify(item.value) : item.value) })).filter((item) => item.value);

  if (!(candidates.duration || []).length) {
    for (const line of lines) if (/\b(duration|contract|term)\b/i.test(line.text)) {
      const months = parseDuration(line.text);
      if (months) pushCandidate(candidates, "duration", String(months), line);
    }
  }
  candidates.duration = (candidates.duration || []).map((item) => ({ ...item, value: Number.isFinite(Number(item.value)) ? Number(item.value) : parseDuration(item.value) })).filter((item) => item.value != null);

  fieldCandidatesFromLocation(candidates, candidates.location, "country");
  fieldCandidatesFromLocation(candidates, candidates.location, "city");
  fieldCandidatesFromLocation(candidates, candidates.location, "state");
  fieldCandidatesFromLocation(candidates, candidates.location, "work_mode");
  if (candidates.work_mode) {
    candidates.work_mode = candidates.work_mode.flatMap((item) => (Array.isArray(item.value) ? item.value : matching(WORK_MODES, item.value)).map((value) => ({ ...item, value })));
  }

  const countryFact = fact(candidates.country, (value) => {
    const text = String(value).trim().toLowerCase();
    const found = COUNTRIES.find(([code, name, aliases]) =>
      code.toLowerCase() === text || name.toLowerCase() === text || aliases.includes(text)
    );
    return found ? { iso2: found[0], name: found[1] } : value;
  });
  const workModeItems = candidates.work_mode || [];
  const workModeValues = dedupe(workModeItems.flatMap((item) =>
    Array.isArray(item.value) ? item.value : [item.value]
  ));
  const workModeFact = workModeValues.length
    ? { value: workModeValues, status: "verified", source: "rules", line: workModeItems[0]?.line || null, quote: workModeItems[0]?.quote || null, candidates: [] }
    : fact([]);
  const facts = {
    title: fact(candidates.title), role_type: fact(candidates.role_type),
    country: countryFact, state: fact(candidates.state), city: fact(candidates.city),
    work_mode: workModeFact, experience: fact(candidates.experience),
    duration_months: fact(candidates.duration, Number),
  };
  const responsibilities = content.responsibilities.map((item) => item.text);
  const requirements = content.requirements.map((item) => item.text);
  const preferred = content.nice_to_have.map((item) => item.text);
  const offer = content.offer.map((item) => item.text);
  const companyProfileOnly = companyIntro && !facts.title.value && !responsibilities.length && !requirements.length;
  const about = companyProfileOnly ? [] : content.about_role.map((item) => item.text);
  const additional = content.additional_info.map((item) => item.text);
  const requiredText = lines.filter((line) => sectionLineRefs.requirements.includes(line.id)).map((line) => line.text).join("\n");
  const preferredText = lines.filter((line) => sectionLineRefs.nice_to_have.includes(line.id)).map((line) => line.text).join("\n");
  const allText = lines.map((line) => line.text).join("\n");
  const skills = { required: skillMatches(requiredText), preferred: skillMatches(preferredText), all: skillMatches(allText) };
  if (companyProfileOnly) {
    duplicates.push({ section: "company_about", line: null, duplicate_of: null, text: "Company profile supplied without role-specific content." });
  }

  const missing = [];
  const conflicts = [];
  for (const [field, item] of Object.entries(facts)) {
    if (item.status === "missing") missing.push(field.replaceAll("_", " ") + ": not stated in the supplied job description");
    if (item.status === "conflict") {
      conflicts.push({ field, candidates: item.candidates });
      missing.push(field.replaceAll("_", " ") + ": conflicting source values need recruiter confirmation");
    }
  }
  if (!responsibilities.length) missing.push("responsibilities: no role-specific responsibilities were identified");
  if (!requirements.length) missing.push("requirements: no required qualifications or skills were identified");
  if (!preferred.length) missing.push("preferred skills: not stated in the supplied job description");
  if (!offer.length) missing.push("compensation or benefits: not stated in the supplied job description");

  const flags = [];
  if (!facts.title.value) flags.push({ code: "title_missing", severity: "block", message: "A clear job title was not found. Add or confirm the role title.", lines: [] });
  if (conflicts.length) flags.push({ code: "source_conflicts", severity: "block", message: conflicts.length + " field conflict(s) need recruiter resolution.", lines: conflicts.flatMap((item) => item.candidates.map((candidate) => candidate.line).filter(Boolean)) });
  if (!responsibilities.length) flags.push({ code: "responsibilities_missing", severity: "warn", message: "No responsibilities were identified. Add role-specific duties before publishing.", lines: [] });
  if (!requirements.length) flags.push({ code: "requirements_missing", severity: "warn", message: "No mandatory qualifications or skills were identified. Add role-related criteria before creating a match rubric.", lines: [] });
  if (companyProfileOnly) flags.push({ code: "company_profile_only", severity: "warn", message: "The source appears to contain a company profile rather than a role-specific job description. Add a specific job title, responsibilities and qualifications.", lines: [] });
  if (duplicates.length) flags.push({ code: "duplicate_content", severity: "info", message: duplicates.length + " duplicate or non-role-specific source item(s) were excluded from standardized sections.", lines: duplicates.map((item) => item.line).filter(Boolean) });
  flags.push({ code: "deterministic_nlp", severity: "info", message: "Standardized with deterministic NLP, a curated skill/occupation taxonomy and source rules. No generative model was called; verify every extracted fact before publishing.", lines: [] });

  const checks = {
    title: facts.title.status === "verified", role_type: facts.role_type.status === "verified",
    location: Boolean(facts.country.value || facts.city.value || facts.work_mode.value),
    experience: facts.experience.status === "verified", responsibilities: responsibilities.length > 0,
    requirements: requirements.length > 0, preferred_skills: preferred.length > 0, benefits: offer.length > 0,
  };
  const weights = { title: 20, role_type: 10, location: 10, experience: 10, responsibilities: 20, requirements: 20, preferred_skills: 5, benefits: 5 };
  const totalWeight = Object.values(weights).reduce((sum, value) => sum + value, 0);
  const qualityScore = Math.round(Object.entries(checks).reduce((sum, entry) => sum + (entry[1] ? weights[entry[0]] : 0), 0) / totalWeight * 100);
  const summarySource = about[0] || responsibilities[0] || null;
  const shortDescription = summarySource ? summarySource.slice(0, 240) : facts.title.value ? "Role profile for " + facts.title.value + ". Review the source requirements and fill the missing details." : null;

  return {
    title: facts.title.value, category_hint: roleFamily(facts.title.value, fullText),
    role_type: facts.role_type.value,
    location: { country: facts.country.value, state: facts.state.value, city: facts.city.value, work_mode: facts.work_mode.value },
    country: facts.country.value, state: facts.state.value, city: facts.city.value, work_mode: facts.work_mode.value,
    experience: facts.experience.value || { min_years: null, max_years: null },
    duration_months: facts.duration_months.value, short_description: shortDescription,
    responsibilities, requirements, nice_to_have: preferred, offer, about_role: about, additional_info: additional,
    required_skills: skills.required, preferred_skills: skills.preferred, extracted_skills: skills.all,
    missing_information: dedupe(missing), review_flags: flags.map((item) => item.message), conflicts,
    quality: { score: qualityScore, band: qualityScore >= 85 ? "strong_source_coverage" : qualityScore >= 60 ? "partial_source_coverage" : "limited_source_coverage", checks, total_source_lines: lines.length, duplicate_items: duplicates.length, extracted_skill_count: skills.all.length },
    source_lines: lines.map((line) => ({ id: line.id, line: line.n, text: line.text, section: line.section })),
    source_line_refs: sectionLineRefs, field_evidence: facts, source_mode: "deterministic",
  };
}
