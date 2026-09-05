import { QueryClient, QueryClientProvider, onlineManager } from "@tanstack/react-query";
import { useState } from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  AgentConnectionResponse,
  AgentManifestResponse,
  AgentRunResponse
} from "../../../api/agentTypes";
import { ApiError, apiClient } from "../../../api/client";
import { AgentHandoffOverlay } from "../AgentHandoffOverlay";

const readyConnection: AgentConnectionResponse = {
  id: "conn-ready",
  name: "Hermes",
  agent_address: "https://agent.example.com",
  auth_scheme: "bearer",
  auth_header_name: null,
  status: "ready",
  stale: false,
  ready_for_handoff: true,
  capabilities: { streaming: true, push_notifications: false },
  controls_offered: { reply: true, cancel: true },
  card: null,
  guarantee_tier: "best_effort",
  tier_disclosure: "Best-effort single start.",
  tier_disclosure_url: "https://example.invalid/single-start/v1.md",
  cancellation_disclosure: "Cancellation depends on the agent.",
  agent_changed: false,
  best_effort_acknowledged_at: null,
  correlation_id_honoured: null,
  disconnect_reason: null,
  last_test_error_detail: null,
  last_test_error_code: null,
  last_contact_at: "2026-08-09T10:00:00Z",
  last_tested_at: "2026-08-09T10:00:00Z",
  stale_after_seconds: 3600,
  created_at: "2026-08-09T09:00:00Z",
  revision: 2
};

const secondReadyConnection: AgentConnectionResponse = {
  ...readyConnection,
  id: "conn-second",
  name: "Ops runner",
  agent_address: "https://ops.example.com"
};

const untestedConnection: AgentConnectionResponse = {
  ...readyConnection,
  id: "conn-untested",
  name: "Fresh agent",
  status: "untested",
  ready_for_handoff: false,
  last_contact_at: null,
  last_tested_at: null
};

const manifest: AgentManifestResponse = {
  token: "a".repeat(64),
  run_id: "run-77",
  task_id: "task-1",
  connection_id: "conn-ready",
  agent_name: "Hermes",
  title: "Fix onboarding drop-off",
  details: "Look at the funnel between step two and three.",
  supporting_items: [{ label: "Funnel notes", body: "Drop-off spikes on mobile." }],
  message_id: "run-77:start",
  correlation_id: "run-77",
  destination_interface: "https://agent.example.com/a2a",
  guarantee_tier: "best_effort",
  tier_disclosure:
    "Best-effort single start. This agent's card does not declare BrainBuddy's single-start extension.",
  tier_disclosure_url: "https://example.invalid/single-start/v1.md",
  acknowledgement_required: false,
  cancellation_disclosure: "Cancellation depends on the agent.",
  push_callback: null,
  parts_preview: ["Fix onboarding drop-off"],
  protocol_version: "1.0",
  external_copy_notice:
    "Your agent keeps its own copy of everything sent here. BrainBuddy cleanup, disconnect, and account deletion cannot guarantee that copy is erased.",
  reauthentication_required: false
};

const dispatchedRun = { id: "run-77", task_id: "task-1" } as AgentRunResponse;

function renderOverlay(onDispatched = vi.fn(), onClose = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <AgentHandoffOverlay
        taskId="task-1"
        taskTitle="Fix onboarding drop-off"
        onClose={onClose}
        onDispatched={onDispatched}
      />
    </QueryClientProvider>
  );
  return { onClose, onDispatched };
}

async function selectReadyAgent(user: ReturnType<typeof userEvent.setup>): Promise<void> {
  const radio = await screen.findByRole("radio", { name: /Hermes/ }, { timeout: 5000 });
  await act(async () => {
    await user.click(radio);
  });
  await screen.findByRole("heading", { name: "What will be sent" });
}

describe("AgentHandoffOverlay", () => {
  beforeEach(() => {
    Object.defineProperty(window.navigator, "onLine", { configurable: true, value: true });
    vi.spyOn(apiClient, "listAgentConnections").mockResolvedValue([readyConnection, untestedConnection]);
    vi.spyOn(apiClient, "previewAgentHandoff").mockResolvedValue(manifest);
  });

  afterEach(() => {
    Object.defineProperty(window.navigator, "onLine", { configurable: true, value: true });
    onlineManager.setOnline(true);
    vi.restoreAllMocks();
  });

  it("offers only tested connections and explains why the others cannot be used", async () => {
    renderOverlay();

    expect(await screen.findByRole("radio", { name: /Hermes/ })).toBeEnabled();
    const blocked = screen.getByRole("radio", { name: /Fresh agent/ });
    expect(blocked).toBeDisabled();
    expect(screen.getByText(/has not contacted this agent yet/i)).toBeInTheDocument();
  });

  it("itemises every value that will leave BrainBuddy", async () => {
    const user = userEvent.setup();
    renderOverlay();
    await selectReadyAgent(user);

    const review = screen.getByRole("region", { name: "What will be sent" });
    expect(within(review).getByText("Fix onboarding drop-off")).toBeInTheDocument();
    expect(within(review).getByText("Look at the funnel between step two and three.")).toBeInTheDocument();
    expect(within(review).getByText("Drop-off spikes on mobile.")).toBeInTheDocument();
    expect(within(review).getByText("task-1")).toBeInTheDocument();
    // The *interface* the card named, not the address the owner typed: that is
    // where content would actually go.
    expect(within(review).getByText("https://agent.example.com/a2a")).toBeInTheDocument();
    // The run ID and the correlation ID are the same value, stated in both
    // places on purpose: the review names what the agent will be told, and the
    // conversation identifier *is* the run's own ID (FR-006).
    expect(within(review).getAllByText("run-77")).toHaveLength(2);
    expect(screen.getByText(manifest.external_copy_notice)).toBeInTheDocument();

    // Both server-owned disclosures, rendered verbatim (FR-014).
    const guarantee = screen.getByRole("region", { name: "Guarantee" });
    expect(within(guarantee).getByText(/Best-effort single start\./)).toBeInTheDocument();
    expect(
      screen.getByText("Cancellation depends on the agent.")
    ).toBeInTheDocument();
    // The bespoke reporting instructions are gone: an A2A agent is told nothing
    // about how to report back, because it reports by answering.
    expect(screen.queryByText(/report accepted, running, blocked/i)).toBeNull();
    expect(screen.queryByText(/reporting instructions/i)).toBeNull();
  });

  it("014-FR-005 discloses the masked push callback only when one is registered", async () => {
    const user = userEvent.setup();
    vi.mocked(apiClient.previewAgentHandoff).mockResolvedValue({
      ...manifest,
      push_callback: {
        registered: true,
        url_preview: "https://brain.example.test/api/a2a/push/run-77/…",
        disclosure: "BrainBuddy also gives this agent a private callback address …"
      }
    });
    renderOverlay();
    await selectReadyAgent(user);

    const review = screen.getByRole("region", { name: "What will be sent" });
    expect(
      within(review).getByText("https://brain.example.test/api/a2a/push/run-77/…")
    ).toBeInTheDocument();
    expect(
      within(review).getByText(/private callback address/i)
    ).toBeInTheDocument();
    // The token itself is never in a response, so it can never be on screen.
    expect(within(review).queryByText(/push\/run-77\/[A-Za-z0-9_-]{20,}/)).toBeNull();
  });

  it("014-FR-005 offers no push callback row when the agent cannot push", async () => {
    const user = userEvent.setup();
    renderOverlay();
    await selectReadyAgent(user);

    // Nothing to disclose. A masked address for a callback the agent cannot use
    // would read as one it can.
    expect(screen.queryByText(/push callback/i)).toBeNull();
  });

  it("014-SC-005 gates Send to agent on the one-time duplicate-risk acknowledgement", async () => {
    const confirm = vi.spyOn(apiClient, "confirmAgentHandoff").mockResolvedValue(dispatchedRun);
    vi.mocked(apiClient.previewAgentHandoff).mockResolvedValue({
      ...manifest,
      acknowledgement_required: true
    });
    const user = userEvent.setup();
    renderOverlay();
    await selectReadyAgent(user);

    const send = screen.getByRole("button", { name: "Send to agent" });
    const acknowledgement = screen.getByRole("checkbox", {
      name: /duplicate task is possible/i
    });
    expect(acknowledgement).not.toBeChecked();
    expect(send).toBeDisabled();
    expect(screen.getByText(/Asked once, on your first hand-off/i)).toBeInTheDocument();

    await act(async () => {
      await user.click(acknowledgement);
    });

    expect(send).toBeEnabled();
    await act(async () => {
      await user.click(send);
    });

    await waitFor(() =>
      expect(confirm.mock.calls[0][1]).toMatchObject({ acknowledge_duplicate_risk: true })
    );
  });

  it("014-FR-003 asks the duplicate-risk acknowledgement again when the agent changes", async () => {
    // AC-026. The tick is consent for one specific agent. Carrying it across a
    // change of selection would arm Send for an agent nobody agreed to.
    vi.mocked(apiClient.listAgentConnections).mockResolvedValue([
      readyConnection,
      secondReadyConnection
    ]);
    vi.mocked(apiClient.previewAgentHandoff).mockImplementation(async (_taskId, payload) => ({
      ...manifest,
      connection_id: payload.connection_id,
      acknowledgement_required: true
    }));
    const user = userEvent.setup();
    renderOverlay();
    await selectReadyAgent(user);

    await act(async () => {
      await user.click(screen.getByRole("checkbox", { name: /duplicate task is possible/i }));
    });
    expect(screen.getByRole("button", { name: "Send to agent" })).toBeEnabled();

    await act(async () => {
      await user.click(screen.getByRole("radio", { name: /Ops runner/ }));
    });

    await waitFor(() =>
      expect(screen.getByRole("checkbox", { name: /duplicate task is possible/i })).not.toBeChecked()
    );
    expect(screen.getByRole("button", { name: "Send to agent" })).toBeDisabled();

    await act(async () => {
      await user.click(screen.getByRole("checkbox", { name: /duplicate task is possible/i }));
    });
    expect(screen.getByRole("button", { name: "Send to agent" })).toBeEnabled();
  });

  it("014-SC-005 does not ask again once the connection carries the acknowledgement", async () => {
    const confirm = vi.spyOn(apiClient, "confirmAgentHandoff").mockResolvedValue(dispatchedRun);
    const user = userEvent.setup();
    renderOverlay();
    await selectReadyAgent(user);

    expect(screen.queryByRole("checkbox", { name: /duplicate task is possible/i })).toBeNull();
    expect(
      screen.getByText(/You acknowledged the duplicate risk for this agent/i)
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send to agent" })).toBeEnabled();

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Send to agent" }));
    });

    await waitFor(() =>
      expect(confirm.mock.calls[0][1]).toMatchObject({ acknowledge_duplicate_risk: false })
    );
  });

  it("states explicitly when no details or context will be copied", async () => {
    vi.mocked(apiClient.previewAgentHandoff).mockResolvedValue({
      ...manifest,
      details: null,
      supporting_items: []
    });
    const user = userEvent.setup();
    renderOverlay();
    await selectReadyAgent(user);

    expect(screen.getByText("No task details will be sent.")).toBeInTheDocument();
    expect(screen.getByText("No supporting items will be sent.")).toBeInTheDocument();
  });

  it("re-previews without the task details when the user excludes them", async () => {
    const user = userEvent.setup();
    renderOverlay();
    await selectReadyAgent(user);

    await act(async () => {
      await user.click(screen.getByRole("checkbox", { name: /include task details/i }));
    });

    await waitFor(() =>
      expect(apiClient.previewAgentHandoff).toHaveBeenLastCalledWith(
        "task-1",
        // The overlay sends its own edited list, which the server echoes back as
        // the manifest — so what is sent is always what the review displayed.
        { connection_id: "conn-ready", include_details: false, supporting_items: [] },
        expect.anything()
      )
    );
  });

  it("drops a removed context item from the next preview", async () => {
    const user = userEvent.setup();
    renderOverlay();
    await selectReadyAgent(user);

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Remove Funnel notes" }));
    });

    await waitFor(() =>
      expect(apiClient.previewAgentHandoff).toHaveBeenLastCalledWith(
        "task-1",
        { connection_id: "conn-ready", include_details: true, supporting_items: [] },
        expect.anything()
      )
    );
  });

  it("removes exactly one duplicate-label context item while preserving body and order", async () => {
    vi.mocked(apiClient.previewAgentHandoff).mockImplementation(async (_taskId, request) => ({
      ...manifest,
      supporting_items: request.supporting_items ?? []
    }));
    const user = userEvent.setup();
    renderOverlay();
    await selectReadyAgent(user);

    for (const body of ["First reviewed body", "Second reviewed body"]) {
      await user.type(screen.getByLabelText("Context label"), "Runbook");
      await user.type(screen.getByLabelText("Context body"), body);
      await user.click(screen.getByRole("button", { name: "Add context" }));
      await waitFor(() => expect(screen.getByText(body)).toBeInTheDocument());
    }
    expect(apiClient.previewAgentHandoff).toHaveBeenLastCalledWith(
      "task-1",
      {
        connection_id: "conn-ready",
        include_details: true,
        supporting_items: [
          { label: "Runbook", body: "First reviewed body" },
          { label: "Runbook", body: "Second reviewed body" }
        ]
      },
      expect.anything()
    );

    const firstItem = screen.getByText("First reviewed body").closest("li");
    expect(firstItem).not.toBeNull();
    if (!firstItem) {
      throw new Error("Expected the first reviewed context item to render in a list item.");
    }
    await user.click(within(firstItem).getByRole("button", { name: "Remove Runbook" }));

    await waitFor(() =>
      expect(apiClient.previewAgentHandoff).toHaveBeenLastCalledWith(
        "task-1",
        {
          connection_id: "conn-ready",
          include_details: true,
          supporting_items: [{ label: "Runbook", body: "Second reviewed body" }]
        },
        expect.anything()
      )
    );
    expect(screen.queryByText("First reviewed body")).not.toBeInTheDocument();
    expect(screen.getByText("Second reviewed body")).toBeInTheDocument();
  });

  it("adds a reviewed context item before sending", async () => {
    const user = userEvent.setup();
    renderOverlay();
    await selectReadyAgent(user);

    await act(async () => {
      await user.type(screen.getByLabelText("Context label"), "Runbook");
      await user.type(screen.getByLabelText("Context body"), "Deploy notes live in docs/.");
      await user.click(screen.getByRole("button", { name: "Add context" }));
    });

    await waitFor(() =>
      expect(apiClient.previewAgentHandoff).toHaveBeenLastCalledWith(
        "task-1",
        {
          connection_id: "conn-ready",
          include_details: true,
          supporting_items: [{ label: "Runbook", body: "Deploy notes live in docs/." }]
        },
        expect.anything()
      )
    );
  });

  it("requires the password when the server demands re-authentication", async () => {
    vi.mocked(apiClient.previewAgentHandoff).mockResolvedValue({ ...manifest, reauthentication_required: true });
    const confirm = vi.spyOn(apiClient, "confirmAgentHandoff").mockResolvedValue(dispatchedRun);
    const user = userEvent.setup();
    renderOverlay();
    await selectReadyAgent(user);

    await act(async () => {
      await user.type(screen.getByLabelText("Current password"), "hunter2hunter2");
      await user.click(screen.getByRole("button", { name: "Send to agent" }));
    });

    await waitFor(() =>
      expect(confirm).toHaveBeenCalledWith(
        "task-1",
        expect.objectContaining({ current_password: "hunter2hunter2", manifest_token: manifest.token }),
        expect.stringContaining("agent-handoff")
      )
    );
  });

  it("dispatches exactly the reviewed manifest token under an idempotency key", async () => {
    const confirm = vi.spyOn(apiClient, "confirmAgentHandoff").mockResolvedValue(dispatchedRun);
    const user = userEvent.setup();
    const { onDispatched } = renderOverlay();
    await selectReadyAgent(user);

    expect(screen.queryByLabelText("Current password")).not.toBeInTheDocument();
    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Send to agent" }));
    });

    await waitFor(() =>
      expect(confirm).toHaveBeenCalledWith(
        "task-1",
        {
          connection_id: "conn-ready",
          include_details: true,
          supporting_items: [],
          manifest_token: manifest.token,
          current_password: null,
          acknowledge_duplicate_risk: false
        },
        expect.stringContaining("agent-handoff")
      )
    );
    await waitFor(() => expect(onDispatched).toHaveBeenCalledWith(dispatchedRun));
  });

  it("re-opens the review when the manifest no longer matches what was reviewed", async () => {
    vi.spyOn(apiClient, "confirmAgentHandoff").mockRejectedValue(
      new ApiError(
        "Bad Request",
        400,
        { message: "Review it again before confirming.", detail: { reason: "manifest_token_mismatch" } },
        "corr-handoff-2"
      )
    );
    const user = userEvent.setup();
    renderOverlay();
    await selectReadyAgent(user);
    expect(apiClient.previewAgentHandoff).toHaveBeenCalledTimes(1);

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Send to agent" }));
    });

    await waitFor(() => expect(apiClient.previewAgentHandoff).toHaveBeenCalledTimes(2));
    expect(screen.getByRole("alert")).toHaveTextContent(/review it again before confirming.*corr-handoff-2/i);
  });

  it("re-previews when the reserved manifest is gone", async () => {
    vi.spyOn(apiClient, "confirmAgentHandoff").mockRejectedValue(
      new ApiError(
        "Bad Request",
        400,
        { message: "This hand-off review is no longer valid.", detail: { reason: "manifest_not_reserved" } },
        "corr-handoff-3"
      )
    );
    const user = userEvent.setup();
    renderOverlay();
    await selectReadyAgent(user);

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Send to agent" }));
    });

    await waitFor(() => expect(apiClient.previewAgentHandoff).toHaveBeenCalledTimes(2));
  });

  it.each(["forbidden", { detail: "not-a-structured-reason" }])(
    "shows an unrelated dispatch failure without silently re-previewing for payload %#",
    async (payload) => {
      vi.spyOn(apiClient, "confirmAgentHandoff").mockRejectedValue(
        new ApiError("Forbidden", 403, payload, "corr-handoff-4")
      );
    const user = userEvent.setup();
    renderOverlay();
    await selectReadyAgent(user);

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Send to agent" }));
    });

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(/corr-handoff-4/i)
    );
    expect(apiClient.previewAgentHandoff).toHaveBeenCalledTimes(1);
  });

  it("creates no run when the review is cancelled", async () => {
    const confirm = vi.spyOn(apiClient, "confirmAgentHandoff");
    const user = userEvent.setup();
    const { onClose } = renderOverlay();
    await selectReadyAgent(user);

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Cancel" }));
    });

    expect(onClose).toHaveBeenCalled();
    expect(confirm).not.toHaveBeenCalled();
  });

  it("points the user at connection setup when nothing is connected", async () => {
    vi.mocked(apiClient.listAgentConnections).mockResolvedValue([]);
    renderOverlay();

    expect(await screen.findByText(/no agents connected yet/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Send to agent" })).not.toBeInTheDocument();
  });

  it("reports a failed connection lookup instead of claiming the account has no agents", async () => {
    vi.mocked(apiClient.listAgentConnections).mockRejectedValue(
      new ApiError("Server Error", 500, { message: "Connection registry unavailable." }, "corr-connections-1")
    );
    renderOverlay();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /connection registry unavailable.*corr-connections-1/i
    );
    expect(screen.queryByText(/no agents connected yet/i)).not.toBeInTheDocument();
  });

  it("does not re-preview when an incomplete context item is submitted", async () => {
    const user = userEvent.setup();
    renderOverlay();
    await selectReadyAgent(user);

    await user.type(screen.getByLabelText("Context label"), "Runbook");
    await user.click(screen.getByRole("button", { name: "Add context" }));

    expect(apiClient.previewAgentHandoff).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText("Context label")).toHaveValue("Runbook");
  });

  it("reports a failed preview instead of showing a partial payload", async () => {
    vi.mocked(apiClient.previewAgentHandoff).mockImplementation(async () => {
      throw new ApiError("Bad Request", 400, { message: "This connection is stale." }, "corr-preview-1");
    });
    renderOverlay();

    // fireEvent, not userEvent: this is the one path where the preview query
    // settles as a rejection, and userEvent's pointer sequence deadlocks
    // against the resulting error render in this environment.
    fireEvent.click(await screen.findByRole("radio", { name: /Hermes/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /this connection is stale.*corr-preview-1/i
    );
    expect(screen.queryByRole("region", { name: "What will be sent" })).not.toBeInTheDocument();
  });

  it("014-FR-005 builds the preview without claiming any task content has been sent", async () => {
    // D-02-S03. A preview that has not resolved is the moment a user is most
    // likely to assume something already left, so the wait says it has not.
    let release: (value: AgentManifestResponse) => void = () => {};
    vi.mocked(apiClient.previewAgentHandoff).mockImplementation(
      () =>
        new Promise<AgentManifestResponse>((resolve) => {
          release = resolve;
        })
    );
    const user = userEvent.setup();
    renderOverlay();
    await act(async () => {
      await user.click(await screen.findByRole("radio", { name: /Hermes/ }));
    });

    expect(screen.getByText("Building the hand-off preview…")).toBeInTheDocument();
    expect(screen.getByText(/no task content has been sent/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Send to agent" })).not.toBeInTheDocument();

    await act(async () => {
      release(manifest);
    });
    await screen.findByRole("heading", { name: "What will be sent" });
  });

  it("014-FR-002 names Agent changed among the reasons no agent can take this hand-off", async () => {
    // D-02-S05. The list is not empty, so "no agents connected" would be a lie;
    // what the user needs is the reason each one is ineligible.
    vi.mocked(apiClient.listAgentConnections).mockResolvedValue([
      {
        ...readyConnection,
        id: "conn-changed",
        name: "Moved agent",
        status: "untested",
        ready_for_handoff: false,
        agent_changed: true
      },
      untestedConnection
    ]);
    renderOverlay();

    expect(
      await screen.findByText("None of your agents can take this hand-off")
    ).toBeInTheDocument();
    expect(screen.getByText("Agent changed")).toBeInTheDocument();
    expect(screen.getByText(/advertises a different interface address/i)).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /Moved agent/ })).toBeDisabled();
    expect(screen.queryByText(/no agents connected yet/i)).toBeNull();
  });

  it("014-FR-002 marks a connection it could not refresh Status unknown and never offers it", async () => {
    // D-02-S07, fail closed. Every reason BrainBuddy actually knows has its own
    // sentence, so a row the server refuses for no stated reason is one whose
    // state is unknown — and an unknown state is never presented as eligible.
    vi.mocked(apiClient.listAgentConnections).mockResolvedValue([
      readyConnection,
      {
        ...readyConnection,
        id: "conn-unknown",
        name: "Drafting sample agent",
        ready_for_handoff: false
      }
    ]);
    renderOverlay();

    expect(await screen.findByText("Status unknown")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /Drafting sample agent/ })).toBeDisabled();
    expect(
      screen.getByText(/could not refresh this connection just now, so it is not offered/i)
    ).toBeInTheDocument();
    // The refreshable one is still offered: partial knowledge fails closed on
    // the row it concerns, not on the whole list.
    expect(screen.getByRole("radio", { name: /Hermes/ })).toBeEnabled();
  });

  it("014-FR-003 links the extension specification as an explicit, marked external click", async () => {
    // D-02-S02. Nothing opens on render; the user clicks, and the marker says
    // where the click goes.
    const user = userEvent.setup();
    renderOverlay();
    await selectReadyAgent(user);

    const guarantee = screen.getByRole("region", { name: "Guarantee" });
    const link = within(guarantee).getByRole("link", {
      name: "Read the single-start extension specification"
    });
    expect(link).toHaveAttribute("href", manifest.tier_disclosure_url);
    expect(link).toHaveAttribute("target", "_blank");
    expect(link.getAttribute("rel")).toContain("noopener");
    expect(
      within(guarantee).getByText("Opens the published specification outside BrainBuddy.")
    ).toBeInTheDocument();
    // The disclosure sentence itself is prose, not a second navigable copy of
    // the same destination.
    expect(within(guarantee).getAllByRole("link")).toHaveLength(1);
  });

  it("014-FR-014 keeps the review readable offline with sending disabled and nothing queued", async () => {
    // D-02-S10. Offline is not a queue: the manifest stays legible so the user
    // can still read what *would* be sent, and the send simply cannot be made.
    const confirm = vi.spyOn(apiClient, "confirmAgentHandoff");
    const user = userEvent.setup();
    renderOverlay();
    await selectReadyAgent(user);

    Object.defineProperty(window.navigator, "onLine", { configurable: true, value: false });
    act(() => {
      window.dispatchEvent(new Event("offline"));
      onlineManager.setOnline(false);
    });

    const send = screen.getByRole("button", { name: "Send to agent" });
    expect(send).toBeDisabled();
    expect(screen.getByText("Sending is unavailable and nothing is queued.")).toBeInTheDocument();
    expect(screen.getByText(manifest.external_copy_notice)).toBeInTheDocument();
    await user.click(send);
    expect(confirm).not.toHaveBeenCalled();
  });

  it("014-SC-005 disables the confirmation in flight and refuses to dismiss the review", async () => {
    // D-02-S12. An interrupted confirmation must not be able to become a second
    // one, so while it is in flight the surface has no exit at all.
    let release: (run: AgentRunResponse) => void = () => {};
    const confirm = vi.spyOn(apiClient, "confirmAgentHandoff").mockImplementation(
      () =>
        new Promise<AgentRunResponse>((resolve) => {
          release = resolve;
        })
    );
    const user = userEvent.setup();
    const { onClose } = renderOverlay();
    await selectReadyAgent(user);

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Send to agent" }));
    });

    // The spinner lends the control its own name while it runs, so the match is
    // on the action, not on the exact accessible name.
    expect(screen.getByRole("button", { name: /Send to agent/ })).toBeDisabled();
    expect(
      screen.getByText("Confirming again while this is in flight returns the same run.")
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Close the review" })).toBeNull();
    expect(screen.queryByTestId("overlay-scrim")).toBeNull();
    await act(async () => {
      await user.keyboard("{Escape}");
    });
    expect(onClose).not.toHaveBeenCalled();

    await act(async () => {
      release(dispatchedRun);
    });
    expect(confirm).toHaveBeenCalledTimes(1);
  });

  it("014-SC-005 confirms the acknowledgement is recorded once the box is ticked", async () => {
    // D-02-S14. The tick is a one-time record, so the review says so instead of
    // leaving the user wondering whether it will be asked again.
    vi.mocked(apiClient.previewAgentHandoff).mockResolvedValue({
      ...manifest,
      acknowledgement_required: true
    });
    const user = userEvent.setup();
    renderOverlay();
    await selectReadyAgent(user);

    await act(async () => {
      await user.click(screen.getByRole("checkbox", { name: /duplicate task is possible/i }));
    });

    expect(
      screen.getByText("Acknowledged. BrainBuddy will not ask again for this agent.")
    ).toBeInTheDocument();
  });

  it("014-FR-005 refuses the hand-off when the agent's card changed at confirm time", async () => {
    // D-02-S09. The refusal happens before content leaves, and it says the next
    // step costs a password, because a new destination is a new first send.
    vi.spyOn(apiClient, "confirmAgentHandoff").mockRejectedValue(
      new ApiError(
        "Bad Request",
        400,
        {
          message:
            "Its card now advertises a different interface address than the one you tested.",
          detail: { reason: "agent_card_changed" }
        },
        "corr-handoff-changed"
      )
    );
    const user = userEvent.setup();
    renderOverlay();
    await selectReadyAgent(user);

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Send to agent" }));
    });

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(
        /different interface address.*corr-handoff-changed/i
      )
    );
    expect(
      screen.getByText(
        "Test this connection again from Connected agents. You will be asked for your password, because a new destination is a new content-bearing send."
      )
    ).toBeInTheDocument();
  });

  it("014-FR-016 renders adversarial agent and destination text as inert plain text", async () => {
    // AC-031. Every one of these values is card-controlled, so none of them may
    // become something a stray click can follow.
    vi.mocked(apiClient.listAgentConnections).mockResolvedValue([
      { ...readyConnection, name: "<img src=x onerror=alert(1)>Agent" }
    ]);
    vi.mocked(apiClient.previewAgentHandoff).mockResolvedValue({
      ...manifest,
      agent_name: "<img src=x onerror=alert(1)>Agent",
      destination_interface: "javascript:alert(document.cookie)"
    });
    const user = userEvent.setup();
    renderOverlay();
    const radio = await screen.findByRole("radio", { name: /onerror/ });
    await act(async () => {
      await user.click(radio);
    });
    await screen.findByRole("heading", { name: "What will be sent" });

    const review = screen.getByRole("region", { name: "What will be sent" });
    const destination = within(review).getByText("javascript:alert(document.cookie)");
    expect(destination.tagName).toBe("P");
    expect(destination.querySelector("a")).toBeNull();
    expect(within(review).queryAllByRole("link")).toHaveLength(0);
    // The markup is text, not nodes: it never became an element.
    expect(screen.getByText(/<img src=x onerror=alert\(1\)>Agent/)).toBeInTheDocument();
    expect(document.querySelector("img")).toBeNull();
  });

  it("014-FR-005 contains focus from the close control to Send to agent and restores it on Escape", async () => {
    // The review is the consent boundary, so the keyboard cannot leave it while
    // it is open — and when it closes, the user is put back where they were.
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <HandoffHarness />
      </QueryClientProvider>
    );

    const invoker = screen.getByRole("button", { name: "Hand to agent" });
    await act(async () => {
      await user.click(invoker);
    });
    await selectReadyAgent(user);

    const dialog = screen.getByRole("dialog");
    const focusable = Array.from(
      dialog.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
      )
    );
    expect(focusable[0]).toHaveAccessibleName("Close the review");
    expect(focusable[focusable.length - 1]).toHaveAccessibleName("Send to agent");

    const send = screen.getByRole("button", { name: "Send to agent" });
    await act(async () => {
      send.focus();
      await user.tab();
    });
    expect(document.activeElement).toHaveAccessibleName("Close the review");

    await act(async () => {
      await user.keyboard("{Escape}");
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(document.activeElement).toBe(invoker);
  });
});

/** A **Hand to agent** control that opens the review, so focus has somewhere to return to. */
function HandoffHarness(): React.JSX.Element {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Hand to agent
      </button>
      {open ? (
        <AgentHandoffOverlay
          taskId="task-1"
          taskTitle="Fix onboarding drop-off"
          onClose={() => setOpen(false)}
          onDispatched={() => setOpen(false)}
        />
      ) : null}
    </>
  );
}
