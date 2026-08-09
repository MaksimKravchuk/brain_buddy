import type {
  AgentCapabilities,
  AgentConnectionResponse,
  AgentConnectionStatus,
  AgentRunResponse,
} from "../../api/types";
import {
  canCancel,
  canDisconnect,
  canHandOff,
  canOpenResultLink,
  canReplaceSigningSecret,
  canReply,
  canRotateCredential,
  canTestConnection,
} from "../agentGuards";

const ALL_CAPS: AgentCapabilities = { progress: true, reply: true, cancel: true };

function makeConnection(
  overrides: Partial<AgentConnectionResponse> = {},
): AgentConnectionResponse {
  return {
    id: "conn1",
    name: "Hermes",
    endpoint_url: "https://agent.example.test/hook",
    auth_header_name: "Authorization",
    status: "ready",
    stale: false,
    ready_for_handoff: true,
    capabilities: { ...ALL_CAPS },
    last_test_error_code: null,
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
    capabilities: { ...ALL_CAPS },
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
    expect(canReply(makeRun(), ALL_CAPS)).toEqual({ ok: true });
  });

  it("defaults to the run's own disclosed capabilities", () => {
    expect(canReply(makeRun())).toEqual({ ok: true });
    expect(
      canReply(makeRun({ capabilities: { progress: true, reply: false, cancel: true } })).ok,
    ).toBe(false);
  });

  it("refuses when the connector does not support replies", () => {
    const guard = canReply(makeRun(), { progress: true, reply: false, cancel: true });
    expectSentence(guard);
    expect(guard.ok === false && guard.reason).toBe("This agent does not support replies.");
  });

  it("refuses on a run that was never sent", () => {
    expectSentence(canReply(makeRun({ dispatch_state: "not_sent" }), ALL_CAPS));
  });

  it("refuses once the connection is disconnected", () => {
    const guard = canReply(makeRun({ connection_disconnected: true }), ALL_CAPS);
    expectSentence(guard);
    expect(guard.ok === false && guard.reason).toContain("disconnected");
  });

  it.each(["completed", "failed", "cancelled"] as const)(
    "refuses on a %s run",
    (reported_state) => {
      const guard = canReply(makeRun({ reported_state }), ALL_CAPS);
      expectSentence(guard);
      expect(guard.ok === false && guard.reason).toContain("already finished");
    },
  );

  it("still allows a reply while an earlier reply is unconfirmed", () => {
    expect(canReply(makeRun({ reply_pending: true }), ALL_CAPS)).toEqual({ ok: true });
  });

  it("still allows a reply after the run stopped reporting", () => {
    expect(canReply(makeRun({ stopped_reporting: true }), ALL_CAPS)).toEqual({ ok: true });
  });

  it("refuses while offline instead of queueing the reply", () => {
    const guard = canReply(makeRun(), ALL_CAPS, { online: false });
    expectSentence(guard);
    expect(guard.ok === false && guard.reason).toContain("offline");
  });
});

describe("canCancel", () => {
  it("allows cancellation on a live run with a cancel-capable connector", () => {
    expect(canCancel(makeRun(), ALL_CAPS)).toEqual({ ok: true });
  });

  it("refuses when the connector does not support cancellation", () => {
    const guard = canCancel(makeRun(), { progress: true, reply: true, cancel: false });
    expectSentence(guard);
    expect(guard.ok === false && guard.reason).toBe("This agent does not support cancellation.");
  });

  it("refuses a duplicate intent while cancellation is already requested", () => {
    const guard = canCancel(makeRun({ cancel_requested: true }), ALL_CAPS);
    expectSentence(guard);
    expect(guard.ok === false && guard.reason).toContain("already requested");
  });

  it.each(["completed", "failed", "cancelled"] as const)(
    "refuses on a %s run",
    (reported_state) => {
      expectSentence(canCancel(makeRun({ reported_state }), ALL_CAPS));
    },
  );

  it("refuses once the connection is disconnected", () => {
    expectSentence(canCancel(makeRun({ connection_disconnected: true }), ALL_CAPS));
  });

  it("refuses while offline instead of queueing the request", () => {
    expectSentence(canCancel(makeRun(), ALL_CAPS, { online: false }));
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

  it("replaces the signing secret on any connection that is not disconnected", () => {
    // Recovery has to work on a connection that is *failing*: an untested or
    // unreachable agent is exactly the one whose secret the owner has lost.
    expect(canReplaceSigningSecret(makeConnection({ status: "untested" }))).toEqual({ ok: true });
    expect(canReplaceSigningSecret(makeConnection({ status: "unreachable" }))).toEqual({
      ok: true,
    });
    expectSentence(canReplaceSigningSecret(makeConnection({ status: "disconnected" })));
    expectSentence(canReplaceSigningSecret(makeConnection(), { online: false }));
  });

  it("does not offer disconnect twice", () => {
    expect(canDisconnect(makeConnection())).toEqual({ ok: true });
    expectSentence(canDisconnect(makeConnection({ status: "disconnected" })));
    expectSentence(canDisconnect(makeConnection(), { online: false }));
  });
});

describe("canOpenResultLink", () => {
  it("opens only a link the server marked interactive", () => {
    expect(
      canOpenResultLink(
        makeRun({ result_link: "https://example.test/r/1", result_link_interactive: true }),
      ),
    ).toEqual({ ok: true });
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
