import type {
  AgentCapabilities,
  AgentConnectionResponse,
  AgentRunEvent,
  AgentRunResponse,
} from "../../api/types";
import { ApiError } from "../../api/client";
import {
  applyRun,
  applyRuns,
  buildContextCandidates,
  capabilityDisclosure,
  connectionStatusLabel,
  errorReasonCode,
  eventLabel,
  EXPIRED_CONTENT_NOTICE,
  INITIAL_POLL_DELAY_MS,
  isOfflineError,
  isRunPollable,
  isTerminalRun,
  lastContactLabel,
  manifestRejectionReason,
  MAX_CONTEXT_BODY_CHARS,
  MAX_POLL_DELAY_MS,
  nextPollDelay,
  runsNewestFirst,
  sortedEvents,
} from "../machine";

const CAPS: AgentCapabilities = { progress: true, reply: true, cancel: true };

function makeRun(overrides: Partial<AgentRunResponse> = {}): AgentRunResponse {
  return {
    id: "run1",
    task_id: "task1",
    connection_id: "conn1",
    agent_name: "Hermes",
    dispatch_state: "sent",
    dispatch_error_code: null,
    reported_state: "running",
    run_version: 2,
    stopped_reporting: false,
    connection_disconnected: false,
    reply_pending: false,
    cancel_requested: false,
    needs_user: false,
    primary_state_label: "Running",
    progress_text: null,
    question_text: null,
    result_text: null,
    result_link: null,
    result_link_interactive: false,
    failure_reason: null,
    content_expired: false,
    content_expires_at: "2026-09-08T00:00:00Z",
    last_contact_at: "2026-08-09T12:00:00Z",
    reporting_window_seconds: 900,
    capabilities: { ...CAPS },
    manifest: null,
    events: [],
    commands: [],
    created_at: "2026-08-09T11:00:00Z",
    revision: 3,
    ...overrides,
  };
}

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
    capabilities: { ...CAPS },
    last_test_error_code: null,
    last_contact_at: "2026-08-09T12:00:00Z",
    last_tested_at: "2026-08-09T12:00:00Z",
    stale_after_seconds: 86_400,
    created_at: "2026-08-01T00:00:00Z",
    revision: 1,
    ...overrides,
  };
}

function makeEvent(overrides: Partial<AgentRunEvent> = {}): AgentRunEvent {
  return {
    id: "ev1",
    type: "accepted",
    run_version: 1,
    received_at: "2026-08-09T11:00:00Z",
    summary: null,
    ...overrides,
  };
}

describe("terminal and pollable runs", () => {
  it("treats only connector-reported terminal states as terminal", () => {
    for (const state of ["completed", "failed", "cancelled"] as const) {
      expect(isTerminalRun(makeRun({ reported_state: state }))).toBe(true);
    }
    for (const state of ["accepted", "running", "blocked"] as const) {
      expect(isTerminalRun(makeRun({ reported_state: state }))).toBe(false);
    }
    expect(isTerminalRun(makeRun({ reported_state: null }))).toBe(false);
  });

  it("polls a live run and stops on terminal, disconnected, expired, or never-sent", () => {
    expect(isRunPollable(makeRun())).toBe(true);
    expect(isRunPollable(makeRun({ reported_state: null, dispatch_state: "sent" }))).toBe(true);
    expect(isRunPollable(makeRun({ dispatch_state: "delivery_unconfirmed" }))).toBe(true);

    expect(isRunPollable(makeRun({ reported_state: "completed" }))).toBe(false);
    expect(isRunPollable(makeRun({ connection_disconnected: true }))).toBe(false);
    expect(isRunPollable(makeRun({ content_expired: true }))).toBe(false);
    expect(isRunPollable(makeRun({ dispatch_state: "not_sent" }))).toBe(false);
  });

  it("keeps polling a run that stopped reporting — a later event may still arrive", () => {
    expect(isRunPollable(makeRun({ stopped_reporting: true }))).toBe(true);
  });

  it("backs off 1.5s → x2 → 8s cap", () => {
    expect(nextPollDelay(null)).toBe(INITIAL_POLL_DELAY_MS);
    expect(nextPollDelay(1500)).toBe(3000);
    expect(nextPollDelay(3000)).toBe(6000);
    expect(nextPollDelay(6000)).toBe(MAX_POLL_DELAY_MS);
    expect(nextPollDelay(MAX_POLL_DELAY_MS)).toBe(MAX_POLL_DELAY_MS);
    expect(nextPollDelay(0)).toBe(INITIAL_POLL_DELAY_MS);
  });
});

describe("applyRun / applyRuns", () => {
  it("never rolls the projection back to a stale revision", () => {
    const current = makeRun({ revision: 5, run_version: 4 });
    const stale = makeRun({ revision: 3, run_version: 4 });
    expect(applyRun(current, stale)).toBe(current);
    const newer = makeRun({ revision: 6, run_version: 4 });
    expect(applyRun(current, newer)).toBe(newer);
  });

  it("never rolls the connector's authoritative run version back", () => {
    const current = makeRun({ revision: 5, run_version: 9 });
    const stale = makeRun({ revision: 5, run_version: 7 });
    expect(applyRun(current, stale)).toBe(current);
  });

  it("always adopts a different run id", () => {
    const current = makeRun({ id: "run1", revision: 9 });
    const other = makeRun({ id: "run2", revision: 1 });
    expect(applyRun(current, other)).toBe(other);
  });

  it("adopts the incoming list shape while keeping each run monotonic", () => {
    const current = [makeRun({ id: "a", revision: 7 }), makeRun({ id: "b", revision: 2 })];
    const incoming = [
      makeRun({ id: "a", revision: 5 }),
      makeRun({ id: "b", revision: 4 }),
      makeRun({ id: "c", revision: 1 }),
    ];
    const merged = applyRuns(current, incoming);
    expect(merged.map((run) => run.id)).toEqual(["a", "b", "c"]);
    expect(merged[0].revision).toBe(7);
    expect(merged[1].revision).toBe(4);
    expect(merged[2].revision).toBe(1);
  });

  it("orders runs newest first without mutating the input", () => {
    const runs = [
      makeRun({ id: "old", created_at: "2026-08-01T00:00:00Z" }),
      makeRun({ id: "new", created_at: "2026-08-09T00:00:00Z" }),
    ];
    expect(runsNewestFirst(runs).map((run) => run.id)).toEqual(["new", "old"]);
    expect(runs.map((run) => run.id)).toEqual(["old", "new"]);
  });
});

describe("offline honesty", () => {
  it("counts only transport failures as offline — a server answer is not offline", () => {
    expect(isOfflineError(new TypeError("Network request failed"))).toBe(true);
    expect(isOfflineError(new DOMException("timed out", "TimeoutError"))).toBe(true);
    expect(isOfflineError(new ApiError("Bad request", 400, null))).toBe(false);
    expect(isOfflineError(new ApiError("Server error", 500, null))).toBe(false);
    expect(isOfflineError(null)).toBe(false);
  });
});

describe("timeline", () => {
  it("sorts events oldest first by receipt then version, without mutating", () => {
    const events = [
      makeEvent({ id: "c", run_version: 3, received_at: "2026-08-09T11:02:00Z" }),
      makeEvent({ id: "a", run_version: 1, received_at: "2026-08-09T11:00:00Z" }),
      makeEvent({ id: "b", run_version: 2, received_at: "2026-08-09T11:00:00Z" }),
    ];
    const run = makeRun({ events });
    expect(sortedEvents(run).map((event) => event.id)).toEqual(["a", "b", "c"]);
    expect(events.map((event) => event.id)).toEqual(["c", "a", "b"]);
  });

  it("labels a completion as an agent report, never as verified completion", () => {
    expect(eventLabel("completed")).toBe("Agent reported complete");
    expect(eventLabel("accepted")).toBe("Accepted");
    expect(eventLabel("running")).toBe("Running");
    expect(eventLabel("blocked")).toBe("Needs you");
    expect(eventLabel("failed")).toBe("Failed");
    expect(eventLabel("cancelled")).toBe("Cancelled");
  });

  it("states expiry as a retention fact, not as loading or an error", () => {
    expect(EXPIRED_CONTENT_NOTICE).toBe("Content expired under retention policy");
  });
});

describe("connection disclosure", () => {
  it("labels each connection status honestly", () => {
    expect(connectionStatusLabel(makeConnection())).toBe("Ready");
    expect(connectionStatusLabel(makeConnection({ status: "untested" }))).toBe("Not tested yet");
    expect(connectionStatusLabel(makeConnection({ status: "invalid_credentials" }))).toBe(
      "Invalid credentials",
    );
    expect(connectionStatusLabel(makeConnection({ status: "unreachable" }))).toBe("Unreachable");
    expect(connectionStatusLabel(makeConnection({ status: "unsupported" }))).toBe(
      "Connector not supported",
    );
    expect(connectionStatusLabel(makeConnection({ status: "disconnected" }))).toBe("Disconnected");
  });

  it("does not call a stale connection simply ready", () => {
    expect(connectionStatusLabel(makeConnection({ stale: true }))).toBe(
      "Tested, but not in contact recently",
    );
    // A failed status stays the more actionable one.
    expect(connectionStatusLabel(makeConnection({ status: "unreachable", stale: true }))).toBe(
      "Unreachable",
    );
  });

  it("names the unsupported capabilities explicitly", () => {
    expect(capabilityDisclosure({ progress: true, reply: true, cancel: true })).toEqual({
      supported: ["progress updates", "replies", "cancellation"],
      unsupported: [],
    });
    expect(capabilityDisclosure({ progress: false, reply: false, cancel: false })).toEqual({
      supported: [],
      unsupported: ["progress updates", "replies", "cancellation"],
    });
    expect(capabilityDisclosure({ progress: true, reply: false, cancel: true })).toEqual({
      supported: ["progress updates", "cancellation"],
      unsupported: ["replies"],
    });
  });

  it("reports last contact without inventing one", () => {
    const now = Date.parse("2026-08-09T12:00:00Z");
    expect(lastContactLabel(null, now)).toBe("No contact yet");
    expect(lastContactLabel("not-a-date", now)).toBe("Last contact unknown");
    expect(lastContactLabel("2026-08-09T11:59:40Z", now)).toBe("Last contact just now");
    expect(lastContactLabel("2026-08-09T11:59:00Z", now)).toBe("Last contact 1 minute ago");
    expect(lastContactLabel("2026-08-09T11:45:00Z", now)).toBe("Last contact 15 minutes ago");
    expect(lastContactLabel("2026-08-09T11:00:00Z", now)).toBe("Last contact 1 hour ago");
    expect(lastContactLabel("2026-08-09T09:00:00Z", now)).toBe("Last contact 3 hours ago");
    expect(lastContactLabel("2026-08-08T12:00:00Z", now)).toBe("Last contact 1 day ago");
    expect(lastContactLabel("2026-08-05T12:00:00Z", now)).toBe("Last contact 4 days ago");
  });
});

describe("manifest rejections", () => {
  const failure = (reason: string) =>
    new ApiError("Bad request", 400, { message: "…", detail: { reason } });

  it("extracts the server's machine-readable reason code", () => {
    expect(errorReasonCode(failure("reauthentication_required"))).toBe("reauthentication_required");
    expect(errorReasonCode(new ApiError("Bad request", 400, { message: "…" }))).toBeNull();
    expect(errorReasonCode(new Error("boom"))).toBeNull();
    expect(errorReasonCode(new ApiError("Bad request", 400, "plain text"))).toBeNull();
  });

  it("only re-previews for the two manifest reasons", () => {
    expect(manifestRejectionReason(failure("manifest_token_mismatch"))).toBe(
      "manifest_token_mismatch",
    );
    expect(manifestRejectionReason(failure("manifest_not_reserved"))).toBe("manifest_not_reserved");
    expect(manifestRejectionReason(failure("reauthentication_required"))).toBeNull();
    expect(manifestRejectionReason(failure("connection_disconnected"))).toBeNull();
    expect(manifestRejectionReason(new Error("offline"))).toBeNull();
  });
});

describe("buildContextCandidates", () => {
  it("offers classification, subtasks, and comments as separate removable items", () => {
    const items = buildContextCandidates(
      {
        subtasks: [
          { id: "s1", title: "Book venue", state: "open", order_key: 1, revision: 1 },
          { id: "s2", title: "Pay deposit", state: "completed", order_key: 2, revision: 1 },
          { id: "s3", title: "Dropped idea", state: "cancelled", order_key: 3, revision: 1 },
        ],
        comments: [
          {
            id: "c1",
            body: "Vendor quoted 400.",
            actor_id: "u1",
            created_at: "2026-08-09T10:00:00Z",
            edited_at: null,
            revision: 1,
          },
          {
            id: "c2",
            body: "   ",
            actor_id: "u1",
            created_at: "2026-08-09T10:05:00Z",
            edited_at: null,
            revision: 1,
          },
        ],
      },
      { projectName: "Offsite", tagNames: ["calls", "urgent"] },
    );

    expect(items).toEqual([
      { label: "Classification", body: "Project: Offsite\nTags: calls, urgent" },
      { label: "Subtasks", body: "- [ ] Book venue\n- [x] Pay deposit" },
      { label: "Comment", body: "Vendor quoted 400." },
    ]);
  });

  it("returns nothing when the task carries no reviewable context", () => {
    expect(buildContextCandidates({})).toEqual([]);
    expect(buildContextCandidates({ subtasks: [], comments: [] }, {})).toEqual([]);
    expect(
      buildContextCandidates({}, { projectName: null, tagNames: [] }),
    ).toEqual([]);
  });

  it("clamps a long body to the server's limit so review shows exactly what is sent", () => {
    const [item] = buildContextCandidates({
      comments: [
        {
          id: "c1",
          body: "x".repeat(MAX_CONTEXT_BODY_CHARS + 500),
          actor_id: "u1",
          created_at: "2026-08-09T10:00:00Z",
          edited_at: null,
          revision: 1,
        },
      ],
    });
    expect(item.body).toHaveLength(MAX_CONTEXT_BODY_CHARS);
    expect(item.body.endsWith("…")).toBe(true);
  });
});
