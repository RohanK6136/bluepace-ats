import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import handler, { extractPdfText } from "../api/v1/[...path].js";
import explicitTestHandler from "../api/v1/test.js";
import { deflateSync } from "node:zlib";
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
function invokeHandler(targetHandler, headers = {}, method = "GET", url = "/api/v1/models", query = {}, body = "") {
  const req = {
    method,
    url,
    headers,
    query,
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
  return Promise.resolve(targetHandler(req, res)).then(() => ({
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

test("curated free OpenRouter models are visible and use the shared OpenRouter key", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({ data: [] }), {
    status: 200, headers: { "content-type": "application/json" },
  });
  try {
    const withoutKey = await invoke({ host: "ats.vercel.app" });
    const freeRows = withoutKey.body.filter((row) => row.free_endpoint);
    assert.equal(freeRows.length, 8);
    assert.ok(freeRows.every((row) => row.enabled === false));
    assert.ok(freeRows.some((row) => row.model === "openrouter/free"));

    const withKey = await invoke({ host: "ats.vercel.app", "x-openrouter-api-key": "test-free-model-key" });
    const enabledFreeRows = withKey.body.filter((row) => row.free_endpoint);
    assert.equal(enabledFreeRows.length, 8);
    assert.ok(enabledFreeRows.every((row) => row.enabled === true));
    assert.ok(enabledFreeRows.every((row) => row.provider === "openrouter"));
    assert.ok(enabledFreeRows.some((row) => row.model === "cohere/north-mini-code:free"));
    assert.ok(enabledFreeRows.some((row) => row.model === "recursive/flint-v1.0:free"));
    assert.equal(enabledFreeRows.some((row) => row.model.includes("thinkingmachines/inkling")), false);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("selecting a free OpenRouter model does not change deterministic JD standardization", async () => {
  const originalFetch = globalThis.fetch;
  let providerCallMade = false;
  globalThis.fetch = async () => {
    providerCallMade = true;
    throw new Error("JD standardization must not invoke a selected model.");
  };
  try {
    const response = await invoke(
      { host: "ats.vercel.app", "x-openrouter-api-key": "test-free-model-key", "content-type": "application/json" },
      "POST",
      ["jd", "standardize"],
      JSON.stringify({
        text: "Python Developer\nResponsibilities\nBuild Python APIs\nRequirements\nPython and SQL experience",
        options: { profile: "openrouter:cohere/north-mini-code:free", mode: "light" },
      }),
    );
    assert.equal(response.statusCode, 200, JSON.stringify(response.body));
    assert.equal(response.body.meta.profile, "rules");
    assert.equal(response.body.meta.llm_calls, 0);
    assert.equal(response.body.fields.title.value, "Python Developer");
    assert.equal(providerCallMade, false);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("OpenRouter inference test verifies a real completion without exposing the key", async () => {
  const originalFetch = globalThis.fetch;
  let capturedUrl = "";
  let capturedAuthorization = "";
  globalThis.fetch = async (url, init = {}) => {
    capturedUrl = String(url);
    capturedAuthorization = String(init.headers?.Authorization || "");
    return new Response(JSON.stringify({
      model: "google/gemini-3.8-flash",
      choices: [{ message: { content: '{"status":"ok"}' } }],
      usage: { prompt_tokens: 9, completion_tokens: 4 },
    }), { status: 200, headers: { "content-type": "application/json" } });
  };
  try {
    const response = await invoke(
      { host: "ats.vercel.app", "x-openrouter-api-key": "test-secret-never-returned" },
      "POST",
      ["test"],
      "{}",
    );
    assert.equal(response.statusCode, 200, JSON.stringify(response.body));
    assert.equal(response.body.status, "connected");
    assert.equal(response.body.completion_verified, true);
    assert.equal(response.body.model, "google/gemini-3.8-flash");
    assert.equal(response.body.prompt_tokens, 9);
    assert.equal(response.body.completion_tokens, 4);
    assert.equal(capturedUrl, "https://openrouter.ai/api/v1/chat/completions");
    assert.equal(capturedAuthorization, "Bearer test-secret-never-returned");
    assert.equal(JSON.stringify(response.body).includes("test-secret-never-returned"), false);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("OpenRouter inference test fails clearly when no provider key is supplied", async () => {
  const originalFetch = globalThis.fetch;
  const previousKey = process.env.OPENROUTER_API_KEY;
  let fetchCalled = false;
  delete process.env.OPENROUTER_API_KEY;
  globalThis.fetch = async () => {
    fetchCalled = true;
    throw new Error("A provider request should not be made without a key.");
  };
  try {
    const response = await invoke({ host: "ats.vercel.app" }, "POST", ["test"], "{}");
    assert.equal(response.statusCode, 400);
    assert.match(response.body.detail, /API key/i);
    assert.equal(fetchCalled, false);
  } finally {
    globalThis.fetch = originalFetch;
    if (previousKey === undefined) delete process.env.OPENROUTER_API_KEY;
    else process.env.OPENROUTER_API_KEY = previousKey;
  }
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


test("JD standardization stays deterministic even when a hosted model key is supplied", async () => {
  const originalFetch = globalThis.fetch;
  let providerCallMade = false;
  globalThis.fetch = async () => {
    providerCallMade = true;
    throw new Error("JD standardization must never call a model provider.");
  };
  try {
    const response = await invoke(
      { host: "ats.vercel.app", "content-type": "application/json", "x-openrouter-api-key": "test-jd-provider-key" },
      "POST",
      ["jd", "standardize"],
      JSON.stringify({
        text: "Software Engineer\nResponsibilities:\n- Build and maintain APIs\nRequirements:\n- Python and 3 years of experience",
        options: { profile: "openrouter", mode: "light" },
      }),
    );
    assert.equal(response.statusCode, 200, JSON.stringify(response.body));
    assert.equal(response.body.fields.title.value, "Software Engineer");
    assert.equal(response.body.meta.profile, "rules");
    assert.equal(response.body.meta.model, "deterministic-nlp-rules-v1");
    assert.equal(response.body.meta.llm_calls, 0);
    assert.equal(response.body.meta.prompt_tokens, 0);
    assert.equal(response.body.meta.completion_tokens, 0);
    assert.equal(response.body.meta.cost_usd, 0);
    assert.equal(providerCallMade, false);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("JD fast generation also uses source-grounded deterministic output with zero inference cost", async () => {
  const originalFetch = globalThis.fetch;
  let providerCallMade = false;
  globalThis.fetch = async () => {
    providerCallMade = true;
    throw new Error("Fast JD generation must not call a model provider.");
  };
  try {
    const response = await invoke(
      { host: "ats.vercel.app", "content-type": "application/json" },
      "POST",
      ["jd", "generate"],
      JSON.stringify({
        text: "QA Automation Engineer\nResponsibilities\n- Maintain Playwright test suites\nRequirements\n- 4 years of test automation experience",
        options: { profile: "openrouter", mode: "rewrite" },
      }),
    );
    assert.equal(response.statusCode, 200, JSON.stringify(response.body));
    assert.equal(response.body.fields.title.value, "QA Automation Engineer");
    assert.equal(response.body.meta.llm_calls, 0);
    assert.equal(response.body.meta.cost_usd, 0);
    assert.equal(response.body.sections.find((section) => section.id === "responsibilities").items[0].origin, "source");
    assert.equal(providerCallMade, false);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("OpenRouter requests enable response healing and retry malformed structured output once", async () => {
  const originalFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (_url, init = {}) => {
    const request = JSON.parse(init.body);
    requests.push(request);
    const content = requests.length === 1
      ? "I will structure this response now."
      : JSON.stringify({
          title: "Software Engineer",
          responsibilities: ["Build REST APIs"],
          requirements: ["Python"],
          location: { work_mode: "hybrid" },
          experience: { min_years: 3, max_years: null },
        });
    return new Response(JSON.stringify({
      model: "google/gemini-3.8-flash",
      choices: [{ message: { content }, finish_reason: "stop" }],
      usage: { prompt_tokens: 20, completion_tokens: 30 },
    }), { status: 200, headers: { "content-type": "application/json" } });
  };
  try {
    const response = await invoke(
      { host: "ats.vercel.app", "content-type": "application/json", "x-openrouter-api-key": "test-repair-key" },
      "POST",
      ["jd", "standardize"],
      JSON.stringify({
        text: "Software Engineer\\nRequirements:\\n- Python and 3 years of experience",
        options: { profile: "openrouter", mode: "light" },
      }),
    );
    assert.equal(response.statusCode, 200, JSON.stringify(response.body));
    assert.equal(requests.length, 2);
    assert.deepEqual(requests[0].response_format, { type: "json_object" });
    assert.deepEqual(requests[0].plugins, [{ id: "response-healing" }]);
    assert.match(requests[1].messages[0].content, /OUTPUT CONTRACT/);
    assert.equal(response.body.fields.title.value, "Software Engineer");
    assert.equal(response.body.meta.model, "google/gemini-3.8-flash");
  } finally {
    globalThis.fetch = originalFetch;
  }
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
    "--" + boundary + "\r\nContent-Disposition: form-data; name=\"rubric\"\r\n\r\n" + JSON.stringify(rubric) + "\r\n",
    "--" + boundary + "\r\nContent-Disposition: form-data; name=\"text\"\r\n\r\n" + resume + "\r\n",
    "--" + boundary + "\r\nContent-Disposition: form-data; name=\"profile\"\r\n\r\nrules\r\n",
    "--" + boundary + "\r\nContent-Disposition: form-data; name=\"rubric_id\"\r\n\r\n" + rubric.rubric_id + "\r\n",
    "--" + boundary + "--\r\n",
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


function encodeAscii85(buffer) {
  const parts = [];
  for (let offset = 0; offset < buffer.length; offset += 4) {
    const chunk = buffer.subarray(offset, offset + 4);
    let value = 0;
    for (let index = 0; index < 4; index++) value = value * 256 + (chunk[index] || 0);
    if (chunk.length === 4 && value === 0) {
      parts.push("z");
      continue;
    }
    const digits = Array(5);
    for (let index = 4; index >= 0; index--) {
      digits[index] = String.fromCharCode((value % 85) + 33);
      value = Math.floor(value / 85);
    }
    parts.push(digits.slice(0, chunk.length + 1).join(""));
  }
  return parts.join("") + "~>";
}

test("PDF extraction decodes ASCII85 then Flate streams and preserves JD headings", () => {
  const content = [
    "BT /F1 12 Tf 72 720 Td (Python Full Stack Developer) Tj ET",
    "BT /F1 11 Tf 72 700 Td (Required Qualifications) Tj ET",
    "BT /F1 10 Tf 72 680 Td (Python and FastAPI experience) Tj ET",
  ].join("\n");
  const encoded = encodeAscii85(deflateSync(Buffer.from(content, "latin1")));
  const pdf = Buffer.from(
    "%PDF-1.4\n1 0 obj\n<< /Length " + encoded.length + " /Filter [ /ASCII85Decode /FlateDecode ] >>\nstream\n" +
    encoded + "endstream\\nendobj\\n%%EOF\\n",
    "latin1",
  );

  const extracted = extractPdfText(pdf);
  assert.match(extracted, /Python Full Stack Developer/);
  assert.match(extracted, /Required Qualifications/);
  assert.match(extracted, /Python and FastAPI experience/);
  assert.ok(extracted.indexOf("Required Qualifications") > extracted.indexOf("Python Full Stack Developer"));
});


test("multipart JD PDF upload extracts requirements using its selected rules profile", async () => {
  const contentStream = [
    "BT /F1 12 Tf 72 720 Td (Python Full Stack Developer) Tj ET",
    "BT /F1 11 Tf 72 700 Td (Key Responsibilities) Tj ET",
    "BT /F1 10 Tf 72 680 Td (Build and maintain REST APIs) Tj ET",
    "BT /F1 11 Tf 72 660 Td (Required Qualifications) Tj ET",
    "BT /F1 10 Tf 72 640 Td (Python and FastAPI experience) Tj ET",
    "BT /F1 11 Tf 72 620 Td (Preferred Skills) Tj ET",
    "BT /F1 10 Tf 72 600 Td (Docker and AWS) Tj ET",
  ].join("\n");
  const encoded = encodeAscii85(deflateSync(Buffer.from(contentStream, "latin1")));
  const pdf = [
    "%PDF-1.4",
    "1 0 obj",
    "<< /Length " + encoded.length + " /Filter [ /ASCII85Decode /FlateDecode ] >>",
    "stream",
    encoded + "endstream",
    "endobj",
    "%%EOF",
  ].join("\n");
  const boundary = "jd-pdf-ascii85-boundary";
  const multipart = [
    "--" + boundary + "\r\nContent-Disposition: form-data; name=\"file\"; filename=\"sample.pdf\"\r\nContent-Type: application/pdf\r\n\r\n",
    pdf,
    "\r\n--" + boundary + "\r\nContent-Disposition: form-data; name=\"options\"\r\n\r\n" +
      JSON.stringify({ mode: "light", profile: "rules" }) + "\r\n",
    "--" + boundary + "--\r\n",
  ].join("");

  const response = await invoke(
    { host: "ats.vercel.app", "content-type": "multipart/form-data; boundary=" + boundary },
    "POST",
    ["jd", "generate", "upload"],
    multipart,
  );
  assert.equal(response.statusCode, 200, JSON.stringify(response.body));
  assert.equal(response.body.meta.profile, "rules");
  const requirements = response.body.sections.find((section) => section.id === "requirements");
  assert.ok(requirements?.items.some((item) => /Python and FastAPI experience/i.test(item.text)));
  assert.equal(requirements?.items.some((item) => item.text === "Required Qualifications"), false);
});


test("direct /api/v1 function URLs serve JD Standardizer and Applicant Match without a rewrite", async () => {
  const hostHeaders = { host: "ats.vercel.app" };
  const models = await invokeHandler(handler, hostHeaders, "GET", "/api/v1/models", {});
  assert.equal(models.statusCode, 200);
  assert.ok(models.body.some((row) => row.id === "rules" && row.enabled));

  const jd = [
    "Senior Software Engineer",
    "Responsibilities:",
    "- Build REST APIs with Python and FastAPI",
    "Requirements:",
    "- 5 years of experience with Python, SQL and AWS",
  ].join("\n");
  const standardize = await invokeHandler(
    handler,
    { ...hostHeaders, "content-type": "application/json" },
    "POST",
    "/api/v1/jd/standardize",
    {},
    JSON.stringify({ text: jd, options: { profile: "rules", mode: "light" } }),
  );
  assert.equal(standardize.statusCode, 200, JSON.stringify(standardize.body));
  assert.equal(standardize.body.meta.profile, "rules");
  assert.equal(standardize.body.fields.title.value, "Senior Software Engineer");

  const rubricResponse = await invokeHandler(
    handler,
    { ...hostHeaders, "content-type": "application/json" },
    "POST",
    "/api/v1/match/rubrics",
    {},
    JSON.stringify({ jd_text: jd, options: { profile: "rules" } }),
  );
  assert.equal(rubricResponse.statusCode, 200, JSON.stringify(rubricResponse.body));
  const rubric = rubricResponse.body.rubric;
  assert.ok(rubric?.items?.length > 0);

  const boundary = "direct-api-path-boundary";
  const resume = "Senior software engineer with 6 years of experience. Built REST APIs using Python and FastAPI. Worked with SQL databases and AWS cloud deployments.";
  const multipart = [
    "--" + boundary + "\r\nContent-Disposition: form-data; name=\"rubric\"\r\n\r\n" + JSON.stringify(rubric) + "\r\n",
    "--" + boundary + "\r\nContent-Disposition: form-data; name=\"text\"\r\n\r\n" + resume + "\r\n",
    "--" + boundary + "\r\nContent-Disposition: form-data; name=\"profile\"\r\n\r\nrules\r\n",
    "--" + boundary + "\r\nContent-Disposition: form-data; name=\"rubric_id\"\r\n\r\n" + rubric.rubric_id + "\r\n",
    "--" + boundary + "--\r\n",
  ].join("");
  const analysis = await invokeHandler(
    handler,
    { ...hostHeaders, "content-type": "multipart/form-data; boundary=" + boundary },
    "POST",
    "/api/v1/match/analyze",
    {},
    multipart,
  );
  assert.equal(analysis.statusCode, 200, JSON.stringify(analysis.body));
  assert.equal(analysis.body.versions.profile, "rules");
  assert.equal(analysis.body.status, "complete");
  assert.ok(analysis.body.evidence.length > 0);
});

test("Vercel model API rewrite preserves the requested path", () => {
  const config = JSON.parse(readFileSync(new URL("../vercel.json", import.meta.url), "utf8"));
  assert.ok(config.rewrites.some((rule) => rule.source === "/v1/:path*" && rule.destination === "/api/v1/:path*"));
});

test("explicit OpenRouter test route and Vercel catch-all path variants complete inference", async () => {
  const originalFetch = globalThis.fetch;
  let capturedAuthorization = "";
  globalThis.fetch = async (_url, init = {}) => {
    capturedAuthorization = String(init.headers?.Authorization || "");
    return new Response(JSON.stringify({
      model: "google/gemini-3.8-flash",
      choices: [{ message: { content: '{"status":"ok"}' } }],
      usage: { prompt_tokens: 9, completion_tokens: 4 },
    }), { status: 200, headers: { "content-type": "application/json" } });
  };

  const headers = {
    host: "ats.vercel.app",
    "x-openrouter-api-key": "test-secret-never-returned",
    "content-type": "application/json",
  };
  const cases = [
    ["explicit /api/v1/test function", explicitTestHandler, "/api/v1/test", {}],
    ["catch-all array parameter", handler, "/api/v1/test", { path: ["test"] }],
    ["catch-all prefixed string parameter", handler, "/api/v1/test", { path: "v1/test" }],
    ["catch-all original /v1 URL fallback", handler, "/v1/test", {}],
    ["catch-all rewritten /api/v1 URL fallback", handler, "/api/v1/test", {}],
  ];

  try {
    for (const [label, targetHandler, url, query] of cases) {
      const response = await invokeHandler(targetHandler, headers, "POST", url, query, "{}");
      assert.equal(response.statusCode, 200, label + ": " + JSON.stringify(response.body));
      assert.equal(response.body.status, "connected", label);
      assert.equal(response.body.completion_verified, true, label);
      assert.equal(response.body.model, "google/gemini-3.8-flash", label);
      assert.equal(response.body.prompt_tokens, 9, label);
      assert.equal(response.body.completion_tokens, 4, label);
      assert.equal(JSON.stringify(response.body).includes("test-secret-never-returned"), false, label);
    }
    assert.equal(capturedAuthorization, "Bearer test-secret-never-returned");
  } finally {
    globalThis.fetch = originalFetch;
  }
});
