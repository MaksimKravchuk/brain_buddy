/**
 * 006-FR-008 / 006-FR-017 — what one rejection of a queued classification
 * change means, and what may follow it.
 *
 * The load-bearing case is the two different 409s. The backend raises
 * `ConflictError("Task", id)` for a stale revision and
 * `ConflictError("Idempotency-Key", key)` when a stored key arrives with a
 * different request hash (backend/app/modules/tasks/service.py). Both surface
 * as 409 with `detail.resource` as the only distinguishing field, and only the
 * first is a disagreement to put to a person.
 */

import type { PendingClassificationChange } from "../classificationTypes";
import {
  decideOnRejection,
  rejectionFromError,
  serverHoldsIntendedValue,
  type ClassificationState,
  type ConflictDecision,
  type SendRejection,
} from "../conflictDecision";

const ENTRY: PendingClassificationChange = {
  taskId: "task_1",
  accountId: "user_1",
  serverUrl: "https://api.example.test",
  value: { projectId: "project_q3", tagIds: ["tag_home", "tag_deep"] },
  observedRevision: 4,
  originalValue: { projectId: "project_inbox", tagIds: [] },
  firstQueuedAt: "2026-08-11T11:00:00.000Z",
  lastEditedAt: "2026-08-11T11:46:00.000Z",
  firstSentAt: "2026-08-11T11:47:00.000Z",
  idempotencyKey: "key-1",
  sendState: "sending",
};

const STALE_REVISION: SendRejection = {
  status: 409,
  detail: { resource: "Task", id: "task_1" },
  serverMessage: "Task 'task_1' has newer changes; reload before saving.",
  correlationId: "corr-stale",
};

const IDEMPOTENCY_REUSE: SendRejection = {
  status: 409,
  detail: { resource: "Idempotency-Key", id: "key-1" },
  serverMessage: "Idempotency-Key 'key-1' already exists.",
  correlationId: "corr-key",
};

const UNREACHABLE: SendRejection = { serverMessage: "Network request failed" };

describe("006-FR-008 a 409 on the Task is the conflict the person decides", () => {
  it("opens the M-04 sheet rather than resolving anything itself", () => {
    const decision = decideOnRejection({ rejection: STALE_REVISION, entry: ENTRY });
    expect(decision.kind).toBe("prompt");
    expect(decision.reason).toBe("stale-revision");
    expect(decision.nextSendState).toBe("conflicted");
    expect(decision.advanceLastSynced).toBe(false);
  });

  it("006-FR-012 carries the correlation id, so the rejection is reportable", () => {
    expect(decideOnRejection({ rejection: STALE_REVISION, entry: ENTRY })).toMatchObject({
      surfaceToPerson: true,
      correlationId: "corr-stale",
    });
  });

  it("006-FR-017 re-mints the key, because resolving the conflict changes the payload", () => {
    // data-model invariant 6: the key is re-minted on a re-send after a
    // conflict is resolved in the person's favour — the revision changes, and
    // `_request_hash` covers it.
    expect(decideOnRejection({ rejection: STALE_REVISION, entry: ENTRY }).reuseIdempotencyKey).toBe(
      false,
    );
  });

  it("keeps the entry: nothing is discarded without the person choosing (006-SC-005)", () => {
    expect(decideOnRejection({ rejection: STALE_REVISION, entry: ENTRY }).nextSendState).not.toBe(
      "removed",
    );
  });
});

describe("006-FR-017 a 409 on the Idempotency-Key is a client bug, never a prompt", () => {
  const decision = (): ConflictDecision =>
    decideOnRejection({ rejection: IDEMPOTENCY_REUSE, entry: ENTRY });

  it("is not routed to the conflict sheet: there is no disagreement to show", () => {
    expect(decision().kind).toBe("error");
    expect(decision().reason).toBe("idempotency-key-reuse");
    expect(decision().nextSendState).not.toBe("conflicted");
  });

  it("must never be retried with the same key — that is the forever loop", () => {
    expect(decision().reuseIdempotencyKey).toBe(false);
    expect(decision().automaticRetry).toBe(false);
  });

  it("006-FR-012 surfaces as an error with its correlation id rather than ageing out silently", () => {
    expect(decision()).toMatchObject({ surfaceToPerson: true, correlationId: "corr-key" });
    expect(decision().advanceLastSynced).toBe(false);
  });

  it("006-SC-003 keeps the payload: a client bug must not destroy the person's change", () => {
    expect(decision().nextSendState).toBe("queued");
  });
});

describe("006-FR-008 the server already holds what the entry intended", () => {
  const applied: ClassificationState = {
    projectId: "project_q3",
    tagIds: ["tag_deep", "tag_home"],
  };

  it("006-SC-005 resolves with no prompt — the one explicit exception, nothing is overwritten", () => {
    const decision = decideOnRejection({
      rejection: STALE_REVISION,
      entry: ENTRY,
      serverState: applied,
    });
    expect(decision.kind).toBe("already-applied");
    expect(decision.nextSendState).toBe("removed");
    expect(decision.surfaceToPerson).toBe(false);
  });

  it("006-SC-004 advances the last-synced footer, because the work did land", () => {
    const decision = decideOnRejection({
      rejection: STALE_REVISION,
      entry: ENTRY,
      serverState: applied,
    });
    expect(decision.advanceLastSynced).toBe(true);
  });

  it("006-FR-017 also covers a send that timed out after it had already applied", () => {
    const decision = decideOnRejection({
      rejection: UNREACHABLE,
      entry: ENTRY,
      serverState: applied,
    });
    expect(decision.kind).toBe("already-applied");
    expect(decision.nextSendState).toBe("removed");
  });

  it("still prompts when the server holds something else", () => {
    const decision = decideOnRejection({
      rejection: STALE_REVISION,
      entry: ENTRY,
      serverState: { projectId: "project_archive", tagIds: ["tag_home", "tag_deep"] },
    });
    expect(decision.kind).toBe("prompt");
  });
});

describe("006-FR-008 serverHoldsIntendedValue compares the net effect, not the keystrokes", () => {
  it.each<[string, ClassificationState, boolean]>([
    ["same project, same Tags in another order", { projectId: "p", tagIds: ["b", "a"] }, true],
    ["same project, same Tags repeated", { projectId: "p", tagIds: ["a", "b", "b"] }, true],
    ["a Tag missing", { projectId: "p", tagIds: ["a"] }, false],
    ["an extra Tag", { projectId: "p", tagIds: ["a", "b", "c"] }, false],
    ["another project", { projectId: "other", tagIds: ["a", "b"] }, false],
    ["no project at all", { projectId: null, tagIds: ["a", "b"] }, false],
  ])("%s", (_why, serverState, expected) => {
    const value = { projectId: "p", tagIds: ["a", "b"] };
    expect(serverHoldsIntendedValue(value, serverState)).toBe(expected);
  });

  it("a field the change never touched is not compared", () => {
    const value = { projectId: undefined, tagIds: ["a"] };
    expect(serverHoldsIntendedValue(value, { projectId: "anything", tagIds: ["a"] })).toBe(true);
  });

  it("006-FR-001 a deliberate clear is applied only when the server holds no project", () => {
    const cleared = { projectId: null, tagIds: undefined };
    expect(serverHoldsIntendedValue(cleared, { projectId: null, tagIds: ["a"] })).toBe(true);
    expect(serverHoldsIntendedValue(cleared, { projectId: "p", tagIds: ["a"] })).toBe(false);
  });
});

describe("006-FR-008 every other outcome of a send", () => {
  it.each<[string, SendRejection, ConflictDecision["kind"], ConflictDecision["reason"]]>([
    ["no answer at all: a timeout or a lost connection", UNREACHABLE, "retry", "unreachable"],
    ["a 503 while the server restarts", { status: 503 }, "retry", "server-error"],
    ["a 500", { status: 500 }, "retry", "server-error"],
    ["a 429", { status: 429 }, "retry", "server-error"],
    ["a 401, which the session layer owns", { status: 401 }, "retry", "unauthenticated"],
    [
      "a 404: the task or its target was deleted elsewhere",
      { status: 404, detail: { resource: "Task", id: "task_1" }, correlationId: "corr-gone" },
      "error",
      "target-missing",
    ],
    ["a 400 the server will never accept", { status: 400 }, "error", "rejected"],
    ["a 422 validation failure", { status: 422 }, "error", "rejected"],
    [
      "an unexpected 409 on some other resource",
      { status: 409, detail: { resource: "Project", id: "project_q3" } },
      "error",
      "rejected",
    ],
    ["a 409 with no detail at all", { status: 409 }, "error", "rejected"],
  ])("%s", (_why, rejection, kind, reason) => {
    const decision = decideOnRejection({ rejection, entry: ENTRY });
    expect(decision.kind).toBe(kind);
    expect(decision.reason).toBe(reason);
  });

  it("006-FR-017 a request that got no answer is retried with the same key", () => {
    const decision = decideOnRejection({ rejection: UNREACHABLE, entry: ENTRY });
    expect(decision).toMatchObject({
      reuseIdempotencyKey: true,
      automaticRetry: true,
      nextSendState: "queued",
      surfaceToPerson: false,
    });
  });

  it("006-SC-008 a 401 keeps the work and says nothing: nobody chose to end the session", () => {
    expect(decideOnRejection({ rejection: { status: 401 }, entry: ENTRY })).toMatchObject({
      nextSendState: "queued",
      automaticRetry: false,
      surfaceToPerson: false,
      reuseIdempotencyKey: true,
    });
  });

  it("006-SC-003 a deleted target is told about, not silently discarded", () => {
    const decision = decideOnRejection({
      rejection: { status: 404, detail: { resource: "Task", id: "task_1" }, correlationId: "c" },
      entry: ENTRY,
    });
    expect(decision.nextSendState).not.toBe("removed");
    // `conflicted` is the only send state that means "stopped, and waiting for
    // the person" — the drain must not keep retrying a task that is gone.
    expect(decision.nextSendState).toBe("conflicted");
    expect(decision.automaticRetry).toBe(false);
    expect(decision.surfaceToPerson).toBe(true);
  });

  it("006-SC-005 only the already-applied case ever removes an entry", () => {
    const everyRejection: SendRejection[] = [
      STALE_REVISION,
      IDEMPOTENCY_REUSE,
      UNREACHABLE,
      { status: 401 },
      { status: 404, detail: { resource: "Task", id: "task_1" } },
      { status: 400 },
      { status: 409 },
      { status: 503 },
    ];
    for (const rejection of everyRejection) {
      const decision = decideOnRejection({ rejection, entry: ENTRY });
      expect(decision.nextSendState).not.toBe("removed");
      expect(decision.kind).not.toBe("already-applied");
    }
    // ...and the single exception is the one the design names, where the
    // server already holds exactly what the entry intended.
    const resolved = decideOnRejection({
      rejection: STALE_REVISION,
      entry: ENTRY,
      serverState: { projectId: "project_q3", tagIds: ["tag_home", "tag_deep"] },
    });
    expect(resolved.nextSendState).toBe("removed");
    expect(resolved.kind).toBe("already-applied");
  });

  it("006-FR-017 no decision both keeps the key and forbids the retry it would be used for", () => {
    const decisions = [
      decideOnRejection({ rejection: STALE_REVISION, entry: ENTRY }),
      decideOnRejection({ rejection: IDEMPOTENCY_REUSE, entry: ENTRY }),
      decideOnRejection({ rejection: UNREACHABLE, entry: ENTRY }),
    ];
    for (const decision of decisions) {
      if (decision.automaticRetry) {
        expect(decision.nextSendState).toBe("queued");
      }
    }
  });
});

describe("006-FR-008 rejectionFromError reads what the client actually throws", () => {
  it("reads status, detail.resource and the correlation id off an ApiError-shaped throw", () => {
    const apiError = Object.assign(new Error("Conflict"), {
      name: "ApiError",
      status: 409,
      payload: {
        message: "Task 'task_1' has newer changes; reload before saving.",
        detail: { resource: "Task", id: "task_1" },
        reference_id: "corr-body",
      },
      correlationId: "corr-header",
    });
    expect(rejectionFromError(apiError)).toEqual({
      status: 409,
      detail: { resource: "Task", id: "task_1" },
      serverMessage: "Task 'task_1' has newer changes; reload before saving.",
      correlationId: "corr-body",
    });
  });

  it("falls back to the header correlation id when the body carries none", () => {
    const apiError = Object.assign(new Error("Conflict"), {
      status: 409,
      payload: { message: "nope", detail: { resource: "Idempotency-Key", id: "key-1" } },
      correlationId: "corr-header",
    });
    expect(rejectionFromError(apiError).correlationId).toBe("corr-header");
    expect(decideOnRejection({ rejection: rejectionFromError(apiError), entry: ENTRY }).reason).toBe(
      "idempotency-key-reuse",
    );
  });

  it("006-FR-019 a bare network throw has no status, so it is unreachable and not a rejection", () => {
    const rejection = rejectionFromError(new TypeError("Network request failed"));
    expect(rejection.status).toBeUndefined();
    expect(decideOnRejection({ rejection, entry: ENTRY }).reason).toBe("unreachable");
  });

  it("survives a throw that is not an error at all", () => {
    expect(rejectionFromError("something went wrong").status).toBeUndefined();
    expect(rejectionFromError(null).status).toBeUndefined();
    expect(rejectionFromError({ status: "409" }).status).toBeUndefined();
  });
});
