import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("./src/AIHiringStudio.jsx", import.meta.url), "utf8");

test("AI provider keys are memory-only and never restored from browser storage", () => {
  assert.match(source, /const \[apiKey, setApiKey\] = useState\("\s*"\)/);
  assert.match(source, /clearStoredProviderKeys\(\)/);
  assert.doesNotMatch(source, /readSessionValue\("bluepace_ai_" \+ current \+ "_key"\)/);
  assert.doesNotMatch(source, /readSessionValue\("bluepace_openrouter_key"\)/);
});

test("AI provider keys are not written to sessionStorage or localStorage", () => {
  assert.doesNotMatch(source, /sessionStorage\.setItem\([^\n]*(?:_key|openrouter_key)/i);
  assert.doesNotMatch(source, /localStorage\.setItem\([^\n]*(?:_key|openrouter_key)/i);
  assert.match(source, /sessionStorage\.removeItem\("bluepace_openrouter_key"\)/);
});

test("provider credential input uses password semantics and does not autofill saved credentials", () => {
  assert.match(source, /type="password" autoComplete="new-password"/);
});
