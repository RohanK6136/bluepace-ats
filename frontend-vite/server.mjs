import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import { createServer as createHttpServer } from "node:http";
import { dirname, extname, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import aiFeatureApiHandler from "./api/v1/[...path].js";

const APP_DIR = dirname(fileURLToPath(import.meta.url));
const DEFAULT_DIST_DIR = resolve(APP_DIR, "dist");
const MIME_TYPES = new Map([
  [".css", "text/css; charset=utf-8"],
  [".gif", "image/gif"],
  [".html", "text/html; charset=utf-8"],
  [".ico", "image/x-icon"],
  [".jpeg", "image/jpeg"],
  [".jpg", "image/jpeg"],
  [".js", "text/javascript; charset=utf-8"],
  [".json", "application/json; charset=utf-8"],
  [".map", "application/json; charset=utf-8"],
  [".mjs", "text/javascript; charset=utf-8"],
  [".png", "image/png"],
  [".svg", "image/svg+xml"],
  [".txt", "text/plain; charset=utf-8"],
  [".webmanifest", "application/manifest+json"],
  [".webp", "image/webp"],
  [".woff", "font/woff"],
  [".woff2", "font/woff2"],
]);

function isInsideDirectory(filePath, directory) {
  return filePath === directory || filePath.startsWith(`${directory}${sep}`);
}

function sendText(response, statusCode, message, additionalHeaders = {}) {
  const body = Buffer.from(message);
  response.writeHead(statusCode, {
    "Cache-Control": "no-store",
    "Content-Length": body.length,
    "Content-Type": "text/plain; charset=utf-8",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    ...additionalHeaders,
  });
  response.end(body);
}

export function createStaticServer({ distDir = DEFAULT_DIST_DIR } = {}) {
  const root = resolve(distDir);
  const indexFile = resolve(root, "index.html");

  return createHttpServer(async (request, response) => {
    // Route AI Feature API calls before the static-server method guard. The
    // same /v1 endpoints run as Vercel/Pages functions elsewhere, but Railway
    // serves this frontend through server.mjs and does not apply vercel.json
    // rewrites or invoke serverless functions automatically.
    let aiPathname;
    try {
      aiPathname = new URL(request.url || "/", "http://localhost").pathname;
    } catch {
      sendText(response, 400, "Invalid URL path");
      return;
    }

    const aiRouteMatch = /^\/v1(?:\/(.*))?$/.exec(aiPathname);
    if (aiRouteMatch) {
      let routeParts;
      try {
        routeParts = (aiRouteMatch[1] || "")
          .split("/")
          .filter(Boolean)
          .map((part) => decodeURIComponent(part));
      } catch {
        sendText(response, 400, "Invalid URL path");
        return;
      }
      request.query = { ...(request.query || {}), path: routeParts };
      try {
        await aiFeatureApiHandler(request, response);
      } catch {
        if (!response.headersSent) sendText(response, 500, "AI Feature API failed");
        else response.destroy();
      }
      return;
    }

    if (request.method !== "GET" && request.method !== "HEAD") {
      sendText(response, 405, "Method not allowed", { Allow: "GET, HEAD" });
      return;
    }

    let pathname;
    try {
      const requestTarget = request.url || "/";
      const rawPath = requestTarget.split("?", 1)[0] || "/";
      pathname = decodeURIComponent(rawPath);
    } catch {
      sendText(response, 400, "Invalid URL path");
      return;
    }

    if (pathname.includes(String.fromCharCode(0)) || pathname.includes("\\")) {
      sendText(response, 400, "Invalid URL path");
      return;
    }

    const requestedPath = pathname.startsWith("/") ? pathname : `/${pathname}`;
    const requestedFile = resolve(root, `.${requestedPath}`);
    if (!isInsideDirectory(requestedFile, root)) {
      sendText(response, 404, "Not found");
      return;
    }

    let filePath = requestedFile;
    let fileStat;
    try {
      fileStat = await stat(filePath);
      if (!fileStat.isFile()) throw new Error("Not a file");
    } catch {
      // Never return the SPA document for a missing JS/CSS/image asset: doing
      // so masks deployment errors and can cause browsers to crash on parsing.
      const isAssetRequest =
        pathname === "/assets" ||
        pathname.startsWith("/assets/") ||
        extname(pathname) !== "";

      if (isAssetRequest) {
        sendText(response, 404, "Not found");
        return;
      }

      filePath = indexFile;
      try {
        fileStat = await stat(filePath);
        if (!fileStat.isFile()) throw new Error("Frontend entry point is not a file");
      } catch {
        sendText(response, 503, "Frontend build artifacts are unavailable");
        return;
      }
    }

    const relativePath = filePath.slice(root.length).split(sep).join("/");
    const isHashedAsset = relativePath.startsWith("/assets/");
    const cacheControl =
      filePath === indexFile
        ? "no-cache"
        : isHashedAsset
          ? "public, max-age=31536000, immutable"
          : "no-cache";

    response.writeHead(200, {
      "Cache-Control": cacheControl,
      "Content-Length": fileStat.size,
      "Content-Type": MIME_TYPES.get(extname(filePath).toLowerCase()) || "application/octet-stream",
      "Last-Modified": fileStat.mtime.toUTCString(),
      "X-Content-Type-Options": "nosniff",
      "Referrer-Policy": "strict-origin-when-cross-origin",
    });

    if (request.method === "HEAD") {
      response.end();
      return;
    }

    const stream = createReadStream(filePath);
    stream.on("error", () => {
      if (!response.headersSent) {
        sendText(response, 500, "Unable to serve file");
      } else {
        response.destroy();
      }
    });
    stream.pipe(response);
  });
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const port = Number.parseInt(process.env.PORT || "8080", 10);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error("PORT must be an integer between 1 and 65535");
  }

  const server = createStaticServer();
  server.listen(port, "0.0.0.0", () => {
    console.log(`BluePace ATS frontend listening on 0.0.0.0:${port}`);
  });
}
