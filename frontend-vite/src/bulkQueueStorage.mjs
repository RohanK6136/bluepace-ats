const DB_NAME = "bluepace-applicant-match-queue-v1";
const DB_VERSION = 1;
const STORE_NAME = "queues";

function requestValue(request) {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error || new Error("IndexedDB request failed."));
  });
}

function openQueueDatabase(factory = globalThis.indexedDB) {
  if (!factory || typeof factory.open !== "function") {
    return Promise.reject(new Error("This browser does not provide IndexedDB. Bulk queue recovery is unavailable."));
  }
  return new Promise((resolve, reject) => {
    const request = factory.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const database = request.result;
      if (!database.objectStoreNames.contains(STORE_NAME)) {
        database.createObjectStore(STORE_NAME, { keyPath: "workspaceId" });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error || new Error("Could not open local bulk queue storage."));
    request.onblocked = () => reject(new Error("Local bulk queue storage is blocked by another browser tab. Close the other BluePace tab and retry."));
  });
}

function fileMetadata(file, fallback = {}) {
  return {
    name: String(file?.name || fallback.name || "resume"),
    size: Number(file?.size ?? fallback.size ?? 0),
    type: String(file?.type || fallback.type || ""),
    lastModified: Number(file?.lastModified ?? fallback.lastModified ?? 0),
  };
}

function serializeRow(row) {
  const meta = fileMetadata(row?.file, row?.fileMeta || row || {});
  return {
    ...row,
    file: row?.file || null,
    fileMeta: meta,
  };
}

function restoreFile(file, meta) {
  if (file && typeof file.name === "string") return file;
  if (typeof Blob === "undefined" || !(file instanceof Blob)) return null;
  const details = fileMetadata(file, meta);
  if (typeof File === "function") {
    return new File([file], details.name, {
      type: details.type || file.type || "application/octet-stream",
      lastModified: details.lastModified || Date.now(),
    });
  }
  try {
    return Object.assign(file, details);
  } catch {
    return null;
  }
}

/**
 * Restore saved rows after a page/browser restart. A row left in "processing"
 * has an unknown server outcome, so return it to "queued" and require a retry.
 * If the browser did not preserve the binary file, make that row explicit.
 */
export function restoreBulkQueueRows(rows) {
  let interrupted = 0;
  const restored = (Array.isArray(rows) ? rows : []).map((stored) => {
    const meta = fileMetadata(stored?.file, stored?.fileMeta || stored || {});
    const file = restoreFile(stored?.file, meta);
    let status = stored?.status || "queued";
    let error = stored?.error || "";
    if (status === "processing") {
      interrupted += 1;
      status = "queued";
      error = "The previous browser session ended while this resume was processing. It was returned to the queue; rerun it to verify completion.";
    }
    if (!file && ["queued", "failed", "processing"].includes(stored?.status || "queued")) {
      status = "file_missing";
      error = "The resume file could not be restored from browser storage. Remove this entry and select the file again.";
    }
    return {
      ...stored,
      file,
      fileName: meta.name,
      fileSize: meta.size,
      status,
      error,
    };
  });
  return { rows: restored, interrupted };
}

export async function loadBulkQueue(workspaceId, factory = globalThis.indexedDB) {
  if (!workspaceId) return { rows: [], interrupted: 0 };
  const database = await openQueueDatabase(factory);
  try {
    const transaction = database.transaction(STORE_NAME, "readonly");
    const record = await requestValue(transaction.objectStore(STORE_NAME).get(String(workspaceId)));
    if (!record || !Array.isArray(record.rows)) return { rows: [], interrupted: 0, updatedAt: null };
    return {
      ...restoreBulkQueueRows(record.rows),
      updatedAt: record.updatedAt || null,
    };
  } finally {
    database.close?.();
  }
}

export async function saveBulkQueue(workspaceId, rows, factory = globalThis.indexedDB) {
  if (!workspaceId) throw new Error("A workspace is required to save a bulk queue.");
  const database = await openQueueDatabase(factory);
  try {
    await new Promise((resolve, reject) => {
      const transaction = database.transaction(STORE_NAME, "readwrite");
      const store = transaction.objectStore(STORE_NAME);
      if (!Array.isArray(rows) || rows.length === 0) {
        store.delete(String(workspaceId));
      } else {
        store.put({
          workspaceId: String(workspaceId),
          updatedAt: new Date().toISOString(),
          rows: rows.map(serializeRow),
        });
      }
      transaction.oncomplete = () => resolve();
      transaction.onerror = () => reject(transaction.error || new Error("Could not save the bulk queue."));
      transaction.onabort = () => reject(transaction.error || new Error("Saving the bulk queue was interrupted."));
    });
    return true;
  } finally {
    database.close?.();
  }
}

export async function deleteBulkQueue(workspaceId, factory = globalThis.indexedDB) {
  if (!workspaceId) return true;
  const database = await openQueueDatabase(factory);
  try {
    await new Promise((resolve, reject) => {
      const transaction = database.transaction(STORE_NAME, "readwrite");
      transaction.objectStore(STORE_NAME).delete(String(workspaceId));
      transaction.oncomplete = () => resolve();
      transaction.onerror = () => reject(transaction.error || new Error("Could not delete the bulk queue."));
      transaction.onabort = () => reject(transaction.error || new Error("Deleting the bulk queue was interrupted."));
    });
    return true;
  } finally {
    database.close?.();
  }
}

export async function moveBulkQueue(fromWorkspaceId, toWorkspaceId, factory = globalThis.indexedDB) {
  if (!fromWorkspaceId || !toWorkspaceId || fromWorkspaceId === toWorkspaceId) return true;
  const source = await loadBulkQueue(fromWorkspaceId, factory);
  if (!source.rows.length) return true;
  await saveBulkQueue(toWorkspaceId, source.rows, factory);
  await deleteBulkQueue(fromWorkspaceId, factory);
  return true;
}
