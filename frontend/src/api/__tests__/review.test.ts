import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, setUnauthorizedHandler } from "../client";
import {
  describeReviewError,
  newIdempotencyKey,
  parseDecisionResponse,
  parseErrorEnvelope,
  parseReviewSettings,
  parseReviewState,
  parseTaskResponse,
  parseUndoDecisionResponse,
  REVIEW_MUTATION_TIMEOUT_MS,
  reviewApi,
  ReviewWireError
} from "../review";
import fixtures from "../../features/review/__tests__/review_wire_fixtures.json";

type Entry = (typeof fixtures.entries)[number];

function fixture(id: string): Entry {
  const entry = fixtures.entries.find((candidate) => candidate.id === id);
  if (!entry) throw new Error(`missing wire fixture ${id}`);
  return entry;
}

function body<T = Record<string, unknown>>(id: string): T {
  return structuredClone(fixture(id).body) as T;
}

function jsonResponse(status: number, payload: unknown, headers: Record<string, string> = {}): Response {
  return new Response(status === 204 ? null : JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json", ...headers }
  });
}

const fetchMock = vi.fn<typeof fetch>();
const infoSpy = vi.spyOn(console, "info");
const warnSpy = vi.spyOn(console, "warn");

function lastRequest(): { url: string; init: RequestInit; headers: Headers; json: unknown } {
  const [url, init] = fetchMock.mock.calls[fetchMock.mock.calls.length - 1] as [string, RequestInit];
  const headers = new Headers(init.headers);
  return { url, init, headers, json: init.body ? JSON.parse(String(init.body)) : undefined };
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  infoSpy.mockImplementation(() => undefined);
  warnSpy.mockImplementation(() => undefined);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  setUnauthorizedHandler(null);
  infoSpy.mockReset();
  warnSpy.mockReset();
});

describe("020-FR-045 the copied wire fixtures parse", () => {
  const parsers: Record<string, (value: unknown) => unknown> = {
    TaskResponse: parseTaskResponse,
    DecisionResponse: parseDecisionResponse,
    UndoDecisionResponse: parseUndoDecisionResponse,
    ReviewStateResponse: parseReviewState,
    ReviewSettingsResponse: parseReviewSettings,
    ErrorResponse: parseErrorEnvelope
  };
  const valid = fixtures.entries.filter((entry) => entry.valid && entry.kind === "response" && entry.model in parsers);

  it("020-FR-045 covers every response model the web reads", () => {
    expect(new Set(valid.map((entry) => entry.model))).toEqual(new Set(Object.keys(parsers)));
  });

  it.each(valid.map((entry) => [entry.id, entry.model, entry] as const))(
    "020-FR-045 %s parses as %s without losing a field",
    (_id, model, entry) => {
      const parsed = parsers[model](structuredClone(entry.body));
      if (model === "ErrorResponse") {
        const envelope = entry.body as { message: string; detail: { reason: string }; reference_id: string };
        expect(parsed).toEqual({ message: envelope.message, reason: envelope.detail.reason, referenceId: envelope.reference_id });
      } else {
        expect(parsed).toEqual(entry.body);
      }
    }
  );

  const obj = (id: string): Record<string, unknown> => body<Record<string, unknown>>(id);
  it.each([
    ["a task without an id", () => parseTaskResponse({ ...obj("W-002"), id: 7 })],
    ["a task whose formulation lost its ask instant", () => parseTaskResponse({ ...obj("W-002"), formulation: { ...(obj("W-002").formulation as object), ask_at: 5 } })],
    ["a parked marker without its time", () => parseTaskResponse({ ...obj("W-003"), parked: { formulation_id: "form_x" } })],
    ["a task that is not an object", () => parseTaskResponse(null)],
    ["a state without explainer_seen", () => parseReviewState({ ...obj("W-030"), explainer_seen: "yes" })],
    ["a state whose unseen park lost its task", () => parseReviewState({ ...obj("W-030"), unseen_parks: [{ formulation_id: "form_a", parked_at: "2026-10-08T09:14:03Z" }] })],
    ["a state with counts as a list", () => parseReviewState({ ...obj("W-030"), counts: [] })],
    ["a state whose receipts are not a list", () => parseReviewState({ ...obj("W-030"), receipts: {} })],
    ["a state with an unknown threshold", () => parseReviewState({ ...obj("W-030"), settings: { ...(obj("W-030").settings as object), threshold_days: 10 } })],
    ["settings without a revision", () => parseReviewSettings({ ...obj("W-035"), revision: "4" })],
    ["a decision without its record", () => parseDecisionResponse({ ...obj("W-014"), decision: null })],
    ["a decision whose counts are text", () => parseDecisionResponse({ ...obj("W-014"), session_counts: { done: "1" } })],
    ["an undo without the undone id", () => parseUndoDecisionResponse({ ...obj("W-017"), undone_decision_id: null })],
    ["an error envelope that is a string", () => parseErrorEnvelope("boom")]
  ])("020-FR-045 refuses %s", (_label, parse) => {
    expect(parse).toThrow(ReviewWireError);
  });

  it("020-FR-045 reads an envelope without a reason or reference as nulls", () => {
    expect(parseErrorEnvelope({ message: "Task has newer changes; reload before saving.", detail: { resource: "task", id: "task_1" } })).toEqual({
      message: "Task has newer changes; reload before saving.",
      reason: null,
      referenceId: null
    });
    expect(parseErrorEnvelope({ message: "Nope", detail: null, reference_id: null })).toEqual({ message: "Nope", reason: null, referenceId: null });
  });
});

describe("020-FR-045 review calls", () => {
  it("020-FR-045 reads the review state without an Idempotency-Key and parses it", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, body("W-031"), { "X-Correlation-ID": "corr_state" }));

    const state = await reviewApi.getState();

    expect(state).toEqual(body("W-031"));
    const request = lastRequest();
    expect(request.url).toBe("/api/review/state");
    expect(request.init.method).toBe("GET");
    expect(request.headers.has("Idempotency-Key")).toBe(false);
    expect(request.headers.get("X-Correlation-ID")).toMatch(/^[0-9a-f-]{36}$/);
    expect(request.init.credentials).toBe("include");
  });

  it("020-FR-045 sends a web decision exactly as the golden request, with an Idempotency-Key", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, body("W-014")));

    const response = await reviewApi.decide("task_9f3c2a1b4d5e", body("W-011"), "key-decide-1");

    expect(response).toEqual(body("W-014"));
    const request = lastRequest();
    expect(request.url).toBe("/api/tasks/task_9f3c2a1b4d5e/decisions");
    expect(request.init.method).toBe("POST");
    expect(request.headers.get("Idempotency-Key")).toBe("key-decide-1");
    expect(request.headers.get("Content-Type")).toBe("application/json");
    expect(request.json).toEqual(body("W-011"));
  });

  it("020-FR-045 sends an undo, an explainer acknowledgement, a threshold change and a park acknowledgement with keys", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, body("W-017")))
      .mockResolvedValueOnce(jsonResponse(200, body("W-030")))
      .mockResolvedValueOnce(jsonResponse(200, body("W-035")))
      .mockResolvedValueOnce(jsonResponse(204, null));

    await expect(reviewApi.undoDecision("decision_6b1e", body("W-016"), "key-undo")).resolves.toEqual(body("W-017"));
    expect(lastRequest().url).toBe("/api/review/decisions/decision_6b1e/undo");
    expect(lastRequest().json).toEqual(body("W-016"));
    expect(lastRequest().headers.get("Idempotency-Key")).toBe("key-undo");

    await expect(reviewApi.acknowledgeExplainer(body("W-032"), "key-ack")).resolves.toEqual(body("W-030"));
    expect(lastRequest().url).toBe("/api/review/explainer/acknowledge");
    expect(lastRequest().json).toEqual(body("W-032"));
    expect(lastRequest().headers.get("Idempotency-Key")).toBe("key-ack");

    await expect(reviewApi.updateSettings(body("W-033"), "key-settings")).resolves.toEqual(body("W-035"));
    expect(lastRequest().url).toBe("/api/review/settings");
    expect(lastRequest().init.method).toBe("PUT");
    expect(lastRequest().json).toEqual(body("W-033"));
    expect(lastRequest().headers.get("Idempotency-Key")).toBe("key-settings");

    await expect(reviewApi.acknowledgeParks(body("W-036"), "key-parks")).resolves.toBeUndefined();
    expect(lastRequest().url).toBe("/api/review/parks/acknowledge");
    expect(lastRequest().json).toEqual(body("W-036"));
    expect(lastRequest().headers.get("Idempotency-Key")).toBe("key-parks");
  });

  it("020-FR-045 escapes ids in the path", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, body("W-014")));
    await reviewApi.decide("task/../x", body("W-011"), "key");
    expect(lastRequest().url).toBe("/api/tasks/task%2F..%2Fx/decisions");
  });

  it("020-FR-045 mints a fresh UUID for every new mutation key", () => {
    const first = newIdempotencyKey();
    const second = newIdempotencyKey();
    expect(first).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/);
    expect(second).not.toBe(first);
  });
});

describe("020-FR-045 failures expose the correlation id", () => {
  it.each([
    [409, { message: "Task 'task_1' has newer changes; reload before saving.", detail: { resource: "task", id: "task_1" } }, "stale"],
    [400, { message: "This decision isn't available for this task's current list. Nothing was changed.", detail: { reason: "decision_not_allowed" } }, "decision_not_allowed"],
    [409, { message: "This decision can no longer be undone.", detail: { reason: "undo_unavailable" } }, "undo_unavailable"],
    [400, { message: "The notes would be too long with the previous title.", detail: { reason: "details_too_long" } }, "details_too_long"],
    [400, { message: "This task was already kept 7 more days.", detail: { reason: "extension_already_used" } }, "extension_already_used"],
    [400, { message: "This task doesn't ask for a decision yet.", detail: { reason: "extension_not_due" } }, "extension_not_due"],
    [409, { message: "Idempotency key reused.", detail: { reason: "idempotency_conflict" } }, "idempotency_conflict"],
    [404, { message: "Not found", detail: { reason: "weekly_review_disabled" } }, "weekly_review_disabled"],
    [503, { message: "Service unavailable" }, "other"],
    [422, [{ msg: "field required" }], "other"]
  ] as const)("020-FR-045 a %s answer is classified and keeps its Ref", async (status, payload, kind) => {
    fetchMock.mockResolvedValueOnce(jsonResponse(status, payload, { "X-Correlation-ID": "corr_9c04e2aa" }));

    const caught = await reviewApi.decide("task_1", { type: "complete", expected_revision: 4 }, "key").catch((error: unknown) => error);

    expect(caught).toBeInstanceOf(ApiError);
    expect((caught as ApiError).status).toBe(status);
    expect(describeReviewError(caught)).toEqual({ kind, referenceId: "corr_9c04e2aa" });
  });

  it("020-FR-045 falls back to the envelope's reference_id, then to the id the client sent", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify(body("W-071")), { status: 409, headers: { "Content-Type": "application/json" } })
    );
    const fromEnvelope = await reviewApi.decide("task_1", { type: "complete", expected_revision: 4 }, "key").catch((error: unknown) => error);
    expect(describeReviewError(fromEnvelope)).toEqual({ kind: "id_conflict", referenceId: "corr_8b1d4f6a2c9e" });

    fetchMock.mockResolvedValueOnce(new Response("Bad gateway", { status: 502, headers: { "Content-Type": "text/plain" } }));
    const fromClient = await reviewApi.getState().catch((error: unknown) => error);
    const sent = lastRequest().headers.get("X-Correlation-ID");
    expect(describeReviewError(fromClient)).toEqual({ kind: "other", referenceId: sent });
  });

  it("020-FR-045 turns a network failure into a Ref the person can quote", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));

    const caught = await reviewApi.getState().catch((error: unknown) => error);

    expect(caught).toBeInstanceOf(ApiError);
    expect((caught as ApiError).status).toBe(0);
    expect(describeReviewError(caught)).toEqual({ kind: "network", referenceId: lastRequest().headers.get("X-Correlation-ID") });
  });

  it("020-FR-045 rejects a 200 whose body is not the review contract, with the Ref", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { unexpected: true }, { "X-Correlation-ID": "corr_bad_body" }));

    const caught = await reviewApi.getState().catch((error: unknown) => error);

    expect(caught).toBeInstanceOf(ApiError);
    expect(describeReviewError(caught)).toEqual({ kind: "other", referenceId: "corr_bad_body" });
  });

  it("020-FR-045 aborts a mutation that outlives its timeout", async () => {
    vi.useFakeTimers();
    fetchMock.mockImplementationOnce((_url, init) => new Promise((_resolve, reject) => {
      (init as RequestInit).signal?.addEventListener("abort", () => reject(new DOMException("timed out", "TimeoutError")));
    }));

    const pending = reviewApi.decide("task_1", { type: "complete", expected_revision: 4 }, "key").catch((error: unknown) => error);
    await vi.advanceTimersByTimeAsync(REVIEW_MUTATION_TIMEOUT_MS);

    expect(describeReviewError(await pending).kind).toBe("network");
  });

  it("020-FR-045 passes a caller's abort through", async () => {
    const controller = new AbortController();
    controller.abort();
    fetchMock.mockImplementationOnce((_url, init) =>
      (init as RequestInit).signal?.aborted ? Promise.reject(new DOMException("aborted", "AbortError")) : Promise.resolve(jsonResponse(200, body("W-031")))
    );
    const caught = await reviewApi.getState(controller.signal).catch((error: unknown) => error);
    expect(describeReviewError(caught).kind).toBe("network");
  });

  it("020-FR-045 a caller abort that arrives mid-flight cancels the request", async () => {
    const controller = new AbortController();
    fetchMock.mockImplementationOnce((_url, init) => new Promise((_resolve, reject) => {
      (init as RequestInit).signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
    }));
    const pending = reviewApi.getState(controller.signal).catch((error: unknown) => error);
    controller.abort();
    expect(describeReviewError(await pending).kind).toBe("network");
  });

  it("020-FR-045 signs the session out on a 401", async () => {
    const onUnauthorized = vi.fn();
    setUnauthorizedHandler(onUnauthorized);
    fetchMock.mockResolvedValueOnce(jsonResponse(401, { message: "Not authenticated" }));

    await reviewApi.getState().catch(() => undefined);

    expect(onUnauthorized).toHaveBeenCalledTimes(1);
  });

  it("020-FR-045 a rejection that is not an Error still yields a Ref and logs only a class name", async () => {
    fetchMock.mockRejectedValueOnce("offline");

    const caught = await reviewApi.getState().catch((error: unknown) => error);

    expect(describeReviewError(caught).kind).toBe("network");
    expect(JSON.stringify(warnSpy.mock.calls)).toContain('"error":"UnknownError"');
  });

  it("020-FR-045 reads the Ref from an error raised by another client when it has no header", () => {
    const fromOtherClient = new ApiError("Conflict", 409, { message: "stale", detail: { resource: "task", id: "task_1" }, reference_id: "corr_env" });
    expect(describeReviewError(fromOtherClient)).toEqual({ kind: "stale", referenceId: "corr_env" });
  });

  it("020-FR-045 describes anything that is not an ApiError as an unexplained failure", () => {
    expect(describeReviewError(new Error("boom"))).toEqual({ kind: "other", referenceId: undefined });
    expect(describeReviewError(new ApiError("x", 400, { detail: { reason: 7 } }))).toEqual({ kind: "other", referenceId: undefined });
    expect(describeReviewError(new ApiError("x", 400, { detail: { reason: "something_new" } }))).toEqual({ kind: "other", referenceId: undefined });
  });
});

describe("020-FR-044 review request telemetry carries ids, codes and timings only", () => {
  it("020-FR-044 logs the route template, never a body or a title", async () => {
    const sentinel = "SENTINEL-TITLE-Renovate";
    fetchMock.mockResolvedValueOnce(jsonResponse(200, body("W-014")));
    await reviewApi.decide("task_9f3c2a1b4d5e", { type: "reformulate", expected_revision: 7, formulation_id: "form_a", title: sentinel }, "key");
    fetchMock.mockResolvedValueOnce(jsonResponse(409, { message: "stale" }, { "X-Correlation-ID": "corr_1" }));
    await reviewApi.decide("task_9f3c2a1b4d5e", { type: "extend", expected_revision: 7, formulation_id: "form_a", reason: sentinel }, "key").catch(() => undefined);
    fetchMock.mockRejectedValueOnce(new TypeError(sentinel));
    await reviewApi.getState().catch(() => undefined);

    const logged = [...infoSpy.mock.calls, ...warnSpy.mock.calls].map((call) => JSON.stringify(call));
    expect(logged).toHaveLength(3);
    expect(logged.join("\n")).not.toContain(sentinel);
    expect(logged[0]).toContain('"route":"/tasks/{task_id}/decisions"');
    expect(logged[0]).toContain('"status":200');
    expect(logged[1]).toContain('"status":409');
    expect(logged[1]).toContain('"correlationId":"corr_1"');
    expect(logged[2]).toContain('"error":"TypeError"');
  });

  it("020-FR-044 reports the time spent in milliseconds", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, body("W-031")));
    await reviewApi.getState();
    const [, payload] = infoSpy.mock.calls[0] as [string, { name: string; durationMs: number; ok: boolean }];
    expect(payload.name).toBe("review.request");
    expect(payload.ok).toBe(true);
    expect(payload.durationMs).toBeGreaterThanOrEqual(0);
  });

  it("020-FR-044 sends the call with the timeout the mutations use", () => {
    expect(REVIEW_MUTATION_TIMEOUT_MS).toBe(30_000);
  });
});
