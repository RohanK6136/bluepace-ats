export const SAVED_RUBRICS_STORAGE_KEY = "bluepace_feature_saved_rubrics";
const MAX_SAVED_RUBRICS = 50;

function parseRows(raw) {
  if (typeof raw !== "string" || !raw.trim()) return [];
  try {
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((row) => row && typeof row === "object"
      && typeof row.rubric_id === "string" && row.rubric_id.trim());
  } catch {
    return [];
  }
}

function mergeRows(primary, secondary) {
  const seen = new Set();
  const merged = [];
  for (const row of [...primary, ...secondary]) {
    if (!row?.rubric_id || seen.has(row.rubric_id)) continue;
    seen.add(row.rubric_id);
    merged.push(row);
    if (merged.length >= MAX_SAVED_RUBRICS) break;
  }
  return merged;
}

/**
 * Read the durable device copy and migrate older session-only copies.
 * Storage objects are injectable so the migration and failure paths are testable.
 */
export function readSavedRubrics(
  persistentStorage = globalThis.localStorage,
  legacyStorage = globalThis.sessionStorage,
) {
  let persistentRows = [];
  let legacyRows = [];
  try {
    persistentRows = parseRows(persistentStorage?.getItem(SAVED_RUBRICS_STORAGE_KEY));
  } catch {
    // Browser storage may be disabled or unavailable in private contexts.
  }
  try {
    legacyRows = parseRows(legacyStorage?.getItem(SAVED_RUBRICS_STORAGE_KEY));
  } catch {
    // The persistent copy remains usable when session storage is unavailable.
  }

  const merged = mergeRows(persistentRows, legacyRows);
  if (legacyRows.length && typeof persistentStorage?.setItem === "function") {
    try {
      persistentStorage.setItem(SAVED_RUBRICS_STORAGE_KEY, JSON.stringify(merged));
      legacyStorage?.removeItem(SAVED_RUBRICS_STORAGE_KEY);
    } catch {
      // Keep the legacy session copy when migration cannot be written.
    }
  }
  return merged;
}

/**
 * Persist immutable rubric versions locally. Returns whether storage succeeded
 * and whether the copy survives closing the browser (localStorage vs sessionStorage).
 */
export function writeSavedRubrics(
  rows,
  persistentStorage = globalThis.localStorage,
  fallbackStorage = globalThis.sessionStorage,
) {
  const safeRows = mergeRows(Array.isArray(rows) ? rows : [], []);
  const serialized = JSON.stringify(safeRows);
  try {
    if (!persistentStorage) throw new Error("localStorage is unavailable");
    persistentStorage.setItem(SAVED_RUBRICS_STORAGE_KEY, serialized);
    try {
      fallbackStorage?.removeItem(SAVED_RUBRICS_STORAGE_KEY);
    } catch {
      // The durable copy has already been written successfully.
    }
    return { ok: true, persistent: true };
  } catch {
    try {
      if (!fallbackStorage) throw new Error("sessionStorage is unavailable");
      fallbackStorage.setItem(SAVED_RUBRICS_STORAGE_KEY, serialized);
      return { ok: true, persistent: false };
    } catch {
      return { ok: false, persistent: false };
    }
  }
}
