import matchApiHandler from "../[...path].js";

/**
 * Explicit Vercel route for the Applicant Match rubric endpoint.
 *
 * Keep this endpoint addressable even on deployments where the nested
 * catch-all function is not registered by the Vercel build. The shared
 * handler still owns validation, deterministic rubric generation, and
 * saved-rubric storage behaviour.
 */
export const config = { api: { bodyParser: false }, maxDuration: 60 };

export default function rubricsHandler(req, res) {
  req.query = { ...(req.query || {}), path: ["match", "rubrics"] };
  return matchApiHandler(req, res);
}
