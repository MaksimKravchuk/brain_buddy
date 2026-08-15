/**
 * 010-FR-009 / 010-SC-004 — an already-open mobile session picks up a flag
 * change without a sign-out, a reload or an app restart.
 *
 * The founder's brief is client-generic: "an already-open session" is not "the
 * web tab". So `SessionProvider` polls `/auth/me` on the same 15-second
 * interval the web store uses, suspended while the app is backgrounded, and
 * with DD-11's split failure tolerance — a transient failure leaves the session
 * and its flags untouched and the poll continues, a 401 signs out and stops it.
 *
 * The mount-time `probe()` is deliberately *not* reused for this. It is the
 * mobile equivalent of the web store's `hydrate()`: any failure there resolves
 * to a signed-out (or signed-in-offline) session so a cold launch cannot hang,
 * which is exactly the behaviour a background poll must not have.
 */
import AsyncStorage from "@react-native-async-storage/async-storage";
import { QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react-native";
import { AppState, Text, type AppStateStatus } from "react-native";

import { DEFAULT_SERVER_URL, saveServerUrl } from "@/config/serverUrl";
import {
  FakeHttpError,
  installFakeBackend,
  makeMe,
  type FakeBackend,
} from "@/test/fakeBackend";
import { makeQueryClient } from "@/test/harness";

import { SESSION_REFRESH_INTERVAL_MS, SessionProvider, useSession } from "../SessionProvider";

let backend: FakeBackend;

/**
 * `AppState` is a device boundary. The React Native jest preset replaces it
 * with a mock whose `addEventListener` records nothing and never fires, so this
 * stand-in keeps the handler the provider registered — and honours `remove()`,
 * so an unmounted provider stops hearing it.
 */
const appStateHandlers = new Set<(state: AppStateStatus) => void>();
let currentAppState: AppStateStatus = "active";

function emitAppState(state: AppStateStatus): void {
  currentAppState = state;
  for (const handler of [...appStateHandlers]) {
    handler(state);
  }
}

function SessionProbe() {
  const session = useSession();
  return (
    <>
      <Text testID="status">{session.status}</Text>
      <Text testID="email">{session.me?.email ?? "-"}</Text>
      <Text testID="voice">{String(session.voiceEnabled)}</Text>
      <Text testID="classification">{String(session.taskClassificationEnabled)}</Text>
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

async function advance(ms: number): Promise<void> {
  await act(async () => {
    await jest.advanceTimersByTimeAsync(ms);
  });
}

function meCalls(): number {
  return backend.callsTo("GET", "/auth/me").length;
}

beforeEach(async () => {
  await AsyncStorage.clear();
  appStateHandlers.clear();
  currentAppState = "active";
  jest.spyOn(AppState, "addEventListener").mockImplementation((type, handler) => {
    if (type === "change") {
      appStateHandlers.add(handler);
    }
    return {
      remove: () => {
        appStateHandlers.delete(handler);
      },
    };
  });
  Object.defineProperty(AppState, "currentState", {
    configurable: true,
    get: () => currentAppState,
  });
  jest.useFakeTimers();
});

afterEach(async () => {
  jest.useRealTimers();
  jest.restoreAllMocks();
  backend?.restore();
  await saveServerUrl(DEFAULT_SERVER_URL);
});

describe("010-FR-009 SessionProvider background flag refresh", () => {
  it("010-FR-009 refetches /auth/me once per 15-second interval while signed in and active", async () => {
    let voice = false;
    backend = installFakeBackend({
      "GET /auth/me": () =>
        makeMe({
          feature_flags: {
            voice_brain_dump: voice,
            mobile_task_classification: voice,
          },
        }),
    });
    await renderProbe();
    expect(screen.getByTestId("voice")).toHaveTextContent("false");
    const afterMount = meCalls();

    voice = true;
    await advance(SESSION_REFRESH_INTERVAL_MS);

    expect(meCalls()).toBe(afterMount + 1);
    await waitFor(() => expect(screen.getByTestId("voice")).toHaveTextContent("true"));
    expect(screen.getByTestId("classification")).toHaveTextContent("true");

    await advance(SESSION_REFRESH_INTERVAL_MS);
    expect(meCalls()).toBe(afterMount + 2);
  });

  it("010-SC-004 foregrounding refetches immediately instead of waiting out the interval", async () => {
    backend = installFakeBackend({ "GET /auth/me": () => makeMe() });
    await renderProbe();
    const afterMount = meCalls();

    await act(async () => {
      emitAppState("background");
    });
    await advance(SESSION_REFRESH_INTERVAL_MS * 3);
    expect(meCalls()).toBe(afterMount);

    await act(async () => {
      emitAppState("active");
    });
    await act(async () => {
      await Promise.resolve();
    });

    expect(meCalls()).toBe(afterMount + 1);
  });

  it("010-SC-004 suspends the poll while the app is inactive", async () => {
    backend = installFakeBackend({ "GET /auth/me": () => makeMe() });
    await renderProbe();
    const afterMount = meCalls();

    await act(async () => {
      emitAppState("inactive");
    });
    await advance(SESSION_REFRESH_INTERVAL_MS * 4);

    expect(meCalls()).toBe(afterMount);
  });

  it("010-FR-009 issues no poll while signed out", async () => {
    backend = installFakeBackend({
      "GET /auth/me": () => new FakeHttpError(401, { message: "Not authenticated" }),
    });
    await renderProbe();
    expect(screen.getByTestId("status")).toHaveTextContent("signed-out");
    const afterMount = meCalls();

    await advance(SESSION_REFRESH_INTERVAL_MS * 3);
    await act(async () => {
      emitAppState("active");
    });

    expect(meCalls()).toBe(afterMount);
  });

  it("010-FR-009 tears the interval and the AppState subscription down on unmount", async () => {
    backend = installFakeBackend({ "GET /auth/me": () => makeMe() });
    const view = await renderProbe();
    const afterMount = meCalls();

    await act(async () => {
      view.unmount();
    });
    await advance(SESSION_REFRESH_INTERVAL_MS * 3);

    expect(meCalls()).toBe(afterMount);
    expect(appStateHandlers.size).toBe(0);
  });

  it("010-SC-004 a transient poll failure leaves the session and its flags untouched", async () => {
    let failNext = false;
    let voice = true;
    backend = installFakeBackend({
      "GET /auth/me": () => {
        if (failNext) {
          throw new TypeError("Network request failed");
        }
        return makeMe({ feature_flags: { voice_brain_dump: voice } });
      },
    });
    await renderProbe();
    expect(screen.getByTestId("voice")).toHaveTextContent("true");
    const afterMount = meCalls();

    failNext = true;
    await advance(SESSION_REFRESH_INTERVAL_MS);

    expect(screen.getByTestId("status")).toHaveTextContent("signed-in");
    expect(screen.getByTestId("email")).toHaveTextContent("dana.reid@example.test");
    expect(screen.getByTestId("voice")).toHaveTextContent("true");
    expect(meCalls()).toBe(afterMount + 1);

    // The poll continues on its normal cadence and recovers.
    failNext = false;
    await advance(SESSION_REFRESH_INTERVAL_MS);
    expect(meCalls()).toBe(afterMount + 2);
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("signed-in"));
    expect(screen.getByTestId("voice")).toHaveTextContent("true");

    // The next successful interval still applies a live flag change made
    // while the transient failure was in effect -- recovering the poll must
    // not require a relogin to pick up a server-side flip.
    voice = false;
    await advance(SESSION_REFRESH_INTERVAL_MS);
    expect(meCalls()).toBe(afterMount + 3);
    await waitFor(() => expect(screen.getByTestId("voice")).toHaveTextContent("false"));
    expect(screen.getByTestId("status")).toHaveTextContent("signed-in");
  });

  it("010-SC-004 a 401 on the poll signs the session out and stops the poll", async () => {
    let unauthorized = false;
    backend = installFakeBackend({
      "GET /auth/me": () => {
        if (unauthorized) {
          throw new FakeHttpError(401, { message: "Not authenticated" });
        }
        return makeMe();
      },
    });
    await renderProbe();
    expect(screen.getByTestId("status")).toHaveTextContent("signed-in");

    unauthorized = true;
    await advance(SESSION_REFRESH_INTERVAL_MS);

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("signed-out"));
    const afterSignOut = meCalls();
    await advance(SESSION_REFRESH_INTERVAL_MS * 3);
    expect(meCalls()).toBe(afterSignOut);
  });

  it("010-FR-009 the mount-time probe still fails closed, unchanged by the poll's tolerance", async () => {
    // Pinned deliberately: a cold launch against an unreachable backend with no
    // stored identity must settle signed-out rather than hang on "loading".
    backend = installFakeBackend({
      "GET /auth/me": () => {
        throw new TypeError("Network request failed");
      },
    });

    await renderProbe();

    expect(screen.getByTestId("status")).toHaveTextContent("signed-out");
  });
});
