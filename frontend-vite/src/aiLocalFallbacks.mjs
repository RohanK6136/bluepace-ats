const STOP_WORDS = new Set([
  "about", "above", "across", "after", "along", "also", "and", "any", "are", "around",
  "because", "been", "before", "being", "below", "between", "both", "candidate", "can",
  "company", "could", "description", "details", "each", "etc", "for", "from", "good",
  "have", "having", "into", "its", "job", "least", "like", "must", "need", "needed",
  "other", "our", "over", "role", "should", "such", "than", "that", "the", "their",
  "them", "then", "there", "these", "they", "this", "those", "through", "under", "using",
  "various", "very", "want", "were", "what", "when", "where", "which", "while", "will",
  "with", "within", "work", "working", "would", "you", "your", "years", "year",
]);
const SKILL_TERMS = [
  "Python", "JavaScript", "TypeScript", "React", "Node.js", "FastAPI", "Django", "Flask",
  "Java", "C++", "C#", "SQL", "PostgreSQL", "MySQL", "MongoDB", "Redis", "AWS", "Azure",
  "Google Cloud", "Docker", "Kubernetes", "Terraform", "Linux", "Git", "REST API", "GraphQL",
  "HTML", "CSS", "Tailwind", "Vite", "pytest", "Jest", "Playwright", "Selenium", "Pandas",
  "NumPy", "Power BI", "Tableau", "Excel", "data analysis", "machine learning", "deep learning",
  "large language models", "LLM", "prompt engineering", "natural language processing", "NLP",
  "cybersecurity", "networking", "accounting", "customer service", "Salesforce", "Zoho",
  "project management", "Agile", "Scrum", "stakeholder management", "communication", "leadership",
  "marketing", "SEO", "paid advertising", "recruitment", "applicant tracking system", "ATS",
  "business analysis", "requirements gathering", "financial analysis", "risk management",
  "compliance", "quality assurance", "testing", "CI/CD", "API integration", "data engineering",
  "statistical analysis", "sales", "product design", "Figma", "user research", "accessibility",
];
const COLLABORATION_TERMS = [
  "communication", "collaboration", "stakeholder", "teamwork", "leadership", "presentation",
  "cross-functional", "customer", "problem-solving", "prioritization", "documentation",
];
const PRIVATE_KEYS = new Set([
  "name", "fullname", "firstname", "middlename", "lastname", "givenname", "familyname",
  "candidatename", "displayname", "email", "emailaddress", "personalemail", "phone",
  "phonenumber", "mobile", "mobilenumber", "contactnumber", "address", "homeaddress",
  "streetaddress", "postaladdress", "postcode", "zipcode", "postalcode", "dateofbirth",
  "dob", "birthdate", "age", "ageyears", "gender", "sex", "nationality", "citizenship",
  "nationalorigin", "race", "ethnicity", "religion", "disability", "maritalstatus",
  "familystatus", "photograph", "photo", "profilepicture", "headshot", "personalinfo",
  "personalinformation", "personaldetails", "contactdetails", "contactinformation",
  "currentlocation", "homelocation",
]);

function keyToken(value) {
  return String(value ?? "").toLowerCase().replace(/[^a-z0-9]/g, "");
}

function escapeRegex(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function includesTerm(text, term) {
  const cleanTerm = String(term ?? "").trim();
  if (!cleanTerm) return false;
  const pattern = new RegExp("(^|[^a-z0-9])" + escapeRegex(cleanTerm) + "(?=$|[^a-z0-9])", "i");
  return pattern.test(String(text ?? ""));
}

function commonTerms(text, limit = 12) {
  const counts = new Map();
  const tokens = String(text ?? "").toLowerCase().match(/[a-z][a-z0-9+#.-]{2,}/g) || [];
  for (const token of tokens) {
    const normalized = token.replace(/^[^a-z0-9]+|[^a-z0-9+#.-]+$/g, "");
    if (normalized.length < 3 || STOP_WORDS.has(normalized) || /^\d+$/.test(normalized)) continue;
    counts.set(normalized, (counts.get(normalized) || 0) + 1);
  }
  return [...counts.entries()]
    .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
    .slice(0, limit)
    .map(([term]) => term);
}

function uniqueTerms(values, limit = 20) {
  const result = [];
  const seen = new Set();
  for (const value of values) {
    const term = String(value ?? "").trim();
    const token = term.toLowerCase();
    if (!term || seen.has(token)) continue;
    seen.add(token);
    result.push(term);
    if (result.length >= limit) break;
  }
  return result;
}

export function buildLocalRubric(jobDescription, jobTitle = "") {
  const source = String(jobDescription ?? "").trim();
  if (source.length < 10) throw new Error("Enter a job description before building a rubric.");
  const roleTerms = commonTerms(source, 18);
  const detectedSkills = SKILL_TERMS.filter((term) => includesTerm(source, term));
  const skillTerms = uniqueTerms(detectedSkills.length ? detectedSkills : roleTerms, 15);
  const responsibilityTerms = uniqueTerms(
    roleTerms.filter((term) => !skillTerms.some((skill) => skill.toLowerCase() === term.toLowerCase())),
    10,
  );
  if (!responsibilityTerms.length) responsibilityTerms.push(...skillTerms.slice(0, 6));
  const detectedCollaboration = COLLABORATION_TERMS.filter((term) => includesTerm(source, term));
  const collaborationTerms = uniqueTerms(
    detectedCollaboration.length ? detectedCollaboration : ["communication", "collaboration", "teamwork"],
    8,
  );

  const criteria = [
    {
      name: "Role-specific skills and tools",
      category: "Skills",
      required: true,
      weight: 40,
      minimum_years: null,
      keywords: skillTerms,
      description: "Check for explicit evidence of the skills and tools identified in the supplied job description.",
      scoring_guide: {
        missing: "No matching terms found in the extracted resume text; this does not prove the skill is absent.",
        partial: "Some relevant terms appear; a recruiter should inspect context and depth.",
        strong: "Most listed terms appear with context that a recruiter can verify.",
      },
    },
    {
      name: "Core responsibilities and role knowledge",
      category: "Experience",
      required: true,
      weight: 35,
      minimum_years: null,
      keywords: responsibilityTerms,
      description: "Check for resume text related to the role-specific responsibilities and domain terms.",
      scoring_guide: {
        missing: "No matching terms found; review the original resume and equivalent wording.",
        partial: "Some relevant terms appear; confirm responsibilities and outcomes manually.",
        strong: "Many relevant terms appear; verify scope, ownership and outcomes manually.",
      },
    },
    {
      name: "Communication and collaboration evidence",
      category: "Work style",
      required: false,
      weight: 25,
      minimum_years: null,
      keywords: collaborationTerms,
      description: "Look for evidence related to communication, teamwork and collaboration; do not infer ability from missing keywords alone.",
      scoring_guide: {
        missing: "No explicit matching terms found; ask a consistent follow-up question.",
        partial: "Some relevant terms appear; verify with structured interview evidence.",
        strong: "Relevant terms appear; confirm the examples and impact in an interview.",
      },
    },
  ];
  const experienceMatch = source.match(/\b(\d+(?:\.\d+)?)\s*(?:\+|plus)?\s*(?:years?|yrs?)\b/i);
  const title = String(jobTitle || "").trim();
  return {
    title: title ? title + " — assessment rubric (local draft)" : "Assessment rubric (local draft)",
    rubric_summary: "Local keyword-based starting template derived from the supplied job description. It is not AI-generated and must be reviewed and edited before use.",
    criteria,
    total_weight: 100,
    minimum_years_overall: experienceMatch ? Number(experienceMatch[1]) : null,
    education_minimum: "",
    equivalent_experience_accepted: true,
    generation_mode: "local_rule_based_fallback",
  };
}

function safeResumeText(value, key = "") {
  if (PRIVATE_KEYS.has(keyToken(key))) return "";
  if (Array.isArray(value)) return value.map((item) => safeResumeText(item)).filter(Boolean).join(" ");
  if (value && typeof value === "object") {
    return Object.entries(value)
      .map(([childKey, childValue]) => safeResumeText(childValue, childKey))
      .filter(Boolean)
      .join(" ");
  }
  return typeof value === "string" || typeof value === "number" ? String(value) : "";
}

export function assessResumeLocally(resumeData, rubric) {
  const safeText = safeResumeText(resumeData).replace(/\s+/g, " ").trim();
  const rubricCriteria = Array.isArray(rubric?.criteria) ? rubric.criteria : [];
  if (!rubricCriteria.length) throw new Error("A rubric with criteria is required for local resume evidence matching.");
  const criteria = rubricCriteria.map((criterion) => {
    const keywords = uniqueTerms(Array.isArray(criterion?.keywords) ? criterion.keywords : [], 100);
    const matched = keywords.filter((term) => includesTerm(safeText, term));
    const weight = Math.max(0, Math.min(100, Number(criterion?.weight) || 0));
    const score = keywords.length ? Math.round((matched.length / keywords.length) * 100) : 0;
    const weightedScore = Number((score * weight / 100).toFixed(2));
    return {
      name: String(criterion?.name || "Criterion"),
      score,
      weight,
      weighted_score: weightedScore,
      assessment: keywords.length
        ? matched.length
          ? "Keyword evidence found for " + matched.length + " of " + keywords.length + " rubric terms. A recruiter must verify context and equivalent wording."
          : "No configured rubric keywords were found in the extracted resume text. This is not proof the candidate lacks the skill; review the original resume."
        : "No keywords are configured for this criterion; assess it manually.",
      evidence: matched,
      gap: keywords.length - matched.length
        ? (keywords.length - matched.length) + " rubric term(s) not found by exact keyword matching. Equivalent wording may be missed."
        : "Matching terms were found; verify the actual examples and impact manually.",
    };
  });
  const weightTotal = criteria.reduce((sum, criterion) => sum + criterion.weight, 0);
  const overallScore = Math.max(0, Math.min(100, Math.round(
    weightTotal ? criteria.reduce((sum, criterion) => sum + criterion.weighted_score, 0) * 100 / weightTotal : 0,
  )));
  const strengths = criteria.filter((criterion) => criterion.evidence.length).map((criterion) => criterion.name);
  const concerns = criteria.filter((criterion) => !criterion.evidence.length).map((criterion) => criterion.name);
  return {
    overall_score: overallScore,
    recommendation: "Human review required — local keyword evidence only",
    summary: "This is a local text-match summary, not an AI assessment or a judgement of candidate ability. Exact keyword matching can miss equivalent experience and context.",
    strengths,
    concerns,
    missing_requirements: concerns,
    criteria,
    decision_support_only: true,
    analysis_mode: "local_keyword_fallback",
  };
}
