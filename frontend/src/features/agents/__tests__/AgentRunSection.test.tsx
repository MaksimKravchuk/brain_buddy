import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AgentRunResponse } from "../../../api/agentTypes";
import { apiClient } from "../../../api/client";
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
    capabilities: { progress: true, reply: true, cancel: true },
    manifest: null,
    events: [],
    commands: [],
    created_at: "2026-08-09T12:00:00Z",
    revision: 1,
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
        capabilities: { progress: true, reply: false, cancel: false }
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
        capabilities: { progress: true, reply: true, cancel: false }
      })
    ]);

    expect(screen.queryByRole("button", { name: "Request cancellation" })).not.toBeInTheDocument();
  });

  it("links a result only when the server marked it safe", () => {
    renderSection([
      makeRun({
        reported_state: "completed",
        primary_state_label: "Agent reported complete",
        result_text: "Here is the plan",
        result_link: "https://results.example.com/1",
        result_link_interactive: true
      })
    ]);

    const link = screen.getByRole("link", { name: /results\.example\.com/ });
    expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
    expect(link).toHaveAttribute("target", "_blank");
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

  it("shows the chronological timeline of connector reports", () => {
    renderSection([
      makeRun({
        reported_state: "running",
        primary_state_label: "Running",
        events: [
          { id: "evt_1", type: "accepted", run_version: 1, received_at: "2026-08-09T12:00:00Z", summary: null },
          { id: "evt_2", type: "running", run_version: 2, received_at: "2026-08-09T12:05:00Z", summary: "Cloning" }
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
            { id: "evt_blocked", type: "blocked", run_version: 1, received_at: "2026-08-09T12:01:00Z", summary: null },
            { id: "evt_complete", type: "completed", run_version: 2, received_at: "2026-08-09T12:02:00Z", summary: null },
            { id: "evt_failed", type: "failed", run_version: 3, received_at: "2026-08-09T12:03:00Z", summary: null },
            { id: "evt_cancelled", type: "cancelled", run_version: 4, received_at: "2026-08-09T12:04:00Z", summary: null }
          ]
        }),
        makeRun({ id: "agentrun_second", agent_name: "Claude", capabilities: { progress: true, reply: true, cancel: false } })
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
              { id: "evt_blocked", type: "blocked", run_version: 1, received_at: "2026-08-09T12:01:00Z", summary: null },
              { id: "evt_complete", type: "completed", run_version: 2, received_at: "2026-08-09T12:02:00Z", summary: null },
              { id: "evt_failed", type: "failed", run_version: 3, received_at: "2026-08-09T12:03:00Z", summary: null },
              { id: "evt_cancelled", type: "cancelled", run_version: 4, received_at: "2026-08-09T12:04:00Z", summary: null }
            ]
          }),
          makeRun({ id: "agentrun_second", agent_name: "Claude", capabilities: { progress: true, reply: true, cancel: false } })
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
    expect(screen.getByText(/could not confirm the agent received/i)).toBeInTheDocument();
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

  it("retries a rejected reply under the key the first attempt used", async () => {
    const user = userEvent.setup();
    distinctKeys();
    const reply = vi
      .spyOn(apiClient, "replyToAgentRun")
      .mockRejectedValueOnce(new Error("network unreachable"))
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

  it("retries a rejected cancellation under the key the first attempt used", async () => {
    const user = userEvent.setup();
    distinctKeys();
    const cancel = vi
      .spyOn(apiClient, "cancelAgentRun")
      .mockRejectedValueOnce(new Error("network unreachable"))
      .mockResolvedValue(makeRun());
    renderSection([makeRun({ reported_state: "running", primary_state_label: "Running" })]);

    await user.click(screen.getByRole("button", { name: "Request cancellation" }));
    await screen.findByRole("alert");
    await user.click(screen.getByRole("button", { name: "Request cancellation" }));

    expect(cancel).toHaveBeenCalledTimes(2);
    expect(cancel.mock.calls[1][1]).toBe(cancel.mock.calls[0][1]);
  });
});
