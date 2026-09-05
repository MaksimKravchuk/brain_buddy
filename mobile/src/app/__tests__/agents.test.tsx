import { fireEvent, screen, waitFor } from "@testing-library/react-native";

import { makeConnection } from "@/test/agentFixtures";
import {
  FakeHttpError,
  installFakeBackend,
  makeMe,
  type FakeBackend,
  type RouteHandler,
} from "@/test/fakeBackend";
import { renderWithSession } from "@/test/harness";

import ConnectedAgentsScreen from "../agents";

let backend: FakeBackend | null = null;

const relayMe = makeMe({ feature_flags: { external_agent_relay: true } });
const connection = makeConnection({ name: "Release agent" });

/**
 * Install a backend, retiring whichever one is already in place. A test that
 * swaps the server's behaviour mid-way needs the first install unwound, or
 * `restore()` puts back the previous fake rather than the real `fetch`.
 */
function serveWith(routes: Record<string, RouteHandler>): FakeBackend {
  backend?.restore();
  backend = installFakeBackend(routes);
  return backend;
}

/** The flag-on account plus one saved agent, which most cases start from. */
function serveConnected(extra: Record<string, RouteHandler> = {}): FakeBackend {
  return serveWith({
    "GET /auth/me": () => relayMe,
    "GET /agent-connections": () => [connection],
    ...extra,
  });
}

const renderScreen = () => renderWithSession(<ConnectedAgentsScreen />);

// Testing Library unmounts the tree in its own `afterEach`, which it registered
// when this file imported it — so it runs before this one, while the fake
// backend is still answering.
afterEach(() => {
  backend?.restore();
  backend = null;
});

describe("connected agents screen", () => {
  it("keeps existing connections readable but hides relay mutations when the account flag is off", async () => {
    const backend = serveWith({
      "GET /auth/me": () => makeMe({ feature_flags: {} }),
      "GET /agent-connections": () => [connection],
    });

    await renderScreen();

    expect(await screen.findByText("Release agent")).toBeOnTheScreen();
    expect(screen.getByText(/Relay rollout is off/)).toBeOnTheScreen();
    expect(backend.callsTo("GET", "/agent-connections")).toHaveLength(1);
    expect(screen.queryByText("Add an agent")).not.toBeOnTheScreen();
    expect(screen.getByText("Test connection")).toBeOnTheScreen();
    fireEvent.press(screen.getByText("Test connection"));
    expect(backend.callsTo("POST", "/agent-connections/conn_1/test")).toHaveLength(0);
  });

  it("tests a listed agent through the real client and refreshes its server-owned status", async () => {
    let tested = false;
    const untested = makeConnection({
      name: "Release agent",
      status: "unreachable",
      ready_for_handoff: false,
    });
    const backend = serveConnected({
      "GET /agent-connections": () => [tested ? connection : untested],
      "POST /agent-connections/conn_1/test": () => {
        tested = true;
        return connection;
      },
    });

    await renderScreen();
    expect(await screen.findByText("Release agent")).toBeOnTheScreen();
    expect(screen.getByText("Unreachable")).toBeOnTheScreen();
    expect(screen.getByText("Supports streaming updates.")).toBeOnTheScreen();

    await fireEvent.press(screen.getByText("Test connection"));

    await waitFor(() =>
      expect(backend.callsTo("POST", "/agent-connections/conn_1/test")).toHaveLength(1),
    );
    await waitFor(() =>
      expect(backend.callsTo("GET", "/agent-connections").length).toBeGreaterThan(1),
    );
    expect(await screen.findByText("Ready")).toBeOnTheScreen();
    expect(screen.queryByText("Unreachable")).not.toBeOnTheScreen();
  });

  it("014-FR-001 creates an agent by address and scheme, and shows no secret", async () => {
    const created = makeConnection({ name: "New relay" });
    const backend = serveConnected({ "POST /agent-connections": () => created });

    await renderScreen();
    await screen.findByText("Release agent");
    await fireEvent.press(screen.getByText("Add an agent"));
    await fireEvent.changeText(screen.getByPlaceholderText("What you call this agent"), " New relay ");
    await fireEvent.changeText(
      screen.getByPlaceholderText("https://your-agent.example.com"),
      " https://relay.example.test ",
    );
    await fireEvent.changeText(screen.getByPlaceholderText("Sent as the credential"), "agent-key");
    await fireEvent.changeText(screen.getByPlaceholderText("Confirm it is you"), "account-password");
    await fireEvent.press(screen.getByText("Save agent"));

    await waitFor(() =>
      expect(backend.callsTo("POST", "/agent-connections")).toHaveLength(1),
    );
    const call = backend.callsTo("POST", "/agent-connections")[0];
    expect(call.body).toEqual({
      name: "New relay",
      agent_address: "https://relay.example.test",
      auth_scheme: "bearer",
      credential: "agent-key",
      current_password: "account-password",
    });
    expect(call.headers["Idempotency-Key"]).toMatch(/^00000000-0000-4000-8000-/);
    // There is nothing to copy: the A2A wire has no inbound secret an owner
    // configures at their agent (014-FR-012).
    expect(screen.queryByText("I have copied it")).not.toBeOnTheScreen();
  });

  it("preserves an ambiguous create key across dismissal for the exact same canonical input", async () => {
    let attempts = 0;
    const backend = serveConnected({
      "POST /agent-connections": () => {
        attempts += 1;
        if (attempts === 1) throw new TypeError("Response lost");
        return makeConnection({ name: "Recovered relay" });
      },
    });

    await renderScreen();
    await screen.findByText("Release agent");
    const enter = async () => {
      await fireEvent.changeText(screen.getByPlaceholderText("What you call this agent"), "Recovered relay");
      await fireEvent.changeText(screen.getByPlaceholderText("https://your-agent.example.com"), "https://relay.example.test/task");
      await fireEvent.changeText(screen.getByPlaceholderText("Sent as the credential"), "same-key");
      await fireEvent.changeText(screen.getByPlaceholderText("Confirm it is you"), "same-password");
    };
    await fireEvent.press(screen.getByText("Add an agent"));
    await enter();
    await fireEvent.press(screen.getByText("Save agent"));
    expect(await screen.findByText("Response lost")).toBeOnTheScreen();
    const firstKey = backend.callsTo("POST", "/agent-connections")[0].headers["Idempotency-Key"];

    await fireEvent.press(screen.getByLabelText("Close"));
    await fireEvent.press(screen.getByText("Add an agent"));
    expect(await screen.findByText(/outcome is unknown/i)).toBeOnTheScreen();
    expect(screen.getByPlaceholderText("Sent as the credential").props.value).toBe("");
    expect(screen.getByPlaceholderText("Confirm it is you").props.value).toBe("");
    await enter();
    await fireEvent.press(screen.getByText("Save agent"));

    // The replay reaches the server under the *original* key, so it resolves the
    // ambiguous first attempt rather than creating a second connection.
    await waitFor(() =>
      expect(backend.callsTo("POST", "/agent-connections")).toHaveLength(2),
    );
    expect(backend.callsTo("POST", "/agent-connections")[1].headers["Idempotency-Key"]).toBe(firstKey);
  });

  it("blocks changed input after an ambiguous create instead of minting a duplicate", async () => {
    const backend = serveConnected({
      "POST /agent-connections": () => {
        throw new TypeError("Response lost");
      },
    });
    await renderScreen();
    await screen.findByText("Release agent");
    await fireEvent.press(screen.getByText("Add an agent"));
    await fireEvent.changeText(screen.getByPlaceholderText("What you call this agent"), "First intent");
    await fireEvent.changeText(screen.getByPlaceholderText("https://your-agent.example.com"), "https://relay.example.test/task");
    await fireEvent.changeText(screen.getByPlaceholderText("Sent as the credential"), "key");
    await fireEvent.changeText(screen.getByPlaceholderText("Confirm it is you"), "password");
    await fireEvent.press(screen.getByText("Save agent"));
    await screen.findByText("Response lost");
    await fireEvent.press(screen.getByLabelText("Close"));
    await fireEvent.press(screen.getByText("Add an agent"));
    await fireEvent.changeText(screen.getByPlaceholderText("What you call this agent"), "Different intent");
    await fireEvent.changeText(screen.getByPlaceholderText("https://your-agent.example.com"), "https://relay.example.test/task");
    await fireEvent.changeText(screen.getByPlaceholderText("Sent as the credential"), "key");
    await fireEvent.changeText(screen.getByPlaceholderText("Confirm it is you"), "password");
    await fireEvent.press(screen.getByText("Save agent"));

    expect(await screen.findByText(/exact same connection details/i)).toBeOnTheScreen();
    expect(backend.callsTo("POST", "/agent-connections")).toHaveLength(1);
  });

  it("rotates the credential and offers no signing-secret control at all", async () => {
    const backend = serveConnected({
      "POST /agent-connections/conn_1/credential": () => ({ ...connection, revision: 2 }),
    });

    await renderScreen();
    await screen.findByText("Release agent");

    await fireEvent.press(screen.getByText("Rotate credential"));
    await fireEvent.changeText(screen.getByLabelText("New credential"), "rotated-agent-key");
    await fireEvent.changeText(screen.getByLabelText("Your Brain Buddy password"), "account-password");
    await fireEvent.press(screen.getByText("Replace credential"));
    await waitFor(() =>
      expect(backend.callsTo("POST", "/agent-connections/conn_1/credential")).toHaveLength(1),
    );
    const credentialCall = backend.callsTo("POST", "/agent-connections/conn_1/credential")[0];
    expect(credentialCall.body).toEqual({
      credential: "rotated-agent-key",
      current_password: "account-password",
      expected_revision: 1,
    });
    expect(credentialCall.headers["Idempotency-Key"]).toMatch(/^00000000-0000-4000-8000-/);
    await waitFor(() => expect(screen.queryByText("Rotate credential")).toBeOnTheScreen());

    // M-01 has no signing-secret state: there is no inbound secret to replace,
    // and offering the control would advertise a step nobody has to take.
    expect(screen.queryByText("Replace signing secret")).not.toBeOnTheScreen();
  });

  it("requires explicit confirmation and preserves the warning before disconnecting", async () => {
    const backend = serveConnected({
      "POST /agent-connections/conn_1/disconnect": () => ({
        ...connection,
        status: "disconnected",
        ready_for_handoff: false,
      }),
    });

    await renderScreen();
    await screen.findByText("Release agent");
    await fireEvent.press(screen.getByText("Disconnect"));
    expect(
      screen.getByText("Disconnecting does not cancel work the agent already accepted."),
    ).toBeOnTheScreen();
    expect(backend.callsTo("POST", "/agent-connections/conn_1/disconnect")).toHaveLength(0);

    await fireEvent.press(screen.getByText("Keep it connected"));
    expect(backend.callsTo("POST", "/agent-connections/conn_1/disconnect")).toHaveLength(0);

    await fireEvent.press(screen.getByText("Disconnect"));
    await fireEvent.changeText(screen.getByLabelText("Your Brain Buddy password"), "account-password");
    await fireEvent.press(screen.getByText("Disconnect and destroy the credential"));

    await waitFor(() =>
      expect(backend.callsTo("POST", "/agent-connections/conn_1/disconnect")).toHaveLength(1),
    );
    const call = backend.callsTo("POST", "/agent-connections/conn_1/disconnect")[0];
    expect(call.body).toEqual({ current_password: "account-password", expected_revision: 1 });
    expect(call.headers["Idempotency-Key"]).toMatch(/^00000000-0000-4000-8000-/);
  });

  it("dismisses each relay-management sheet without sending a mutation", async () => {
    const backend = serveConnected();

    await renderScreen();
    await screen.findByText("Release agent");

    for (const action of ["Add an agent", "Rotate credential", "Disconnect"]) {
      await fireEvent.press(screen.getByText(action));
      await fireEvent.press(screen.getByLabelText("Close"));
    }

    expect(backend.calls.filter((call) => call.method === "POST")).toHaveLength(0);
  });

  it("reports a server rejection as an error the user can retry, not as stale data", async () => {
    const backend = serveWith({
      "GET /auth/me": () => relayMe,
      "GET /agent-connections": () => new FakeHttpError(503, { message: "Relay unavailable" }),
    });

    await renderScreen();
    expect(await screen.findByText("Relay unavailable")).toBeOnTheScreen();
    // The server answered, so nothing on screen is a cache — saying otherwise
    // would tell the user their agent list might be out of date when the truth
    // is that there is no list at all.
    expect(screen.queryByText(/cached copy/)).not.toBeOnTheScreen();

    await fireEvent.press(screen.getByText("Retry"));

    await waitFor(() => expect(backend.callsTo("GET", "/agent-connections")).toHaveLength(2));
  });

  it("warns that the list may be out of date when the request never reached the server", async () => {
    serveWith({
      "GET /auth/me": () => relayMe,
      "GET /agent-connections": () => {
        throw new TypeError("Network request failed");
      },
    });

    await renderScreen();

    expect(await screen.findByText(/cached copy and may be out of date/)).toBeOnTheScreen();
    expect(screen.getByText("No agents yet")).toBeOnTheScreen();
    // An unreachable server is not a server error: offering "Retry" here would
    // present the transport failure as something the server rejected.
    expect(screen.queryByText("Retry")).not.toBeOnTheScreen();
  });
});
