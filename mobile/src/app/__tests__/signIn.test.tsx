import AsyncStorage from "@react-native-async-storage/async-storage";
import { fireEvent, screen, waitFor } from "@testing-library/react-native";

import { identityStorageKey } from "@/auth/flagResolution";
import { DEFAULT_SERVER_URL, saveServerUrl } from "@/config/serverUrl";
import type { PendingClassificationChange } from "@/features/tasks/classificationTypes";
import { queueKey } from "@/features/tasks/storageKeys";
import {
  FakeHttpError,
  installFakeBackend,
  makeMe,
  type FakeBackend,
} from "@/test/fakeBackend";
import { renderWithSession } from "@/test/harness";

import SignInScreen from "../sign-in";

let backend: FakeBackend;

afterEach(async () => {
  backend?.restore();
  await saveServerUrl(DEFAULT_SERVER_URL);
});

const SIGNED_OUT = { "GET /auth/me": () => new FakeHttpError(401, { message: "Not authenticated" }) };

async function typeCredentials(email = "dana@example.test", password = "hunter2hunter2") {
  await fireEvent.changeText(screen.getByPlaceholderText("you@example.com"), email);
  await fireEvent.changeText(screen.getByPlaceholderText("Your password"), password);
}

describe("sign-in", () => {
  it("keeps the submit button inert until both fields are filled", async () => {
    backend = installFakeBackend({ ...SIGNED_OUT });
    await renderWithSession(<SignInScreen />);

    await fireEvent.press(screen.getByText("Sign in"));
    expect(backend.callsTo("POST", "/auth/login")).toHaveLength(0);

    await fireEvent.changeText(screen.getByPlaceholderText("you@example.com"), "dana@example.test");
    await fireEvent.press(screen.getByText("Sign in"));
    expect(backend.callsTo("POST", "/auth/login")).toHaveLength(0);
  });

  it("signs in with the typed credentials", async () => {
    backend = installFakeBackend({
      ...SIGNED_OUT,
      "POST /auth/login": () => makeMe({ email: "dana@example.test" }),
    });
    await renderWithSession(<SignInScreen />);

    await typeCredentials();
    await fireEvent.press(screen.getByText("Sign in"));

    await waitFor(() => expect(backend.callsTo("POST", "/auth/login")).toHaveLength(1));
    expect(backend.callsTo("POST", "/auth/login")[0].body).toEqual({
      email: "dana@example.test",
      password: "hunter2hunter2",
    });
  });

  it("shows the server's rejection instead of a generic failure", async () => {
    backend = installFakeBackend({
      ...SIGNED_OUT,
      "POST /auth/login": () =>
        new FakeHttpError(401, { message: "Email or password is incorrect." }),
    });
    await renderWithSession(<SignInScreen />);

    await typeCredentials();
    await fireEvent.press(screen.getByText("Sign in"));

    expect(await screen.findByText("Email or password is incorrect.")).toBeOnTheScreen();
  });

  it("adds rate-limit guidance on a 429", async () => {
    backend = installFakeBackend({
      ...SIGNED_OUT,
      "POST /auth/login": () => new FakeHttpError(429, { message: "Too many requests" }),
    });
    await renderWithSession(<SignInScreen />);

    await typeCredentials();
    await fireEvent.press(screen.getByText("Sign in"));

    expect(
      await screen.findByText("Too many attempts — wait a few minutes before trying again."),
    ).toBeOnTheScreen();
  });

  it("switches to signup, which additionally requires an invite code", async () => {
    backend = installFakeBackend({
      ...SIGNED_OUT,
      "POST /auth/signup": () => makeMe({ email: "new@example.test" }),
    });
    await renderWithSession(<SignInScreen />);

    await fireEvent.press(screen.getByText("Have an invite code? Create an account"));
    expect(screen.getByText("Create your account")).toBeOnTheScreen();
    expect(screen.getByText("At least 12 characters. Longer is better.")).toBeOnTheScreen();

    await fireEvent.changeText(screen.getByPlaceholderText("you@example.com"), "new@example.test");
    await fireEvent.changeText(
      screen.getByPlaceholderText("At least 12 characters"),
      "hunter2hunter2",
    );
    await fireEvent.press(screen.getByText("Create account"));
    expect(backend.callsTo("POST", "/auth/signup")).toHaveLength(0);

    await fireEvent.changeText(screen.getByPlaceholderText("Paste your invite code"), "INVITE-1");
    await fireEvent.press(screen.getByText("Create account"));

    await waitFor(() => expect(backend.callsTo("POST", "/auth/signup")).toHaveLength(1));
    expect(backend.callsTo("POST", "/auth/signup")[0].body).toEqual({
      email: "new@example.test",
      password: "hunter2hunter2",
      invite_code: "INVITE-1",
    });
  });

  it("clears a previous error when switching mode", async () => {
    backend = installFakeBackend({
      ...SIGNED_OUT,
      "POST /auth/login": () => new FakeHttpError(401, { message: "Email or password is incorrect." }),
    });
    await renderWithSession(<SignInScreen />);

    await typeCredentials();
    await fireEvent.press(screen.getByText("Sign in"));
    await screen.findByText("Email or password is incorrect.");

    await fireEvent.press(screen.getByText("Have an invite code? Create an account"));

    expect(screen.queryByText("Email or password is incorrect.")).toBeNull();
  });

  it("hides server settings by default and reveals them on request", async () => {
    backend = installFakeBackend({ ...SIGNED_OUT });
    await renderWithSession(<SignInScreen />);

    expect(screen.queryByText("Server URL")).toBeNull();

    await fireEvent.press(screen.getByText("Server settings"));
    expect(screen.getByText("Server URL")).toBeOnTheScreen();

    await fireEvent.press(screen.getByText("Hide server settings"));
    expect(screen.queryByText("Server URL")).toBeNull();
  });

  it("opens with server settings already showing when a custom server is stored", async () => {
    await saveServerUrl("http://10.0.0.9:8000/api");
    backend = installFakeBackend({ ...SIGNED_OUT });

    await renderWithSession(<SignInScreen />);

    await waitFor(() => expect(screen.getByText("Hide server settings")).toBeOnTheScreen());
    expect(screen.getByDisplayValue("http://10.0.0.9:8000/api")).toBeOnTheScreen();
  });

  it("switches server before signing in when the URL was edited", async () => {
    backend = installFakeBackend({
      ...SIGNED_OUT,
      "POST /auth/login": () => makeMe(),
    });
    await renderWithSession(<SignInScreen />);

    await fireEvent.press(screen.getByText("Server settings"));
    await fireEvent.changeText(
      screen.getByDisplayValue(DEFAULT_SERVER_URL),
      "http://10.0.0.5:8000/api",
    );
    await typeCredentials();
    await fireEvent.press(screen.getByText("Sign in"));

    await waitFor(() => expect(backend.callsTo("POST", "/auth/login")).toHaveLength(1));
    // The login went to the newly chosen server, not the default one.
    expect(screen.getByDisplayValue("http://10.0.0.5:8000/api")).toBeOnTheScreen();
  });

  it("006-FR-011 treats a trailing slash as the same server and keeps the unsent work", async () => {
    // `updateServerUrl` normalizes before deciding there is nothing to do, so
    // comparing raw here means an equivalent URL takes the discard path for a
    // save that then changes nothing: the person is warned that continuing
    // loses their unsent work, and with an empty queue the cached project and
    // Tag lists go with no sheet shown at all. Settings compares normalized;
    // this screen is the gate's other call site and used not to.
    const custom = "http://10.0.0.5:8000/api";
    await saveServerUrl(custom);
    await AsyncStorage.setItem(
      identityStorageKey(custom),
      JSON.stringify({ accountId: "user-1", savedAt: new Date().toISOString() }),
    );
    const at = new Date().toISOString();
    const pending: PendingClassificationChange = {
      taskId: "task-1",
      accountId: "user-1",
      serverUrl: custom,
      value: { projectId: "proj-q3", tagIds: undefined },
      observedRevision: 1,
      originalValue: { projectId: null, tagIds: [] },
      firstQueuedAt: at,
      lastEditedAt: at,
      idempotencyKey: "key-1",
      sendState: "queued",
    };
    await AsyncStorage.setItem(queueKey(custom, "user-1"), JSON.stringify([pending]));

    backend = installFakeBackend({
      ...SIGNED_OUT,
      "POST /auth/login": () => makeMe({ id: "user-1" }),
    });
    await renderWithSession(<SignInScreen />);

    // Server settings open already: the stored URL is not the default one.
    await fireEvent.changeText(screen.getByDisplayValue(custom), `${custom}/`);
    await typeCredentials();
    await fireEvent.press(screen.getByText("Sign in"));

    await waitFor(() => expect(backend.callsTo("POST", "/auth/login")).toHaveLength(1));
    // Nobody was asked to give anything up, because nothing was changing.
    expect(screen.queryByText("1 change has not been sent")).toBeNull();
    expect(await AsyncStorage.getItem(queueKey(custom, "user-1"))).toContain("task-1");
  });
});
