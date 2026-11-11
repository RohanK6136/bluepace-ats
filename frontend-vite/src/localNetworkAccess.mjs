/**
 * Read browser permission for a hosted BluePace page to contact a local
 * companion service on 127.0.0.1. Permission-query support varies by browser.
 * Unknown/unsupported states are treated as "prompt" so the actual request
 * can still be made from an explicit button click and let the browser ask.
 */
export async function getLoopbackNetworkPermission(
  permissions = globalThis.navigator?.permissions,
  userAgent = globalThis.navigator?.userAgent || "",
) {
  if (!permissions?.query) return { state: "prompt", permissionName: null };

  const query = async (name) => {
    const status = await permissions.query({ name });
    return ["granted", "denied", "prompt"].includes(status?.state) ? status.state : "prompt";
  };

  // Microsoft Edge documents the combined permission name as its supported
  // query. Newer Chromium also exposes the more granular loopback permission.
  if (/Edg\//i.test(String(userAgent))) {
    try {
      return { state: await query("local-network-access"), permissionName: "local-network-access" };
    } catch {
      // Try the granular name below for builds that expose the newer API.
    }
  }

  try {
    return { state: await query("loopback-network"), permissionName: "loopback-network" };
  } catch {
    return { state: "prompt", permissionName: null };
  }
}

export function localAiPermissionHelp(origin = "this BluePace site") {
  return `Edge is blocking ${origin} from reaching the local computer. In Edge, open Settings → Privacy, search, and services → Site permissions → All permissions → Local network access. Allow access for this BluePace site, then return here and reconnect. You can also use the site icon beside the address bar → Site permissions. The local API must still be running at http://127.0.0.1:8000.`;
}

export function localAiServiceHelp() {
  return "The browser could not reach http://127.0.0.1:8000. In PowerShell, check that the BluePace local AI window is still running and shows Uvicorn on 127.0.0.1:8000. Then open http://127.0.0.1:8000/healthz in a new tab; it should return { status: \"ok\" }. Keep Ollama running as well.";
}
