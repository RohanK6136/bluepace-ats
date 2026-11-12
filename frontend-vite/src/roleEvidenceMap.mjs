const asList = (value) => Array.isArray(value) ? value : [];
const clean = (value) => String(value ?? "").trim();
const unique = (values) => [...new Set(values.map(clean).filter(Boolean))];

function sourceLinesFor(item) {
  return unique(asList(item?.sources).flatMap((source) => asList(source?.source_lines).map(String)));
}

/**
 * Convert the existing fit-analysis response into a recruiter-review map.
 * "Not located" is deliberately distinct from "candidate does not have".
 */
export function buildRoleEvidenceMap(analysis) {
  if (!analysis || typeof analysis !== "object") {
    return { requirements: [], followUpQuestions: [], coverage: { supported: 0, total: 0, percent: 0 }, experience: null, education: null };
  }

  const evidence = analysis.match_evidence || {};
  const requiredEvidence = asList(evidence.required_skills);
  const located = unique([
    ...asList(analysis.required_skills_met),
    ...asList(analysis.mandatory_skills_met),
    ...requiredEvidence.filter((item) => item?.evidenced).map((item) => item.skill),
  ]);
  const needsReview = unique([
    ...asList(analysis.mandatory_skills_missed),
    ...asList(analysis.missing_skills),
    ...asList(analysis.skill_gaps),
    ...asList(analysis.gaps),
  ]);
  const allRequired = unique([...located, ...needsReview]);

  const requirements = allRequired.map((skill) => {
    const source = requiredEvidence.find((item) => clean(item?.skill).toLowerCase() === skill.toLowerCase());
    const projectReferences = asList(evidence.projects).filter((project) =>
      asList(project?.matched_required_skills).some((value) => clean(value).toLowerCase() === skill.toLowerCase())
    );
    const isLocated = located.some((value) => value.toLowerCase() === skill.toLowerCase()) || Boolean(source?.evidenced);
    return {
      id: skill.toLowerCase().replace(/[^a-z0-9]+/g, "-"),
      label: skill,
      status: isLocated ? "located" : "verify",
      sourceLines: sourceLinesFor(source),
      projectReferences: projectReferences.map((item) => ({
        title: clean(item.project) || "Project evidence",
        excerpt: clean(item.excerpt),
      })),
      explanation: isLocated
        ? "This requirement appears in the parsed resume skills. Review the source references and confirm depth during the conversation."
        : "This requirement was not located in the parsed resume evidence. Treat it as an unanswered question, not proof that the candidate lacks the skill.",
    };
  });

  const experienceEvidence = evidence.experience || {};
  const parsedYearsValue = experienceEvidence.parsed_years ?? analysis.experience_years ?? analysis.experience_years_estimate;
  const requiredYearsValue = experienceEvidence.required_years ?? analysis.required_experience_years;
  const parsedYears = Number.isFinite(Number(parsedYearsValue)) ? Number(parsedYearsValue) : null;
  const requiredYears = Number.isFinite(Number(requiredYearsValue)) ? Number(requiredYearsValue) : null;
  const experience = parsedYears === null && requiredYears === null
    ? null
    : {
        parsedYears,
        requiredYears,
        status: parsedYears === null ? "verify" : requiredYears === null || parsedYears >= requiredYears ? "located" : "verify",
        explanation: parsedYears === null
          ? "Work-history dates could not be reliably summarised from the parsed profile."
          : "Check overlapping dates, relevance of the roles, and whether the parsed total reflects the experience required for this position.",
      };

  const educationEvidence = evidence.education || {};
  const hasEducation = asList(educationEvidence.resume_fields).includes("education")
    || Boolean(clean(analysis.highest_education))
    || asList(analysis.extracted_education ?? analysis.education).length > 0;
  const educationRequirement = clean(educationEvidence.required);
  const education = educationRequirement
    ? {
        required: educationRequirement,
        status: hasEducation ? "located" : "verify",
        explanation: hasEducation
          ? "Education information is present in the parsed profile. Confirm the credential and any role-specific equivalency."
          : "The required education was not located in the extracted profile. Ask the candidate to clarify rather than assuming it is absent.",
      }
    : null;

  const followUpQuestions = requirements
    .filter((item) => item.status === "verify")
    .map((item) => "Could you describe a recent project or role where you used " + item.label + ", including your contribution and the outcome?");
  if (experience?.status === "verify") {
    followUpQuestions.push("Could you walk us through your work-history dates and the experience most relevant to this role?");
  }
  if (education?.status === "verify") {
    followUpQuestions.push("Could you clarify your relevant education or equivalent professional training for this role?");
  }

  const supported = requirements.filter((item) => item.status === "located").length;
  return {
    requirements,
    followUpQuestions,
    coverage: {
      supported,
      total: requirements.length,
      percent: requirements.length ? Math.round((supported / requirements.length) * 100) : 0,
    },
    experience,
    education,
  };
}
