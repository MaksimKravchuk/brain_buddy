import { render, waitFor } from "@testing-library/react-native";
import { Text } from "react-native";

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
