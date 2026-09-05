import { onlineManager, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AgentConnectionResponse } from "../../../api/agentTypes";
import { ApiError, apiClient } from "../../../api/client";
import { useAuthStore } from "../../../stores/authStore";
import { AgentSettingsGate } from "../AgentSettingsGate";

const card: NonNullable<AgentConnectionResponse["card"]> = {
  name: "Hermes",
  version: "1.2.3",
  description: "A research agent.",
  protocol_version: "1.0",
  interface_url: "https://agent.example.com/a2a",
  streaming: true,
  push_notifications: false,
  skills: [{ id: "research", name: "Research", description: "Digs." }],
  auth_schemes_offered: [{ name: "bearer", kind: "bearer", header_name: null }],
  extension_uris: [],
  fetched_at: "2026-08-09T10:00:00Z"
};

const ready: AgentConnectionResponse = {
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
  card,
  guarantee_tier: "best_effort",
  tier_disclosure:
    "Best-effort single start. This agent's card does not declare BrainBuddy's single-start extension.",
  tier_disclosure_url: "https://example.invalid/single-start/v1.md",
  cancellation_disclosure: "Cancellation depends on the agent.",
  agent_changed: false,
  best_effort_acknowledged_at: null,
  correlation_id_honoured: null,
  disconnect_reason: null,
  last_test_error_code: null,
  last_test_error_detail: null,
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
    await user.click(within(dialog).getByRole("button", { name: "Disconnect", exact: true }));
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
      /enter a replacement credential, then test the connection/i
    );
    expect(card).not.toHaveTextContent("legacy_invalid_auth_header_requires_reconfiguration");
  });

  it("014-FR-001 adds a connection by address and scheme, and shows no secret (D-01-S08/S09)", async () => {
    const create = vi
      .spyOn(apiClient, "createAgentConnection")
      .mockResolvedValue(
        connection({ id: "conn-new", status: "untested", stale: false, ready_for_handoff: false, card: null, revision: 1 })
      );
    renderPage();

    const user = userEvent.setup();
    const form = await screen.findByRole("form", { name: /add an agent/i });
    await act(async () => {
      await user.type(within(form).getByLabelText("Agent name"), "Hermes");
      await user.clear(within(form).getByLabelText("Agent address"));
      await user.type(within(form).getByLabelText("Agent address"), "https://agent.example.com");
      await user.click(within(form).getByRole("radio", { name: "API key" }));
      await user.type(within(form).getByLabelText("Credential"), "token-abc");
      await user.type(within(form).getByLabelText("Current password"), "hunter2hunter2");
      await user.click(within(form).getByRole("button", { name: "Add agent" }));
    });

    await waitFor(() =>
      expect(create).toHaveBeenCalledWith(
        {
          name: "Hermes",
          agent_address: "https://agent.example.com",
          auth_scheme: "api_key",
          credential: "token-abc",
          current_password: "hunter2hunter2"
        },
        expect.stringContaining("agent-connection-create")
      )
    );

    // There is no secret to show once: the A2A wire has no inbound secret an
    // owner has to configure at their agent (014-FR-012).
    expect(screen.queryByRole("region", { name: /signing secret/i })).not.toBeInTheDocument();
    expect(await screen.findByText(/BrainBuddy reads its card/i)).toBeInTheDocument();
  });

  it("014-FR-001 reads the API-key header name off the card and never accepts one typed", async () => {
    renderPage();

    const user = userEvent.setup();
    const form = await screen.findByRole("form", { name: /add an agent/i });
    expect(within(form).queryByLabelText("Header name")).not.toBeInTheDocument();

    await act(async () => {
      await user.click(within(form).getByRole("radio", { name: "API key" }));
    });

    const headerField = within(form).getByLabelText(/Header name/);
    expect(headerField).toHaveAttribute("readonly");
    expect(headerField).toHaveValue("Read from the agent card when you test");
    expect(within(form).getByText(/You do not type it/i)).toBeInTheDocument();

    // Switching back withdraws the field: a bearer connection derives
    // `Authorization` from the scheme and has no header name to show.
    await act(async () => {
      await user.click(within(form).getByRole("radio", { name: "Bearer token" }));
    });
    expect(within(form).queryByLabelText(/Header name/)).toBeNull();
    expect(within(form).getByRole("radio", { name: "Bearer token" })).toBeChecked();
  });

  it.each([408, 429, 502])("retries an ambiguous unchanged add after %i with the exact key and body", async (status: number) => {
    const create = vi
      .spyOn(apiClient, "createAgentConnection")
      .mockRejectedValueOnce(new ApiError("Ambiguous", status, { message: "No answer." }, "corr-add-ambiguous"))
      .mockResolvedValue(
        connection({ id: "conn-new", status: "untested", ready_for_handoff: false, revision: 1 })
      );
    renderPage();

    const user = userEvent.setup();
    const form = await screen.findByRole("form", { name: /add an agent/i });
    await user.type(within(form).getByLabelText("Agent name"), "Hermes");
    await user.type(within(form).getByLabelText("Agent address"), "https://agent.example.com");
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
      .mockResolvedValue(
        connection({ id: "conn-new", status: "untested", ready_for_handoff: false, revision: 1 })
      );
    renderPage();

    const user = userEvent.setup();
    const form = await screen.findByRole("form", { name: /add an agent/i });
    await user.type(within(form).getByLabelText("Agent name"), "Hermes");
    await user.type(within(form).getByLabelText("Agent address"), "https://agent.example.com");
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
    ["Agent address", "/changed"],
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
    await user.type(within(form).getByLabelText("Agent address"), "https://agent.example.com");
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
    const created = connection({
      id: "conn-new",
      status: "untested",
      ready_for_handoff: false,
      revision: 1
    });
    const create = vi.spyOn(apiClient, "createAgentConnection").mockResolvedValue(created);
    renderPage();

    const user = userEvent.setup();
    const form = await screen.findByRole("form", { name: /add an agent/i });
    for (let attempt = 0; attempt < 2; attempt += 1) {
      await user.type(within(form).getByLabelText("Agent name"), "Hermes");
      await user.type(within(form).getByLabelText("Agent address"), "https://agent.example.com/hooks");
      await user.type(within(form).getByLabelText("Credential"), "token-abc");
      await user.type(within(form).getByLabelText("Current password"), "hunter2hunter2");
      await user.click(within(form).getByRole("button", { name: "Add agent" }));
      await waitFor(() => expect(create).toHaveBeenCalledTimes(attempt + 1));
      await waitFor(() => expect(within(form).getByLabelText("Agent name")).toHaveValue(""));
    }

    expect(create.mock.calls[1][1]).not.toBe(create.mock.calls[0][1]);
  });

  it("014-FR-012 a replayed add is confirmed without any secret to recover", async () => {
    const replayed = connection({
      id: "conn-replayed",
      name: "Hermes replayed",
      status: "untested",
      ready_for_handoff: false,
      card: null,
      revision: 1
    });
    vi.mocked(apiClient.listAgentConnections).mockResolvedValueOnce([]).mockResolvedValue([replayed]);
    vi.spyOn(apiClient, "createAgentConnection").mockResolvedValue(replayed);
    renderPage();

    const user = userEvent.setup();
    const form = await screen.findByRole("form", { name: /add an agent/i });
    await user.type(within(form).getByLabelText("Agent name"), "Hermes replayed");
    await user.type(within(form).getByLabelText("Agent address"), "https://agent.example.com");
    await user.type(within(form).getByLabelText("Credential"), "token-abc");
    await user.type(within(form).getByLabelText("Current password"), "hunter2hunter2");
    await user.click(within(form).getByRole("button", { name: "Add agent" }));

    // A replay used to strand the owner: the one-time secret was already spent,
    // so the second answer could not carry it. There is no secret now, so a
    // replay is simply the same success (014-FR-012).
    expect(await screen.findByRole("status")).toHaveTextContent(
      /Hermes replayed was added/i
    );
    expect(screen.queryByText(/signing secret/i)).not.toBeInTheDocument();
    const card = await screen.findByRole("article", { name: "Hermes replayed" });
    expect(within(card).queryByRole("button", { name: /replace signing secret/i })).toBeNull();
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

  it("014-FR-002 shows the discovery result and the tier on a ready connection (D-01-S10/S11)", async () => {
    vi.mocked(apiClient.listAgentConnections).mockResolvedValue([ready]);
    renderPage();

    const card = await screen.findByRole("article", { name: "Hermes" });
    const discovery = within(card).getByRole("region", { name: "Discovery result" });
    expect(within(discovery).getByText("1.2.3")).toBeInTheDocument();
    expect(within(discovery).getByText("A research agent.")).toBeInTheDocument();
    expect(within(discovery).getByText("1.0")).toBeInTheDocument();
    expect(within(discovery).getByText("https://agent.example.com/a2a")).toBeInTheDocument();
    expect(within(discovery).getByRole("listitem")).toHaveTextContent("Research");

    const guarantee = within(card).getByRole("region", { name: "Guarantee" });
    expect(within(guarantee).getByText(/Best-effort single start\./)).toBeInTheDocument();
    expect(within(guarantee).getByText(/Cancellation depends on the agent/)).toBeInTheDocument();
    const link = within(guarantee).getByRole("link", {
      name: /Read the single-start extension specification/i
    });
    expect(link).toHaveAttribute("href", "https://example.invalid/single-start/v1.md");
    expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
    expect(within(guarantee).getByText(/Opens the published specification outside BrainBuddy/i)).toBeInTheDocument();
  });

  it("014-FR-016 renders card text inertly, whatever the agent put in it (AC-031)", async () => {
    const hostile = "<script>alert(1)</script> **not markdown**";
    vi.mocked(apiClient.listAgentConnections).mockResolvedValue([
      connection({
        name: "Hostile agent",
        card: {
          ...card,
          name: hostile,
          description: hostile,
          interface_url: "javascript:alert(2)"
        }
      })
    ]);
    renderPage();

    const article = await screen.findByRole("article", { name: "Hostile agent" });
    const discovery = within(article).getByRole("region", { name: "Discovery result" });

    // Verbatim, and inert: no anchor, no navigable element, no markup applied.
    expect(within(discovery).getAllByText(hostile).length).toBeGreaterThan(0);
    expect(discovery.querySelector("script")).toBeNull();
    expect(discovery.querySelector("strong")).toBeNull();
    expect(within(discovery).queryByRole("link")).toBeNull();
    expect(within(discovery).getByText("javascript:alert(2)")).toBeInTheDocument();
  });

  it.each([
    [
      "a2a_not_an_agent",
      null,
      /no agent card at its well-known location/i
    ],
    [
      "a2a_protocol_version_unsupported",
      { found_version: "0.9.4" },
      /card declares A2A 0\.9\.4/i
    ],
    ["a2a_no_supported_interface", null, /No JSON-RPC interface BrainBuddy can use over HTTPS/i],
    ["a2a_auth_scheme_unsupported", { scheme: "oauth2" }, /This card requires oauth2/i]
  ])(
    "014-FR-002 gives the %s category its own sentence (D-01-S14..S17)",
    async (code, detail, expected) => {
      vi.mocked(apiClient.listAgentConnections).mockResolvedValue([
        connection({
          name: "Unsupported agent",
          status: "unsupported",
          ready_for_handoff: false,
          card: null,
          last_test_error_code: code,
          last_test_error_detail: detail as AgentConnectionResponse["last_test_error_detail"]
        })
      ]);
      renderPage();

      const article = await screen.findByRole("article", { name: "Unsupported agent" });
      expect(within(article).getByText("Unsupported")).toBeInTheDocument();
      expect(within(article).getByText(expected)).toBeInTheDocument();
      expect(within(article).getByText(/cannot receive a hand-off yet/i)).toBeInTheDocument();
    }
  );

  it("014-FR-002 shows Agent changed with both interfaces side by side (D-01-S20)", async () => {
    vi.mocked(apiClient.listAgentConnections).mockResolvedValue([
      connection({
        name: "Moved agent",
        status: "untested",
        ready_for_handoff: false,
        agent_changed: true,
        last_test_error_code: "agent_card_changed",
        last_test_error_detail: { interface_url: "https://second.example.com/a2a" }
      })
    ]);
    renderPage();

    const article = await screen.findByRole("article", { name: "Moved agent" });
    expect(within(article).getByText("Agent changed")).toBeInTheDocument();
    expect(within(article).getByText(/will not send task content to a destination you have not tested/i)).toBeInTheDocument();
    const comparison = within(article).getByText("Tested interface").closest("dl");
    expect(comparison).not.toBeNull();
    expect(within(comparison as HTMLElement).getByText("https://agent.example.com/a2a")).toBeInTheDocument();
    expect(within(comparison as HTMLElement).getByText("Card now says")).toBeInTheDocument();
    expect(
      within(comparison as HTMLElement).getByText("https://second.example.com/a2a")
    ).toBeInTheDocument();
    expect(within(article).getByText(/cannot receive a hand-off yet/i)).toBeInTheDocument();
  });

  it("014-FR-012 names a superseded wire contract with no path back to it (D-01-S21)", async () => {
    vi.mocked(apiClient.listAgentConnections).mockResolvedValue([
      connection({
        name: "Legacy agent",
        status: "disconnected",
        ready_for_handoff: false,
        card: null,
        disconnect_reason: "superseded_wire_contract"
      })
    ]);
    renderPage();

    const article = await screen.findByRole("article", { name: "Legacy agent" });
    expect(within(article).getByText("Superseded wire contract")).toBeInTheDocument();
    expect(within(article).getByText(/Add the agent again by its address/i)).toBeInTheDocument();
    for (const name of ["Edit connection", "Test connection", "Disconnect…"]) {
      expect(within(article).getByRole("button", { name })).toBeDisabled();
    }
  });

  it.each([
    [30, /Test again in about 30 seconds\./],
    [null, /Test again shortly\./]
  ])(
    "014-FR-002 keeps a rate-limited connection untested and offers the retry (D-01-S25)",
    async (retryAfter, expected) => {
      vi.mocked(apiClient.listAgentConnections).mockResolvedValue([
        connection({
          name: "Busy agent",
          status: "untested",
          ready_for_handoff: false,
          last_test_error_code: "a2a_rate_limited",
          last_test_error_detail: { retry_after_seconds: retryAfter }
        })
      ]);
      renderPage();

      const article = await screen.findByRole("article", { name: "Busy agent" });
      expect(within(article).getByText("Rate limited")).toBeInTheDocument();
      expect(within(article).getByText(/answered the test by refusing it/i)).toBeInTheDocument();
      expect(within(article).getByText(expected)).toBeInTheDocument();
      // Never `ready`, so still no hand-off — and the retry stays available and
      // asks for nothing to be retyped.
      expect(within(article).getByText(/cannot receive a hand-off yet/i)).toBeInTheDocument();
      expect(within(article).getByRole("button", { name: "Test connection" })).toBeEnabled();
    }
  );

  it("014-FR-016 disables every secret-bearing action while rollout is off (D-01-S22)", async () => {
    act(() => signIn(false));
    vi.mocked(apiClient.listAgentConnections).mockResolvedValue([ready]);
    renderPage();

    const article = await screen.findByRole("article", { name: "Hermes" });
    expect(screen.getByText(/external-agent relay rollout is off/i)).toBeInTheDocument();
    expect(screen.queryByRole("form", { name: /add an agent/i })).toBeNull();
    for (const name of ["Edit connection", "Test connection"]) {
      expect(within(article).queryByRole("button", { name })).toBeNull();
    }
    // Disconnect stays: it only ever destroys, so it is safe while rollout is off.
    expect(within(article).getByRole("button", { name: /disconnect/i })).toBeEnabled();
  });

  it("014-FR-011 states the guaranteed tier without the extension link (D-01-S10)", async () => {
    vi.mocked(apiClient.listAgentConnections).mockResolvedValue([
      connection({
        name: "Guaranteed agent",
        guarantee_tier: "guaranteed",
        tier_disclosure: "Guaranteed single start. This agent's card declares it.",
        cancellation_disclosure: null
      })
    ]);
    renderPage();

    const article = await screen.findByRole("article", { name: "Guaranteed agent" });
    const guarantee = within(article).getByRole("region", { name: "Guarantee" });
    expect(within(guarantee).getByText(/Guaranteed single start\./)).toBeInTheDocument();
    // The link exists to tell an owner what to ask their operator to declare.
    // This agent already declares it, so there is nothing to ask for.
    expect(within(guarantee).queryByRole("link")).toBeNull();
    expect(within(guarantee).queryByText(/Cancellation depends/)).toBeNull();
  });

  it("014-FR-002 says 'Not stated' rather than inventing a card value it lacks", async () => {
    vi.mocked(apiClient.listAgentConnections).mockResolvedValue([
      connection({
        name: "Terse agent",
        card: {
          ...card,
          name: null,
          version: null,
          description: null,
          protocol_version: null,
          interface_url: null,
          skills: []
        }
      })
    ]);
    renderPage();

    const article = await screen.findByRole("article", { name: "Terse agent" });
    const discovery = within(article).getByRole("region", { name: "Discovery result" });
    expect(within(discovery).getAllByText("Not stated")).toHaveLength(5);
    expect(within(discovery).queryByRole("list", { name: "Skills" })).toBeNull();
  });

  it("014-FR-002 names a skill by whatever the card gave it, in that order", async () => {
    vi.mocked(apiClient.listAgentConnections).mockResolvedValue([
      connection({
        name: "Terse skills agent",
        card: {
          ...card,
          skills: [
            { id: "research", name: "Research", description: null },
            { id: "summarise", name: null, description: null },
            { id: null, name: null, description: null }
          ]
        }
      })
    ]);
    renderPage();

    const article = await screen.findByRole("article", { name: "Terse skills agent" });
    const skills = within(article).getByRole("list", { name: "Skills" });
    expect(within(skills).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "Research",
      "summarise",
      "Unnamed skill"
    ]);
  });

  it("014-FR-002 shows no tier at all before a connection has been tested", async () => {
    vi.mocked(apiClient.listAgentConnections).mockResolvedValue([
      connection({
        name: "Untested agent",
        status: "untested",
        ready_for_handoff: false,
        card: null,
        guarantee_tier: null,
        tier_disclosure: null,
        tier_disclosure_url: null,
        cancellation_disclosure: null
      })
    ]);
    renderPage();

    const article = await screen.findByRole("article", { name: "Untested agent" });
    // The tier is a claim about how this agent behaves. Nothing has asked it
    // yet, so there is nothing honest to say (D-01-S01).
    expect(within(article).queryByRole("region", { name: "Guarantee" })).toBeNull();
    expect(within(article).queryByRole("region", { name: "Discovery result" })).toBeNull();
    expect(within(article).getByText(/card is only read on a successful test/i)).toBeInTheDocument();
  });

  it("014-FR-012 tones an owner disconnect neutrally, not as a failure", async () => {
    vi.mocked(apiClient.listAgentConnections).mockResolvedValue([
      connection({
        name: "Retired agent",
        status: "disconnected",
        ready_for_handoff: false,
        card: null,
        tier_disclosure: null,
        disconnect_reason: "owner"
      })
    ]);
    renderPage();

    const article = await screen.findByRole("article", { name: "Retired agent" });
    const badge = within(article).getByText("Disconnected");
    expect(badge.className).toContain("bg-surface-sunken");
    expect(within(article).getByText(/were destroyed/i)).toBeInTheDocument();
  });

  it("014-FR-002 falls back to Unknown when a drift has no interface to compare", async () => {
    vi.mocked(apiClient.listAgentConnections).mockResolvedValue([
      connection({
        name: "Opaque agent",
        status: "untested",
        ready_for_handoff: false,
        card: null,
        agent_changed: true,
        last_test_error_code: "agent_card_changed",
        last_test_error_detail: null
      })
    ]);
    renderPage();

    const article = await screen.findByRole("article", { name: "Opaque agent" });
    const comparison = within(article).getByText("Tested interface").closest("dl");
    expect(within(comparison as HTMLElement).getAllByText("Unknown")).toHaveLength(2);
  });

  it("014-FR-001 shows the card-sourced header name on an API-key connection", async () => {
    vi.mocked(apiClient.listAgentConnections).mockResolvedValue([
      connection({ auth_scheme: "api_key", auth_header_name: "X-API-Key" })
    ]);
    renderPage();

    const article = await screen.findByRole("article", { name: "Hermes" });
    expect(within(article).getByText(/API key in X-API-Key · stored sealed/)).toBeInTheDocument();

    const user = userEvent.setup();
    await act(async () => {
      await user.click(within(article).getByRole("button", { name: "Edit connection" }));
    });
    const form = within(article).getByRole("form", { name: "Edit connection" });
    expect(within(form).getByLabelText(/Header name/)).toHaveValue("X-API-Key");
  });

  it("014-FR-004 treats a scheme change as a scope change needing the password", async () => {
    vi.mocked(apiClient.listAgentConnections).mockResolvedValue([ready]);
    const update = vi
      .spyOn(apiClient, "updateAgentConnection")
      .mockResolvedValue(connection({ auth_scheme: "api_key", status: "untested", revision: 3 }));
    renderPage();

    const article = await screen.findByRole("article", { name: "Hermes" });
    const user = userEvent.setup();
    await act(async () => {
      await user.click(within(article).getByRole("button", { name: "Edit connection" }));
    });
    const form = within(article).getByRole("form", { name: "Edit connection" });
    await act(async () => {
      await user.click(within(form).getByRole("radio", { name: "API key" }));
    });
    expect(
      within(form).getByText(/credential scheme resets readiness/i)
    ).toBeInTheDocument();
    await act(async () => {
      await user.type(within(form).getByLabelText("Current password"), "reauth-secret");
      await user.click(within(form).getByRole("button", { name: "Save connection" }));
    });

    await waitFor(() =>
      expect(update).toHaveBeenCalledWith(
        "conn-ready",
        { auth_scheme: "api_key", expected_revision: 2, current_password: "reauth-secret" },
        expect.stringContaining("agent-connection-update")
      )
    );
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

  it("014-FR-002 names what the card declared, and only that (D-01-S10)", async () => {
    vi.mocked(apiClient.listAgentConnections).mockResolvedValue([ready]);
    renderPage();

    const card = await screen.findByRole("article", { name: "Hermes" });
    expect(within(card).getByText("Streaming updates")).toBeInTheDocument();
    expect(within(card).getByText("Push notifications")).toBeInTheDocument();
    expect(within(card).getByText("Supported")).toBeInTheDocument();
    expect(within(card).getByText("Not supported")).toBeInTheDocument();
    // Neither control is a card declaration, so neither appears here.
    expect(within(card).queryByText("Replies to questions")).toBeNull();
    expect(within(card).queryByText("Cancellation")).toBeNull();
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

  it("014-FR-004 requires reauthentication for an address change and explains the reset", async () => {
    vi.mocked(apiClient.listAgentConnections).mockResolvedValue([ready]);
    const update = vi.spyOn(apiClient, "updateAgentConnection").mockResolvedValue({
      ...ready,
      agent_address: "https://new.example.com",
      status: "untested",
      ready_for_handoff: false,
      revision: 3
    });
    renderPage();

    const card = await screen.findByRole("article", { name: "Hermes" });
    const user = userEvent.setup();
    await user.click(within(card).getByRole("button", { name: "Edit connection" }));
    const form = within(card).getByRole("form", { name: "Edit connection" });
    await user.clear(within(form).getByLabelText("Agent address"));
    await user.type(within(form).getByLabelText("Agent address"), "https://new.example.com");
    expect(
      within(form).getByText(/credential scheme resets readiness.*test/i)
    ).toBeInTheDocument();
    await user.type(within(form).getByLabelText("Current password"), "reauth-secret");
    await user.click(within(form).getByRole("button", { name: "Save connection" }));

    await waitFor(() => expect(update).toHaveBeenCalledWith(
      "conn-ready",
      {
        agent_address: "https://new.example.com",
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
      .mockResolvedValue({ ...ready, agent_address: "https://new.example.com", revision: 3 });
    renderPage();

    const card = await screen.findByRole("article", { name: "Hermes" });
    const user = userEvent.setup();
    await user.click(within(card).getByRole("button", { name: "Edit connection" }));
    const form = within(card).getByRole("form", { name: "Edit connection" });
    await user.clear(within(form).getByLabelText("Agent address"));
    await user.type(within(form).getByLabelText("Agent address"), "https://new.example.com");
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
    await user.clear(within(form).getByLabelText("Agent address"));
    await user.type(within(form).getByLabelText("Agent address"), "https://new.example.com/hooks");
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

  it("014-FR-012 offers no signing-secret control at all", async () => {
    vi.mocked(apiClient.listAgentConnections).mockResolvedValue([ready]);
    const replace = vi.spyOn(apiClient, "rotateAgentSigningSecret");
    renderPage();

    const card = await screen.findByRole("article", { name: "Hermes" });

    // D-01 has no state for it. There is no inbound secret under the A2A wire,
    // so there is nothing to lose and nothing to replace — offering the control
    // would advertise a step the owner does not have to take.
    expect(within(card).queryByRole("button", { name: /signing secret/i })).toBeNull();
    expect(within(card).queryByText(/signing secret/i)).toBeNull();
    expect(replace).not.toHaveBeenCalled();
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
    expect(within(dialog).getByText(/are erased together/i)).toBeInTheDocument();

    await act(async () => {
      await user.type(within(dialog).getByLabelText("Confirm with your password"), "hunter2hunter2");
      await user.click(within(dialog).getByRole("button", { name: "Disconnect", exact: true }));
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
    const confirm = within(dialog).getByRole("button", { name: "Disconnect", exact: true });
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
    await user.click(within(dialog).getByRole("button", { name: "Disconnect", exact: true }));
    await within(dialog).findByRole("alert");
    await user.click(within(dialog).getByRole("button", { name: "Disconnect", exact: true }));
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
    await user.click(within(dialog).getByRole("button", { name: "Disconnect", exact: true }));
    await within(dialog).findByRole("alert");
    await user.clear(password);
    await user.type(password, "correct");
    await user.click(within(dialog).getByRole("button", { name: "Disconnect", exact: true }));
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
      await user.click(
        within(screen.getByRole("dialog")).getByRole("button", { name: "Keep it connected" })
      );
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
    await user.click(within(dialog).getByRole("button", { name: "Disconnect", exact: true }));

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

describe("014-FR-016 the disconnect confirmation is a decision, not a keystroke", () => {
  /**
   * D-01-S23, AC-022.
   *
   * This dialog destroys a credential and the only record of where a
   * connection pointed. Everything asserted here exists so that outcome can
   * only follow from someone deliberately choosing it.
   */
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
    vi.spyOn(apiClient, "listAgentConnections").mockResolvedValue([ready]);
  });

  afterEach(() => {
    onlineManager.setOnline(true);
    vi.restoreAllMocks();
    act(() => {
      useAuthStore.setState({ user: null, status: "loading" });
    });
  });

  async function openDialog() {
    renderPage();
    const card = await screen.findByRole("article", { name: "Hermes" });
    const user = userEvent.setup();
    const trigger = within(card).getByRole("button", { name: "Disconnect…" });
    await act(async () => {
      await user.click(trigger);
    });
    return { user, trigger, dialog: screen.getByRole("dialog") };
  }

  it("names the credential, the card summary and the fingerprint as erased together", async () => {
    const { dialog } = await openDialog();

    const text = dialog.textContent ?? "";
    expect(text).toContain("The stored credential and the agent-card summary BrainBuddy discovered");
    expect(text).toContain("card fingerprint");
    // AC-024: a connection that could no longer say where it pointed would
    // outlive the decision to stop pointing there.
    expect(text).toContain("interface");
    expect(text).toContain("Disconnecting does not cancel work this agent has already accepted.");
  });

  it("requires the password and reads safe-then-destructive", async () => {
    const { dialog } = await openDialog();

    expect(within(dialog).getByLabelText("Confirm with your password")).toBeInTheDocument();
    const actions = within(dialog)
      .getAllByRole("button")
      .map((button) => button.textContent?.trim());
    expect(actions).toEqual(["Keep it connected", "Disconnect"]);
  });

  it("traps focus with Disconnect as the last control", async () => {
    const { user, dialog } = await openDialog();

    const focusable = Array.from(
      dialog.querySelectorAll<HTMLElement>("button, input, textarea, select, a[href]")
    );
    expect(focusable[focusable.length - 1]).toHaveTextContent("Disconnect");

    // Tabbing off the end wraps back inside: the page behind is never
    // reachable while the confirmation is open.
    focusable[focusable.length - 1].focus();
    await act(async () => {
      await user.tab();
    });
    expect(dialog.contains(document.activeElement)).toBe(true);
  });

  it("is not dismissed by Escape alone", async () => {
    const { user } = await openDialog();
    const disconnect = vi.spyOn(apiClient, "disconnectAgentConnection");

    await act(async () => {
      await user.keyboard("{Escape}");
    });

    // A stray key is not a decision — in either direction.
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(disconnect).not.toHaveBeenCalled();
  });

  it("restores focus to the invoking Disconnect control", async () => {
    const { user, trigger, dialog } = await openDialog();

    await act(async () => {
      await user.click(within(dialog).getByRole("button", { name: "Keep it connected" }));
    });

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(document.activeElement).toBe(trigger);
  });
});
