import { QueryClient, QueryClientProvider, onlineManager } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  AgentManifestResponse,
  AgentRunEvent,
  AgentRunResponse
} from "../../../api/agentTypes";
import { ApiError, apiClient } from "../../../api/client";
import { AgentRunSection } from "../AgentRunSection";

function makeRun(overrides: Partial<AgentRunResponse> = {}): AgentRunResponse {
  return {
    id: "agentrun_1",
    task_id: "task_1",
    connection_id: "agentconn_1",
    agent_name: "Hermes",
    dispatch_state: "sent",
    dispatch_error_code: null,
    reported_state: null,
    run_version: 0,
    stopped_reporting: false,
    connection_disconnected: false,
    reply_pending: false,
    cancel_requested: false,
    needs_user: false,
    primary_state_label: "Sent",
    progress_text: null,
    question_text: null,
    result_text: null,
    result_link: null,
    result_link_interactive: false,
    failure_reason: null,
    content_expired: false,
    content_expires_at: "2026-09-08T12:00:00Z",
    last_contact_at: "2026-08-09T12:00:00Z",
    reporting_window_seconds: 3600,
    capabilities: { reply: true, cancel: true },
    guarantee_tier: null,
    message_id: null,
    correlation_id: null,
    agent_task_id: null,
    exchange_open: false,
    exchange_state: "none",
    exchange_kind: null,
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
    created_at: "2026-08-09T12:00:00Z",
    revision: 1,
    ...overrides
  };
}

/** One timeline row with the 014 fields at their "ordinary observation" values. */
function makeEvent(
  overrides: Partial<AgentRunEvent> & Pick<AgentRunEvent, "id" | "type" | "run_version">
): AgentRunEvent {
  return {
    received_at: "2026-08-09T12:00:00Z",
    summary: null,
    trigger: "schedule",
    kind: "observation",
    previous_agent_task_id: null,
    new_agent_task_id: null,
    ...overrides
  };
}

function renderSection(runs: AgentRunResponse[], node?: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return {
    ...render(
      <QueryClientProvider client={client}>
        {node ?? <AgentRunSection taskId="task_1" runs={runs} isLoading={false} error={null} />}
      </QueryClientProvider>
    ),
    client
  };
}

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("AgentRunSection", () => {
  it("renders the server's honest state label verbatim", () => {
    renderSection([makeRun({ primary_state_label: "Agent reported complete", reported_state: "completed" })]);

    expect(screen.getByText("Agent reported complete")).toBeInTheDocument();
    expect(screen.getByText("Hermes")).toBeInTheDocument();
  });

  it("never invents a percentage, stage, or ETA", () => {
    const { container } = renderSection([
      makeRun({ reported_state: "running", primary_state_label: "Running", progress_text: "Cloning the repo" })
    ]);

    expect(screen.getByText("Cloning the repo")).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/%|\bETA\b|\bestimated\b/i);
    expect(container.querySelector("progress")).toBeNull();
  });

  it("shows a reply box only when the connector supports replies", async () => {
    const user = userEvent.setup();
    const reply = vi.spyOn(apiClient, "replyToAgentRun").mockResolvedValue(makeRun());
    renderSection([
      makeRun({
        reported_state: "blocked",
        primary_state_label: "Needs you",
        needs_user: true,
        question_text: "Which environment?",
        revision: 7
      })
    ]);

    expect(screen.getByText("Which environment?")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Your answer"), "Use staging.");
    await user.click(screen.getByRole("button", { name: "Send answer" }));

    expect(reply).toHaveBeenCalledWith(
      "agentrun_1",
      { message: "Use staging.", expected_revision: 7 },
      expect.any(String)
    );
  });

  it("states that replies are unsupported instead of showing a dead control", () => {
    renderSection([
      makeRun({
        reported_state: "blocked",
        primary_state_label: "Needs you",
        needs_user: true,
        question_text: "Which environment?",
        capabilities: { reply: false, cancel: false }
      })
    ]);

    expect(screen.queryByRole("button", { name: "Send answer" })).not.toBeInTheDocument();
    expect(screen.getByText(/does not support replies/i)).toBeInTheDocument();
  });

  it("offers cancellation only when supported and never claims it succeeded", async () => {
    const user = userEvent.setup();
    const cancel = vi.spyOn(apiClient, "cancelAgentRun").mockResolvedValue(makeRun());
    renderSection([makeRun({ reported_state: "running", primary_state_label: "Running" })]);

    await user.click(screen.getByRole("button", { name: "Request cancellation" }));

    expect(cancel).toHaveBeenCalledWith("agentrun_1", expect.any(String));
  });

  it("shows a requested cancellation as unconfirmed", () => {
    renderSection([
      makeRun({
        reported_state: "running",
        cancel_requested: true,
        primary_state_label: "Cancellation requested"
      })
    ]);

    expect(screen.getByText("Cancellation requested")).toBeInTheDocument();
    expect(screen.getByText(/not confirmed/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Request cancellation" })).not.toBeInTheDocument();
  });

  it("hides the cancel control when the connector cannot cancel", () => {
    renderSection([
      makeRun({
        reported_state: "running",
        primary_state_label: "Running",
        capabilities: { reply: true, cancel: false }
      })
    ]);

    expect(screen.queryByRole("button", { name: "Request cancellation" })).not.toBeInTheDocument();
  });

  it("014-SC-004 keeps every reported address inert beside Copy link", () => {
    // Product decision, 2026-09-04 (D-03-S11): even a well-formed HTTPS
    // address the server marked interactive stays text. A link the product
    // renders as navigable is a link the product is vouching for, and
    // BrainBuddy verified nothing about where it leads.
    renderSection([
      makeRun({
        reported_state: "completed",
        primary_state_label: "Agent reported complete",
        result_text: "Here is the plan",
        result_link: "https://results.example.com/1",
        result_link_interactive: true
      })
    ]);

    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.getByText("https://results.example.com/1")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy link" })).toBeInTheDocument();
  });

  it("014-SC-004 Copy link actually copies the address it is showing", async () => {
    // A control labelled "Copy link" that quietly did nothing would be exactly
    // the fabricated affordance this feature's honesty rules exist to prevent.
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText }
    });
    renderSection([
      makeRun({
        reported_state: "completed",
        primary_state_label: "Agent reported complete",
        result_link: "javascript:alert(1)"
      })
    ]);

    await userEvent.click(screen.getByRole("button", { name: "Copy link" }));

    // Whatever the scheme: copying is not navigating, and the address is the
    // user's to inspect.
    expect(writeText).toHaveBeenCalledWith("javascript:alert(1)");
  });

  it("renders an unsafe result link as inert text", () => {
    renderSection([
      makeRun({
        reported_state: "completed",
        primary_state_label: "Agent reported complete",
        result_link: "javascript:alert(1)",
        result_link_interactive: false
      })
    ]);

    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.getByText("javascript:alert(1)")).toBeInTheDocument();
  });

  it("renders agent markup as inert text rather than markup", () => {
    const { container } = renderSection([
      makeRun({
        reported_state: "completed",
        primary_state_label: "Agent reported complete",
        result_text: "<script>alert('x')</script> done"
      })
    ]);

    expect(container.querySelector("script")).toBeNull();
    expect(screen.getByText("<script>alert('x')</script> done")).toBeInTheDocument();
  });

  it("marks expired content explicitly rather than looking like a failure", () => {
    renderSection([
      makeRun({
        reported_state: "completed",
        primary_state_label: "Agent reported complete",
        content_expired: true
      })
    ]);

    expect(screen.getByText("Content expired under retention policy")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("redacts cached content and controls exactly when the local deadline passes", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-09T12:00:00Z"));
    const cached = makeRun({
      reported_state: "blocked",
      primary_state_label: "Needs you",
      needs_user: true,
      progress_text: "Sensitive progress",
      question_text: "Sensitive question?",
      result_text: "Sensitive result",
      result_link: "https://secret.example.test/result",
      failure_reason: "Sensitive failure",
      content_expires_at: "2026-08-09T12:00:01Z",
      events: [
        makeEvent({ id: "evt-sensitive", type: "blocked", run_version: 1, received_at: "2026-08-09T12:00:00Z", summary: "Sensitive summary" })
      ]
    });
    const { container } = renderSection([cached]);

    expect(container).toHaveTextContent("Sensitive question?");
    expect(screen.getByRole("button", { name: "Send answer" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Request cancellation" })).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });

    expect(screen.getByText("Content expired under retention policy")).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/Sensitive (progress|question|result|failure|summary)/);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Send answer" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Request cancellation" })).not.toBeInTheDocument();
    vi.useRealTimers();
  });

  it("shows the chronological timeline of connector reports", () => {
    renderSection([
      makeRun({
        reported_state: "running",
        primary_state_label: "Running",
        events: [
          makeEvent({ id: "evt_1", type: "accepted", run_version: 1, received_at: "2026-08-09T12:00:00Z", summary: null }),
          makeEvent({ id: "evt_2", type: "running", run_version: 2, received_at: "2026-08-09T12:05:00Z", summary: "Cloning" })
        ]
      })
    ]);

    const items = screen.getAllByRole("listitem");
    expect(items.length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("Accepted")).toBeInTheDocument();
  });

  it("renders every honest exceptional projection without inventing work state", () => {
    renderSection(
      [
        makeRun({
          id: "agentrun_exceptional",
          dispatch_state: "delivery_unconfirmed",
          reported_state: "failed",
          primary_state_label: "Failed",
          failure_reason: "Connector rejected the request",
          reply_pending: true,
          stopped_reporting: true,
          connection_disconnected: true,
          events: [
            makeEvent({ id: "evt_blocked", type: "blocked", run_version: 1, received_at: "2026-08-09T12:01:00Z", summary: null }),
            makeEvent({ id: "evt_complete", type: "completed", run_version: 2, received_at: "2026-08-09T12:02:00Z", summary: null }),
            makeEvent({ id: "evt_failed", type: "failed", run_version: 3, received_at: "2026-08-09T12:03:00Z", summary: null }),
            makeEvent({ id: "evt_cancelled", type: "cancelled", run_version: 4, received_at: "2026-08-09T12:04:00Z", summary: null })
          ]
        }),
        makeRun({ id: "agentrun_second", agent_name: "Claude", capabilities: { reply: true, cancel: false } })
      ],
      <AgentRunSection
        taskId="task_1"
        runs={[
          makeRun({
            id: "agentrun_exceptional",
            dispatch_state: "delivery_unconfirmed",
            reported_state: "failed",
            primary_state_label: "Failed",
            failure_reason: "Connector rejected the request",
            reply_pending: true,
            stopped_reporting: true,
            connection_disconnected: true,
            events: [
              makeEvent({ id: "evt_blocked", type: "blocked", run_version: 1, received_at: "2026-08-09T12:01:00Z", summary: null }),
              makeEvent({ id: "evt_complete", type: "completed", run_version: 2, received_at: "2026-08-09T12:02:00Z", summary: null }),
              makeEvent({ id: "evt_failed", type: "failed", run_version: 3, received_at: "2026-08-09T12:03:00Z", summary: null }),
              makeEvent({ id: "evt_cancelled", type: "cancelled", run_version: 4, received_at: "2026-08-09T12:04:00Z", summary: null })
            ]
          }),
          makeRun({ id: "agentrun_second", agent_name: "Claude", capabilities: { reply: true, cancel: false } })
        ]}
        isLoading
        error={null}
      />
    );

    expect(screen.getByText("Agent runs · 2")).toBeInTheDocument();
    expect(screen.getByText("Loading runs…")).toBeInTheDocument();
    expect(screen.getByText("Needs you")).toBeInTheDocument();
    expect(screen.getByText("Agent reported complete")).toBeInTheDocument();
    expect(screen.getAllByText("Failed").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Cancelled")).toBeInTheDocument();
    expect(screen.getByText("Connector rejected the request")).toBeInTheDocument();
    expect(screen.getByText(/answer was sent but the agent has not acknowledged/i)).toBeInTheDocument();
    expect(screen.getByText(/does not know whether the agent is still working/i)).toBeInTheDocument();
    expect(screen.getByText(/disconnecting did not cancel/i)).toBeInTheDocument();
    // 014-FR-006: the agent reported. That *is* the delivery evidence, so the
    // ambiguous-delivery sentence is now known to be false and is withdrawn.
    expect(screen.queryByText(/could not confirm the agent received/i)).toBeNull();
    expect(screen.queryByRole("button", { name: "Check again" })).toBeNull();
  });

  it("says nothing at all when the task has no runs", () => {
    const { container } = renderSection([]);

    expect(container).toBeEmptyDOMElement();
  });

  it("keeps cached runs visible and marks them stale after a failed refresh", () => {
    const cached = makeRun({
      reported_state: "running",
      primary_state_label: "Running",
      progress_text: "Cloning the repo"
    });
    renderSection(
      [cached],
      <AgentRunSection
        taskId="task_1"
        runs={[cached]}
        isLoading={false}
        error={new Error("network unreachable")}
      />
    );

    expect(screen.getByText("Cloning the repo")).toBeInTheDocument();
    expect(screen.getByText("Hermes")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/cached|stale|last known/i);
    expect(screen.getByRole("alert")).toHaveTextContent(/network unreachable/i);
  });

  it("surfaces a load error with its correlation id when no cached run exists", () => {
    renderSection([], <AgentRunSection taskId="task_1" runs={[]} isLoading={false} error={new Error("boom")} />);

    expect(screen.getByRole("alert")).toHaveTextContent(/boom/);
  });
});

/**
 * A retry of a command the server may already have executed.
 *
 * A rejected reply is ambiguous — the request may have reached the relay and
 * only the response was lost — so the retry must arrive under the key the first
 * attempt used, and a *different* thing to say must not.
 */
describe("AgentRunSection idempotency across retries", () => {
  const blocked = () =>
    makeRun({
      reported_state: "blocked",
      primary_state_label: "Needs you",
      needs_user: true,
      question_text: "Which environment?"
    });

  /**
   * Failures that say nothing about whether the command was executed.
   *
   * A transport failure and a 5xx are the obvious ones, but 408 and 429 are the
   * same shape of ignorance wearing a 4xx: both can be raised by a proxy, a
   * gateway or a rate limiter anywhere between the user and the handler, and
   * neither states that this command was rejected. Retrying any of them under a
   * fresh key would turn that ambiguity into a second command (FR-006).
   */
  const AMBIGUOUS_FAILURES: Array<[string, unknown]> = [
    ["network failure", new Error("network unreachable")],
    ["server failure", new ApiError("Server Error", 500, { message: "Try again later." })],
    ["non-error response", new ApiError("Redirect", 399, { message: "No rejection was reported." })],
    ["untyped transport failure", { status: 409, message: "socket closed" }],
    ["request timeout", new ApiError("Request Timeout", 408, { message: "The request timed out." })],
    [
      "rate-limit refusal",
      new ApiError("Too Many Requests", 429, { message: "Too many attempts. Try again later." })
    ]
  ];

  const DEFINITIVE_FAILURES: Array<[string, ApiError]> = [
    ["bad request", new ApiError("Bad Request", 400, { message: "The command is invalid." })],
    ["conflict", new ApiError("Conflict", 409, { message: "The run changed." })]
  ];

  function distinctKeys() {
    // The real key mixes the clock with a random suffix. A mock that always
    // answered the same value would make "a new intent mints a new key"
    // unfalsifiable, so hand out a strictly increasing sequence instead.
    let issued = 0;
    return vi.spyOn(Math, "random").mockImplementation(() => {
      issued += 1;
      return issued / 100;
    });
  }

  it("reuses the frozen key and revision after the same question refreshes", async () => {
    const user = userEvent.setup();
    distinctKeys();
    const reply = vi
      .spyOn(apiClient, "replyToAgentRun")
      .mockRejectedValueOnce(new Error("network unreachable"))
      .mockResolvedValue(makeRun());
    const firstRun = blocked();
    const { rerender, client } = renderSection([firstRun]);

    await user.type(screen.getByLabelText("Your answer"), "Use staging.");
    await user.click(screen.getByRole("button", { name: "Send answer" }));
    await screen.findByRole("alert");

    rerender(
      <QueryClientProvider client={client}>
        <AgentRunSection
          taskId="task_1"
          runs={[{ ...firstRun, revision: firstRun.revision + 1 }]}
          isLoading={false}
          error={null}
        />
      </QueryClientProvider>
    );
    await user.click(screen.getByRole("button", { name: "Send answer" }));

    expect(reply).toHaveBeenCalledTimes(2);
    expect(reply.mock.calls[1][2]).toBe(reply.mock.calls[0][2]);
    expect(reply.mock.calls[1][1]).toEqual({ message: "Use staging.", expected_revision: firstRun.revision });
  });

  it("mints a new key and uses the current revision when the question changes", async () => {
    const user = userEvent.setup();
    distinctKeys();
    const reply = vi
      .spyOn(apiClient, "replyToAgentRun")
      .mockRejectedValueOnce(new Error("network unreachable"))
      .mockResolvedValue(makeRun());
    const firstRun = blocked();
    const { rerender, client } = renderSection([firstRun]);

    await user.type(screen.getByLabelText("Your answer"), "Use staging.");
    await user.click(screen.getByRole("button", { name: "Send answer" }));
    await screen.findByRole("alert");

    const changedRun = {
      ...firstRun,
      revision: firstRun.revision + 1,
      question_text: "Which deployment target?"
    };
    rerender(
      <QueryClientProvider client={client}>
        <AgentRunSection taskId="task_1" runs={[changedRun]} isLoading={false} error={null} />
      </QueryClientProvider>
    );
    await user.click(screen.getByRole("button", { name: "Send answer" }));

    expect(reply).toHaveBeenCalledTimes(2);
    expect(reply.mock.calls[1][2]).not.toBe(reply.mock.calls[0][2]);
    expect(reply.mock.calls[1][1]).toEqual({
      message: "Use staging.",
      expected_revision: changedRun.revision
    });
  });

  it.each(AMBIGUOUS_FAILURES)("retries a reply after %s under the exact first-attempt key", async (_case, failure) => {
    const user = userEvent.setup();
    distinctKeys();
    const reply = vi
      .spyOn(apiClient, "replyToAgentRun")
      .mockRejectedValueOnce(failure)
      .mockResolvedValue(makeRun());
    renderSection([blocked()]);

    await user.type(screen.getByLabelText("Your answer"), "Use staging.");
    await user.click(screen.getByRole("button", { name: "Send answer" }));
    await screen.findByRole("alert");

    // The text is still in the box, so pressing send again is the same intent.
    await user.click(screen.getByRole("button", { name: "Send answer" }));

    expect(reply).toHaveBeenCalledTimes(2);
    const [firstKey, secondKey] = reply.mock.calls.map((call) => call[2]);
    expect(secondKey).toBe(firstKey);
    expect(reply.mock.calls[1][1]).toEqual({ message: "Use staging.", expected_revision: 1 });
  });

  it("mints a new key once the previous reply definitively succeeded", async () => {
    const user = userEvent.setup();
    distinctKeys();
    const reply = vi.spyOn(apiClient, "replyToAgentRun").mockResolvedValue(makeRun());
    renderSection([blocked()]);

    await user.type(screen.getByLabelText("Your answer"), "Use staging.");
    await user.click(screen.getByRole("button", { name: "Send answer" }));
    await waitFor(() => expect(reply).toHaveBeenCalledTimes(1));

    // A second question answered in the same session is a genuinely new intent,
    // and deduplicating it against the first would silently drop it.
    await user.type(screen.getByLabelText("Your answer"), "Use production.");
    await user.click(screen.getByRole("button", { name: "Send answer" }));

    await waitFor(() => expect(reply).toHaveBeenCalledTimes(2));
    const [firstKey, secondKey] = reply.mock.calls.map((call) => call[2]);
    expect(secondKey).not.toBe(firstKey);
    expect(reply.mock.calls[1][1]).toEqual({ message: "Use production.", expected_revision: 1 });
  });

  it.each(DEFINITIVE_FAILURES)("retires a reply key after a definitive %s", async (_case, failure) => {
    const user = userEvent.setup();
    distinctKeys();
    const reply = vi
      .spyOn(apiClient, "replyToAgentRun")
      .mockRejectedValueOnce(failure)
      .mockResolvedValue(makeRun());
    renderSection([blocked()]);

    await user.type(screen.getByLabelText("Your answer"), "Use staging.");
    await user.click(screen.getByRole("button", { name: "Send answer" }));
    await screen.findByRole("alert");
    await user.click(screen.getByRole("button", { name: "Send answer" }));

    expect(reply).toHaveBeenCalledTimes(2);
    expect(reply.mock.calls[1][2]).not.toBe(reply.mock.calls[0][2]);
  });

  it.each(AMBIGUOUS_FAILURES)("retries a cancellation after %s under the exact first-attempt key", async (_case, failure) => {
    const user = userEvent.setup();
    distinctKeys();
    const cancel = vi
      .spyOn(apiClient, "cancelAgentRun")
      .mockRejectedValueOnce(failure)
      .mockResolvedValue(makeRun());
    renderSection([makeRun({ reported_state: "running", primary_state_label: "Running" })]);

    await user.click(screen.getByRole("button", { name: "Request cancellation" }));
    await screen.findByRole("alert");
    await user.click(screen.getByRole("button", { name: "Request cancellation" }));

    expect(cancel).toHaveBeenCalledTimes(2);
    expect(cancel.mock.calls[1][1]).toBe(cancel.mock.calls[0][1]);
  });

  it.each(DEFINITIVE_FAILURES)("retires a cancellation key after a definitive %s", async (_case, failure) => {
    const user = userEvent.setup();
    distinctKeys();
    const cancel = vi
      .spyOn(apiClient, "cancelAgentRun")
      .mockRejectedValueOnce(failure)
      .mockResolvedValue(makeRun());
    renderSection([makeRun({ reported_state: "running", primary_state_label: "Running" })]);

    await user.click(screen.getByRole("button", { name: "Request cancellation" }));
    await screen.findByRole("alert");
    await user.click(screen.getByRole("button", { name: "Request cancellation" }));

    expect(cancel).toHaveBeenCalledTimes(2);
    expect(cancel.mock.calls[1][1]).not.toBe(cancel.mock.calls[0][1]);
  });
});

describe("AgentRunSection dispatch states", () => {
  const frozenManifest: AgentManifestResponse = {
    token: "f".repeat(64),
    run_id: "agentrun_1",
    task_id: "task_1",
    connection_id: "agentconn_1",
    agent_name: "Hermes",
    title: "Write the migration runbook",
    details: "Cover the cutover window.",
    supporting_items: [{ label: "Runbook", body: "Deploy notes live in docs/." }],
    message_id: "agentrun_1:start",
    correlation_id: "agentrun_1",
    destination_interface: "https://agent.example.com/a2a",
    protocol_version: "1.0",
    guarantee_tier: "guaranteed",
    tier_disclosure: "Guaranteed single start.",
    tier_disclosure_url: "https://example.invalid/single-start/v1.md",
    acknowledgement_required: false,
    cancellation_disclosure: "Cancellation depends on the agent.",
    push_callback: null,
    external_copy_notice: "Your agent keeps its own copy of everything sent here.",
    reauthentication_required: false,
    parts_preview: ["Write the migration runbook"]
  };

  const restartedRun = makeRun({
    dispatch_state: "not_sent",
    dispatch_error_code: "restarted_before_send",
    primary_state_label: "Not sent",
    message_id: "agentrun_1:start",
    correlation_id: "agentrun_1",
    exchange_state: "closed",
    manifest: frozenManifest
  });

  async function reopenTheReview(user: ReturnType<typeof userEvent.setup>): Promise<void> {
    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Try this hand-off again" }));
    });
    await screen.findByRole("heading", { name: "What will be sent" });
  }

  it("014-SC-004 shows a queued exchange as Queued and never as Sent", () => {
    renderSection([
      makeRun({
        dispatch_state: "delivery_unconfirmed",
        exchange_state: "queued",
        exchange_open: true,
        primary_state_label: "Queued"
      })
    ]);

    expect(screen.getByText("Queued")).toBeInTheDocument();
    expect(
      screen.getByText("Waiting for a free connection slot; nothing has been sent yet")
    ).toBeInTheDocument();
    expect(screen.queryByText("Sent")).toBeNull();
    // A queued hand-off has provably not been sent, so the ambiguous-delivery
    // sentence and its Check again must not appear either.
    expect(screen.queryByRole("button", { name: "Check again" })).toBeNull();
  });

  it("014-FR-006 states a restart that never sent and re-offers the hand-off", () => {
    renderSection([restartedRun]);

    expect(screen.getByText("Not sent")).toBeInTheDocument();
    expect(
      screen.getByText("BrainBuddy restarted before this hand-off was sent. Nothing left BrainBuddy.")
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try this hand-off again" })).toBeEnabled();
  });

  it("014-FR-006 names the rate-limited category on a hand-off that was refused", () => {
    renderSection([
      makeRun({
        dispatch_state: "not_sent",
        dispatch_error_code: "a2a_rate_limited",
        primary_state_label: "Not sent",
        manifest: frozenManifest
      })
    ]);

    expect(screen.getByText("The agent is rate limiting.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try this hand-off again" })).toBeEnabled();
  });

  it("014-SC-004 retries an unchanged review under the same key, so the run and message ids are reused", async () => {
    // Nothing left BrainBuddy, so the identifiers are still free to reuse — and
    // reusing them is what stops a retry from becoming a second task.
    vi.spyOn(apiClient, "listAgentConnections").mockResolvedValue([]);
    vi.spyOn(apiClient, "previewAgentHandoff").mockResolvedValue(frozenManifest);
    const confirm = vi.spyOn(apiClient, "confirmAgentHandoff").mockResolvedValue(
      makeRun({
        dispatch_state: "sent",
        primary_state_label: "Sent",
        message_id: "agentrun_1:start",
        correlation_id: "agentrun_1"
      })
    );
    const user = userEvent.setup();
    renderSection([restartedRun]);
    await reopenTheReview(user);

    // Seeded from the frozen manifest, so the server rebuilds the identical
    // review and hands back the identical token.
    expect(apiClient.previewAgentHandoff).toHaveBeenCalledWith(
      "task_1",
      {
        connection_id: "agentconn_1",
        include_details: true,
        supporting_items: [{ label: "Runbook", body: "Deploy notes live in docs/." }]
      },
      expect.anything()
    );

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Send to agent" }));
    });

    await waitFor(() =>
      expect(confirm).toHaveBeenCalledWith(
        "task_1",
        {
          connection_id: "agentconn_1",
          include_details: true,
          supporting_items: [{ label: "Runbook", body: "Deploy notes live in docs/." }],
          manifest_token: frozenManifest.token,
          current_password: null,
          acknowledge_duplicate_risk: false
        },
        `agent-handoff-${frozenManifest.token}`
      )
    );
    await expect(confirm.mock.results[0].value).resolves.toMatchObject({
      id: "agentrun_1",
      message_id: "agentrun_1:start"
    });
  });

  it("014-FR-006 previews anew and spends a different key once the review changes", async () => {
    vi.spyOn(apiClient, "listAgentConnections").mockResolvedValue([]);
    const rebuilt: AgentManifestResponse = {
      ...frozenManifest,
      token: "e".repeat(64),
      run_id: "agentrun_2",
      message_id: "agentrun_2:start",
      details: null
    };
    vi.spyOn(apiClient, "previewAgentHandoff")
      .mockResolvedValueOnce(frozenManifest)
      .mockResolvedValue(rebuilt);
    const confirm = vi.spyOn(apiClient, "confirmAgentHandoff").mockResolvedValue(
      makeRun({ id: "agentrun_2", dispatch_state: "sent", primary_state_label: "Sent" })
    );
    const user = userEvent.setup();
    renderSection([restartedRun]);
    await reopenTheReview(user);

    await act(async () => {
      await user.click(screen.getByRole("checkbox", { name: "Include task details" }));
    });
    await waitFor(() => expect(apiClient.previewAgentHandoff).toHaveBeenCalledTimes(2));
    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Send to agent" }));
    });

    await waitFor(() =>
      expect(confirm).toHaveBeenCalledWith(
        "task_1",
        expect.objectContaining({ manifest_token: rebuilt.token, include_details: false }),
        `agent-handoff-${rebuilt.token}`
      )
    );
    // The old run is untouched by the new one: it was never sent, and it still says so.
    expect(
      screen.getByText("BrainBuddy restarted before this hand-off was sent. Nothing left BrainBuddy.")
    ).toBeInTheDocument();
  });

  it("014-FR-004 asks for the password again when the reopened review demands it", async () => {
    vi.spyOn(apiClient, "listAgentConnections").mockResolvedValue([]);
    vi.spyOn(apiClient, "previewAgentHandoff").mockResolvedValue({
      ...frozenManifest,
      reauthentication_required: true
    });
    const user = userEvent.setup();
    renderSection([restartedRun]);
    await reopenTheReview(user);

    expect(screen.getByLabelText("Current password")).toBeInTheDocument();
  });

  it("014-FR-006 checks delivery with the run's own ids and never mints a second run", async () => {
    const check = vi.spyOn(apiClient, "checkAgentRunDelivery").mockResolvedValue(
      makeRun({ dispatch_state: "sent", primary_state_label: "Sent" })
    );
    const confirm = vi.spyOn(apiClient, "confirmAgentHandoff");
    const user = userEvent.setup();
    const unconfirmed = makeRun({
      dispatch_state: "delivery_unconfirmed",
      exchange_state: "closed",
      primary_state_label: "Delivery unconfirmed",
      message_id: "agentrun_1:start",
      correlation_id: "agentrun_1",
      revision: 4
    });
    renderSection([unconfirmed]);

    expect(
      screen.getByText(
        "Runs the same check again with the same correlation ID and the same message ID. It is never a new send."
      )
    ).toBeInTheDocument();
    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Check again" }));
    });

    await waitFor(() => expect(check).toHaveBeenCalledTimes(1));
    expect(check.mock.calls[0][0]).toBe("agentrun_1");
    // Tied to the revision the user was looking at: a check composed against a
    // stale cached run must not resend for a state nobody is being shown.
    expect(check.mock.calls[0][1]).toEqual({
      current_password: null,
      expected_revision: unconfirmed.revision
    });
    expect(check.mock.calls[0][2]).toMatch(/^agent-check-delivery-agentrun_1/);
    expect(confirm).not.toHaveBeenCalled();
  });

  it("014-FR-006 surfaces a refused delivery check with its correlation reference", async () => {
    // Parity with iOS. A refusal (rollout_disabled, connection_not_ready,
    // agent_card_changed, a 409 on expected_revision) or a transport failure
    // must never look like a check that ran and found nothing.
    vi.spyOn(apiClient, "checkAgentRunDelivery").mockRejectedValue(
      new ApiError(
        "Bad Request",
        400,
        {
          message: "This agent is not part of the current rollout.",
          detail: { reason: "rollout_disabled" }
        },
        "corr-check-refused"
      )
    );
    const user = userEvent.setup();
    renderSection([
      makeRun({
        dispatch_state: "delivery_unconfirmed",
        exchange_state: "closed",
        primary_state_label: "Delivery unconfirmed"
      })
    ]);

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Check again" }));
    });

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("This agent is not part of the current rollout.");
    expect(alert).toHaveTextContent("corr-check-refused");
    // The run is unchanged, so the check stays on offer.
    expect(screen.getByRole("button", { name: "Check again" })).toBeInTheDocument();
  });

  it("014-FR-006 never offers Check again while the browser is offline", async () => {
    Object.defineProperty(window.navigator, "onLine", { configurable: true, value: false });
    onlineManager.setOnline(false);
    const check = vi.spyOn(apiClient, "checkAgentRunDelivery");
    renderSection([
      makeRun({
        dispatch_state: "delivery_unconfirmed",
        exchange_state: "closed",
        primary_state_label: "Delivery unconfirmed"
      })
    ]);

    const again = screen.getByRole("button", { name: "Check again" });
    expect(again).toBeDisabled();
    await userEvent.click(again);
    expect(check).not.toHaveBeenCalled();
    Object.defineProperty(window.navigator, "onLine", { configurable: true, value: true });
    onlineManager.setOnline(true);
  });
});


describe("014-SC-004 every run state reads as itself", () => {
  /**
   * D-03-S06..S20. One projection in, one label out, rendered verbatim.
   *
   * `it.each` over the whole vocabulary rather than a handful of samples,
   * because the requirement is exhaustive: an operator must be able to tell any
   * two of these apart on sight, and a suite that checked five of fifteen would
   * pass while three of them rendered identically.
   */
  it.each([
    ["Accepted", { reported_state: "accepted" as const }],
    ["Running", { reported_state: "running" as const }],
    ["Needs you", { reported_state: "blocked" as const, needs_user: true }],
    ["Cancellation requested", { cancel_requested: true }],
    ["Agent reported complete", { reported_state: "completed" as const }],
    ["Failed", { reported_state: "failed" as const }],
    ["Cancelled", { reported_state: "cancelled" as const }],
    ["Stopped reporting", { stopped_reporting: true }],
    ["Agent no longer reports this run", { agent_task_missing: true }],
    ["Connection disconnected", { connection_disconnected: true }],
    ["Queued", { exchange_state: "queued" as const, exchange_open: true }],
    ["Sent", {}],
    ["Delivery unconfirmed", { dispatch_state: "delivery_unconfirmed" as const }],
    ["Not sent", { dispatch_state: "not_sent" as const }]
  ])("renders %s verbatim from the projection", (label, overrides) => {
    renderSection([makeRun({ ...overrides, primary_state_label: label })]);

    expect(screen.getByText(label)).toBeInTheDocument();
  });

  it("014-SC-004 D-03-S07 attributes the agent's own status text", () => {
    renderSection([
      makeRun({
        reported_state: "running",
        primary_state_label: "Running",
        progress_text: "Cloning the repository"
      })
    ]);

    expect(screen.getByText("Cloning the repository")).toBeInTheDocument();
    // AC-013: never a percentage, a stage or an ETA BrainBuddy invented.
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
    expect(screen.queryByText(/step \d+ of \d+/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/ETA/i)).not.toBeInTheDocument();
  });

  it("014-SC-004 D-03-S10 offers no reply control for an authentication block", () => {
    renderSection([
      makeRun({
        reported_state: "blocked",
        primary_state_label: "Needs you",
        needs_user: true,
        blocked_reason: "Agent needs additional authentication",
        question_text: null
      })
    ]);

    // A reply box here would invite the user to type a secret to a third party.
    expect(screen.queryByLabelText("Your answer")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Send answer" })).not.toBeInTheDocument();
  });

  it("014-FR-009 D-03-S10 states the block reason as inert text with no reply control", () => {
    renderSection([
      makeRun({
        reported_state: "blocked",
        primary_state_label: "Needs you",
        needs_user: true,
        blocked_reason: "Agent needs additional authentication",
        question_text: null
      })
    ]);

    // "Needs you" with nothing else on the card is a dead end: the user is told
    // they are needed and never told what for.
    expect(screen.getByText("Agent needs additional authentication")).toBeInTheDocument();
    // Inert. A control here would invite typing a credential to a third party.
    expect(screen.queryByLabelText("Your answer")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Send answer" })).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("014-FR-009 hides the block reason once retention has expired the content", () => {
    renderSection([
      makeRun({
        reported_state: "blocked",
        primary_state_label: "Needs you",
        needs_user: true,
        blocked_reason: "Agent needs additional authentication",
        content_expired: true
      })
    ]);

    expect(screen.queryByText("Agent needs additional authentication")).not.toBeInTheDocument();
    expect(screen.getByText("Content expired under retention policy")).toBeInTheDocument();
  });

  it("014-SC-004 D-03-S11 names artifact content types and never a download", () => {
    renderSection([
      makeRun({
        reported_state: "completed",
        primary_state_label: "Agent reported complete",
        result_text: "Done.",
        artifacts_summary: [
          { name: "report.pdf", media_type: "application/pdf", kind: "file" }
        ]
      })
    ]);

    expect(screen.getByText("report.pdf · application/pdf")).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("014-SC-004 D-03-S11 marks a too-large result and never calls it silence", () => {
    renderSection([
      makeRun({
        reported_state: "completed",
        primary_state_label: "Agent reported complete",
        result_availability: "too_large",
        result_text: null
      })
    ]);

    expect(screen.getByText("Result too large to store.")).toBeInTheDocument();
    expect(screen.queryByText("Stopped reporting")).not.toBeInTheDocument();
  });

  it("014-SC-004 D-03-S16 withdraws cancel on a refusal and keeps it on silence", () => {
    const { unmount } = renderSection([
      makeRun({
        reported_state: "running",
        primary_state_label: "Running",
        cancel_outcome: "unsupported"
      })
    ]);

    expect(screen.getByText("Cancellation not supported by this agent.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Request cancellation" })).not.toBeInTheDocument();
    unmount();

    renderSection([
      makeRun({
        reported_state: "running",
        primary_state_label: "Running",
        cancel_outcome: "unconfirmed",
        cancel_requested: true
      })
    ]);

    expect(
      screen.getByText("Cancellation request unconfirmed — you can try again.")
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Request cancellation" })).toBeInTheDocument();
  });

  it("014-SC-004 D-03-S18 withdraws both controls when the agent forgot the run", () => {
    renderSection([
      makeRun({
        reported_state: "blocked",
        needs_user: true,
        question_text: "Which environment?",
        primary_state_label: "Agent no longer reports this run",
        agent_task_missing: true
      })
    ]);

    expect(screen.getByText("Agent no longer reports this run")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Send answer" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Request cancellation" })).not.toBeInTheDocument();
    // Not a failure claim: BrainBuddy lost sight of the work, which is a
    // different thing from the work having gone wrong.
    expect(screen.queryByText("Failed")).not.toBeInTheDocument();
  });

  it("014-SC-004 D-03-S27 shows the succession row with both task identifiers", () => {
    renderSection([
      makeRun({
        reported_state: "running",
        primary_state_label: "Running",
        agent_task_id: "task-b2",
        events: [
          makeEvent({
            id: "evt-1",
            type: "running",
            run_version: 4,
            summary: "The agent continued this run in a new task",
            trigger: "command",
            kind: "task_succession",
            previous_agent_task_id: "task-a1",
            new_agent_task_id: "task-b2"
          })
        ]
      })
    ]);

    expect(screen.getByText("The agent continued this run in a new task")).toBeInTheDocument();
    expect(screen.getByText("task-a1 → task-b2")).toBeInTheDocument();
    // The projection is unchanged by the succession itself.
    expect(screen.getByText("Running")).toBeInTheDocument();
  });

  it("014-SC-004 AC-031 renders an agent name carrying markup as plain text", () => {
    renderSection([
      makeRun({
        agent_name: '<img src=x onerror=alert(1)> javascript:alert(2)',
        reported_state: "running",
        primary_state_label: "Running"
      })
    ]);

    expect(
      screen.getByText('<img src=x onerror=alert(1)> javascript:alert(2)')
    ).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(document.querySelector("img")).toBeNull();
  });

  it("014-SC-004 D-03-S26 shows two runs on one task with their own frozen content", () => {
    renderSection([
      makeRun({
        id: "agentrun_1",
        reported_state: "completed",
        primary_state_label: "Agent reported complete",
        result_text: "First result"
      }),
      makeRun({
        id: "agentrun_2",
        reported_state: "running",
        primary_state_label: "Running",
        progress_text: "Second attempt"
      })
    ]);

    expect(screen.getByText("First result")).toBeInTheDocument();
    expect(screen.getByText("Second attempt")).toBeInTheDocument();
  });
});
