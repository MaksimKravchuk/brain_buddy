import { afterEach, describe, expect, it, vi } from "vitest";
import { captureCode, clearCode, normalizeCode, rememberCode, retainedCode } from "../code";

describe("024-FR-013 tab code retention is bounded and never stores device proof", () => {
  afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers(); sessionStorage.clear(); history.replaceState(null, "", "/"); });
  it("normalizes only an unambiguous eight-character code", () => {
    expect(normalizeCode(" abcdefgh ")).toBe("ABCD-EFGH");
    for (const value of ["IO01-ABCD", "ABCD--EFGHZZ", "https://evil.example"]) expect(normalizeCode(value)).toBeNull();
  });
  it("refresh cannot extend the original ten-minute deadline", () => {
    vi.useFakeTimers();
    const first = rememberCode("ABCD-EFGH");
    vi.advanceTimersByTime(10000);
    expect(rememberCode("ABCD-EFGH")?.expiresAt).toBe(first?.expiresAt);
    history.replaceState(null, "", "/cli/authorize#user_code=ABCD-EFGH");
    expect(captureCode("#user_code=ABCD-EFGH")?.expiresAt).toBe(first?.expiresAt);
    expect(location.hash).toBe("");
    expect(captureCode("")?.userCode).toBe("ABCD-EFGH");
  });
  it.each([null, { userCode: "ABCD-EFGH", expiresAt: 0 }, { userCode: "ABCD-EFGH", expiresAt: Date.now() + 900000 }, { userCode: "ABCD-EFGH", expiresAt: "private" }, { userCode: "BAD", expiresAt: Date.now() + 5000 }])("erases invalid or stale state %j", value => {
    sessionStorage.setItem("brainbuddy.cli.authorization", JSON.stringify(value));
    expect(retainedCode()).toBeNull();
    expect(sessionStorage.getItem("brainbuddy.cli.authorization")).toBeNull();
  });
  it("falls back to manual entry when tab storage is blocked", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("Blocked"); });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("Blocked"); });
    vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => { throw new Error("Blocked"); });
    expect(rememberCode("ABCD-EFGH")).toBeNull();
    expect(retainedCode()).toBeNull();
    expect(() => clearCode()).not.toThrow();
  });
  it("rejects malformed JSON, duplicate fragment keys and invalid deadlines", () => {
    sessionStorage.setItem("brainbuddy.cli.authorization", "{");
    expect(retainedCode()).toBeNull();
    expect(captureCode("#user_code=ABCD-EFGH&user_code=JKLM-NPQR")).toBeNull();
    expect(rememberCode("BAD")).toBeNull();
    expect(rememberCode("ABCD-EFGH", Infinity)).toBeNull();
  });
});
