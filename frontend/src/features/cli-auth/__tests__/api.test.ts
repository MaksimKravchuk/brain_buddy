import { afterEach, describe, expect, it, vi } from "vitest";
import { cliAuthApi } from "../api";

describe("024-FR-013 bounded browser authorization transport", () => {
  afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });
  it("posts a code as JSON with cookies and refuses redirects", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ state: "denied" }), { status: 200 }));
    vi.stubGlobal("fetch", fetcher);
    expect(await cliAuthApi.decision("ABCD-EFGH", "deny", "A", new AbortController().signal)).toEqual({ state: "denied" });
    const [url, options] = fetcher.mock.calls[0];
    expect(url).toMatch(/\/auth\/device\/decision$/);
    expect(url).not.toContain("ABCD");
    expect(options).toMatchObject({ method: "POST", credentials: "include", redirect: "error", cache: "no-store", body: '{"user_code":"ABCD-EFGH","decision":"deny","expected_owner":"A"}' });
  });
  it("suppresses remote error content", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("private-sentinel", { status: 403 })));
    await expect(cliAuthApi.request("ABCD-EFGH", new AbortController().signal)).rejects.toMatchObject({ status: 403, message: "CLI authorization could not complete.", payload: null });
  });
  it.each(["12345678-1234-4234-8234-123456789abc", "private-header-sentinel", "", "a".repeat(500)])("retains only a safe correlation reference %s", async reference => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("private-body-sentinel", { status: 503, headers: { "X-Correlation-ID": reference } })));
    await expect(cliAuthApi.request("ABCD-EFGH", new AbortController().signal)).rejects.toMatchObject({
      status: 503, payload: null, message: "CLI authorization could not complete.",
      correlationId: reference.startsWith("12345678-") ? reference : undefined
    });
  });
  it.each(["timeout", "cancelled", "already cancelled"])("aborts a %s request without extending the grant", async reason => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn((_url, options: RequestInit) => new Promise((_resolve, reject) => {
      const fail = () => reject(new DOMException("Aborted", "AbortError"));
      if (options.signal?.aborted) fail(); else options.signal?.addEventListener("abort", fail);
    })));
    const controller = new AbortController();
    if (reason === "already cancelled") controller.abort();
    const call = cliAuthApi.request("ABCD-EFGH", controller.signal);
    const outcome = expect(call).rejects.toMatchObject({ name: "AbortError" });
    if (reason === "timeout") await vi.advanceTimersByTimeAsync(30000); else controller.abort();
    await outcome;
    expect(vi.getTimerCount()).toBe(0);
  });
});
