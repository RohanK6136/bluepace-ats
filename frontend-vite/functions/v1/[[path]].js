import apiHandler from "../../api/v1/[...path].js";

/**
 * Adapt the existing JD & Applicant Match API handler to Cloudflare Pages
 * Functions. The core API remains shared with Vercel so both deployments
 * behave consistently while the Cloudflare version is validated.
 */
export async function onRequest({ request, params }) {
  const url = new URL(request.url);
  const routeParam = params?.path;
  const routeParts = Array.isArray(routeParam)
    ? routeParam
    : typeof routeParam === "string" && routeParam.length
      ? routeParam.split("/")
      : [];

  const headers = Object.fromEntries(request.headers.entries());
  headers.host = url.host;

  const req = {
    method: request.method,
    headers,
    query: { path: routeParts },
    url: url.pathname,
    async *[Symbol.asyncIterator]() {
      if (["POST", "PUT", "PATCH"].includes(String(request.method).toUpperCase()) && request.body) {
        yield Buffer.from(await request.arrayBuffer());
      }
    },
  };

  const responseHeaders = new Headers();
  let responseBody = "";
  const res = {
    statusCode: 200,
    setHeader(name, value) {
      responseHeaders.set(name, String(value));
    },
    end(value = "") {
      responseBody = Buffer.isBuffer(value) ? value.toString("utf8") : String(value);
    },
  };

  try {
    await apiHandler(req, res);
    return new Response(responseBody, {
      status: res.statusCode || 200,
      headers: responseHeaders,
    });
  } catch (error) {
    return Response.json(
      { detail: String(error?.message || "JD & Applicant Match API failed.").slice(0, 500) },
      { status: Number(error?.statusCode) || 500, headers: { "Cache-Control": "no-store" } },
    );
  }
}
