import { afterEach, describe, expect, it, vi } from "vitest";
import { createClientProof, takeProviderCallback, saveProviderAttempt, safeAuthDestination } from "../authFlow";

describe("023-FR-015/021 provider client proof and restricted destinations", () => {
  afterEach(() => { sessionStorage.clear(); history.replaceState(null, "", "/"); vi.restoreAllMocks(); });
  it("creates a 32-byte cryptographic verifier and S256 challenge", async () => {
    const result = await createClientProof();
    expect(result.verifier).toMatch(/^[\w-]{43}$/);
    expect(result.challenge).toMatch(/^[\w-]{43}$/);
    expect(result.verifier).not.toBe(result.challenge);
  });
  it("clears the fragment immediately and consumes matching callback state once", () => {
    const token = "a".repeat(43);
    saveProviderAttempt({ attemptId: token, state: token, verifier: "v".repeat(43), purpose: "login", destination: "/", expiresAt: Date.now() + 60000 });
    history.replaceState(null, "", `/auth/complete#attempt=${token}&state=${token}&grant=${token}`);
    const result = takeProviderCallback();
    if (!("request" in result)) throw new Error("Expected a successful handoff");
    expect(location.hash).toBe("");
    expect(result.request.handoff_code).toBe(token);
    expect(result.request.client_verifier).toBe("v".repeat(43));
    expect(() => takeProviderCallback()).toThrow();
    expect(sessionStorage.length).toBe(0);
  });
  it("rejects duplicate fields, stale attempts and arbitrary redirect destinations", () => {
    history.replaceState(null, "", "/auth/complete#attempt=a&attempt=b&state=a&grant=a");
    expect(() => takeProviderCallback()).toThrow();
    expect(location.hash).toBe("");
    expect(safeAuthDestination("//evil.example")).toBe("/");
    expect(safeAuthDestination("/settings/account/delete?expected_owner=A")).toBe("/settings/account/delete?expected_owner=A");
    expect(safeAuthDestination("/settings/account?redirect=https://evil.example")).toBe("/settings/account");
  });
  it.each(["state", "duplicate", "both", "unknown", "expired"])("rejects an invalid cancellation %s before returning a saved destination", failure => {
    const token = "a".repeat(43);
    saveProviderAttempt({ attemptId: token, state: token, verifier: "v".repeat(43), purpose: "login", destination: "/cli/authorize", expiresAt: Date.now() + (failure === "expired" ? -1 : 60000) });
    const state = failure === "state" ? "b".repeat(43) : token;
    const error = failure === "unknown" ? "unsafe-description" : "cancelled";
    const extra = failure === "duplicate" ? "&error=cancelled" : failure === "both" ? `&grant=${token}` : "";
    history.replaceState(null, "", `/auth/complete#attempt=${token}&state=${state}&error=${error}${extra}`);
    expect(() => takeProviderCallback()).toThrow();
    expect(location.hash).toBe(""); expect(sessionStorage.length).toBe(0);
  });
});
