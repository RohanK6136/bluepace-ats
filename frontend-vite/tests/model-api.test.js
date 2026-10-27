import assert from "node:assert/strict";
import { test } from "node:test";
import handler from "../api/v1/[...path].js";
import { onRequest as pagesFunction } from "../functions/v1/[[path]].js";

function invoke(headers = {}, method = "GET", pathParts = ["models"], body = "") {
  const req = {
    method,
    url: "/api/v1/" + pathParts.join("/"),
    headers,
    query: { path: pathParts },
    async *[Symbol.asyncIterator]() {
      if (body) yield Buffer.from(body);
    },
  };
  const res = {
    statusCode: 200,
    headers: {},
    body: "",
    setHeader(name, value) { this.headers[name.toLowerCase()] = value; },
    end(value = "") { this.body = value; },
  };
  return Promise.resolve(handler(req, res)).then(() => ({
    statusCode: res.statusCode,
    headers: res.headers,
    body: JSON.parse(res.body || "null"),
  }));
}

test("model registry reports hosted profiles as disabled without session keys", async () => {
  const response = await invoke({ host: "ats.vercel.app" });
  assert.equal(response.statusCode, 200);
  assert.equal(response.headers["cache-control"], "no-store");
  assert.ok(response.body.some((row) => row.id === "openrouter" && row.enabled === false));
  assert.ok(response.body.some((row) => row.id === "gemini" && row.enabled === false));
  assert.ok(response.body.some((row) => row.id === "deepseek" && row.enabled === false));
  assert.ok(response.body.some((row) => row.id === "grok" && row.enabled === false));
});

test("model registry enables OpenRouter when the session key is supplied", async () => {
  const response = await invoke({ host: "ats.vercel.app", "x-openrouter-api-key": "test-key-not-used-in-this-test" });
  const openrouter = response.body.find((row) => row.id === "openrouter");
  assert.equal(response.statusCode, 200);
  assert.equal(openrouter.enabled, true);
  assert.equal(openrouter.is_default, true);
});

test("retired GitHub Models API remains visibly disabled", async () => {
  const response = await invoke({ host: "ats.vercel.app", "x-github-models-api-key": "unused" });
  const profile = response.body.find((row) => row.id === "github-models");
  assert.equal(profile.enabled, false);
  assert.match(profile.disabled_reason, /retired/i);
});
test("one OpenRouter key enables Gemini, DeepSeek, Grok, and OpenAI profile choices", async () => {
  const response = await invoke({ host: "ats.vercel.app", "x-openrouter-api-key": "test-key-not-used-in-this-test" });
  const byId = Object.fromEntries(response.body.map((row) => [row.id, row]));
  assert.equal(byId.gemini.enabled, true);
  assert.equal(byId.gemini.model, "google/gemini-3.8-flash");
  assert.equal(byId.deepseek.enabled, true);
  assert.equal(byId.deepseek.model, "deepseek/deepseek-v4.1-flash-1017");
  assert.equal(byId.grok.enabled, true);
  assert.equal(byId.grok.model, "x-ai/grok-4.7");
  assert.equal(byId.openai.enabled, true);
  assert.equal(byId.openai.model, "openai/gpt-5.4");
});
test("Vercel environment credentials also enable provider choices without browser keys", async () => {
  const previousOpenRouter = process.env.OPENROUTER_API_KEY;
  const previousGoogle = process.env.GOOGLE_API_KEY;
  try {
    process.env.OPENROUTER_API_KEY = "test-env-openrouter-key";
    delete process.env.GOOGLE_API_KEY;
    const routed = await invoke({ host: "ats.vercel.app" });
    const byId = Object.fromEntries(routed.body.map((row) => [row.id, row]));
    assert.equal(byId.openrouter.enabled, true);
    assert.equal(byId.gemini.enabled, true);
    assert.equal(byId.deepseek.enabled, true);
    assert.equal(byId.grok.enabled, true);
    assert.equal(byId.openai.enabled, true);
    delete process.env.OPENROUTER_API_KEY;
    process.env.GOOGLE_API_KEY = "test-env-google-key";
    const direct = await invoke({ host: "ats.vercel.app" });
    assert.equal(direct.body.find((row) => row.id === "gemini").enabled, true);
    assert.equal(direct.body.find((row) => row.id === "openrouter").enabled, false);
  } finally {
    if (previousOpenRouter === undefined) delete process.env.OPENROUTER_API_KEY;
    else process.env.OPENROUTER_API_KEY = previousOpenRouter;
    if (previousGoogle === undefined) delete process.env.GOOGLE_API_KEY;
    else process.env.GOOGLE_API_KEY = previousGoogle;
  }
});

test("built-in rules engine is available without a provider key and is the default", async () => {
  const response = await invoke({ host: "ats.vercel.app" });
  const rules = response.body.find((row) => row.id === "rules");
  const openrouter = response.body.find((row) => row.id === "openrouter");
  assert.equal(response.statusCode, 200);
  assert.equal(rules.enabled, true);
  assert.equal(rules.is_default, true);
  assert.match(rules.label, /no AI key required/i);
  assert.equal(openrouter.enabled, false);
});

test("built-in rules engine standardizes a job description without an external provider", async () => {
  const jd = [
    "Senior Software Engineer",
    "Responsibilities",
    "- Build APIs with Python and FastAPI",
    "- Maintain services and collaborate with product teams",
    "Requirements",
    "- 5 years experience with Python, SQL and AWS",
    "Nice to have",
    "- Kubernetes experience",
    "Location: Hybrid",
  ].join("\n");
  const response = await invoke(
    { host: "ats.vercel.app", "content-type": "application/json" },
    "POST",
    ["jd", "standardize"],
    JSON.stringify({ text: jd, options: { profile: "rules", mode: "light" } }),
  );
  assert.equal(response.statusCode, 200);
  assert.equal(response.body.meta.profile, "rules");
  assert.equal(response.body.fields.title.value, "Senior Software Engineer");
  assert.ok(response.body.sections.some((section) => section.items.length));
  assert.match(response.body.flags.map((flag) => flag.message).join(" "), /rules engine/i);
});

test("built-in rules engine builds a rubric and returns evidence-based resume matching", async () => {
  const jd = [
    "Senior Software Engineer",
    "Requirements",
    "- 5 years experience with Python, SQL and AWS",
    "- Build REST API services",
    "Nice to have",
    "- Kubernetes",
  ].join("\n");
  const rubricResponse = await invoke(
    { host: "ats.vercel.app", "content-type": "application/json" },
    "POST",
    ["match", "rubrics"],
    JSON.stringify({ jd_text: jd, options: { profile: "rules" } }),
  );
  assert.equal(rubricResponse.statusCode, 200);
  const rubric = rubricResponse.body.rubric;
  assert.ok(rubric.rubric_id);
  assert.ok(rubric.items.length > 0);

  const boundary = "rules-test-boundary";
  const resume = [
    "Senior software engineer with 6 years of experience.",
    "Built REST API services using Python and FastAPI.",
    "Worked with SQL databases and AWS cloud deployments.",
  ].join("\n");
  const parts = [
    { name: "rubric", value: JSON.stringify(rubric) },
    { name: "text", value: resume },
    { name: "profile", value: "rules" },
    { name: "rubric_id", value: rubric.rubric_id },
  ];
  const multipart = parts.map((part) =>
    "--" + boundary + "\r\n" +
    'Content-Disposition: form-data; name="' + part.name + '"\r\n\r\n' +
    part.value + "\r\n"
  ).join("") + "--" + boundary + "--\r\n";
  const matchResponse = await invoke(
    { host: "ats.vercel.app", "content-type": "multipart/form-data; boundary=" + boundary },
    "POST",
    ["match", "analyze"],
    multipart,
  );
  assert.equal(matchResponse.statusCode, 200, JSON.stringify(matchResponse.body));
  assert.equal(matchResponse.body.versions.profile, "rules");
  assert.equal(matchResponse.body.status, "complete");
  assert.ok(matchResponse.body.evidence.length > 0);
  assert.match(matchResponse.body.flags.join(" "), /not generative AI/i);
});


async function invokePagesFunction(pathParts, { method = "GET", headers = {}, body } = {}) {
  const url = "https://bluepace-ats-frontend.pages.dev/v1/" + pathParts.join("/");
  const request = new Request(url, {
    method,
    headers,
    ...(body === undefined ? {} : { body }),
  });
  const response = await pagesFunction({ request, params: { path: pathParts } });
  const responseText = await response.text();
  let parsed;
  try { parsed = JSON.parse(responseText); } catch { parsed = responseText; }
  return { statusCode: response.status, headers: Object.fromEntries(response.headers.entries()), body: parsed };
}

test("Cloudflare Pages adapter exposes the keyless rules model on /v1/models", async () => {
  const response = await invokePagesFunction(["models"]);
  assert.equal(response.statusCode, 200);
  assert.equal(response.headers["cache-control"], "no-store");
  assert.equal(response.body.find((row) => row.id === "rules")?.enabled, true);
});

test("Cloudflare Pages adapter standardizes job descriptions through the keyless rules engine", async () => {
  const text = [
    "Software Engineer",
    "Responsibilities:",
    "- Build REST APIs in Python",
    "Requirements:",
    "- SQL and 3 years of experience",
  ].join("\n");
  const response = await invokePagesFunction(["jd", "standardize"], {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ text, options: { profile: "rules", mode: "light" } }),
  });
  assert.equal(response.statusCode, 200, JSON.stringify(response.body));
  assert.equal(response.body.meta.profile, "rules");
  assert.equal(response.body.fields.title.value, "Software Engineer");
});

test("Cloudflare Pages adapter builds a rubric and assesses resume evidence without an AI key", async () => {
  const jd = [
    "Software Engineer",
    "Requirements:",
    "- Python and SQL",
    "- 3 years of experience",
    "Responsibilities:",
    "- Build and maintain REST APIs",
  ].join("\n");
  const rubricResponse = await invokePagesFunction(["match", "rubrics"], {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ jd_text: jd, options: { profile: "rules" } }),
  });
  assert.equal(rubricResponse.statusCode, 200, JSON.stringify(rubricResponse.body));
  const rubric = rubricResponse.body.rubric;
  assert.ok(rubric?.items?.length > 0);

  const boundary = "cloudflare-rules-test-boundary";
  const resume = "Software engineer with 4 years of experience. Built REST APIs in Python and SQL; maintained production services.";
  const multipart = [
    "--" + boundary + "\\r\nContent-Disposition: form-data; name=\"rubric\"\\r\n\\r\n" + JSON.stringify(rubric) + "\\r\n",
    "--" + boundary + "\\r\nContent-Disposition: form-data; name=\"text\"\\r\n\\r\n" + resume + "\\r\n",
    "--" + boundary + "\\r\nContent-Disposition: form-data; name=\"profile\"\\r\n\\r\nrules\\r\n",
    "--" + boundary + "\\r\nContent-Disposition: form-data; name=\"rubric_id\"\\r\n\\r\n" + rubric.rubric_id + "\\r\n",
    "--" + boundary + "--\\r\n",
  ].join("");
  const matchResponse = await invokePagesFunction(["match", "analyze"], {
    method: "POST",
    headers: { "content-type": "multipart/form-data; boundary=" + boundary },
    body: multipart,
  });
  assert.equal(matchResponse.statusCode, 200, JSON.stringify(matchResponse.body));
  assert.equal(matchResponse.body.versions.profile, "rules");
  assert.ok(matchResponse.body.evidence.length > 0);
});
