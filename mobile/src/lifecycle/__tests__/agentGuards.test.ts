import type {
  AgentCapabilities,
  AgentControls,
  AgentConnectionResponse,
  AgentConnectionStatus,
  AgentRunResponse,
} from "../../api/types";
import {
  canCancel,
  canDisconnect,
  canHandOff,
  canOpenResultLink,
  canReply,
  canRotateCredential,
  canTestConnection,
} from "../agentGuards";

const CARD_CAPS: AgentCapabilities = { streaming: true, push_notifications: false };
const ALL_CONTROLS: AgentControls = { reply: true, cancel: true };

function makeConnection(
  overrides: Partial<AgentConnectionResponse> = {},
): AgentConnectionResponse {
  return {
    id: "conn1",
    name: "Hermes",
    agent_address: "https://agent.example.test",
    auth_scheme: "bearer",
    auth_header_name: null,
    status: "ready",
    stale: false,
    ready_for_handoff: true,
    capabilities: { ...CARD_CAPS },
    controls_offered: { ...ALL_CONTROLS },
    card: null,
    guarantee_tier: "best_effort",
    tier_disclosure: "Best-effort single start.",
    tier_disclosure_url: "https://example.invalid/single-start/v1.md",
    cancellation_disclosure: "Cancellation depends on the agent.",
    agent_changed: false,
    best_effort_acknowledged_at: null,
    correlation_id_honoured: null,
    disconnect_reason: null,
    last_test_error_code: null,
    last_test_error_detail: null,
    last_contact_at: "2026-08-09T12:00:00Z",
    last_tested_at: "2026-08-09T12:00:00Z",
    stale_after_seconds: 86_400,
    created_at: "2026-08-01T00:00:00Z",
    revision: 1,
    ...overrides,
  };
}

function makeRun(overrides: Partial<AgentRunResponse> = {}): AgentRunResponse {
  return {
    id: "run1",
    task_id: "task1",
    connection_id: "conn1",
    agent_name: "Hermes",
    dispatch_state: "sent",
    dispatch_error_code: null,
    reported_state: "blocked",
    run_version: 3,
    stopped_reporting: false,
    connection_disconnected: false,
    reply_pending: false,
    cancel_requested: false,
    needs_user: true,
    primary_state_label: "Needs you",
    progress_text: null,
    question_text: "Which vendor should I book?",
    result_text: null,
    result_link: null,
    result_link_interactive: false,
    failure_reason: null,
    content_expired: false,
    content_expires_at: "2026-09-08T00:00:00Z",
    last_contact_at: "2026-08-09T12:00:00Z",
    reporting_window_seconds: 900,
    capabilities: { ...ALL_CONTROLS },
    guarantee_tier: "best_effort",
    message_id: "run1:start",
    correlation_id: "run1",
    agent_task_id: null,
    exchange_open: false,
    exchange_state: "closed",
    exchange_kind: "start",
    push_registration: "unregistered",
    agent_task_missing: false,
    cancel_outcome: "none",
    blocked_reason: null,
    artifacts_summary: [],
    result_availability: null,
    last_observed_at: null,
    observation_interval_seconds: 60,
    identifiers_expired: false,
    manifest: null,
    events: [],
    commands: [],
    created_at: "2026-08-09T11:00:00Z",
    revision: 4,
    ...overrides,
  };
}

/** Every refusal is a sentence the user can read as-is. */
function expectSentence(guard: ReturnType<typeof canHandOff>) {
  expect(guard.ok).toBe(false);
  if (guard.ok) {
    return;
  }
  expect(guard.reason.length).toBeGreaterThan(0);
  expect(guard.reason[0]).toBe(guard.reason[0].toUpperCase());
  expect(guard.reason.endsWith(".")).toBe(true);
}

describe("canHandOff", () => {
  it("allows a tested, fresh, connected agent", () => {
    expect(canHandOff(makeConnection())).toEqual({ ok: true });
  });

  it("refuses a disconnected connection before any task content moves", () => {
    const guard = canHandOff(makeConnection({ status: "disconnected", ready_for_handoff: false }));
    expectSentence(guard);
    expect(guard.ok === false && guard.reason).toContain("disconnected");
  });

  it.each<AgentConnectionStatus>(["untested", "invalid_credentials", "unreachable", "unsupported"])(
    "refuses a %s connection and asks for a successful test",
    (status) => {
      const guard = canHandOff(makeConnection({ status, ready_for_handoff: false }));
      expectSentence(guard);
      expect(guard.ok === false && guard.reason).toContain("Test this connection");
    },
  );

  it("refuses a stale connection even though its last test succeeded", () => {
    const guard = canHandOff(makeConnection({ stale: true, ready_for_handoff: false }));
    expectSentence(guard);
    expect(guard.ok === false && guard.reason).toContain("not been in contact recently");
  });

  it("agrees with the server's own ready_for_handoff flag", () => {
    const statuses: AgentConnectionStatus[] = [
      "untested",
      "ready",
      "invalid_credentials",
      "unreachable",
      "unsupported",
      "disconnected",
    ];
    for (const status of statuses) {
      for (const stale of [false, true]) {
        const ready = status === "ready" && !stale;
        const connection = makeConnection({ status, stale, ready_for_handoff: ready });
        expect(canHandOff(connection).ok).toBe(ready);
      }
    }
  });

  it("refuses while offline rather than promising a dispatch", () => {
    const guard = canHandOff(makeConnection(), { online: false });
    expectSentence(guard);
    expect(guard.ok === false && guard.reason).toContain("offline");
  });
});

describe("canReply", () => {
  it("allows a reply on a live run with a reply-capable connector", () => {
    expect(canReply(makeRun(), ALL_CONTROLS)).toEqual({ ok: true });
  });

  it("defaults to the run's own disclosed capabilities", () => {
    expect(canReply(makeRun())).toEqual({ ok: true });
    expect(
      canReply(makeRun({ capabilities: { reply: false, cancel: true } })).ok,
    ).toBe(false);
  });

  it("refuses when the connector does not support replies", () => {
    const guard = canReply(makeRun(), { reply: false, cancel: true });
    expectSentence(guard);
    expect(guard.ok === false && guard.reason).toBe("This agent does not support replies.");
  });

  it("refuses on a run that was never sent", () => {
    expectSentence(canReply(makeRun({ dispatch_state: "not_sent" }), ALL_CONTROLS));
  });

  it("refuses once the connection is disconnected", () => {
    const guard = canReply(makeRun({ connection_disconnected: true }), ALL_CONTROLS);
    expectSentence(guard);
    expect(guard.ok === false && guard.reason).toContain("disconnected");
  });

  it.each(["completed", "failed", "cancelled"] as const)(
    "refuses on a %s run",
    (reported_state) => {
      const guard = canReply(makeRun({ reported_state }), ALL_CONTROLS);
      expectSentence(guard);
      expect(guard.ok === false && guard.reason).toContain("already finished");
    },
  );

  it("still allows a reply while an earlier reply is unconfirmed", () => {
    expect(canReply(makeRun({ reply_pending: true }), ALL_CONTROLS)).toEqual({ ok: true });
  });

  it("still allows a reply after the run stopped reporting", () => {
    expect(canReply(makeRun({ stopped_reporting: true }), ALL_CONTROLS)).toEqual({ ok: true });
  });

  it("refuses while offline instead of queueing the reply", () => {
    const guard = canReply(makeRun(), ALL_CONTROLS, { online: false });
    expectSentence(guard);
    expect(guard.ok === false && guard.reason).toContain("offline");
  });

  it("refuses once authoritative projection marks content expired", () => {
    const guard = canReply(
      makeRun({ content_expired: true, question_text: null }),
      ALL_CONTROLS,
    );
    expectSentence(guard);
    expect(guard.ok === false && guard.reason).toContain("expired");
  });
});

describe("canCancel", () => {
  it("allows cancellation on a live run with a cancel-capable connector", () => {
    expect(canCancel(makeRun(), ALL_CONTROLS)).toEqual({ ok: true });
  });

  it("refuses when the connector does not support cancellation", () => {
    const guard = canCancel(makeRun(), { reply: true, cancel: false });
    expectSentence(guard);
    expect(guard.ok === false && guard.reason).toBe("This agent does not support cancellation.");
  });

  it("refuses a duplicate intent while cancellation is already requested", () => {
    const guard = canCancel(makeRun({ cancel_requested: true }), ALL_CONTROLS);
    expectSentence(guard);
    expect(guard.ok === false && guard.reason).toContain("already requested");
  });

  it.each(["completed", "failed", "cancelled"] as const)(
    "refuses on a %s run",
    (reported_state) => {
      expectSentence(canCancel(makeRun({ reported_state }), ALL_CONTROLS));
    },
  );

  it("refuses once the connection is disconnected", () => {
    expectSentence(canCancel(makeRun({ connection_disconnected: true }), ALL_CONTROLS));
  });

  it("refuses while offline instead of queueing the request", () => {
    expectSentence(canCancel(makeRun(), ALL_CONTROLS, { online: false }));
  });

  it("still allows cancellation after content expiry on a nonterminal run", () => {
    const guard = canCancel(
      makeRun({ content_expired: true, question_text: null }),
      ALL_CONTROLS,
    );
    expect(guard).toEqual({ ok: true });
  });
});

describe("connection management guards", () => {
  it("tests any connection that is not disconnected", () => {
    expect(canTestConnection(makeConnection({ status: "untested" }))).toEqual({ ok: true });
    expect(canTestConnection(makeConnection({ status: "invalid_credentials" }))).toEqual({
      ok: true,
    });
    expectSentence(canTestConnection(makeConnection({ status: "disconnected" })));
    expectSentence(canTestConnection(makeConnection(), { online: false }));
  });

  it("rotates a credential on any connection that is not disconnected", () => {
    expect(canRotateCredential(makeConnection({ status: "unreachable" }))).toEqual({ ok: true });
    expectSentence(canRotateCredential(makeConnection({ status: "disconnected" })));
    expectSentence(canRotateCredential(makeConnection(), { online: false }));
  });

  it("does not offer disconnect twice", () => {
    expect(canDisconnect(makeConnection())).toEqual({ ok: true });
    expectSentence(canDisconnect(makeConnection({ status: "disconnected" })));
    expectSentence(canDisconnect(makeConnection(), { online: false }));
  });
});

describe("canOpenResultLink", () => {
  it("014-SC-004 opens no address an agent reported, however well formed", () => {
    // Product decision, 2026-09-04 (M-03-S10). A link the product makes
    // tappable is a link the product is vouching for, and Brain Buddy verified
    // nothing about where it leads — so even a well-formed HTTPS address the
    // server once marked interactive stays inert text beside **Copy link**.
    expectSentence(
      canOpenResultLink(
        makeRun({ result_link: "https://example.test/r/1", result_link_interactive: true }),
      ),
    );
  });

  it("keeps a non-interactive link as plain text", () => {
    const guard = canOpenResultLink(
      makeRun({ result_link: "javascript:alert(1)", result_link_interactive: false }),
    );
    expectSentence(guard);
  });

  it("refuses when there is no link at all", () => {
    expectSentence(canOpenResultLink(makeRun({ result_link: null })));
  });
});

describe("014-SC-004 the guards agree with the server on every state", () => {
  /**
   * M-03-S22 and the withdrawal rules, over the full enumeration.
   *
   * The guards are what decide whether iOS *offers* a control at all, so a gap
   * here is a control the user can press that the server will refuse — which
   * reads to them as the product being broken rather than the agent being
   * unable.
   */
  it.each([
    ["a live blocked run", {}, true],
    ["a run the agent no longer reports", { agent_task_missing: true }, false],
    ["a terminal run", { reported_state: "completed" as const }, false],
    ["a disconnected connection", { connection_disconnected: true }, false],
    ["a run that never left", { dispatch_state: "not_sent" as const }, false],
    ["expired content", { content_expired: true }, false],
  ])("offers reply for %s: %s", (_name, overrides, expected) => {
    const run = makeRun({
      reported_state: "blocked",
      needs_user: true,
      question_text: "Which environment?",
      ...overrides,
    });

    expect(canReply(run).ok).toBe(expected);
  });

  it.each([
    ["nothing said yet", { cancel_outcome: "none" as const }, true],
    ["an ambiguous answer", { cancel_outcome: "unconfirmed" as const }, true],
    ["an explicit refusal", { cancel_outcome: "unsupported" as const }, false],
    ["a task that cannot be cancelled", { cancel_outcome: "not_cancelable" as const }, false],
    ["a task the agent forgot", { agent_task_missing: true }, false],
  ])("offers cancel for %s: %s", (_name, overrides, expected) => {
    const run = makeRun({ reported_state: "running", ...overrides });

    expect(canCancel(run).ok).toBe(expected);
  });

  it("014-SC-004 M-03-S22 refuses both offline and queues nothing", () => {
    const run = makeRun({
      reported_state: "blocked",
      needs_user: true,
      question_text: "Which environment?",
    });

    const reply = canReply(run, run.capabilities, { online: false });
    const cancel = canCancel(run, run.capabilities, { online: false });

    expect(reply.ok).toBe(false);
    expect(cancel.ok).toBe(false);
    // A sentence the user can act on, not a silent disabled control — and
    // deliberately no queue: a reply held until the network returns would be
    // sent to a question the agent may have moved past.
    expectSentence(reply);
    expectSentence(cancel);
  });

  it("014-SC-004 an ambiguous cancellation keeps the control it already used", () => {
    // AC-029. Brain Buddy does not know whether the request landed, and hiding
    // the control would present its own uncertainty as the agent's refusal.
    const run = makeRun({
      reported_state: "running",
      cancel_requested: true,
      cancel_outcome: "unconfirmed",
    });

    expect(canCancel(run)).toEqual({ ok: true });
  });
});
