import aiFeatureApiHandler from "./[...path].js";

// Keep the provider test addressable independently of the catch-all rewrite.
// The shared handler owns credential validation, provider invocation and redaction.
export const config = { api: { bodyParser: false }, maxDuration: 60 };

export default async function testHandler(req, res) {
  req.query = { ...(req.query || {}), path: ["test"] };
  return aiFeatureApiHandler(req, res);
}
