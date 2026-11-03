/**
 * Public job posting is intentionally disabled.
 *
 * Roles must be created and approved by an authenticated recruiter in the ATS.
 * This component remains as a no-op so any legacy import cannot expose the
 * unauthenticated "Hiring team / Post an open role" form on the careers portal.
 */
export default function PublicJobPostForm() {
  return null;
}
