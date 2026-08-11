import { act, fireEvent, screen, waitFor } from "@testing-library/react-native";

import { DEFAULT_SERVER_URL, saveServerUrl } from "@/config/serverUrl";
import { routerSpy } from "@/test/expoRouterMock";
import { installFakeBackend, makeMe, type FakeBackend } from "@/test/fakeBackend";
import { renderWithSession } from "@/test/harness";

import SettingsScreen from "../settings";

let backend: FakeBackend;

afterEach(async () => {
  backend?.restore();
  await saveServerUrl(DEFAULT_SERVER_URL);
});

describe("settings", () => {
  it("shows the signed-in account and its voice entitlement", async () => {
    backend = installFakeBackend({
      "GET /auth/me": () =>
        makeMe({ email: "dana@example.test", feature_flags: { voice_brain_dump: true } }),
    });

    await renderWithSession(<SettingsScreen />);

    expect(screen.getByText("dana@example.test")).toBeOnTheScreen();
    expect(
      screen.getByText("Voice brain dump is enabled for this account."),
    ).toBeOnTheScreen();
  });

  it("says plainly when voice is not enabled", async () => {
    backend = installFakeBackend({ "GET /auth/me": () => makeMe({ feature_flags: {} }) });

    await renderWithSession(<SettingsScreen />);

    expect(
      screen.getByText("Voice brain dump is not enabled for this account."),
    ).toBeOnTheScreen();
  });

  it("shows a signed-out placeholder rather than an empty row", async () => {
    backend = installFakeBackend({
      "GET /auth/me": () => {
        throw new TypeError("Network request failed");
      },
    });

    await renderWithSession(<SettingsScreen />);

    expect(screen.getByText("Not signed in")).toBeOnTheScreen();
  });

  it("saves a normalized server URL and confirms it, then clears the confirmation", async () => {
    jest.useFakeTimers({ doNotFake: ["nextTick"] });
    try {
      backend = installFakeBackend({ "GET /auth/me": () => makeMe() });
      await renderWithSession(<SettingsScreen />);

      await fireEvent.changeText(
        screen.getByDisplayValue(DEFAULT_SERVER_URL),
        "http://10.0.0.5:8000/api/",
      );
      await fireEvent.press(screen.getByText("Save server URL"));

      await waitFor(() => expect(screen.getByText("Saved")).toBeOnTheScreen());

      await act(async () => {
        await jest.advanceTimersByTimeAsync(2500);
      });
      expect(screen.getByText("Save server URL")).toBeOnTheScreen();
    } finally {
      jest.useRealTimers();
    }
  });

  it("signs out and returns to where the user came from", async () => {
    backend = installFakeBackend({
      "GET /auth/me": () => makeMe(),
      "POST /auth/logout": () => undefined,
    });
    await renderWithSession(<SettingsScreen />);

    await fireEvent.press(screen.getByText("Sign out"));

    await waitFor(() => expect(backend.callsTo("POST", "/auth/logout")).toHaveLength(1));
    expect(routerSpy().back).toHaveBeenCalled();
  });
});
