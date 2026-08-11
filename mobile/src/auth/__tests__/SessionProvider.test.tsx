import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react-native";
import { Pressable, Text } from "react-native";

import { DEFAULT_SERVER_URL, saveServerUrl } from "@/config/serverUrl";
import {
  FakeHttpError,
  installFakeBackend,
  makeMe,
  type FakeBackend,
} from "@/test/fakeBackend";
import { makeQueryClient } from "@/test/harness";

import { SessionProvider, useSession } from "../SessionProvider";

let backend: FakeBackend;

afterEach(async () => {
  backend?.restore();
  // The server URL is device configuration held by its module; reset it so one
  // test's "point at my laptop" does not leak into the next.
  await saveServerUrl(DEFAULT_SERVER_URL);
});

/** Renders the whole session surface as text plus buttons for each action. */
function SessionProbe() {
  const session = useSession();
  return (
    <>
      <Text testID="status">{session.status}</Text>
      <Text testID="email">{session.me?.email ?? "-"}</Text>
      <Text testID="server">{session.serverUrl}</Text>
      <Text testID="voice">{String(session.voiceEnabled)}</Text>
      <Pressable
        accessibilityLabel="sign-in"
        onPress={() => void session.signIn(" dana@example.test ", "hunter2hunter2")}
      >
        <Text>sign in</Text>
      </Pressable>
      <Pressable
        accessibilityLabel="sign-up"
        onPress={() => void session.signUp(" new@example.test ", "hunter2hunter2", " INVITE ")}
      >
        <Text>sign up</Text>
      </Pressable>
      <Pressable accessibilityLabel="sign-out" onPress={() => void session.signOut()}>
        <Text>sign out</Text>
      </Pressable>
      <Pressable accessibilityLabel="refresh" onPress={() => void session.refreshMe()}>
        <Text>refresh</Text>
      </Pressable>
      <Pressable
        accessibilityLabel="set-server"
        onPress={() => void session.updateServerUrl("http://10.0.0.5:8000/api/")}
      >
        <Text>set server</Text>
      </Pressable>
    </>
  );
}

async function renderProbe() {
  const result = await render(
    <QueryClientProvider client={makeQueryClient()}>
      <SessionProvider>
        <SessionProbe />
      </SessionProvider>
    </QueryClientProvider>,
  );
  await waitFor(() => expect(screen.getByTestId("status")).not.toHaveTextContent("loading"));
  return result;
}

describe("SessionProvider startup", () => {
  it("signs in from a live cookie session", async () => {
    backend = installFakeBackend({ "GET /auth/me": () => makeMe() });

    await renderProbe();

    expect(screen.getByTestId("status")).toHaveTextContent("signed-in");
    expect(screen.getByTestId("email")).toHaveTextContent("dana.reid@example.test");
  });

  it("lands signed-out when the probe is unauthorized", async () => {
    backend = installFakeBackend({
      "GET /auth/me": () => new FakeHttpError(401, { message: "Not authenticated" }),
    });

    await renderProbe();

    expect(screen.getByTestId("status")).toHaveTextContent("signed-out");
    expect(screen.getByTestId("email")).toHaveTextContent("-");
  });

  it("lands signed-out when the server is unreachable, not stuck loading", async () => {
    backend = installFakeBackend({
      "GET /auth/me": () => {
        throw new TypeError("Network request failed");
      },
    });

    await renderProbe();

    expect(screen.getByTestId("status")).toHaveTextContent("signed-out");
  });

  it("reports the stored server URL, not the default, once startup has read it", async () => {
    await saveServerUrl("http://10.0.0.9:8000/api");
    backend = installFakeBackend({ "GET /auth/me": () => makeMe() });

    await renderProbe();

    expect(screen.getByTestId("server")).toHaveTextContent("http://10.0.0.9:8000/api");
    expect(backend.calls[0].path).toBe("/auth/me");
  });
});

describe("SessionProvider actions", () => {
  it("trims the email before signing in and adopts the returned profile", async () => {
    backend = installFakeBackend({
      "GET /auth/me": () => new FakeHttpError(401),
      "POST /auth/login": () => makeMe({ email: "dana@example.test" }),
    });
    await renderProbe();

    await fireEvent.press(screen.getByLabelText("sign-in"));

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("signed-in"));
    expect(screen.getByTestId("email")).toHaveTextContent("dana@example.test");
    expect(backend.callsTo("POST", "/auth/login")[0].body).toEqual({
      email: "dana@example.test",
      password: "hunter2hunter2",
    });
  });

  it("trims the email and invite code before signing up", async () => {
    backend = installFakeBackend({
      "GET /auth/me": () => new FakeHttpError(401),
      "POST /auth/signup": () => makeMe({ email: "new@example.test" }),
    });
    await renderProbe();

    await fireEvent.press(screen.getByLabelText("sign-up"));

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("signed-in"));
    expect(backend.callsTo("POST", "/auth/signup")[0].body).toEqual({
      email: "new@example.test",
      password: "hunter2hunter2",
      invite_code: "INVITE",
    });
  });

  it("signs out locally even when the logout call fails", async () => {
    backend = installFakeBackend({
      "GET /auth/me": () => makeMe(),
      "POST /auth/logout": () => new FakeHttpError(503, { message: "Service unavailable" }),
    });
    await renderProbe();
    expect(screen.getByTestId("status")).toHaveTextContent("signed-in");

    await fireEvent.press(screen.getByLabelText("sign-out"));

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("signed-out"));
    expect(screen.getByTestId("email")).toHaveTextContent("-");
  });

  it("drops the session when any request comes back 401", async () => {
    backend = installFakeBackend({ "GET /auth/me": () => makeMe() });
    await renderProbe();
    expect(screen.getByTestId("status")).toHaveTextContent("signed-in");

    backend.route("GET /auth/me", () => new FakeHttpError(401, { message: "Session expired" }));
    await fireEvent.press(screen.getByLabelText("refresh"));

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("signed-out"));
  });

  it("normalizes a new server URL and sends the next request there", async () => {
    backend = installFakeBackend({ "GET /auth/me": () => makeMe() });
    await renderProbe();

    await fireEvent.press(screen.getByLabelText("set-server"));

    // The trailing slash is normalized away before it is stored or shown.
    await waitFor(() =>
      expect(screen.getByTestId("server")).toHaveTextContent("http://10.0.0.5:8000/api"),
    );

    // Changing the server is now a real identity transition (spec 006,
    // FR-011): it clears the session and re-probes, so the save itself costs a
    // /auth/me. Before that, this screen told the person it signed them out
    // while the code only rewrote a string. The refresh below is the third.
    await waitFor(() => expect(backend.callsTo("GET", "/auth/me")).toHaveLength(2));

    await fireEvent.press(screen.getByLabelText("refresh"));
    await waitFor(() => expect(backend.callsTo("GET", "/auth/me")).toHaveLength(3));
  });

  it("reads the voice flag from the profile and fails closed without it", async () => {
    backend = installFakeBackend({
      "GET /auth/me": () => makeMe({ feature_flags: { voice_brain_dump: true } }),
    });
    await renderProbe();
    expect(screen.getByTestId("voice")).toHaveTextContent("true");

    backend.route("GET /auth/me", () => makeMe({ feature_flags: {} }));
    await fireEvent.press(screen.getByLabelText("refresh"));
    await waitFor(() => expect(screen.getByTestId("voice")).toHaveTextContent("false"));
  });
});

describe("useSession outside a provider", () => {
  it("throws rather than handing back an empty session", async () => {
    const consoleError = jest.spyOn(console, "error").mockImplementation(() => {});
    try {
      await expect(render(<SessionProbe />)).rejects.toThrow(
        "useSession must be used inside SessionProvider",
      );
    } finally {
      consoleError.mockRestore();
    }
  });
});
