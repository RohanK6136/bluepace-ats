import aiFeatureApiHandler from "../../[...path].js";

/**
 * Explicit Vercel function for JD file uploads.
 *
 * Keep this nested multipart route addressable even when Vercel does not
 * register the generic api/v1 catch-all on a deployment. The shared handler
 * owns upload parsing, validation, extraction, and JD generation.
 */
export const config = { api: { bodyParser: false }, maxDuration: 60 };

export default function jdGenerateUploadHandler(req, res) {
  req.query = { ...(req.query || {}), path: ["jd", "generate", "upload"] };
  return aiFeatureApiHandler(req, res);
}
