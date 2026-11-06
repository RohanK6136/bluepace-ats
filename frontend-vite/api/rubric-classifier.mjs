const CATEGORY_META = Object.freeze({
  technical_skill: { label: "Technical skill", type: "skill", group: "coding" },
  cloud_platform: { label: "Cloud / platform", type: "skill", group: "cloud_tools" },
  domain_knowledge: { label: "Domain knowledge", type: "skill", group: "domain" },
  soft_skill: { label: "Professional skill", type: "skill", group: "soft" },
  experience: { label: "Experience", type: "other", group: "other" },
  education: { label: "Education", type: "other", group: "other" },
  certification: { label: "Certification / licence", type: "certification", group: "other" },
  language: { label: "Language", type: "language", group: "other" },
  responsibility: { label: "Role responsibility", type: "other", group: "other" },
  work_arrangement: { label: "Work arrangement", type: "other", group: "other" },
  work_authorization: { label: "Work authorization", type: "other", group: "other" },
  availability: { label: "Availability", type: "other", group: "other" },
  other: { label: "Other · review", type: "other", group: "other" },
  job_context: { label: "Context only", type: "other", group: "other" },
});

export const RUBRIC_CATEGORY_OPTIONS = Object.freeze(
  Object.entries(CATEGORY_META).map(([value, meta]) => ({ value, ...meta })),
);

export function getRubricCategory(category) {
  return CATEGORY_META[String(category || "")] || CATEGORY_META.other;
}

const KNOWN_SKILLS = [
  "Spring Boot", "Power BI", "PostgreSQL", "JavaScript", "TypeScript", "Node.js",
  "Next.js", "FastAPI", "Playwright", "Selenium", "Kubernetes", "Terraform",
  "MongoDB", "GraphQL", "REST APIs", "REST API", "Amazon Web Services",
  "Google Cloud", "Microsoft Azure", "C++", "C#", ".NET", "Python", "Java",
  "React", "Django", "Flask", "Docker", "AWS", "Azure", "GCP", "SQL", "MySQL",
  "Redis", "Ruby", "PHP", "Rust", "Go", "Excel", "Tableau", "Cypress", "Git",
  "Linux", "HTML", "CSS", "Figma", "Jira",
];

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function findWholeTerm(text, term) {
  const pattern = new RegExp("(^|[^A-Za-z0-9+#.])(" + escapeRegExp(term) + ")(?![A-Za-z0-9+#.])", "i");
  const match = pattern.exec(text);
  if (!match) return null;
  const start = match.index + match[1].length;
  return text.slice(start, start + match[2].length);
}

export function extractKnownSkills(value) {
  const text = String(value || "");
  const found = [];
  const seen = new Set();
  for (const term of KNOWN_SKILLS) {
    const match = findWholeTerm(text, term);
    if (!match) continue;
    const key = match.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    found.push(match);
  }
  return found;
}

export function classifyRubricCriterion(value, sourceSection = "requirements") {
  const text = String(value || "").trim();
  const normalized = text.toLowerCase();
  const section = String(sourceSection || "unlabelled").toLowerCase();
  const exactSkill = extractKnownSkills(text).some((skill) => skill.toLowerCase() === normalized);

  let category = "other";
  let confidence = "low";
  let reason = "No clear criterion category was detected; recruiter review is required.";

  if (["about_role", "company_context", "benefits", "compensation"].includes(section)) {
    category = "job_context";
    confidence = "high";
    reason = "The source heading identifies descriptive or employment-offer context, not an applicant qualification.";
  } else if (section === "work_arrangement") {
    category = "work_arrangement";
    confidence = "medium";
    reason = "The source is under a location or work-mode heading; confirm whether it should be assessed against resume evidence.";
  } else if (exactSkill && /\b(?:aws|azure|gcp|google cloud|amazon web services|microsoft azure|docker|kubernetes|terraform)\b/i.test(text)) {
    category = "cloud_platform";
    confidence = "high";
    reason = "The source contains a recognized cloud or platform technology.";
  } else if (exactSkill) {
    category = "technical_skill";
    confidence = "high";
    reason = "The source contains a recognized technical skill or tool.";
  } else if (/\b(certification|certified|licen[cs]e|licensed|pmp|cfa|cpa|security clearance)\b/i.test(normalized)) {
    category = "certification";
    confidence = "high";
    reason = "The source explicitly names a certification, licence or clearance.";
  } else if (/\b(bachelor'?s?|master'?s?|ph\.?d|doctorate|degree|diploma|b\.?tech|b\.?e\.?|b\.?sc|m\.?tech|m\.?sc|mba|high school|academic qualification)\b/i.test(normalized)) {
    category = "education";
    confidence = "high";
    reason = "The source explicitly names an education level or qualification.";
  } else if (/\b\d+(?:\.\d+)?\s*(?:\+|plus)?\s*(?:years?|yrs?|months?)\b|\b(?:relevant|professional|hands-on|commercial) experience\b/i.test(normalized)) {
    category = "experience";
    confidence = "high";
    reason = "The source explicitly describes a duration or type of experience.";
  } else if (/\b(english|hindi|spanish|french|german|mandarin|chinese|arabic|japanese|korean|portuguese|bengali|telugu|tamil|marathi|language|bilingual|fluent|fluency)\b/i.test(normalized)) {
    category = "language";
    confidence = "high";
    reason = "The source names a language or language-proficiency requirement.";
  } else if (/\b(visa|work authorization|right to work|work permit|sponsorship|citizenship|security clearance)\b/i.test(normalized)) {
    category = "work_authorization";
    confidence = "high";
    reason = "The source explicitly refers to work eligibility or authorization.";
  } else if (/\b(remote|hybrid|on[- ]site|onsite|relocat(e|ion)|based in|located in|commute)\b/i.test(normalized)) {
    category = "work_arrangement";
    confidence = "high";
    reason = "The source specifies a location or work-arrangement condition.";
  } else if (/\b(shift|night|weekend|rotational|availability|weekdays|on call|on-call)\b/i.test(normalized)) {
    category = "availability";
    confidence = "high";
    reason = "The source specifies working hours, shifts or availability.";
  } else if (/\b(communication|collaboration|leadership|problem.solving|stakeholder management|negotiation|presentation|adaptability|interpersonal|teamwork|critical thinking)\b/i.test(normalized)) {
    category = "soft_skill";
    confidence = "high";
    reason = "The source explicitly names a professional or interpersonal skill.";
  } else if (/\b(recruitment|talent acquisition|human resources|hr |payroll|accounting|finance|banking|healthcare|insurance|supply chain|logistics|retail|e.?commerce|customer success|sales operations)\b/i.test(normalized)) {
    category = "domain_knowledge";
    confidence = "high";
    reason = "The source explicitly names an industry or business-domain competency.";
  } else if (section === "responsibilities") {
    category = "responsibility";
    confidence = "medium";
    reason = "The source appears under the responsibilities heading; confirm that it is suitable as an applicant-evaluation criterion.";
  } else if (/\b(programming|software development|api|database|frontend|front.end|backend|back.end|automation|testing|data analysis|machine learning|devops|security|networking|architecture|debugging)\b/i.test(normalized)) {
    category = "technical_skill";
    confidence = "medium";
    reason = "The source uses technical-work terminology; confirm the precise skill being assessed.";
  } else if (normalized.length >= 8 && section !== "unlabelled") {
    confidence = "low";
    reason = "The source is linked to a JD section but does not match a supported category.";
  }

  return {
    category,
    category_label: CATEGORY_META[category].label,
    type: CATEGORY_META[category].type,
    group: CATEGORY_META[category].group,
    classification_confidence: confidence,
    classification_reason: reason,
    requires_review: confidence !== "high",
  };
}
