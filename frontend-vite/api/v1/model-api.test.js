import assert from "node:assert/strict";
import { test } from "node:test";
import handler from "./[...path].js";

function invoke(headers = {}) {
  const req = {
    method: "GET",
    url: "/api/v1/models",
    headers,
    query: { path: ["models"] },
    async *[Symbol.asyncIterator]() {},
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
  assert.equal(byId.deepseek.model, "deepseek/deepseek-v4.1-flash");
  assert.equal(byId.grok.enabled, true);
  assert.equal(byId.grok.model, "x-ai/grok-4.7");
  assert.equal(byId.openai.enabled, true);
  assert.equal(byId.openai.model, "openai/gpt-4.1");
});
