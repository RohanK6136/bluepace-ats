import assert from "node:assert/strict";
import { mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { after, before, test } from "node:test";
import { createStaticServer } from "./server.mjs";
import { assessResumeLocally, buildLocalRubric } from "./src/aiLocalFallbacks.mjs";

let temporaryDirectory;
let server;
let origin;

before(async () => {
  temporaryDirectory = await mkdtemp(join(tmpdir(), "bluepace-frontend-server-"));
  await mkdir(join(temporaryDirectory, "assets"));
  await writeFile(join(temporaryDirectory, "index.html"), "<!doctype html><title>BluePace Test</title>");
  await writeFile(join(temporaryDirectory, "assets", "index-abc123.js"), "console.log('ok')");

  server = createStaticServer({ distDir: temporaryDirectory });
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  origin = `http://127.0.0.1:${server.address().port}`;
});

after(async () => {
  if (server?.listening) {
    await new Promise((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
  }
  if (temporaryDirectory) await rm(temporaryDirectory, { recursive: true, force: true });
});

test("serves the entry document without caching it long-term", async () => {
  const response = await fetch(origin);
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type"), /text\/html/);
  assert.equal(response.headers.get("cache-control"), "no-cache");
  assert.match(await response.text(), /BluePace Test/);
});

test("falls back to the entry document for client-side routes", async () => {
  const response = await fetch(`${origin}/jobs/42`);
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type"), /text\/html/);
  assert.match(await response.text(), /BluePace Test/);
});

test("serves hashed assets with JavaScript content type and immutable caching", async () => {
  const response = await fetch(`${origin}/assets/index-abc123.js`);
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type"), /javascript/);
  assert.match(response.headers.get("cache-control"), /immutable/);
  assert.equal(await response.text(), "console.log('ok')");
});

test("returns a real 404 for missing assets instead of the SPA HTML", async () => {
  const response = await fetch(`${origin}/assets/missing-chunk.js`);
  assert.equal(response.status, 404);
  assert.doesNotMatch(response.headers.get("content-type") || "", /javascript|html/);
});

test("supports HEAD without returning a body", async () => {
  const response = await fetch(origin, { method: "HEAD" });
  assert.equal(response.status, 200);
  assert.equal(await response.text(), "");
});

test("rejects unsupported HTTP methods", async () => {
  const response = await fetch(origin, { method: "POST" });
  assert.equal(response.status, 405);
  assert.equal(response.headers.get("allow"), "GET, HEAD");
});

test("fails healthfully when the production build entry point is missing", async () => {
  const emptyDist = join(temporaryDirectory, "empty-dist");
  await mkdir(emptyDist);
  const emptyServer = createStaticServer({ distDir: emptyDist });
  await new Promise((resolve, reject) => {
    emptyServer.once("error", reject);
    emptyServer.listen(0, "127.0.0.1", resolve);
  });

  try {
    const response = await fetch(`http://127.0.0.1:${emptyServer.address().port}/`);
    assert.equal(response.status, 503);
    assert.match(await response.text(), /build artifacts are unavailable/);
  } finally {
    await new Promise((resolve, reject) => {
      emptyServer.close((error) => error ? reject(error) : resolve());
    });
  }
});


test("Vercel config sets security headers and safe cache policies", async () => {
  const configText = await readFile(new URL("./vercel.json", import.meta.url), "utf8");
  const config = JSON.parse(configText);
  assert.ok(Array.isArray(config.headers));

  const headerValue = (source, name) => {
    const rule = config.headers.find((item) => item.source === source);
    assert.ok(rule, `missing Vercel header rule for ${source}`);
    const header = rule.headers.find((item) => item.key.toLowerCase() === name.toLowerCase());
    assert.ok(header, `missing ${name} header for ${source}`);
    return header.value;
  };

  assert.match(headerValue("/(.*)", "Strict-Transport-Security"), /max-age=31536000/);
  assert.equal(headerValue("/(.*)", "X-Content-Type-Options"), "nosniff");
  assert.equal(headerValue("/(.*)", "X-Frame-Options"), "DENY");
  assert.equal(headerValue("/(.*)", "Referrer-Policy"), "strict-origin-when-cross-origin");
  assert.match(headerValue("/(.*)", "Permissions-Policy"), /camera=\(\)/);
  assert.match(headerValue("/(.*)", "Permissions-Policy"), /microphone=\(\)/);
  assert.match(headerValue("/(.*)", "Permissions-Policy"), /geolocation=\(\)/);
  assert.match(headerValue("/", "Cache-Control"), /max-age=0.*must-revalidate/);
  assert.match(headerValue("/assets/(.*)", "Cache-Control"), /max-age=31536000.*immutable/);
});


test("local fallback creates a transparent, weighted rubric without an AI provider", () => {
  const rubric = buildLocalRubric(
    "We need a Python and FastAPI engineer to build REST API integrations. Strong communication and teamwork are useful. Minimum 3 years of experience.",
    "Backend Engineer",
  );

  assert.equal(rubric.generation_mode, "local_rule_based_fallback");
  assert.match(rubric.rubric_summary, /not AI-generated/i);
  assert.equal(rubric.criteria.length, 3);
  assert.equal(rubric.criteria.reduce((total, criterion) => total + criterion.weight, 0), 100);
  assert.equal(rubric.minimum_years_overall, 3);
  assert.ok(rubric.criteria[0].keywords.some((keyword) => /python/i.test(keyword)));
  assert.ok(rubric.criteria[0].keywords.some((keyword) => /fastapi/i.test(keyword)));
});

test("local fallback resume assessment reports keyword evidence and omits direct identifiers", () => {
  const rubric = buildLocalRubric(
    "Python and FastAPI experience is required. REST API integrations and communication are useful.",
    "Backend Engineer",
  );
  const assessment = assessResumeLocally({
    name: "Example Candidate",
    email: "candidate@example.com",
    phone: "+44 7700 900123",
    skills: ["Python", "FastAPI"],
    experience: [{ description: "Built Python services and REST API integrations with FastAPI." }],
    summary: "Worked with a product team.",
  }, rubric);

  assert.equal(assessment.analysis_mode, "local_keyword_fallback");
  assert.equal(assessment.decision_support_only, true);
  assert.match(assessment.recommendation, /Human review required/i);
  assert.match(assessment.summary, /not an AI assessment/i);
  assert.ok(assessment.overall_score > 0);
  assert.ok(assessment.criteria[0].evidence.some((term) => /python/i.test(term)));
  assert.doesNotMatch(JSON.stringify(assessment), /Example Candidate|candidate@example\.com|7700 900123/i);
});

test("local rubric fallback validates short job descriptions", () => {
  assert.throws(() => buildLocalRubric("short"), /Enter a job description/);
});
