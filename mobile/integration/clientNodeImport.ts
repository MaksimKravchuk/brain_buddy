import assert from "node:assert/strict";

import { createApiClient } from "../src/api/client";
import { IntentSnapshotRegistry } from "../src/utils/intentSnapshot";

/** Node/tsx preflight: keep the mobile API client's import graph React-Native-free. */
export function verifyNodeSafeClientImport(): void {
  assert.equal(typeof createApiClient, "function");

  const registry = new IntentSnapshotRegistry();
  const request = {
    method: "POST",
    baseUrl: "https://example.test/api",
    requestEpoch: 7,
    path: "/agent-runs/run-1/reply",
    body: { message: "same intent", nested: { right: 2, left: 1 } },
  };

  assert.equal(registry.hold("reply", "relay-key", request), "relay-key");
  assert.equal(
    registry.hold("reply", "relay-key", {
      path: request.path,
      requestEpoch: request.requestEpoch,
      baseUrl: request.baseUrl,
      method: request.method,
      body: { nested: { left: 1, right: 2 }, message: "same intent" },
    }),
    "relay-key",
  );
  registry.settle("relay-key");
  assert.throws(
    () => registry.hold("reply", "relay-key", { ...request, body: { message: "changed" } }),
    /cannot be reused with a different request/,
  );
  registry.preserve("relay-key");
  assert.equal(
    registry.hold("reply", "relay-key", { ...request, body: { message: "changed" } }),
    "relay-key",
  );
  registry.settle("relay-key");
}
