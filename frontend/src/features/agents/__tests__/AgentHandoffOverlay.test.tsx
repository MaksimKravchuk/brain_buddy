import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
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
  endpoint_url: "https://agent.example.com/hooks",
  auth_header_name: "Authorization",
  status: "ready",
  stale: false,
  ready_for_handoff: true,
  capabilities: { progress: true, reply: true, cancel: true },
  last_test_error_code: null,
  last_contact_at: "2026-08-09T10:00:00Z",
  last_tested_at: "2026-08-09T10:00:00Z",
  stale_after_seconds: 3600,
  created_at: "2026-08-09T09:00:00Z",
  revision: 2
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
  context_items: [{ label: "Funnel notes", body: "Drop-off spikes on mobile." }],
  reporting: {
    callback_url: "https://brain.example.test/api/agent-runs/run-77/reports",
    connection_id: "conn-ready",
    connection_header: "X-BrainBuddy-Connection",
    timestamp_header: "X-BrainBuddy-Timestamp",
    signature_header: "X-BrainBuddy-Signature",
    timestamp_format: "ascii-base-10-unix-seconds-no-sign-space-or-leading-zero",
    signature_algorithm: "hmac-sha256",
    signing_bytes: "timestamp_bytes + b'.' + raw_body",
    signature_format: "v1=<lowercase hex>",
    body_envelope_version: "1"
  },
  reporting_instructions: "Report accepted, running, blocked, completed, failed.",
  instructions_version: "2026-08-01",
  protocol_version: "1",
  destination_endpoint: "https://agent.example.com/hooks",
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
    vi.spyOn(apiClient, "listAgentConnections").mockResolvedValue([readyConnection, untestedConnection]);
    vi.spyOn(apiClient, "previewAgentHandoff").mockResolvedValue(manifest);
  });

  afterEach(() => {
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
    expect(within(review).getByText("run-77")).toBeInTheDocument();
    expect(within(review).getByText("https://agent.example.com/hooks")).toBeInTheDocument();
    expect(within(review).getByText(/report accepted, running, blocked/i)).toBeInTheDocument();
    expect(screen.getByText(manifest.external_copy_notice)).toBeInTheDocument();
  });

  it("states explicitly when no details or context will be copied", async () => {
    vi.mocked(apiClient.previewAgentHandoff).mockResolvedValue({
      ...manifest,
      details: null,
      context_items: []
    });
    const user = userEvent.setup();
    renderOverlay();
    await selectReadyAgent(user);

    expect(screen.getByText("No task details will be sent.")).toBeInTheDocument();
    expect(screen.getByText("No context items will be sent.")).toBeInTheDocument();
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
        { connection_id: "conn-ready", include_details: false, context_items: [] },
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
        { connection_id: "conn-ready", include_details: true, context_items: [] },
        expect.anything()
      )
    );
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
          context_items: [{ label: "Runbook", body: "Deploy notes live in docs/." }]
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
          context_items: [],
          manifest_token: manifest.token,
          current_password: null
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
});
