import AsyncStorage from "@react-native-async-storage/async-storage";
import { render, screen, waitFor } from "@testing-library/react-native";
import * as SplashScreen from "expo-splash-screen";

import { routerSpy, setPathname } from "@/test/expoRouterMock";
import { FakeHttpError, installFakeBackend, makeMe, type FakeBackend } from "@/test/fakeBackend";

import { identityStorageKey } from "@/auth/flagResolution";
import { DEFAULT_SERVER_URL } from "@/config/serverUrl";

import RootLayout from "../_layout";

const mockFontState = { loaded: true };

// Auto-mocked native modules are not jest.fn()s, so the splash calls would not
// be observable; this makes "the splash was hidden" assertable.
jest.mock("expo-splash-screen", () => ({
  __esModule: true,
  preventAutoHideAsync: jest.fn(async () => true),
  hideAsync: jest.fn(async () => true),
}));

jest.mock("@expo-google-fonts/inter", () => ({
  __esModule: true,
  useFonts: () => [mockFontState.loaded],
  Inter_400Regular: "Inter_400Regular",
  Inter_500Medium: "Inter_500Medium",
  Inter_600SemiBold: "Inter_600SemiBold",
  Inter_700Bold: "Inter_700Bold",
}));

let backend: FakeBackend;

beforeEach(() => {
  mockFontState.loaded = true;
});

afterEach(() => backend?.restore());

describe("root layout", () => {
  it("renders nothing until the fonts are ready", async () => {
    mockFontState.loaded = false;
    backend = installFakeBackend({ "GET /auth/me": () => makeMe() });

    const { toJSON } = await render(<RootLayout />);

    expect(toJSON()).toBeNull();
  });

  it("mounts the navigator once the fonts are ready", async () => {
    backend = installFakeBackend({ "GET /auth/me": () => makeMe() });

    await render(<RootLayout />);

    expect(await screen.findByTestId("stack")).toBeOnTheScreen();
  });

  it("hides the splash and sends a signed-out visitor to sign-in", async () => {
    backend = installFakeBackend({
      "GET /auth/me": () => new FakeHttpError(401, { message: "Not authenticated" }),
    });
    setPathname("/list/next");

    await render(<RootLayout />);

    await waitFor(() => expect(routerSpy().replace).toHaveBeenCalledWith("/sign-in"));
    expect(SplashScreen.hideAsync).toHaveBeenCalled();
  });

  it("leaves a signed-out visitor already on sign-in where they are", async () => {
    backend = installFakeBackend({
      "GET /auth/me": () => new FakeHttpError(401, { message: "Not authenticated" }),
    });
    setPathname("/sign-in");

    await render(<RootLayout />);

    await waitFor(() => expect(SplashScreen.hideAsync).toHaveBeenCalled());
    expect(routerSpy().replace).not.toHaveBeenCalled();
  });

  it("moves a signed-in visitor off the sign-in screen", async () => {
    backend = installFakeBackend({ "GET /auth/me": () => makeMe() });
    setPathname("/sign-in");

    await render(<RootLayout />);

    await waitFor(() => expect(routerSpy().replace).toHaveBeenCalledWith("/"));
  });

  it("leaves a signed-in visitor on a normal route alone", async () => {
    backend = installFakeBackend({ "GET /auth/me": () => makeMe() });
    setPathname("/list/next");

    await render(<RootLayout />);

    await waitFor(() => expect(SplashScreen.hideAsync).toHaveBeenCalled());
    expect(routerSpy().replace).not.toHaveBeenCalled();
  });

  it("006-SC-009 moves an offline visitor with a valid session off sign-in", async () => {
    // The gate used to test `status === "signed-in"` only. `signed-in-offline`
    // is an authenticated person whose profile could not be refreshed
    // (006-FR-019), and treating it as anything else strands them on sign-in
    // with a queue of unsent work behind it — the cold start on a train that
    // this whole feature exists for. It was one equality check, and it lived
    // in a file no implementation lane owned.
    await AsyncStorage.setItem(
      identityStorageKey(DEFAULT_SERVER_URL),
      JSON.stringify({ accountId: "user-1", flags: {}, rejectedAt: null }),
    );
    backend = installFakeBackend({
      "GET /auth/me": () => {
        throw new TypeError("Network request failed");
      },
    });
    setPathname("/sign-in");

    await render(<RootLayout />);

    await waitFor(() => expect(routerSpy().replace).toHaveBeenCalledWith("/"));
  });

  it("006-FR-019 does not send an offline visitor with a valid session to sign-in", async () => {
    await AsyncStorage.setItem(
      identityStorageKey(DEFAULT_SERVER_URL),
      JSON.stringify({ accountId: "user-1", flags: {}, rejectedAt: null }),
    );
    backend = installFakeBackend({
      "GET /auth/me": () => {
        throw new TypeError("Network request failed");
      },
    });
    setPathname("/list/next");

    await render(<RootLayout />);

    await waitFor(() => expect(SplashScreen.hideAsync).toHaveBeenCalled());
    expect(routerSpy().replace).not.toHaveBeenCalled();
  });
});
