import assert from "node:assert/strict";
import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { after, before, test } from "node:test";
import { createStaticServer } from "./server.mjs";

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
