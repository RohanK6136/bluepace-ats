import test from "node:test";
import assert from "node:assert/strict";
import {
  getLoopbackNetworkPermission,
  localAiPermissionHelp,
  localAiServiceHelp,
} from "./localNetworkAccess.mjs";

test("queries Edge Local Network Access permission first", async () => {
  const calls = [];
  const permissions = {
    async query({ name }) {
      calls.push(name);
      if (name === "local-network-access") return { state: "denied" };
      throw new Error("should not query fallback");
    },
  };
  const result = await getLoopbackNetworkPermission(permissions, "Mozilla/5.0 Edg/157.0.0.0");
  assert.deepEqual(result, { state: "denied", permissionName: "local-network-access" });
  assert.deepEqual(calls, ["local-network-access"]);
});

test("uses granular loopback permission when combined name is unsupported", async () => {
  const permissions = {
    async query({ name }) {
      if (name === "loopback-network") return { state: "granted" };
      throw new TypeError("unknown permission");
    },
  };
  const result = await getLoopbackNetworkPermission(permissions, "Chrome/150.0");
  assert.deepEqual(result, { state: "granted", permissionName: "loopback-network" });
});

test("treats unsupported permission APIs as prompt so user action can continue", async () => {
  assert.deepEqual(await getLoopbackNetworkPermission(null, ""), { state: "prompt", permissionName: null });
  const result = await getLoopbackNetworkPermission({ query: async () => { throw new TypeError(); } }, "Chrome/150");
  assert.deepEqual(result, { state: "prompt", permissionName: null });
});

test("provides actionable but distinct browser-permission and local-service guidance", () => {
  assert.match(localAiPermissionHelp("https://bluepace-ats-frontend.vercel.app"), /Local network access/);
  assert.match(localAiServiceHelp(), /127\.0\.0\.1:8000/);
  assert.notEqual(localAiPermissionHelp(), localAiServiceHelp());
});
