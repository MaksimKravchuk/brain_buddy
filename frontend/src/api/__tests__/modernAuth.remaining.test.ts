import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, setUnauthorizedHandler } from "../client";
import { modernAuthApi } from "../modernAuth";

const owner = { recent_proof: "one-use-proof", expected_account_id: "owner-A" };
const response = (body: unknown, status = 200, headers: Record<string, string> = {}) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });
describe("023-FR-006/008/013/015/018/021 remaining auth transport boundaries", () => {
  const fetchMock = vi.fn<typeof fetch>();
  beforeEach(() => { vi.stubGlobal("fetch", fetchMock); fetchMock.mockReset(); });
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  it("exposes safe account expiry errors and notifies authorization loss only for protected account requests", async () => {
    const unauthorized = vi.fn(); setUnauthorizedHandler(unauthorized);
    try {
      fetchMock.mockResolvedValue(response({ detail: { code: "owner_mismatch" } }, 401, { "X-Correlation-ID": "safe-ref" }));
      await expect(modernAuthApi.accountMethods()).rejects.toMatchObject({ status: 401, correlationId: "safe-ref", message: "Authentication request failed" });
      expect(unauthorized).toHaveBeenCalledTimes(1);
      await expect(modernAuthApi.confirmPassword({ current_password: "private-password", action: "export", expected_account_id: "owner-A" })).rejects.toBeInstanceOf(ApiError);
      expect(unauthorized).toHaveBeenCalledTimes(1);
      expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: "GET", credentials: "include", cache: "no-store", headers: { Accept: "application/json" } });
      expect(fetchMock.mock.calls[1][0]).not.toContain("private-password");
    } finally { setUnauthorizedHandler(null); }
  });
  it("handles a non-JSON failure without echoing upstream credential-bearing text", async () => {
    fetchMock.mockResolvedValue(new Response("secret upstream body", { status: 503 }));
    await expect(modernAuthApi.resendEmail({ challenge_id: "challenge", client_verifier: "private-verifier" })).rejects.toMatchObject({ status: 503, payload: null, message: "Authentication request failed" });
  });
  it("propagates an aborted one-use completion without retry or authentication authority", async () => {
    const aborted = new DOMException("Cancelled", "AbortError"); fetchMock.mockRejectedValue(aborted);
    await expect(modernAuthApi.completeProvider({ attempt_id: "attempt", state: "state", handoff_code: "private-grant", client_verifier: "private-verifier" })).rejects.toBe(aborted);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
  it("accepts only boolean availability flags rather than advertising malformed configuration", async () => {
    fetchMock.mockResolvedValueOnce(response({ password: true, google: false, apple: true, email: false, web_account_origin: null }));
    expect(await modernAuthApi.methods()).toMatchObject({ apple: true, email: false });
    fetchMock.mockResolvedValueOnce(response({ password: true, google: "false", apple: true, email: false }));
    await expect(modernAuthApi.methods()).rejects.toThrow("Invalid methods response");
  });
  it.each([
    { status: "changed_email", user: { id: 42, email: "a@example.com" } },
    { status: "linked", user: { id: "A", email: 42 } },
    { status: "signed_in", user: null },
    { status: "reset_ready", reset_grant: "", expires_at: "2026-10-06T12:00:00Z" },
    { status: "reauthenticated", recent_proof: "proof", expires_at: "invalid" },
    { status: "verify_mailbox", challenge_id: 42, expires_at: "2026-10-06T12:00:00Z", resend_at: "2026-10-06T12:00:00Z" },
    { status: "verify_mailbox", challenge_id: "c", expires_at: "invalid", resend_at: "2026-10-06T12:00:00Z" },
    { status: "verify_mailbox", challenge_id: "c", expires_at: "2026-10-06T12:00:00Z", resend_at: "invalid" }
  ])("rejects malformed proof/account authority in known outcome $status", async outcome => {
    fetchMock.mockResolvedValue(response(outcome));
    await expect(modernAuthApi.verifyEmail({ challenge_id: "c", code: "123456", client_verifier: "verifier" })).rejects.toThrow();
  });
  it("returns valid recent proof and staged mailbox authority without changing their purpose", async () => {
    const proof = { status: "reauthenticated", recent_proof: "proof", expires_at: "2026-10-06T12:00:00Z" };
    const mailbox = { status: "verify_mailbox", challenge_id: "c", expires_at: "2026-10-06T12:00:00Z", resend_at: "2026-10-06T11:51:00Z", message: "neutral" };
    fetchMock.mockResolvedValueOnce(response(proof)).mockResolvedValueOnce(response(mailbox));
    expect(await modernAuthApi.verifyEmail({ challenge_id: "c", code: "123456", client_verifier: "verifier" })).toEqual(proof);
    expect(await modernAuthApi.completeProvider({ attempt_id: "attempt", state: "state", handoff_code: "grant", client_verifier: "verifier" })).toEqual(mailbox);
  });
  it("keeps provider start, unlink and deletion bodies bound to the captured owner", async () => {
    fetchMock.mockResolvedValueOnce(response({ attempt_id: "attempt", state: "state", nonce: "nonce", authorization_url: "https://appleid.apple.com/auth/authorize" })).mockResolvedValueOnce(response({ methods: { account_id: "owner-A" }, signed_out: false })).mockResolvedValueOnce(response({ purge_at: "2026-10-20T12:00:00Z" }, 202));
    await modernAuthApi.startProvider("apple", { purpose: "link", client: "web", client_challenge: "challenge", action: "link:apple", ...owner });
    await modernAuthApi.unlink("apple", owner); await modernAuthApi.deleteAccount(owner);
    expect(fetchMock.mock.calls.map(([url]) => String(url))).toEqual([expect.stringMatching(/\/auth\/providers\/apple\/start$/), expect.stringMatching(/\/account\/auth-methods\/apple\/unlink$/), expect.stringMatching(/\/account\/auth-delete$/)]);
    expect(fetchMock.mock.calls.map(([, init]) => JSON.parse(String(init?.body)))).toEqual([expect.objectContaining(owner), owner, owner]);
  });
  it("downloads an owner-protected export and always revokes its temporary blob URL", async () => {
    const createUrl = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:account-export");
    const revoke = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    let download = "";
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) { download = this.download; });
    fetchMock.mockResolvedValue(new Response("zip", { headers: { "Content-Disposition": 'attachment; filename="safe-export.zip"' } }));
    expect(await modernAuthApi.exportAccount(owner)).toBe("safe-export.zip");
    expect(download).toBe("safe-export.zip"); expect(document.querySelector('a[download]')).toBeNull();
    expect(createUrl).toHaveBeenCalledWith(expect.any(Blob)); expect(revoke).toHaveBeenCalledWith("blob:account-export");
    expect(fetchMock.mock.calls[0][0]).not.toContain(owner.recent_proof);
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: "POST", body: JSON.stringify(owner) });
  });
});
