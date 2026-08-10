import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AgentConnectionResponse } from "../../../api/agentTypes";
import { ApiError, apiClient } from "../../../api/client";
import { useAuthStore } from "../../../stores/authStore";
import { AgentSettingsGate } from "../AgentSettingsGate";

const ready: AgentConnectionResponse = {
  id: "conn-ready",
  name: "Hermes",
  endpoint_url: "https://agent.example.com/hooks",
  auth_header_name: "Authorization",
  status: "ready",
  stale: false,
  ready_for_handoff: true,
  capabilities: { progress: true, reply: true, cancel: false },
  last_test_error_code: null,
  last_contact_at: "2026-08-09T10:00:00Z",
  last_tested_at: "2026-08-09T10:00:00Z",
  stale_after_seconds: 3600,
  created_at: "2026-08-09T09:00:00Z",
  revision: 2
};

function connection(overrides: Partial<AgentConnectionResponse>): AgentConnectionResponse {
  return { ...ready, ...overrides };
}

function signIn(flagOn: boolean): void {
  useAuthStore.setState({
    user: {
      id: "user-1",
      email: "max@example.test",
      feature_flags: flagOn ? { external_agent_relay: true } : {}
    },
    status: "authed"
  });
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/settings/agents"]}>
        <AgentSettingsGate />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

function cardFor(name: string): HTMLElement {
  return screen.getByRole("article", { name });
}

describe("AgentSettingsPage", () => {
  beforeEach(() => {
    Object.defineProperty(window.navigator, "onLine", { configurable: true, value: true });
    act(() => signIn(true));
    vi.spyOn(apiClient, "listTasks").mockResolvedValue({
      items: [],
      next_cursor: null,
      has_more: false,
      counts_by_state: { inbox: 0, next: 0, waiting: 0, someday: 0 }
    });
    vi.spyOn(apiClient, "listProjects").mockResolvedValue([]);
    vi.spyOn(apiClient, "listTags").mockResolvedValue([]);
    vi.spyOn(apiClient, "listAgentConnections").mockResolvedValue([]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    act(() => {
      useAuthStore.setState({ user: null, status: "loading" });
    });
  });

  it("keeps the page dark and asks for nothing while the relay flag is off", async () => {
    act(() => signIn(false));
    renderPage();

    expect(await screen.findByRole("heading", { name: /external agents are off/i })).toBeInTheDocument();
    expect(apiClient.listAgentConnections).not.toHaveBeenCalled();
  });

  it("adds a connection and shows the inbound signing secret exactly once", async () => {
    const create = vi.spyOn(apiClient, "createAgentConnection").mockResolvedValue({
      ...connection({ id: "conn-new", status: "untested", stale: false, ready_for_handoff: false, revision: 1 }),
      inbound_signing_secret: "sk-inbound-9f2c"
    });
    renderPage();

    const user = userEvent.setup();
    const form = await screen.findByRole("form", { name: /add an agent/i });
    await act(async () => {
      await user.type(within(form).getByLabelText("Agent name"), "Hermes");
      await user.clear(within(form).getByLabelText("Endpoint URL"));
      await user.type(within(form).getByLabelText("Endpoint URL"), "https://agent.example.com/hooks");
      await user.type(within(form).getByLabelText("Credential"), "token-abc");
      await user.type(within(form).getByLabelText("Current password"), "hunter2hunter2");
      await user.click(within(form).getByRole("button", { name: "Add agent" }));
    });

    await waitFor(() =>
      expect(create).toHaveBeenCalledWith(
        {
          name: "Hermes",
          endpoint_url: "https://agent.example.com/hooks",
          auth_header_name: "Authorization",
          credential: "token-abc",
          current_password: "hunter2hunter2"
        },
        expect.stringContaining("agent-connection-create")
      )
    );

    const panel = await screen.findByRole("region", { name: /inbound signing secret/i });
    expect(within(panel).getByText("sk-inbound-9f2c")).toBeInTheDocument();
    expect(within(panel).getByText(/never show it again/i)).toBeInTheDocument();
    expect(within(panel).getByText(/sign every report/i)).toBeInTheDocument();

    await act(async () => {
      await user.click(within(panel).getByRole("button", { name: /i've saved it/i }));
    });
    expect(screen.queryByText("sk-inbound-9f2c")).not.toBeInTheDocument();
  });

  it("masks the credential field and never echoes a saved secret in the list", async () => {
    vi.mocked(apiClient.listAgentConnections).mockResolvedValue([ready]);
    renderPage();

    await screen.findByRole("article", { name: "Hermes" });
    const credential = screen.getByLabelText("Credential");
    expect(credential).toHaveAttribute("type", "password");
    expect(credential).toHaveAttribute("autocomplete", "off");
    expect(screen.queryByText(/inbound signing secret/i)).not.toBeInTheDocument();
  });

  it("refuses to call an untested connection ready and blocks its hand-off", async () => {
    vi.mocked(apiClient.listAgentConnections).mockResolvedValue([
      connection({ id: "conn-untested", name: "Fresh agent", status: "untested", ready_for_handoff: false, last_contact_at: null, last_tested_at: null })
    ]);
    renderPage();

    const card = await screen.findByRole("article", { name: "Fresh agent" });
    expect(within(card).getByText("Not tested")).toBeInTheDocument();
    expect(within(card).getByText(/has not contacted this agent yet/i)).toBeInTheDocument();
    expect(within(card).getByText(/cannot receive a hand-off yet/i)).toBeInTheDocument();
    expect(within(card).queryByText("Tested ready")).not.toBeInTheDocument();
    expect(within(card).getByText(/last contact: never/i)).toBeInTheDocument();
  });

  it("distinguishes invalid credentials from an unreachable endpoint", async () => {
    vi.mocked(apiClient.listAgentConnections).mockResolvedValue([
      connection({ id: "conn-bad-key", name: "Bad key agent", status: "invalid_credentials", ready_for_handoff: false }),
      connection({ id: "conn-down", name: "Offline agent", status: "unreachable", ready_for_handoff: false })
    ]);
    renderPage();

    const badKey = await screen.findByRole("article", { name: "Bad key agent" });
    expect(within(badKey).getByText("Invalid credentials")).toBeInTheDocument();
    expect(within(badKey).getByText(/rejected the credential/i)).toBeInTheDocument();

    const offline = cardFor("Offline agent");
    expect(within(offline).getByText("Unreachable")).toBeInTheDocument();
    expect(within(offline).getByText(/nothing was sent/i)).toBeInTheDocument();
  });

  it("marks a ready-but-aged connection stale and asks for a fresh test", async () => {
    vi.mocked(apiClient.listAgentConnections).mockResolvedValue([
      connection({ name: "Aged agent", stale: true, ready_for_handoff: false })
    ]);
    renderPage();

    const card = await screen.findByRole("article", { name: "Aged agent" });
    expect(within(card).getByText("Stale")).toBeInTheDocument();
    expect(within(card).getByText(/1 hour staleness threshold/i)).toBeInTheDocument();
  });

  it("names the capabilities the agent does not support", async () => {
    vi.mocked(apiClient.listAgentConnections).mockResolvedValue([ready]);
    renderPage();

    const card = await screen.findByRole("article", { name: "Hermes" });
    expect(within(card).getByText("Progress updates")).toBeInTheDocument();
    expect(within(card).getByText("Cancellation")).toBeInTheDocument();
    expect(within(card).getAllByText("Supported")).toHaveLength(2);
    expect(within(card).getByText("Not supported")).toBeInTheDocument();
  });

  it("tests a connection and reports the refreshed server verdict", async () => {
    vi.mocked(apiClient.listAgentConnections).mockResolvedValue([
      connection({ name: "Hermes", status: "untested", ready_for_handoff: false })
    ]);
    const test = vi.spyOn(apiClient, "testAgentConnection").mockResolvedValue(ready);
    renderPage();

    const card = await screen.findByRole("article", { name: "Hermes" });
    const user = userEvent.setup();
    await act(async () => {
      await user.click(within(card).getByRole("button", { name: "Test connection" }));
    });

    await waitFor(() => expect(test).toHaveBeenCalledWith("conn-ready"));
    await waitFor(() => expect(within(cardFor("Hermes")).getByText(/tested ready/i)).toBeInTheDocument());
  });

  it("surfaces a failed test with the correlation id instead of claiming success", async () => {
    vi.mocked(apiClient.listAgentConnections).mockResolvedValue([ready]);
    vi.spyOn(apiClient, "testAgentConnection").mockRejectedValue(
      new ApiError("Bad Gateway", 502, { message: "The agent did not answer." }, "corr-test-7")
    );
    renderPage();

    const card = await screen.findByRole("article", { name: "Hermes" });
    const user = userEvent.setup();
    await act(async () => {
      await user.click(within(card).getByRole("button", { name: "Test connection" }));
    });

    await waitFor(() =>
      expect(within(cardFor("Hermes")).getByRole("alert")).toHaveTextContent(/the agent did not answer.*corr-test-7/i)
    );
  });

  it("rotates the credential against the revision the user is looking at", async () => {
    vi.mocked(apiClient.listAgentConnections).mockResolvedValue([ready]);
    const rotate = vi.spyOn(apiClient, "rotateAgentCredential").mockResolvedValue({ ...ready, revision: 3 });
    renderPage();

    const card = await screen.findByRole("article", { name: "Hermes" });
    const user = userEvent.setup();
    await act(async () => {
      await user.type(within(card).getByLabelText("New credential"), "token-def");
      await user.type(within(card).getByLabelText("Current password"), "hunter2hunter2");
      await user.click(within(card).getByRole("button", { name: "Replace credential" }));
    });

    await waitFor(() =>
      expect(rotate).toHaveBeenCalledWith(
        "conn-ready",
        { credential: "token-def", current_password: "hunter2hunter2", expected_revision: 2 },
        expect.stringContaining("agent-credential-rotate")
      )
    );
  });

  it("replaces a lost signing secret and shows the replacement exactly once", async () => {
    vi.mocked(apiClient.listAgentConnections).mockResolvedValue([ready]);
    const replace = vi
      .spyOn(apiClient, "rotateAgentSigningSecret")
      .mockResolvedValue({ ...ready, revision: 3, inbound_signing_secret: "sk-inbound-new" });
    renderPage();

    const card = await screen.findByRole("article", { name: "Hermes" });
    const user = userEvent.setup();
    await act(async () => {
      await user.click(within(card).getByRole("button", { name: /replace signing secret/i }));
    });

    const dialog = screen.getByRole("dialog");
    // The honest part: this is the reporting secret, not the credential, and
    // the old one dies the moment the new one is issued.
    expect(within(dialog).getByText(/stops verifying/i)).toBeInTheDocument();
    await act(async () => {
      await user.type(within(dialog).getByLabelText("Confirm with your password"), "hunter2hunter2");
      await user.click(within(dialog).getByRole("button", { name: "Replace signing secret" }));
    });

    await waitFor(() =>
      expect(replace).toHaveBeenCalledWith(
        "conn-ready",
        { current_password: "hunter2hunter2", expected_revision: 2 },
        expect.stringContaining("agent-signing-secret")
      )
    );

    const panel = await screen.findByRole("region", { name: /replacement signing secret/i });
    expect(within(panel).getByText("sk-inbound-new")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());

    await act(async () => {
      await user.click(within(panel).getByRole("button", { name: /i've saved it/i }));
    });
    expect(screen.queryByText("sk-inbound-new")).not.toBeInTheDocument();
  });

  it("retries an ambiguous replacement under the same idempotency key", async () => {
    vi.mocked(apiClient.listAgentConnections).mockResolvedValue([ready]);
    const replace = vi
      .spyOn(apiClient, "rotateAgentSigningSecret")
      .mockRejectedValueOnce(new ApiError("Bad Gateway", 502, { message: "No answer." }, "corr-sign-1"))
      .mockResolvedValue({ ...ready, revision: 3, inbound_signing_secret: "sk-inbound-new" });
    renderPage();

    const card = await screen.findByRole("article", { name: "Hermes" });
    const user = userEvent.setup();
    await act(async () => {
      await user.click(within(card).getByRole("button", { name: /replace signing secret/i }));
    });

    const dialog = screen.getByRole("dialog");
    await act(async () => {
      await user.type(within(dialog).getByLabelText("Confirm with your password"), "hunter2hunter2");
      await user.click(within(dialog).getByRole("button", { name: "Replace signing secret" }));
    });
    await waitFor(() => expect(within(dialog).getByRole("alert")).toHaveTextContent(/no answer/i));

    await act(async () => {
      await user.click(within(dialog).getByRole("button", { name: "Replace signing secret" }));
    });

    await waitFor(() => expect(replace).toHaveBeenCalledTimes(2));
    // A 502 is ambiguous: the rotation may already have happened, so the retry
    // must be the same request rather than a second one.
    expect(replace.mock.calls[1][2]).toBe(replace.mock.calls[0][2]);
  });

  it("does not offer a signing-secret replacement on a disconnected connection", async () => {
    vi.mocked(apiClient.listAgentConnections).mockResolvedValue([
      connection({ name: "Retired agent", status: "disconnected", ready_for_handoff: false })
    ]);
    renderPage();

    const card = await screen.findByRole("article", { name: "Retired agent" });
    expect(within(card).getByRole("button", { name: /replace signing secret/i })).toBeDisabled();
  });

  it("does not submit a signing-secret replacement while the browser is offline", async () => {
    Object.defineProperty(window.navigator, "onLine", { configurable: true, value: false });
    vi.mocked(apiClient.listAgentConnections).mockResolvedValue([ready]);
    const replace = vi.spyOn(apiClient, "rotateAgentSigningSecret");
    renderPage();

    const card = await screen.findByRole("article", { name: "Hermes" });
    expect(within(card).getByRole("button", { name: /replace signing secret/i })).toBeDisabled();
    expect(replace).not.toHaveBeenCalled();
  });

  it("reacts to browser connectivity changes before allowing one-time secret rotation", async () => {
    vi.mocked(apiClient.listAgentConnections).mockResolvedValue([ready]);
    renderPage();

    const card = await screen.findByRole("article", { name: "Hermes" });
    const replace = within(card).getByRole("button", { name: /replace signing secret/i });
    expect(replace).toBeEnabled();

    act(() => window.dispatchEvent(new Event("offline")));
    expect(replace).toBeDisabled();

    act(() => window.dispatchEvent(new Event("online")));
    expect(replace).toBeEnabled();
  });

  it("warns that disconnecting does not cancel external work before it is confirmed", async () => {
    vi.mocked(apiClient.listAgentConnections).mockResolvedValue([ready]);
    const disconnect = vi
      .spyOn(apiClient, "disconnectAgentConnection")
      .mockResolvedValue(connection({ status: "disconnected", ready_for_handoff: false, revision: 3 }));
    renderPage();

    const card = await screen.findByRole("article", { name: "Hermes" });
    const user = userEvent.setup();
    await act(async () => {
      await user.click(within(card).getByRole("button", { name: /disconnect/i }));
    });

    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText(/does not cancel work/i)).toBeInTheDocument();
    expect(within(dialog).getByText(/credential is destroyed/i)).toBeInTheDocument();

    await act(async () => {
      await user.type(within(dialog).getByLabelText("Confirm with your password"), "hunter2hunter2");
      await user.click(within(dialog).getByRole("button", { name: "Disconnect agent" }));
    });

    await waitFor(() =>
      expect(disconnect).toHaveBeenCalledWith(
        "conn-ready",
        { current_password: "hunter2hunter2", expected_revision: 2 },
        expect.stringContaining("agent-disconnect")
      )
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("lets the user back out of the disconnect dialog", async () => {
    vi.mocked(apiClient.listAgentConnections).mockResolvedValue([ready]);
    const disconnect = vi.spyOn(apiClient, "disconnectAgentConnection");
    renderPage();

    const card = await screen.findByRole("article", { name: "Hermes" });
    const user = userEvent.setup();
    await act(async () => {
      await user.click(within(card).getByRole("button", { name: /disconnect/i }));
    });
    await act(async () => {
      await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Cancel" }));
    });

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(disconnect).not.toHaveBeenCalled();
  });

  it("keeps a failed credential replacement visible for correction", async () => {
    vi.mocked(apiClient.listAgentConnections).mockResolvedValue([ready]);
    vi.spyOn(apiClient, "rotateAgentCredential").mockRejectedValue(
      new ApiError("Forbidden", 403, { message: "Current password is incorrect." }, "corr-credential-2")
    );
    renderPage();

    const card = await screen.findByRole("article", { name: "Hermes" });
    const user = userEvent.setup();
    await user.type(within(card).getByLabelText("New credential"), "token-def");
    await user.type(within(card).getByLabelText("Current password"), "wrong-password");
    await user.click(within(card).getByRole("button", { name: "Replace credential" }));

    expect(await within(card).findByRole("alert")).toHaveTextContent(
      /current password is incorrect.*corr-credential-2/i
    );
    expect(within(card).getByLabelText("New credential")).toHaveValue("token-def");
  });

  it("keeps disconnect confirmation open when re-authentication fails", async () => {
    vi.mocked(apiClient.listAgentConnections).mockResolvedValue([ready]);
    vi.spyOn(apiClient, "disconnectAgentConnection").mockRejectedValue(
      new ApiError("Forbidden", 403, { message: "Current password is incorrect." }, "corr-disconnect-2")
    );
    renderPage();

    const card = await screen.findByRole("article", { name: "Hermes" });
    const user = userEvent.setup();
    await user.click(within(card).getByRole("button", { name: /disconnect/i }));
    const dialog = screen.getByRole("dialog");
    await user.type(within(dialog).getByLabelText("Confirm with your password"), "wrong-password");
    await user.click(within(dialog).getByRole("button", { name: "Disconnect agent" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      /current password is incorrect.*corr-disconnect-2/i
    );
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("reports a failed connection load instead of showing an empty agent list", async () => {
    vi.mocked(apiClient.listAgentConnections).mockRejectedValue(
      new ApiError("Server Error", 500, { message: "Storage unavailable." }, "corr-list-3")
    );
    renderPage();

    expect(await screen.findByRole("alert")).toHaveTextContent(/storage unavailable.*corr-list-3/i);
    expect(screen.queryByText(/no agents connected yet/i)).not.toBeInTheDocument();
  });

  it("shows an empty state once the list loads with no connections", async () => {
    renderPage();

    expect(await screen.findByText(/no agents connected yet/i)).toBeInTheDocument();
  });

  it("reports an add failure with its correlation id and keeps the form filled", async () => {
    vi.spyOn(apiClient, "createAgentConnection").mockRejectedValue(
      new ApiError("Bad Request", 400, { message: "Endpoint must use HTTPS." }, "corr-add-4")
    );
    renderPage();

    const user = userEvent.setup();
    const form = await screen.findByRole("form", { name: /add an agent/i });
    await act(async () => {
      await user.type(within(form).getByLabelText("Agent name"), "Loopback agent");
      await user.type(within(form).getByLabelText("Credential"), "token-abc");
      await user.type(within(form).getByLabelText("Current password"), "hunter2hunter2");
      await user.click(within(form).getByRole("button", { name: "Add agent" }));
    });

    await waitFor(() =>
      expect(within(form).getByRole("alert")).toHaveTextContent(/endpoint must use https.*corr-add-4/i)
    );
    expect(within(form).getByLabelText("Agent name")).toHaveValue("Loopback agent");
    expect(screen.queryByRole("region", { name: /inbound signing secret/i })).not.toBeInTheDocument();
  });
});
