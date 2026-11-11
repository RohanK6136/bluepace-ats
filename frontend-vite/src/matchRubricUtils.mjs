/**
 * The hosted stateless API returns a frozen rubric directly, while the local
 * Python API returns a RubricDraft wrapper containing an unsaved rubric.
 * Normalize both contracts before the explicit immutable-save request.
 */
export function unwrapRubricDraft(responseData) {
  const rubric = responseData?.rubric || responseData;
  const hasExperienceRequirement = rubric?.required_years !== null && rubric?.required_years !== undefined;
  const hasEducationRequirement = Boolean(rubric?.education?.min_level && rubric.education.min_level !== "none");
  if (!rubric || !Array.isArray(rubric.items)
      || (!rubric.items.length && !hasExperienceRequirement && !hasEducationRequirement)) {
    throw new Error("The match rubric could not be generated. Check that the original JD contains clear requirements and qualifications.");
  }
  return rubric;
}
