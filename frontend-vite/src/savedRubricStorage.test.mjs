import test from "node:test";
import assert from "node:assert/strict";

import {
  SAVED_RUBRICS_STORAGE_KEY,
  readSavedRubrics,
  writeSavedRubrics,
} from "./savedRubricStorage.mjs";

function memoryStorage(initial = {}) {
  const values = new Map(Object.entries(initial));
  return {
    getItem(key) { return values.has(key) ? values.get(key) : null; },
    setItem(key, value) { values.set(key, String(value)); },
    removeItem(key) { values.delete(key); },
    snapshot() { return Object.fromEntries(values.entries()); },
  };
}

function rubric(id, title = id) {
  return { rubric_id: id, title, items: [{ id: "R01", label: "Python" }] };
}

test("saved rubrics survive a new browser tab/session using persistent storage", () => {
  const local = memoryStorage();
  const firstSession = memoryStorage();
  const firstWrite = writeSavedRubrics([rubric("rb_one")], local, firstSession);

  assert.deepEqual(firstWrite, { ok: true, persistent: true });

  // Simulate a later browser session: localStorage is shared, sessionStorage is new.
  const nextSession = memoryStorage();
  const loaded = readSavedRubrics(local, nextSession);

  assert.deepEqual(loaded, [rubric("rb_one")]);
  assert.equal(nextSession.getItem(SAVED_RUBRICS_STORAGE_KEY), null);
});

test("legacy session-only rubrics migrate into persistent browser storage", () => {
  const local = memoryStorage();
  const session = memoryStorage({
    [SAVED_RUBRICS_STORAGE_KEY]: JSON.stringify([rubric("rb_legacy")]),
  });

  const loaded = readSavedRubrics(local, session);

  assert.deepEqual(loaded, [rubric("rb_legacy")]);
  assert.deepEqual(JSON.parse(local.getItem(SAVED_RUBRICS_STORAGE_KEY)), [rubric("rb_legacy")]);
  assert.equal(session.getItem(SAVED_RUBRICS_STORAGE_KEY), null);
});

test("existing persistent rubrics are retained and duplicate legacy versions are deduplicated", () => {
  const local = memoryStorage({
    [SAVED_RUBRICS_STORAGE_KEY]: JSON.stringify([rubric("rb_saved", "Saved")]),
  });
  const session = memoryStorage({
    [SAVED_RUBRICS_STORAGE_KEY]: JSON.stringify([
      rubric("rb_saved", "Old duplicate"),
      rubric("rb_new", "New legacy"),
    ]),
  });

  const loaded = readSavedRubrics(local, session);

  assert.deepEqual(loaded.map((row) => row.rubric_id), ["rb_saved", "rb_new"]);
  assert.equal(loaded[0].title, "Saved");
  assert.equal(loaded[1].title, "New legacy");
});

test("storage quota failures fall back to the current session and report non-persistent status", () => {
  const local = {
    getItem() { return null; },
    setItem() { throw new Error("quota exceeded"); },
  };
  const session = memoryStorage();
  const result = writeSavedRubrics([rubric("rb_fallback")], local, session);

  assert.deepEqual(result, { ok: true, persistent: false });
  assert.deepEqual(JSON.parse(session.getItem(SAVED_RUBRICS_STORAGE_KEY)), [rubric("rb_fallback")]);
});

test("reports failure when both browser storage mechanisms are unavailable", () => {
  const unavailable = {
    getItem() { throw new Error("blocked"); },
    setItem() { throw new Error("blocked"); },
    removeItem() { throw new Error("blocked"); },
  };

  assert.deepEqual(
    writeSavedRubrics([rubric("rb_none")], unavailable, unavailable),
    { ok: false, persistent: false },
  );
});

test("saved rubric collection is bounded to the newest 50 input rows", () => {
  const rows = Array.from({ length: 60 }, (_, index) => rubric("rb_" + index));
  const local = memoryStorage();

  const result = writeSavedRubrics(rows, local, memoryStorage());
  const loaded = readSavedRubrics(local, memoryStorage());

  assert.deepEqual(result, { ok: true, persistent: true });
  assert.equal(loaded.length, 50);
  assert.equal(loaded[0].rubric_id, "rb_0");
  assert.equal(loaded[49].rubric_id, "rb_49");
});
