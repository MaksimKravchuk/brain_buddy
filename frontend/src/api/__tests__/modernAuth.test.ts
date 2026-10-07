import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { modernAuthApi } from "../modernAuth";

describe("023-FR-001/006/008/013 Modern authentication wire authority", () => {
  const fetchMock = vi.fn();
  beforeEach(() => { fetchMock.mockReset(); vi.stubGlobal("fetch", fetchMock); });
  afterEach(() => vi.unstubAllGlobals());
  it("sends immutable purpose and owner only in cookie-bearing JSON bodies", async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ challenge_id: "challenge", expires_at: "date", resend_at: "date" }), { headers: { "Content-Type": "application/json" } }));
    const payload = { email: "person@example.com", purpose: "change_email" as const, client: "web" as const, client_challenge: "challenge", expected_account_id: "A", action: "change_email" as const, recent_proof: "proof" };
    await modernAuthApi.requestEmail(payload);
    expect(fetchMock).toHaveBeenCalledWith(expect.stringMatching(/\/auth\/email\/request$/), expect.objectContaining({ method: "POST", credentials: "include", body: JSON.stringify(payload) }));
  });
  it("rejects unknown completion outcomes rather than inventing signed-in authority", async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ status: "ready", user: { id: "A" } }), { headers: { "Content-Type": "application/json" } }));
    await expect(modernAuthApi.verifyEmail({ challenge_id: "challenge", client_verifier: "verifier", code: "123456" })).rejects.toThrow();
  });
  it("rejects incomplete known outcomes and unusable grant expiry", async () => {
    for (const outcome of [{ status: "linked" }, { status: "reset_ready", reset_grant: "grant", expires_at: "invalid" }, { status: "reauthenticated", expires_at: new Date().toISOString() }]) {
      fetchMock.mockResolvedValue(new Response(JSON.stringify(outcome), { headers: { "Content-Type": "application/json" } }));
      await expect(modernAuthApi.completeProvider({ attempt_id: "attempt", state: "state", handoff_code: "grant", client_verifier: "verifier" })).rejects.toThrow();
    }
  });
  it("posts reset and password actions without credentials in URL", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    await modernAuthApi.resetPassword({ reset_grant: "grant", client_verifier: "verifier", new_password: "a-long-password" });
    await modernAuthApi.setPassword({ recent_proof: "proof", expected_account_id: "A", new_password: "a-long-password" });
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/auth\/recovery\/reset$/);
    expect(fetchMock.mock.calls[1][0]).toMatch(/\/account\/auth-password$/);
    expect(fetchMock.mock.calls.map(([url]) => url).join()).not.toContain("grant");
  });
});
