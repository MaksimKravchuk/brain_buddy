/**
 * FR-011's gate on the two screens that can end an identity: Settings and
 * sign-in.
 *
 * `settings.test.tsx` and `signIn.test.tsx` cover what those screens do with an
 * empty device — no queue, no cached vocabulary, nothing to lose. Nothing here
 * repeats them. What is asserted below is the screen with unsent work on it:
 * the warning, the choice, and — the load-bearing part — that both the warning
 * and the discard happen while the identity is still nameable.
 *
 * That ordering is not a style preference. `signOut()` and `updateServerUrl()`
 * both clear the persisted identity, and the persisted identity is both halves
 * of the queue's storage key. So the observable claims are: while the sheet is
 * up the person is still signed in and their work is still on the device; and
 * when they choose to continue, both device stores are gone *and* the session
 * has ended. A failed discard leaves both untouched and hands the choice back.
 *
 * Every assertion is either something on the screen or something the device
 * holds afterwards.
 */

import AsyncStorage from "@react-native-async-storage/async-storage";
import { fireEvent, screen, waitFor } from "@testing-library/react-native";

import { identityStorageKey } from "@/auth/flagResolution";
import { DEFAULT_SERVER_URL, currentServerUrl, saveServerUrl } from "@/config/serverUrl";
import type { PendingClassificationChange } from "@/features/tasks/classificationTypes";
import { cacheKey, queueKey } from "@/features/tasks/storageKeys";
import {
  FakeHttpError,
  installFakeBackend,
  makeMe,
  type FakeBackend,
  type RouteHandler,
} from "@/test/fakeBackend";
import { renderWithSession } from "@/test/harness";

import SettingsScreen from "../settings";
import SignInScreen from "../sign-in";

const ACCOUNT = "user-1";
const OTHER_SERVER = "http://10.0.0.5:8000/api";
const QUEUE_KEY = queueKey(DEFAULT_SERVER_URL, ACCOUNT);
const CACHE_KEY = cacheKey(DEFAULT_SERVER_URL, ACCOUNT);

let backend: FakeBackend;

afterEach(async () => {
  backend?.restore();
  jest.restoreAllMocks();
  await AsyncStorage.clear();
  await saveServerUrl(DEFAULT_SERVER_URL);
});

function unsentChange(index: number, serverUrl = DEFAULT_SERVER_URL): PendingClassificationChange {
  const at = new Date(Date.now() - index * 60_000).toISOString();
  return {
    taskId: `task-${index}`,
    accountId: ACCOUNT,
    serverUrl,
    value: { projectId: "p1", tagIds: undefined },
    observedRevision: 1,
    originalValue: { projectId: null, tagIds: [] },
    firstQueuedAt: at,
    lastEditedAt: at,
    idempotencyKey: `key-${index}`,
    sendState: "queued",
  };
}

/**
 * Put `count` unsent changes and this identity's cached vocabulary on the
 * device, the way a person who classified offline would leave it.
 */
async function seedDevice(count: number): Promise<void> {
  const entries = Array.from({ length: count }, (_unused, index) => unsentChange(index + 1));
  const writes: [string, string][] = [
    [
      CACHE_KEY,
      JSON.stringify({
        projects: [{ id: "p1", name: "Wedding" }],
        tags: [{ id: "g1", name: "errand" }],
        fetchedAt: new Date().toISOString(),
      }),
    ],
  ];
  if (entries.length > 0) {
    writes.push([QUEUE_KEY, JSON.stringify(entries)]);
  }
  await AsyncStorage.multiSet(writes);
}

/** What the device still holds for the identity the queue belongs to. */
async function deviceStores(): Promise<{ queue: string | null; cache: string | null }> {
  const [queue, cache] = await Promise.all([
    AsyncStorage.getItem(QUEUE_KEY),
    AsyncStorage.getItem(CACHE_KEY),
  ]);
  return { queue, cache };
}

async function openSettings(routes: Record<string, RouteHandler> = {}) {
  backend = installFakeBackend({
    "GET /auth/me": () => makeMe({ id: ACCOUNT, email: "dana@example.test" }),
    "POST /auth/logout": () => undefined,
    ...routes,
  });
  return renderWithSession(<SettingsScreen />);
}

async function openSignIn(routes: Record<string, RouteHandler> = {}) {
  backend = installFakeBackend({
    "GET /auth/me": () => new FakeHttpError(401, { message: "Not authenticated" }),
    "POST /auth/login": () => makeMe({ id: ACCOUNT, email: "dana@example.test" }),
    ...routes,
  });
  return renderWithSession(<SignInScreen />);
}

async function typeCredentials(): Promise<void> {
  await fireEvent.changeText(screen.getByPlaceholderText("you@example.com"), "dana@example.test");
  await fireEvent.changeText(screen.getByPlaceholderText("Your password"), "hunter2hunter2");
}

describe("settings — signing out with unsent work", () => {
  it("006-FR-011 states the count and ends nothing until the person answers", async () => {
    await seedDevice(2);
    await openSettings();

    await fireEvent.press(screen.getByText("Sign out"));

    expect(await screen.findByText("2 changes have not been sent")).toBeOnTheScreen();
    expect(
      screen.getByText(
        "Signing out discards them, because they belong to the account and server " +
          "they were made on and cannot be sent from another. This cannot be undone.",
      ),
    ).toBeOnTheScreen();

    // Still signed in behind the sheet, and the work is still on the device —
    // the warning runs before anything that makes its key unnameable.
    expect(screen.getByText("dana@example.test")).toBeOnTheScreen();
    expect(backend.callsTo("POST", "/auth/logout")).toHaveLength(0);
    const held = await deviceStores();
    expect(held.queue).not.toBeNull();
    expect(held.cache).not.toBeNull();
  });

  it("006-FR-011 keeps the queue when the person stays", async () => {
    await seedDevice(2);
    await openSettings();

    await fireEvent.press(screen.getByText("Sign out"));
    await fireEvent.press(await screen.findByText("Stay and let them send"));

    await waitFor(() => expect(screen.queryByText("2 changes have not been sent")).toBeNull());
    expect(screen.getByText("dana@example.test")).toBeOnTheScreen();
    expect(backend.callsTo("POST", "/auth/logout")).toHaveLength(0);
    const held = await deviceStores();
    expect(held.queue).not.toBeNull();
    expect(held.cache).not.toBeNull();
  });

  it("006-FR-011 discards both device stores and only then ends the session", async () => {
    await seedDevice(2);
    await openSettings();

    await fireEvent.press(screen.getByText("Sign out"));
    await fireEvent.press(await screen.findByText("Discard 2 changes and continue"));

    expect(await screen.findByText("Not signed in")).toBeOnTheScreen();
    // Both stores of the outgoing identity are gone, including the names the
    // person wrote — not merely left unread under a key nothing can open.
    expect(await deviceStores()).toEqual({ queue: null, cache: null });
    expect(await AsyncStorage.getItem(identityStorageKey(DEFAULT_SERVER_URL))).toBeNull();
    expect(backend.callsTo("POST", "/auth/logout")).toHaveLength(1);
  });

  it("006-FR-012 hands the choice back when the discard itself fails", async () => {
    await seedDevice(1);
    await openSettings();
    jest
      .spyOn(AsyncStorage, "multiRemove")
      .mockRejectedValueOnce(new Error("Device storage is unavailable"));

    await fireEvent.press(screen.getByText("Sign out"));
    await fireEvent.press(await screen.findByText("Discard 1 change and continue"));

    expect(
      await screen.findByText(
        "We couldn't send them just now. Nothing has been discarded — you can still choose.",
      ),
    ).toBeOnTheScreen();
    expect(screen.getByText("Device storage is unavailable")).toBeOnTheScreen();
    // Nothing was discarded and nothing transitioned: the session is intact and
    // so is the work, and the same two choices are offered again.
    expect(screen.getByText("dana@example.test")).toBeOnTheScreen();
    expect(screen.getByText("Stay and let it send")).toBeOnTheScreen();
    expect(backend.callsTo("POST", "/auth/logout")).toHaveLength(0);
    expect((await deviceStores()).queue).not.toBeNull();
  });

  it("006-FR-011 clears the cached vocabulary on a sign-out with nothing unsent", async () => {
    await seedDevice(0);
    await openSettings();

    await fireEvent.press(screen.getByText("Sign out"));

    // M-05 never appears with an empty queue, so without this the account's
    // whole project and Tag vocabulary would outlive it on the device.
    await waitFor(() => expect(backend.callsTo("POST", "/auth/logout")).toHaveLength(1));
    expect(screen.queryByText(/have not been sent/)).toBeNull();
    expect(await deviceStores()).toEqual({ queue: null, cache: null });
  });

  it("006-FR-011 has nothing to warn about when no session names a queue", async () => {
    backend = installFakeBackend({
      "GET /auth/me": () => new FakeHttpError(401, { message: "Not authenticated" }),
      "POST /auth/logout": () => undefined,
    });
    await renderWithSession(<SettingsScreen />);

    await fireEvent.press(screen.getByText("Sign out"));

    await waitFor(() => expect(backend.callsTo("POST", "/auth/logout")).toHaveLength(1));
    expect(screen.queryByText(/have not been sent/)).toBeNull();
  });
});

describe("settings — changing the server", () => {
  it("006-FR-011 warns about the same work, named as a server switch", async () => {
    await seedDevice(1);
    await openSettings();

    await fireEvent.changeText(screen.getByDisplayValue(DEFAULT_SERVER_URL), OTHER_SERVER);
    await fireEvent.press(screen.getByText("Save server URL"));

    expect(await screen.findByText("1 change has not been sent")).toBeOnTheScreen();
    expect(
      screen.getByText(
        "Switching server discards it, because it belongs to the account and server " +
          "it was made on and cannot be sent from another. This cannot be undone.",
      ),
    ).toBeOnTheScreen();
    // The server has not moved while the sheet is up, so the queue is still
    // both nameable and sendable.
    expect(currentServerUrl()).toBe(DEFAULT_SERVER_URL);
    expect((await deviceStores()).queue).not.toBeNull();
  });

  it("006-FR-011 cancels the server change and leaves the queue sendable", async () => {
    await seedDevice(1);
    await openSettings();

    await fireEvent.changeText(screen.getByDisplayValue(DEFAULT_SERVER_URL), OTHER_SERVER);
    await fireEvent.press(screen.getByText("Save server URL"));
    await fireEvent.press(await screen.findByText("Stay and let it send"));

    await waitFor(() => expect(screen.queryByText("1 change has not been sent")).toBeNull());
    expect(currentServerUrl()).toBe(DEFAULT_SERVER_URL);
    expect((await deviceStores()).queue).not.toBeNull();
  });

  it("006-FR-011 discards both stores before the server moves", async () => {
    await seedDevice(1);
    await openSettings();

    await fireEvent.changeText(screen.getByDisplayValue(DEFAULT_SERVER_URL), OTHER_SERVER);
    await fireEvent.press(screen.getByText("Save server URL"));
    await fireEvent.press(await screen.findByText("Discard 1 change and continue"));

    expect(await screen.findByText("Saved")).toBeOnTheScreen();
    expect(currentServerUrl()).toBe(OTHER_SERVER);
    expect(await deviceStores()).toEqual({ queue: null, cache: null });
  });

  it("006-FR-011 saving the URL it already has does not end the session", async () => {
    await seedDevice(0);
    await openSettings();

    await fireEvent.press(screen.getByText("Save server URL"));

    expect(await screen.findByText("Saved")).toBeOnTheScreen();
    expect(currentServerUrl()).toBe(DEFAULT_SERVER_URL);
    expect(screen.getByText("dana@example.test")).toBeOnTheScreen();
    expect(screen.queryByText("Not signed in")).toBeNull();
  });

  it("006-FR-011 saving the URL it already has warns about nothing and discards nothing", async () => {
    // Saving an unchanged URL is not an identity transition — `updateServerUrl`
    // itself does nothing with it. Warning first, and then discarding on
    // "continue", destroys unsent work to accomplish exactly nothing.
    await seedDevice(1);
    await openSettings();

    await fireEvent.press(screen.getByText("Save server URL"));

    expect(await screen.findByText("Saved")).toBeOnTheScreen();
    expect(screen.queryByText("1 change has not been sent")).toBeNull();
    expect(screen.queryByText(/discards it/)).toBeNull();
    expect(currentServerUrl()).toBe(DEFAULT_SERVER_URL);
    const held = await deviceStores();
    expect(held.queue).not.toBeNull();
    expect(held.cache).not.toBeNull();
  });

  it("006-FR-011 treats a trailing slash as the server it is already on", async () => {
    // `normalizeServerUrl` is what decides whether this is a transition at all,
    // so the comparison in front of the warning has to be the same one — a raw
    // string compare makes an added slash a full identity change.
    await seedDevice(1);
    await openSettings();

    await fireEvent.changeText(
      screen.getByDisplayValue(DEFAULT_SERVER_URL),
      `${DEFAULT_SERVER_URL}/`,
    );
    await fireEvent.press(screen.getByText("Save server URL"));

    expect(await screen.findByText("Saved")).toBeOnTheScreen();
    expect(screen.queryByText("1 change has not been sent")).toBeNull();
    expect(screen.getByText("dana@example.test")).toBeOnTheScreen();
    expect(currentServerUrl()).toBe(DEFAULT_SERVER_URL);
    expect((await deviceStores()).queue).not.toBeNull();
  });

  it("006-FR-011 keeps the cached vocabulary when the server did not change", async () => {
    // With an empty queue no sheet is shown at all, so the discard that follows
    // the gate is silent: the account's whole project and Tag vocabulary — the
    // names the person wrote — would go for a save that changed nothing.
    await seedDevice(0);
    await openSettings();

    await fireEvent.press(screen.getByText("Save server URL"));

    expect(await screen.findByText("Saved")).toBeOnTheScreen();
    expect((await deviceStores()).cache).not.toBeNull();
  });
});

describe("sign-in — changing the server before signing in", () => {
  /**
   * There is no session on this screen, so the identity comes from storage: a
   * device whose token expired still holds its identity and its unsent work,
   * and FR-011 keeps both through an involuntary end.
   */
  async function seedSignedOutIdentity(count: number): Promise<void> {
    await seedDevice(count);
    await AsyncStorage.setItem(
      identityStorageKey(DEFAULT_SERVER_URL),
      JSON.stringify({ accountId: ACCOUNT, savedAt: new Date().toISOString() }),
    );
  }

  async function editServer(url: string): Promise<void> {
    await fireEvent.press(screen.getByText("Server settings"));
    await fireEvent.changeText(screen.getByDisplayValue(DEFAULT_SERVER_URL), url);
  }

  it("006-FR-011 warns before the server moves, not after", async () => {
    await seedSignedOutIdentity(2);
    await openSignIn();

    await editServer(OTHER_SERVER);
    await typeCredentials();
    await fireEvent.press(screen.getByText("Sign in"));

    expect(await screen.findByText("2 changes have not been sent")).toBeOnTheScreen();
    // Neither the server nor the sign-in has moved, so the queue's key is still
    // nameable and its work is still on the device.
    expect(currentServerUrl()).toBe(DEFAULT_SERVER_URL);
    expect(backend.callsTo("POST", "/auth/login")).toHaveLength(0);
    expect((await deviceStores()).queue).not.toBeNull();
  });

  it("006-FR-011 cancels the server change and signs nobody in", async () => {
    await seedSignedOutIdentity(2);
    await openSignIn();

    await editServer(OTHER_SERVER);
    await typeCredentials();
    await fireEvent.press(screen.getByText("Sign in"));
    await fireEvent.press(await screen.findByText("Stay and let them send"));

    await waitFor(() => expect(screen.queryByText("2 changes have not been sent")).toBeNull());
    expect(currentServerUrl()).toBe(DEFAULT_SERVER_URL);
    expect(backend.callsTo("POST", "/auth/login")).toHaveLength(0);
    expect((await deviceStores()).queue).not.toBeNull();
  });

  it("006-FR-011 discards both stores, then moves the server and signs in", async () => {
    await seedSignedOutIdentity(2);
    await openSignIn();

    await editServer(OTHER_SERVER);
    await typeCredentials();
    await fireEvent.press(screen.getByText("Sign in"));
    await fireEvent.press(await screen.findByText("Discard 2 changes and continue"));

    await waitFor(() => expect(backend.callsTo("POST", "/auth/login")).toHaveLength(1));
    expect(currentServerUrl()).toBe(OTHER_SERVER);
    expect(await deviceStores()).toEqual({ queue: null, cache: null });
  });

  it("006-FR-012 reports a failed discard on the form and signs nobody in", async () => {
    await seedSignedOutIdentity(1);
    await openSignIn();
    jest
      .spyOn(AsyncStorage, "multiRemove")
      .mockRejectedValueOnce(new Error("Device storage is unavailable"));

    await editServer(OTHER_SERVER);
    await typeCredentials();
    await fireEvent.press(screen.getByText("Sign in"));
    await fireEvent.press(await screen.findByText("Discard 1 change and continue"));

    expect(await screen.findByText("Device storage is unavailable")).toBeOnTheScreen();
    expect(currentServerUrl()).toBe(DEFAULT_SERVER_URL);
    expect(backend.callsTo("POST", "/auth/login")).toHaveLength(0);
    expect((await deviceStores()).queue).not.toBeNull();
  });

  it("006-FR-011 clears the cached vocabulary on a server change with nothing unsent", async () => {
    await seedSignedOutIdentity(0);
    await openSignIn();

    await editServer(OTHER_SERVER);
    await typeCredentials();
    await fireEvent.press(screen.getByText("Sign in"));

    await waitFor(() => expect(backend.callsTo("POST", "/auth/login")).toHaveLength(1));
    expect(screen.queryByText(/have not been sent/)).toBeNull();
    expect(await deviceStores()).toEqual({ queue: null, cache: null });
  });

  it("006-FR-011 has nothing to discard when this device holds no identity", async () => {
    await seedDevice(2);
    await openSignIn();

    await editServer(OTHER_SERVER);
    await typeCredentials();
    await fireEvent.press(screen.getByText("Sign in"));

    // No persisted identity means no key this screen could name, so there is
    // nothing to warn about and the sign-in simply proceeds.
    await waitFor(() => expect(backend.callsTo("POST", "/auth/login")).toHaveLength(1));
    expect(screen.queryByText(/have not been sent/)).toBeNull();
  });

  it("006-FR-011 leaves the queue alone when the server URL was not changed", async () => {
    await saveServerUrl(OTHER_SERVER);
    await AsyncStorage.multiSet([
      [queueKey(OTHER_SERVER, ACCOUNT), JSON.stringify([unsentChange(1, OTHER_SERVER)])],
      [
        identityStorageKey(OTHER_SERVER),
        JSON.stringify({ accountId: ACCOUNT, savedAt: new Date().toISOString() }),
      ],
    ]);
    await openSignIn();
    // A custom server is stored, so the panel opens already showing it.
    await screen.findByDisplayValue(OTHER_SERVER);

    await typeCredentials();
    await fireEvent.press(screen.getByText("Sign in"));

    await waitFor(() => expect(backend.callsTo("POST", "/auth/login")).toHaveLength(1));
    // Saving the URL it already had is not a transition, so nothing is warned
    // about and nothing is destroyed.
    expect(screen.queryByText(/have not been sent/)).toBeNull();
    expect(await AsyncStorage.getItem(queueKey(OTHER_SERVER, ACCOUNT))).not.toBeNull();
  });
});
