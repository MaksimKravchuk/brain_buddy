/**
 * 006-FR-019 — the client must tell an authentication rejection apart from a
 * failure to reach the server, and end the session only on the former.
 *
 * The rules live in a pure module rather than inside `SessionProvider`
 * because `mobile/` cannot render a component in a test: left in the provider
 * they would have no testable home at all.
 */

import { ApiError } from "../../api/client";
import { classifySessionFailure, resolveFailedProbe } from "../sessionOutcome";

function apiError(status: number): ApiError {
  return new ApiError("Request failed", status, { message: "no" }, "corr-1");
}

/** An error identified by `name`, the way DOM/RN aborts and timeouts are. */
function namedError(name: string, message: string): Error {
  const error = new Error(message);
  error.name = name;
  return error;
}

describe("classifySessionFailure", () => {
  it("006-FR-019 reads a 401 as an authentication rejection", () => {
    expect(classifySessionFailure(apiError(401))).toBe("unauthenticated");
  });

  it.each([500, 502, 503, 504])(
    "006-FR-019 reads a %i as other — the server answered, so nothing rejected the session",
    (status) => {
      expect(classifySessionFailure(apiError(status))).toBe("other");
    },
  );

  it.each([403, 404, 409, 422, 429])(
    "006-FR-019 reads a %i as other — only 401 is an authentication rejection",
    (status) => {
      expect(classifySessionFailure(apiError(status))).toBe("other");
    },
  );

  it("006-FR-019 reads a bare TypeError as unreachable — that is what fetch throws offline", () => {
    // React Native's fetch: "Network request failed". undici (Node, used by the
    // integration harness): "fetch failed". Both are a plain TypeError.
    expect(classifySessionFailure(new TypeError("Network request failed"))).toBe("unreachable");
    expect(classifySessionFailure(new TypeError("fetch failed"))).toBe("unreachable");
  });

  it("006-FR-019 reads a request timeout as unreachable, never as a rejection", () => {
    // The client arms `AbortSignal.timeout(30_000)` on every request; a bad
    // connection surfaces as that timeout far more often than as a refusal.
    expect(classifySessionFailure(namedError("TimeoutError", "The operation timed out"))).toBe(
      "unreachable",
    );
    expect(classifySessionFailure(namedError("AbortError", "Aborted"))).toBe("unreachable");
  });

  it("006-FR-019 reads something it does not recognise as other, never as unreachable", () => {
    // Claiming unreachable would assert something about the network that the
    // value does not support; other is the honest answer.
    expect(classifySessionFailure(new Error("boom"))).toBe("other");
    expect(classifySessionFailure("boom")).toBe("other");
    expect(classifySessionFailure(undefined)).toBe("other");
  });
});

describe("resolveFailedProbe", () => {
  const known = { accountId: "acct-1" };
  const rejected = { accountId: "acct-1", sessionRejectedAt: "2026-08-11T09:00:00.000Z" };

  it("006-FR-019 signs the person out on a rejection even though the device knows the identity", () => {
    expect(resolveFailedProbe("unauthenticated", known)).toBe("signed-out");
  });

  it("006-SC-008 keeps an unreachable server's session as signed-in-offline", () => {
    // The queue is discarded on a deliberate sign-out. Collapsing an offline
    // launch onto signed-out is what would destroy it on the feature's main
    // path, so the offline launch has to be representable as its own state.
    expect(resolveFailedProbe("unreachable", known)).toBe("signed-in-offline");
  });

  it("006-SC-008 does not end the session on a server-side failure either", () => {
    expect(resolveFailedProbe("other", known)).toBe("signed-in-offline");
  });

  it("006-FR-019 falls back to signed-out when no identity was ever persisted", () => {
    expect(resolveFailedProbe("unreachable", null)).toBe("signed-out");
    expect(resolveFailedProbe("other", null)).toBe("signed-out");
    expect(resolveFailedProbe("unauthenticated", null)).toBe("signed-out");
  });

  it("006-FR-019 stays signed out offline once the session has already been rejected", () => {
    // A 401 seen while online is knowledge; a later offline launch must not
    // resurrect the session it already learned was over.
    expect(resolveFailedProbe("unreachable", rejected)).toBe("signed-out");
    expect(resolveFailedProbe("other", rejected)).toBe("signed-out");
  });
});
