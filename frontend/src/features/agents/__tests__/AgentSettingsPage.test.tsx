import { onlineManager, QueryClient, QueryClientProvider } from "@tanstack/react-query";
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
    onlineManager.setOnline(true);
    vi.restoreAllMocks();
    act(() => {
      useAuthStore.setState({ user: null, status: "loading" });
    });
  });

  it("never queues an offline connection create for automatic replay", async () => {
    Object.defineProperty(window.navigator, "onLine", { configurable: true, value: false });
    onlineManager.setOnline(false);
    const create = vi.spyOn(apiClient, "createAgentConnection");
    renderPage();
    const form = await screen.findByRole("form", { name: /add an agent/i });
    const submit = within(form).getByRole("button", { name: "Add agent" });

    expect(submit).toBeDisabled();
    await userEvent.click(submit);
    expect(create).not.toHaveBeenCalled();

    Object.defineProperty(window.navigator, "onLine", { configurable: true, value: true });
    act(() => {
      window.dispatchEvent(new Event("online"));
      onlineManager.setOnline(true);
    });
    await Promise.resolve();
    expect(create).not.toHaveBeenCalled();
  });

  it("keeps rollout-off connection reads and safe disconnect while hiding blocked mutations", async () => {
    act(() => signIn(false));
    vi.mocked(apiClient.listAgentConnections).mockResolvedValue([ready]);
    const disconnect = vi
      .spyOn(apiClient, "disconnectAgentConnection")
      .mockResolvedValue(connection({ status: "disconnected", ready_for_handoff: false, revision: 3 }));
    renderPage();

    const card = await screen.findByRole("article", { name: "Hermes" });
    expect(apiClient.listAgentConnections).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/relay rollout is off/i)).toBeInTheDocument();
    expect(screen.queryByRole("form", { name: /add an agent/i })).not.toBeInTheDocument();
    expect(within(card).queryByRole("button", { name: /edit connection/i })).not.toBeInTheDocument();
    expect(within(card).queryByRole("button", { name: /test connection/i })).not.toBeInTheDocument();
    expect(within(card).queryByRole("button", { name: /replace signing secret/i })).not.toBeInTheDocument();
    expect(within(card).queryByRole("button", { name: /replace credential/i })).not.toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(within(card).getByRole("button", { name: /disconnect/i }));
    const dialog = screen.getByRole("dialog");
    await user.type(within(dialog).getByLabelText("Confirm with your password"), "hunter2hunter2");
    await user.click(within(dialog).getByRole("button", { name: "Disconnect agent" }));
    await waitFor(() => expect(disconnect).toHaveBeenCalledTimes(1));
  });

  it("maps a migrated invalid header to recovery guidance without exposing its code", async () => {
    vi.spyOn(apiClient, "listAgentConnections").mockResolvedValue([
      connection({
        id: "conn-migrated",
        name: "Migrated agent",
        auth_header_name: "X-Agent-Key",
        status: "untested",
        ready_for_handoff: false,
        last_test_error_code: "legacy_invalid_auth_header_requires_reconfiguration"
      })
    ]);
    renderPage();

    const card = await screen.findByRole("article", { name: "Migrated agent" });
    expect(card).toHaveTextContent(
      /enter a replacement credential for X-Agent-Key, then test the connection/i
    );
    expect(card).not.toHaveTextContent("legacy_invalid_auth_header_requires_reconfiguration");
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
      await user.clear(within(form).getByLabelText("Auth header name"));
      await user.type(within(form).getByLabelText("Auth header name"), "X-Custom-Agent-Key");
      await user.type(within(form).getByLabelText("Credential"), "token-abc");
      await user.type(within(form).getByLabelText("Current password"), "hunter2hunter2");
      await user.click(within(form).getByRole("button", { name: "Add agent" }));
    });

    await waitFor(() =>
      expect(create).toHaveBeenCalledWith(
        {
          name: "Hermes",
          endpoint_url: "https://agent.example.com/hooks",
          auth_header_name: "X-Custom-Agent-Key",
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
    expect(within(form).getByLabelText("Auth header name")).toHaveValue("X-Agent-Key");

    await act(async () => {
      await user.click(within(panel).getByRole("button", { name: /i've saved it/i }));
    });
    expect(screen.queryByText("sk-inbound-9f2c")).not.toBeInTheDocument();
  });

  it.each([408, 429, 502])("retries an ambiguous unchanged add after %i with the exact key and body", async (status: number) => {
    const create = vi
      .spyOn(apiClient, "createAgentConnection")
      .mockRejectedValueOnce(new ApiError("Ambiguous", status, { message: "No answer." }, "corr-add-ambiguous"))
      .mockResolvedValue({
        ...connection({ id: "conn-new", status: "untested", ready_for_handoff: false, revision: 1 }),
        inbound_signing_secret: "secret-on-replay"
      });
    renderPage();

    const user = userEvent.setup();
    const form = await screen.findByRole("form", { name: /add an agent/i });
    await user.type(within(form).getByLabelText("Agent name"), "Hermes");
    await user.type(within(form).getByLabelText("Endpoint URL"), "https://agent.example.com/hooks");
    await user.type(within(form).getByLabelText("Credential"), "token-abc");
    await user.type(within(form).getByLabelText("Current password"), "hunter2hunter2");
    await user.click(within(form).getByRole("button", { name: "Add agent" }));
    await waitFor(() => expect(within(form).getByRole("alert")).toHaveTextContent(/no answer/i));

    await user.click(within(form).getByRole("button", { name: "Add agent" }));
    await waitFor(() => expect(create).toHaveBeenCalledTimes(2));

    expect(create.mock.calls[1][0]).toEqual(create.mock.calls[0][0]);
    expect(create.mock.calls[1][1]).toBe(create.mock.calls[0][1]);
  });

  it("mints a new add key after a definitive 4xx response", async () => {
    const create = vi
      .spyOn(apiClient, "createAgentConnection")
      .mockRejectedValueOnce(new ApiError("Bad Request", 400, { message: "Invalid endpoint." }, "corr-add-4xx"))
      .mockResolvedValue({
        ...connection({ id: "conn-new", status: "untested", ready_for_handoff: false, revision: 1 }),
        inbound_signing_secret: "new-secret"
      });
    renderPage();

    const user = userEvent.setup();
    const form = await screen.findByRole("form", { name: /add an agent/i });
    await user.type(within(form).getByLabelText("Agent name"), "Hermes");
    await user.type(within(form).getByLabelText("Endpoint URL"), "https://agent.example.com/hooks");
    await user.type(within(form).getByLabelText("Credential"), "token-abc");
    await user.type(within(form).getByLabelText("Current password"), "hunter2hunter2");
    await user.click(within(form).getByRole("button", { name: "Add agent" }));
    await waitFor(() => expect(within(form).getByRole("alert")).toHaveTextContent(/invalid endpoint/i));

    await user.click(within(form).getByRole("button", { name: "Add agent" }));
    await waitFor(() => expect(create).toHaveBeenCalledTimes(2));

    expect(create.mock.calls[1][1]).not.toBe(create.mock.calls[0][1]);
  });

  it.each([
    ["Agent name", " 2"],
    ["Endpoint URL", "/changed"],
    ["Auth header name", "-Changed"],
    ["Credential", "-changed"],
    ["Current password", "-changed"]
  ])("mints a new add key when material field %s changes", async (label, suffix) => {
    const create = vi
      .spyOn(apiClient, "createAgentConnection")
      .mockRejectedValue(new ApiError("Bad Gateway", 502, { message: "No answer." }, "corr-add-change"));
    renderPage();

    const user = userEvent.setup();
    const form = await screen.findByRole("form", { name: /add an agent/i });
    await user.type(within(form).getByLabelText("Agent name"), "Hermes");
    await user.type(within(form).getByLabelText("Endpoint URL"), "https://agent.example.com/hooks");
    await user.type(within(form).getByLabelText("Credential"), "token-abc");
    await user.type(within(form).getByLabelText("Current password"), "hunter2hunter2");
    await user.click(within(form).getByRole("button", { name: "Add agent" }));
    await waitFor(() => expect(create).toHaveBeenCalledTimes(1));

    await user.type(within(form).getByLabelText(label), suffix);
    await user.click(within(form).getByRole("button", { name: "Add agent" }));
    await waitFor(() => expect(create).toHaveBeenCalledTimes(2));

    expect(create.mock.calls[1][1]).not.toBe(create.mock.calls[0][1]);
  });

  it("retires the add key after success settlement", async () => {
    const created = {
      ...connection({ id: "conn-new", status: "untested", ready_for_handoff: false, revision: 1 }),
      inbound_signing_secret: "new-secret"
    };
    const create = vi.spyOn(apiClient, "createAgentConnection").mockResolvedValue(created);
    renderPage();

    const user = userEvent.setup();
    const form = await screen.findByRole("form", { name: /add an agent/i });
    for (let attempt = 0; attempt < 2; attempt += 1) {
      await user.type(within(form).getByLabelText("Agent name"), "Hermes");
      await user.type(within(form).getByLabelText("Endpoint URL"), "https://agent.example.com/hooks");
      await user.type(within(form).getByLabelText("Credential"), "token-abc");
      await user.type(within(form).getByLabelText("Current password"), "hunter2hunter2");
      await user.click(within(form).getByRole("button", { name: "Add agent" }));
      await waitFor(() => expect(create).toHaveBeenCalledTimes(attempt + 1));
      await waitFor(() => expect(within(form).getByLabelText("Agent name")).toHaveValue(""));
    }

    expect(create.mock.calls[1][1]).not.toBe(create.mock.calls[0][1]);
  });

  it("directs an empty-secret replay to explicit signing-secret recovery", async () => {
    const replayed = connection({
      id: "conn-replayed",
      name: "Hermes replayed",
      status: "untested",
      ready_for_handoff: false,
      revision: 1
    });
    vi.mocked(apiClient.listAgentConnections).mockResolvedValueOnce([]).mockResolvedValue([replayed]);
    vi.spyOn(apiClient, "createAgentConnection").mockResolvedValue({
      ...replayed,
      inbound_signing_secret: ""
    });
    renderPage();

    const user = userEvent.setup();
    const form = await screen.findByRole("form", { name: /add an agent/i });
    await user.type(within(form).getByLabelText("Agent name"), "Hermes replayed");
    await user.type(within(form).getByLabelText("Endpoint URL"), "https://agent.example.com/hooks");
    await user.type(within(form).getByLabelText("Credential"), "token-abc");
    await user.type(within(form).getByLabelText("Current password"), "hunter2hunter2");
    await user.click(within(form).getByRole("button", { name: "Add agent" }));

    expect(await screen.findByRole("status")).toHaveTextContent(
      /Hermes replayed was added.*signing secret.*replace signing secret/i
    );
    expect(screen.queryByRole("region", { name: /inbound signing secret/i })).not.toBeInTheDocument();
    const card = await screen.findByRole("article", { name: "Hermes replayed" });
    expect(within(card).getByRole("button", { name: /replace signing secret/i })).toBeEnabled();
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

  it("updates a connection name without asking for a password or resetting readiness", async () => {
    vi.mocked(apiClient.listAgentConnections).mockResolvedValue([ready]);
    const update = vi.spyOn(apiClient, "updateAgentConnection").mockResolvedValue({ ...ready, name: "Hermes prod", revision: 3 });
    renderPage();

    const card = await screen.findByRole("article", { name: "Hermes" });
    const user = userEvent.setup();
    await user.click(within(card).getByRole("button", { name: "Edit connection" }));
    const form = within(card).getByRole("form", { name: "Edit connection" });
    await user.clear(within(form).getByLabelText("Agent name"));
    await user.type(within(form).getByLabelText("Agent name"), "Hermes prod");
    expect(within(form).queryByLabelText("Current password")).not.toBeInTheDocument();
    expect(within(form).queryByText(/readiness.*reset/i)).not.toBeInTheDocument();
    await user.click(within(form).getByRole("button", { name: "Save connection" }));

    await waitFor(() => expect(update).toHaveBeenCalledWith(
      "conn-ready",
      { name: "Hermes prod", expected_revision: 2 },
      expect.stringContaining("agent-connection-update")
    ));
  });

  it("requires reauthentication for an endpoint change and explains readiness reset", async () => {
    vi.mocked(apiClient.listAgentConnections).mockResolvedValue([ready]);
    const update = vi.spyOn(apiClient, "updateAgentConnection").mockResolvedValue({
      ...ready,
      endpoint_url: "https://new.example.com/hooks",
      status: "untested",
      ready_for_handoff: false,
      revision: 3
    });
    renderPage();

    const card = await screen.findByRole("article", { name: "Hermes" });
    const user = userEvent.setup();
    await user.click(within(card).getByRole("button", { name: "Edit connection" }));
    const form = within(card).getByRole("form", { name: "Edit connection" });
    await user.clear(within(form).getByLabelText("Endpoint URL"));
    await user.type(within(form).getByLabelText("Endpoint URL"), "https://new.example.com/hooks");
    expect(within(form).getByText(/endpoint change resets readiness.*test/i)).toBeInTheDocument();
    await user.type(within(form).getByLabelText("Current password"), "reauth-secret");
    await user.click(within(form).getByRole("button", { name: "Save connection" }));

    await waitFor(() => expect(update).toHaveBeenCalledWith(
      "conn-ready",
      {
        endpoint_url: "https://new.example.com/hooks",
        expected_revision: 2,
        current_password: "reauth-secret"
      },
      expect.stringContaining("agent-connection-update")
    ));
    expect(screen.queryByRole("form", { name: "Edit connection" })).not.toBeInTheDocument();
    expect(screen.queryByDisplayValue("reauth-secret")).not.toBeInTheDocument();
  });

  it.each([408, 429, 502])("retries an ambiguous connection update after %i with the frozen request and key", async (status) => {
    vi.mocked(apiClient.listAgentConnections).mockResolvedValue([ready]);
    const update = vi.spyOn(apiClient, "updateAgentConnection")
      .mockRejectedValueOnce(new ApiError("Ambiguous", status, { message: "Lost response" }))
      .mockResolvedValue({ ...ready, endpoint_url: "https://new.example.com/hooks", revision: 3 });
    renderPage();

    const card = await screen.findByRole("article", { name: "Hermes" });
    const user = userEvent.setup();
    await user.click(within(card).getByRole("button", { name: "Edit connection" }));
    const form = within(card).getByRole("form", { name: "Edit connection" });
    await user.clear(within(form).getByLabelText("Endpoint URL"));
    await user.type(within(form).getByLabelText("Endpoint URL"), "https://new.example.com/hooks");
    await user.type(within(form).getByLabelText("Current password"), "reauth-secret");
    await user.click(within(form).getByRole("button", { name: "Save connection" }));
    await within(form).findByRole("alert");
    expect(within(form).getByLabelText("Current password")).toHaveValue("");
    await user.click(within(form).getByRole("button", { name: "Retry exact update" }));
    await waitFor(() => expect(update).toHaveBeenCalledTimes(2));

    expect(update.mock.calls[1][1]).toEqual(update.mock.calls[0][1]);
    expect(update.mock.calls[1][2]).toBe(update.mock.calls[0][2]);
  });

  it("retires a stale-revision update after conflict without leaking its password into cache or UI", async () => {
    vi.mocked(apiClient.listAgentConnections).mockResolvedValue([ready]);
    vi.spyOn(apiClient, "updateAgentConnection")
      .mockRejectedValueOnce(new ApiError("Conflict", 409, { message: "Connection changed. Refresh and try again." }))
      .mockRejectedValue(new ApiError("Conflict", 409, { message: "Connection changed. Refresh and try again." }));
    renderPage();

    const card = await screen.findByRole("article", { name: "Hermes" });
    const user = userEvent.setup();
    await user.click(within(card).getByRole("button", { name: "Edit connection" }));
    const form = within(card).getByRole("form", { name: "Edit connection" });
    await user.clear(within(form).getByLabelText("Endpoint URL"));
    await user.type(within(form).getByLabelText("Endpoint URL"), "https://new.example.com/hooks");
    await user.type(within(form).getByLabelText("Current password"), "never-cache-me");
    await user.click(within(form).getByRole("button", { name: "Save connection" }));

    expect(await within(form).findByRole("alert")).toHaveTextContent(/changed.*refresh/i);
    expect(within(form).getByLabelText("Current password")).toHaveValue("");
    expect(screen.queryByDisplayValue("never-cache-me")).not.toBeInTheDocument();
    expect(within(form).queryByRole("button", { name: "Retry exact update" })).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain("never-cache-me");
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

  it.each([408, 429, 502])("retries an ambiguous credential rotation after %i with the exact key and body", async (status: number) => {
    vi.mocked(apiClient.listAgentConnections).mockResolvedValue([ready]);
    const rotate = vi.spyOn(apiClient, "rotateAgentCredential")
      .mockRejectedValueOnce(new ApiError("Ambiguous", status, { message: "Lost response" }))
      .mockResolvedValue({ ...ready, revision: 3 });
    renderPage();
    const card = await screen.findByRole("article", { name: "Hermes" });
    const user = userEvent.setup();
    await user.type(within(card).getByLabelText("New credential"), "token-def");
    await user.type(within(card).getByLabelText("Current password"), "hunter2hunter2");
    await user.click(within(card).getByRole("button", { name: "Replace credential" }));
    await within(card).findByRole("alert");
    await user.click(within(card).getByRole("button", { name: "Replace credential" }));
    await waitFor(() => expect(rotate).toHaveBeenCalledTimes(2));

    expect(rotate.mock.calls[1][1]).toEqual(rotate.mock.calls[0][1]);
    expect(rotate.mock.calls[1][2]).toBe(rotate.mock.calls[0][2]);
  });

  it("retires credential rotation intent after 4xx or a material payload change", async () => {
    vi.mocked(apiClient.listAgentConnections).mockResolvedValue([ready]);
    const rotate = vi.spyOn(apiClient, "rotateAgentCredential")
      .mockRejectedValueOnce(new ApiError("Forbidden", 403, { message: "Wrong password" }))
      .mockRejectedValue(new ApiError("Bad Gateway", 502, { message: "Lost response" }));
    renderPage();
    const card = await screen.findByRole("article", { name: "Hermes" });
    const user = userEvent.setup();
    await user.type(within(card).getByLabelText("New credential"), "token-one");
    await user.type(within(card).getByLabelText("Current password"), "wrong");
    await user.click(within(card).getByRole("button", { name: "Replace credential" }));
    await within(card).findByRole("alert");
    await user.clear(within(card).getByLabelText("Current password"));
    await user.type(within(card).getByLabelText("Current password"), "correct");
    await user.click(within(card).getByRole("button", { name: "Replace credential" }));
    await waitFor(() => expect(rotate).toHaveBeenCalledTimes(2));
    await user.clear(within(card).getByLabelText("New credential"));
    await user.type(within(card).getByLabelText("New credential"), "token-two");
    await user.click(within(card).getByRole("button", { name: "Replace credential" }));
    await waitFor(() => expect(rotate).toHaveBeenCalledTimes(3));

    expect(rotate.mock.calls[1][2]).not.toBe(rotate.mock.calls[0][2]);
    expect(rotate.mock.calls[2][2]).not.toBe(rotate.mock.calls[1][2]);
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

  it.each([408, 429, 502])("retries an ambiguous signing-secret replacement after %i with the exact key and body", async (status: number) => {
    vi.mocked(apiClient.listAgentConnections).mockResolvedValue([ready]);
    const replace = vi
      .spyOn(apiClient, "rotateAgentSigningSecret")
      .mockRejectedValueOnce(new ApiError("Ambiguous", status, { message: "No answer." }, "corr-sign-1"))
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
    // The rotation may already have happened, so the retry
    // must be the same request rather than a second one.
    expect(replace.mock.calls[1][1]).toEqual(replace.mock.calls[0][1]);
    expect(replace.mock.calls[1][2]).toBe(replace.mock.calls[0][2]);
  });

  it("mints a new signing-secret key when the password changes after an ambiguous failure", async () => {
    vi.mocked(apiClient.listAgentConnections).mockResolvedValue([ready]);
    const replace = vi
      .spyOn(apiClient, "rotateAgentSigningSecret")
      .mockRejectedValue(new ApiError("Bad Gateway", 502, { message: "No answer." }, "corr-sign-password"));
    renderPage();

    const user = userEvent.setup();
    const card = await screen.findByRole("article", { name: "Hermes" });
    await user.click(within(card).getByRole("button", { name: /replace signing secret/i }));
    let dialog = screen.getByRole("dialog");
    await user.type(within(dialog).getByLabelText("Confirm with your password"), "wrong-password");
    await user.click(within(dialog).getByRole("button", { name: "Replace signing secret" }));
    await waitFor(() => expect(replace).toHaveBeenCalledTimes(1));

    await user.clear(within(dialog).getByLabelText("Confirm with your password"));
    await user.type(within(dialog).getByLabelText("Confirm with your password"), "correct-password");
    await user.click(within(dialog).getByRole("button", { name: "Replace signing secret" }));
    await waitFor(() => expect(replace).toHaveBeenCalledTimes(2));

    expect(replace.mock.calls[1][2]).not.toBe(replace.mock.calls[0][2]);
    dialog = screen.getByRole("dialog");
    expect(within(dialog).getByLabelText("Confirm with your password")).toHaveValue("correct-password");
  });

  it("retires a signing-secret key after a definitive 4xx before a corrected retry", async () => {
    vi.mocked(apiClient.listAgentConnections).mockResolvedValue([ready]);
    const replace = vi
      .spyOn(apiClient, "rotateAgentSigningSecret")
      .mockRejectedValueOnce(
        new ApiError("Forbidden", 403, { message: "Current password is incorrect." }, "corr-sign-4xx"),
      )
      .mockResolvedValue({ ...ready, revision: 3, inbound_signing_secret: "replacement-secret" });
    renderPage();

    const user = userEvent.setup();
    const card = await screen.findByRole("article", { name: "Hermes" });
    await user.click(within(card).getByRole("button", { name: /replace signing secret/i }));
    const dialog = screen.getByRole("dialog");
    await user.type(within(dialog).getByLabelText("Confirm with your password"), "wrong-password");
    await user.click(within(dialog).getByRole("button", { name: "Replace signing secret" }));
    await waitFor(() => expect(within(dialog).getByRole("alert")).toHaveTextContent(/incorrect/i));

    await user.clear(within(dialog).getByLabelText("Confirm with your password"));
    await user.type(within(dialog).getByLabelText("Confirm with your password"), "correct-password");
    await user.click(within(dialog).getByRole("button", { name: "Replace signing secret" }));
    await waitFor(() => expect(replace).toHaveBeenCalledTimes(2));

    expect(replace.mock.calls[1][2]).not.toBe(replace.mock.calls[0][2]);
  });

  it("reuses the ambiguous signing-secret intent after close and reopen for the exact same payload", async () => {
    vi.mocked(apiClient.listAgentConnections).mockResolvedValue([ready]);
    const replace = vi
      .spyOn(apiClient, "rotateAgentSigningSecret")
      .mockRejectedValue(new ApiError("Bad Gateway", 502, { message: "No answer." }, "corr-sign-reopen"));
    renderPage();

    const user = userEvent.setup();
    const card = await screen.findByRole("article", { name: "Hermes" });
    await user.click(within(card).getByRole("button", { name: /replace signing secret/i }));
    let dialog = screen.getByRole("dialog");
    await user.type(within(dialog).getByLabelText("Confirm with your password"), "same-password");
    await user.click(within(dialog).getByRole("button", { name: "Replace signing secret" }));
    await waitFor(() => expect(replace).toHaveBeenCalledTimes(1));
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));

    await user.click(within(cardFor("Hermes")).getByRole("button", { name: /replace signing secret/i }));
    dialog = screen.getByRole("dialog");
    await user.type(within(dialog).getByLabelText("Confirm with your password"), "same-password");
    await user.click(within(dialog).getByRole("button", { name: "Replace signing secret" }));
    await waitFor(() => expect(replace).toHaveBeenCalledTimes(2));

    expect(replace.mock.calls[1][2]).toBe(replace.mock.calls[0][2]);
  });

  it("mints a new signing-secret key when the connection revision changes", async () => {
    vi.mocked(apiClient.listAgentConnections)
      .mockResolvedValueOnce([ready])
      .mockResolvedValue([connection({ revision: 3 })]);
    vi.spyOn(apiClient, "testAgentConnection").mockResolvedValue(connection({ revision: 3 }));
    const replace = vi
      .spyOn(apiClient, "rotateAgentSigningSecret")
      .mockRejectedValue(new ApiError("Bad Gateway", 502, { message: "No answer." }, "corr-sign-revision"));
    renderPage();

    const user = userEvent.setup();
    let card = await screen.findByRole("article", { name: "Hermes" });
    await user.click(within(card).getByRole("button", { name: /replace signing secret/i }));
    let dialog = screen.getByRole("dialog");
    await user.type(within(dialog).getByLabelText("Confirm with your password"), "same-password");
    await user.click(within(dialog).getByRole("button", { name: "Replace signing secret" }));
    await waitFor(() => expect(replace).toHaveBeenCalledTimes(1));
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));

    card = cardFor("Hermes");
    await user.click(within(card).getByRole("button", { name: "Test connection" }));
    await waitFor(() => expect(apiClient.listAgentConnections).toHaveBeenCalledTimes(2));
    await user.click(within(cardFor("Hermes")).getByRole("button", { name: /replace signing secret/i }));
    dialog = screen.getByRole("dialog");
    await user.type(within(dialog).getByLabelText("Confirm with your password"), "same-password");
    await user.click(within(dialog).getByRole("button", { name: "Replace signing secret" }));
    await waitFor(() => expect(replace).toHaveBeenCalledTimes(2));

    expect(replace.mock.calls[1][1].expected_revision).toBe(3);
    expect(replace.mock.calls[1][2]).not.toBe(replace.mock.calls[0][2]);
  });

  it("retires a signing-secret key after success settlement", async () => {
    vi.mocked(apiClient.listAgentConnections).mockResolvedValue([ready]);
    const replace = vi
      .spyOn(apiClient, "rotateAgentSigningSecret")
      .mockResolvedValue({ ...ready, revision: 3, inbound_signing_secret: "replacement-secret" });
    renderPage();

    const user = userEvent.setup();
    let card = await screen.findByRole("article", { name: "Hermes" });
    for (let attempt = 0; attempt < 2; attempt += 1) {
      await user.click(within(card).getByRole("button", { name: /replace signing secret/i }));
      const dialog = screen.getByRole("dialog");
      await user.type(within(dialog).getByLabelText("Confirm with your password"), "same-password");
      await user.click(within(dialog).getByRole("button", { name: "Replace signing secret" }));
      await waitFor(() => expect(replace).toHaveBeenCalledTimes(attempt + 1));
      await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
      const panel = screen.getByRole("region", { name: /replacement signing secret/i });
      await user.click(within(panel).getByRole("button", { name: /i've saved it/i }));
      card = cardFor("Hermes");
    }

    expect(replace.mock.calls[1][2]).not.toBe(replace.mock.calls[0][2]);
  });

  it("uses distinct signing-secret keys for different connections", async () => {
    vi.mocked(apiClient.listAgentConnections).mockResolvedValue([
      ready,
      connection({ id: "conn-second", name: "Second agent" }),
    ]);
    const replace = vi
      .spyOn(apiClient, "rotateAgentSigningSecret")
      .mockRejectedValue(new ApiError("Bad Gateway", 502, { message: "No answer." }, "corr-sign-connection"));
    renderPage();

    const user = userEvent.setup();
    for (const name of ["Hermes", "Second agent"]) {
      const card = await screen.findByRole("article", { name });
      await user.click(within(card).getByRole("button", { name: /replace signing secret/i }));
      const dialog = screen.getByRole("dialog");
      await user.type(within(dialog).getByLabelText("Confirm with your password"), "same-password");
      await user.click(within(dialog).getByRole("button", { name: "Replace signing secret" }));
      await waitFor(() => expect(replace).toHaveBeenCalledTimes(name === "Hermes" ? 1 : 2));
      await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    }

    expect(replace.mock.calls[1][2]).not.toBe(replace.mock.calls[0][2]);
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

  it("disables an open disconnect confirmation when connectivity is lost", async () => {
    vi.mocked(apiClient.listAgentConnections).mockResolvedValue([ready]);
    const disconnect = vi.spyOn(apiClient, "disconnectAgentConnection");
    renderPage();

    const card = await screen.findByRole("article", { name: "Hermes" });
    const user = userEvent.setup();
    await user.click(within(card).getByRole("button", { name: /disconnect/i }));
    const dialog = screen.getByRole("dialog");
    const confirm = within(dialog).getByRole("button", { name: "Disconnect agent" });
    expect(confirm).toBeEnabled();

    Object.defineProperty(window.navigator, "onLine", { configurable: true, value: false });
    act(() => {
      window.dispatchEvent(new Event("offline"));
      onlineManager.setOnline(false);
    });

    expect(confirm).toBeDisabled();
    await user.click(confirm);
    expect(disconnect).not.toHaveBeenCalled();
  });

  it.each([408, 429, 502])("retries an ambiguous disconnect after %i with the exact key and body", async (status: number) => {
    vi.mocked(apiClient.listAgentConnections).mockResolvedValue([ready]);
    const disconnect = vi.spyOn(apiClient, "disconnectAgentConnection")
      .mockRejectedValueOnce(new ApiError("Ambiguous", status, { message: "Lost response" }))
      .mockResolvedValue(connection({ status: "disconnected", ready_for_handoff: false, revision: 3 }));
    renderPage();
    const card = await screen.findByRole("article", { name: "Hermes" });
    const user = userEvent.setup();
    await user.click(within(card).getByRole("button", { name: /disconnect/i }));
    const dialog = screen.getByRole("dialog");
    await user.type(within(dialog).getByLabelText("Confirm with your password"), "hunter2hunter2");
    await user.click(within(dialog).getByRole("button", { name: "Disconnect agent" }));
    await within(dialog).findByRole("alert");
    await user.click(within(dialog).getByRole("button", { name: "Disconnect agent" }));
    await waitFor(() => expect(disconnect).toHaveBeenCalledTimes(2));

    expect(disconnect.mock.calls[1][1]).toEqual(disconnect.mock.calls[0][1]);
    expect(disconnect.mock.calls[1][2]).toBe(disconnect.mock.calls[0][2]);
  });

  it("retires disconnect intent after a definitive 4xx and changed password", async () => {
    vi.mocked(apiClient.listAgentConnections).mockResolvedValue([ready]);
    const disconnect = vi.spyOn(apiClient, "disconnectAgentConnection")
      .mockRejectedValueOnce(new ApiError("Forbidden", 403, { message: "Wrong password" }))
      .mockRejectedValue(new ApiError("Bad Gateway", 502, { message: "Lost response" }));
    renderPage();
    const card = await screen.findByRole("article", { name: "Hermes" });
    const user = userEvent.setup();
    await user.click(within(card).getByRole("button", { name: /disconnect/i }));
    const dialog = screen.getByRole("dialog");
    const password = within(dialog).getByLabelText("Confirm with your password");
    await user.type(password, "wrong");
    await user.click(within(dialog).getByRole("button", { name: "Disconnect agent" }));
    await within(dialog).findByRole("alert");
    await user.clear(password);
    await user.type(password, "correct");
    await user.click(within(dialog).getByRole("button", { name: "Disconnect agent" }));
    await waitFor(() => expect(disconnect).toHaveBeenCalledTimes(2));

    expect(disconnect.mock.calls[1][2]).not.toBe(disconnect.mock.calls[0][2]);
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
