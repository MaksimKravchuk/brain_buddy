import { act, fireEvent, render, waitFor } from "@testing-library/react-native";
import { Pressable, Text } from "react-native";

import { mobileAllure, withAllure } from "@/test/allureTaxonomy";
import { AuthProvider, useAuth } from "../AuthProvider";

jest.mock("expo-constants", () => ({
  __esModule: true,
  default: { expoConfig: { extra: { apiOrigin: "https://api.example.test/api" } } },
}));

jest.mock("expo-file-system/legacy", () => ({
  documentDirectory: "file:///docs/",
  getInfoAsync: jest.fn().mockResolvedValue({ exists: true }),
  writeAsStringAsync: jest.fn().mockResolvedValue(undefined),
}));

const secureStore = jest.requireMock("expo-secure-store") as {
  getItemAsync: jest.Mock;
  setItemAsync: jest.Mock;
  deleteItemAsync: jest.Mock;
};

function Probe() {
  const { ready, user, bootstrapError } = useAuth();
  return (
    <Text testID="probe">
      {JSON.stringify({ ready, hasUser: Boolean(user), bootstrapError })}
    </Text>
  );
}

function readProbe(screen: ReturnType<typeof render>) {
  return JSON.parse(screen.getByTestId("probe").props.children);
}

describe("AuthProvider bootstrap failure recovery", () => {
  beforeEach(() => {
    secureStore.getItemAsync.mockReset().mockResolvedValue("stored-session-token");
    secureStore.setItemAsync.mockReset().mockResolvedValue(undefined);
    secureStore.deleteItemAsync.mockReset().mockResolvedValue(undefined);
  });

  it(
    mobileAllure.auth("a transient network failure preserves the stored token and stays retryable").title,
    async () => {
      await withAllure(
        mobileAllure.auth("a transient network failure preserves the stored token and stays retryable"),
        async () => {
          global.fetch = jest.fn().mockRejectedValue(new TypeError("Network request failed"));
          const screen = await render(<AuthProvider><Probe /></AuthProvider>);

          await waitFor(() => expect(readProbe(screen).ready).toBe(true));
          expect(readProbe(screen)).toEqual({ ready: true, hasUser: false, bootstrapError: true });
          expect(secureStore.deleteItemAsync).not.toHaveBeenCalled();
        },
      );
    },
  );

  it(
    mobileAllure.auth("a retryable 5xx during bootstrap preserves the stored token").title,
    async () => {
      await withAllure(
        mobileAllure.auth("a retryable 5xx during bootstrap preserves the stored token"),
        async () => {
          global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 503, headers: new Headers() });
          const screen = await render(<AuthProvider><Probe /></AuthProvider>);

          await waitFor(() => expect(readProbe(screen).ready).toBe(true));
          expect(readProbe(screen)).toEqual({ ready: true, hasUser: false, bootstrapError: true });
          expect(secureStore.deleteItemAsync).not.toHaveBeenCalled();
        },
      );
    },
  );

  it(
    mobileAllure.auth("a definitive 401 clears the stored token and is not marked retryable").title,
    async () => {
      await withAllure(
        mobileAllure.auth("a definitive 401 clears the stored token and is not marked retryable"),
        async () => {
          global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 401, headers: new Headers() });
          const screen = await render(<AuthProvider><Probe /></AuthProvider>);

          await waitFor(() => expect(readProbe(screen).ready).toBe(true));
          expect(readProbe(screen)).toEqual({ ready: true, hasUser: false, bootstrapError: false });
          expect(secureStore.deleteItemAsync).toHaveBeenCalled();
        },
      );
    },
  );

  it(
    mobileAllure.auth("no stored token bootstraps cleanly without a network call").title,
    async () => {
      await withAllure(
        mobileAllure.auth("no stored token bootstraps cleanly without a network call"),
        async () => {
          secureStore.getItemAsync.mockResolvedValue(null);
          global.fetch = jest.fn();
          const screen = await render(<AuthProvider><Probe /></AuthProvider>);

          await waitFor(() => expect(readProbe(screen).ready).toBe(true));
          expect(readProbe(screen)).toEqual({ ready: true, hasUser: false, bootstrapError: false });
          expect(global.fetch).not.toHaveBeenCalled();
        },
      );
    },
  );
});

function jsonResponse(body: unknown) {
  return { ok: true, status: 200, headers: new Headers(), json: async () => body };
}

function Harness() {
  const { user, ready, logoutRevocationUnresolved, signOut, retryLogout, signIn } = useAuth();
  return (
    <>
      <Text testID="probe">{JSON.stringify({ ready, hasUser: Boolean(user), logoutRevocationUnresolved })}</Text>
      <Pressable testID="sign-out" onPress={() => void signOut()}><Text>Sign out</Text></Pressable>
      <Pressable testID="retry-logout" onPress={() => void retryLogout()}><Text>Retry logout</Text></Pressable>
      <Pressable testID="sign-in" onPress={() => void signIn("person@example.test", "hunter2")}><Text>Sign in</Text></Pressable>
    </>
  );
}

function readHarnessProbe(screen: ReturnType<typeof render>) {
  return JSON.parse(screen.getByTestId("probe").props.children);
}

describe("AuthProvider failed remote logout (ADR-0008)", () => {
  beforeEach(() => {
    secureStore.getItemAsync.mockReset().mockResolvedValue("stored-session-token");
    secureStore.setItemAsync.mockReset().mockResolvedValue(undefined);
    secureStore.deleteItemAsync.mockReset().mockResolvedValue(undefined);
  });

  it(
    mobileAllure.auth("a failed remote logout clears the local token immediately but reports revocation as unresolved").title,
    async () => {
      await withAllure(
        mobileAllure.auth("a failed remote logout clears the local token immediately but reports revocation as unresolved"),
        async () => {
          global.fetch = jest.fn((url: string) => {
            if (url.endsWith("/auth/me")) return Promise.resolve(jsonResponse({ id: "u1", email: "person@example.test" }));
            if (url.endsWith("/auth/logout")) return Promise.resolve({ ok: false, status: 500, headers: new Headers() });
            return Promise.reject(new Error(`unexpected fetch: ${url}`));
          }) as unknown as typeof fetch;

          const screen = await render(<AuthProvider><Harness /></AuthProvider>);
          await waitFor(() => expect(readHarnessProbe(screen).ready).toBe(true));
          expect(readHarnessProbe(screen).hasUser).toBe(true);

          await act(async () => { fireEvent.press(screen.getByTestId("sign-out")); });

          await waitFor(() => expect(readHarnessProbe(screen).logoutRevocationUnresolved).toBe(true));
          expect(readHarnessProbe(screen).hasUser).toBe(false);
          expect(secureStore.deleteItemAsync).toHaveBeenCalled();
          expect(secureStore.setItemAsync).not.toHaveBeenCalled();
        },
      );
    },
  );

  it(
    mobileAllure.auth("a successful retry clears the unresolved revocation without restoring the local token").title,
    async () => {
      await withAllure(
        mobileAllure.auth("a successful retry clears the unresolved revocation without restoring the local token"),
        async () => {
          let logoutShouldSucceed = false;
          global.fetch = jest.fn((url: string) => {
            if (url.endsWith("/auth/me")) return Promise.resolve(jsonResponse({ id: "u1", email: "person@example.test" }));
            if (url.endsWith("/auth/logout")) {
              return logoutShouldSucceed
                ? Promise.resolve(jsonResponse(undefined))
                : Promise.resolve({ ok: false, status: 500, headers: new Headers() });
            }
            return Promise.reject(new Error(`unexpected fetch: ${url}`));
          }) as unknown as typeof fetch;

          const screen = await render(<AuthProvider><Harness /></AuthProvider>);
          await waitFor(() => expect(readHarnessProbe(screen).ready).toBe(true));

          await act(async () => { fireEvent.press(screen.getByTestId("sign-out")); });
          await waitFor(() => expect(readHarnessProbe(screen).logoutRevocationUnresolved).toBe(true));

          logoutShouldSucceed = true;
          await act(async () => { fireEvent.press(screen.getByTestId("retry-logout")); });

          await waitFor(() => expect(readHarnessProbe(screen).logoutRevocationUnresolved).toBe(false));
          expect(secureStore.setItemAsync).not.toHaveBeenCalled();
        },
      );
    },
  );

  it(
    mobileAllure.auth("signing in again discards a stale unresolved prior logout instead of retrying it").title,
    async () => {
      await withAllure(
        mobileAllure.auth("signing in again discards a stale unresolved prior logout instead of retrying it"),
        async () => {
          let logoutCalls = 0;
          global.fetch = jest.fn((url: string) => {
            if (url.endsWith("/auth/me")) return Promise.resolve(jsonResponse({ id: "u1", email: "person@example.test" }));
            if (url.endsWith("/auth/logout")) {
              logoutCalls += 1;
              return Promise.resolve({ ok: false, status: 500, headers: new Headers() });
            }
            if (url.endsWith("/auth/mobile/sessions")) {
              return Promise.resolve(jsonResponse({
                session_token: "new-session-token",
                token_type: "Bearer",
                expires_at: "2026-08-01T00:00:00Z",
                user: { id: "u2", email: "person@example.test" },
              }));
            }
            return Promise.reject(new Error(`unexpected fetch: ${url}`));
          }) as unknown as typeof fetch;

          const screen = await render(<AuthProvider><Harness /></AuthProvider>);
          await waitFor(() => expect(readHarnessProbe(screen).ready).toBe(true));

          await act(async () => { fireEvent.press(screen.getByTestId("sign-out")); });
          await waitFor(() => expect(readHarnessProbe(screen).logoutRevocationUnresolved).toBe(true));
          expect(logoutCalls).toBe(1);

          await act(async () => { fireEvent.press(screen.getByTestId("sign-in")); });
          await waitFor(() => expect(readHarnessProbe(screen).hasUser).toBe(true));
          expect(readHarnessProbe(screen).logoutRevocationUnresolved).toBe(false);

          await act(async () => { fireEvent.press(screen.getByTestId("retry-logout")); });
          expect(logoutCalls).toBe(1);
        },
      );
    },
  );
});
