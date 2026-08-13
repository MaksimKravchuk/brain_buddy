import { useState, type ReactElement } from "react";

import { ApiError } from "@/api/client";
import type { AgentConnectionResponse } from "@/api/types";
import { Button } from "@/components/Button";
import { DisconnectSheet } from "@/features/agents/DisconnectSheet";
import { RotateCredentialSheet } from "@/features/agents/RotateCredentialSheet";
import { makeConnection } from "@/test/agentFixtures";
import {
  getByLabel,
  pressLabel,
  pressText,
  renderWithProviders,
  settle,
  typeInto,
  visibleText,
} from "@/test/render";

const mockRotate = jest.fn();
const mockDisconnect = jest.fn();
const mockKeys = { issued: 0 };

jest.mock("expo-crypto", () => ({
  randomUUID: () => {
    mockKeys.issued += 1;
    return `intent-key-${mockKeys.issued}`;
  },
}));

jest.mock("react-native-safe-area-context", () => ({
  useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }),
}));

jest.mock("@/auth/SessionProvider", () => {
  const api = {
    rotateAgentCredential: (...args: unknown[]) => mockRotate(...args),
    disconnectAgentConnection: (...args: unknown[]) => mockDisconnect(...args),
  };
  return {
    useApi: () => api,
    useSession: () => ({
      api,
      serverUrl: "https://brain.example.test/api",
      me: { id: "user-test" },
    }),
  };
});

beforeEach(() => {
  mockKeys.issued = 0;
  mockRotate.mockReset();
  mockDisconnect.mockReset();
});

const firstAgent = makeConnection({ id: "conn_1", name: "First agent", revision: 1 });
const secondAgent = makeConnection({ id: "conn_2", name: "Second agent", revision: 4 });

/**
 * The screen keeps one mounted sheet and swaps the target into it, so the
 * sheet — not the screen — owns the boundary between one agent and the next.
 */
function TargetSwitcher({
  render,
}: {
  render: (connection: AgentConnectionResponse | null, onClose: () => void) => ReactElement;
}) {
  const [target, setTarget] = useState<AgentConnectionResponse | null>(firstAgent);
  return (
    <>
      {render(target, () => setTarget(null))}
      <Button onPress={() => setTarget(firstAgent)}>Open first agent</Button>
      <Button onPress={() => setTarget(secondAgent)}>Open second agent</Button>
    </>
  );
}

describe("RotateCredentialSheet intent ownership", () => {
  it("reuses the exact key and frozen payload across an ambiguous retry", async () => {
    mockRotate.mockRejectedValue(new Error("Connection lost"));
    const { renderer, unmount } = await renderWithProviders(
      <RotateCredentialSheet connection={makeConnection()} onClose={jest.fn()} onRotated={jest.fn()} />,
    );
    await typeInto(getByLabel(renderer, "New credential"), "sealed-one");
    await typeInto(getByLabel(renderer, "Your Brain Buddy password"), "password");

    await pressText(renderer, "Replace credential");
    await settle();
    await pressText(renderer, "Replace credential");
    await settle();

    expect(mockRotate).toHaveBeenCalledTimes(2);
    expect(mockRotate.mock.calls[1][2]).toBe(mockRotate.mock.calls[0][2]);
    expect(mockRotate.mock.calls[1][1]).toEqual(mockRotate.mock.calls[0][1]);
    await unmount();
  });

  it("blocks changed credentials while the original outcome is ambiguous", async () => {
    mockRotate.mockRejectedValue(new Error("Connection lost"));
    const { renderer, unmount } = await renderWithProviders(
      <RotateCredentialSheet connection={makeConnection()} onClose={jest.fn()} onRotated={jest.fn()} />,
    );
    await typeInto(getByLabel(renderer, "New credential"), "sealed-one");
    await typeInto(getByLabel(renderer, "Your Brain Buddy password"), "password");
    await pressText(renderer, "Replace credential");
    await settle();

    await typeInto(getByLabel(renderer, "New credential"), "sealed-two");
    await pressText(renderer, "Replace credential");
    await settle();

    expect(mockRotate).toHaveBeenCalledTimes(1);
    expect(visibleText(renderer)).toContain("previous credential change outcome is unknown");
    await unmount();
  });

  it("retires the key after a definitive 4xx", async () => {
    mockRotate.mockRejectedValue(new ApiError("Bad request", 400, {}));
    const { renderer, unmount } = await renderWithProviders(
      <RotateCredentialSheet connection={makeConnection()} onClose={jest.fn()} onRotated={jest.fn()} />,
    );
    await typeInto(getByLabel(renderer, "New credential"), "sealed-one");
    await typeInto(getByLabel(renderer, "Your Brain Buddy password"), "password");
    await pressText(renderer, "Replace credential");
    await settle();
    await pressText(renderer, "Replace credential");
    await settle();

    expect(mockRotate.mock.calls[1][2]).not.toBe(mockRotate.mock.calls[0][2]);
    await unmount();
  });
});

describe("DisconnectSheet intent ownership", () => {
  it("reuses the exact key and frozen payload across an ambiguous retry", async () => {
    mockDisconnect.mockRejectedValue(new Error("Connection lost"));
    const { renderer, unmount } = await renderWithProviders(
      <DisconnectSheet connection={makeConnection()} onClose={jest.fn()} onDisconnected={jest.fn()} />,
    );
    await typeInto(getByLabel(renderer, "Your Brain Buddy password"), "password");
    await pressText(renderer, "Disconnect and destroy the credential");
    await settle();
    await pressText(renderer, "Disconnect and destroy the credential");
    await settle();

    expect(mockDisconnect).toHaveBeenCalledTimes(2);
    expect(mockDisconnect.mock.calls[1][2]).toBe(mockDisconnect.mock.calls[0][2]);
    expect(mockDisconnect.mock.calls[1][1]).toEqual(mockDisconnect.mock.calls[0][1]);
    await unmount();
  });

  it("blocks a changed password until the disconnect outcome is definitive", async () => {
    mockDisconnect
      .mockRejectedValueOnce(new Error("Connection lost"))
      .mockRejectedValue(new ApiError("Bad request", 400, {}));
    const { renderer, unmount } = await renderWithProviders(
      <DisconnectSheet connection={makeConnection()} onClose={jest.fn()} onDisconnected={jest.fn()} />,
    );
    await typeInto(getByLabel(renderer, "Your Brain Buddy password"), "password-one");
    await pressText(renderer, "Disconnect and destroy the credential");
    await settle();

    await typeInto(getByLabel(renderer, "Your Brain Buddy password"), "password-two");
    await pressText(renderer, "Disconnect and destroy the credential");
    await settle();

    expect(mockDisconnect).toHaveBeenCalledTimes(1);
    expect(visibleText(renderer)).toContain("previous disconnect outcome is unknown");
    await unmount();
  });
});

describe("RotateCredentialSheet target isolation", () => {
  it("clears the credential, password and error when another agent becomes the target", async () => {
    mockRotate.mockRejectedValue(new Error("Connection lost"));
    const { renderer, unmount } = await renderWithProviders(
      <TargetSwitcher
        render={(connection, onClose) => (
          <RotateCredentialSheet
            connection={connection}
            onClose={onClose}
            onRotated={onClose}
          />
        )}
      />,
    );
    await typeInto(getByLabel(renderer, "New credential"), "sealed-for-first");
    await typeInto(getByLabel(renderer, "Your Brain Buddy password"), "first-password");
    await pressText(renderer, "Replace credential");
    await settle();

    await pressText(renderer, "Open second agent");

    // Whatever was typed for the first agent is that agent's secret. Carrying
    // it into the second agent's form offers to send it somewhere the user
    // never chose.
    expect(getByLabel(renderer, "New credential").props.value).toBe("");
    expect(getByLabel(renderer, "Your Brain Buddy password").props.value).toBe("");
    expect(visibleText(renderer)).not.toContain("Connection lost");
    await unmount();
  });

  it("retires the held intent when the target changes and comes back", async () => {
    mockRotate.mockRejectedValue(new Error("Connection lost"));
    const { renderer, unmount } = await renderWithProviders(
      <TargetSwitcher
        render={(connection, onClose) => (
          <RotateCredentialSheet
            connection={connection}
            onClose={onClose}
            onRotated={onClose}
          />
        )}
      />,
    );
    await typeInto(getByLabel(renderer, "New credential"), "sealed-one");
    await typeInto(getByLabel(renderer, "Your Brain Buddy password"), "password");
    await pressText(renderer, "Replace credential");
    await settle();

    await pressText(renderer, "Open second agent");
    await pressText(renderer, "Open first agent");
    await typeInto(getByLabel(renderer, "New credential"), "sealed-one");
    await typeInto(getByLabel(renderer, "Your Brain Buddy password"), "password");
    await pressText(renderer, "Replace credential");
    await settle();

    // Retargeting is a deliberate act, not a retry: the abandoned intent must
    // not be resurrected by retyping the same values.
    expect(mockRotate.mock.calls[1][2]).not.toBe(mockRotate.mock.calls[0][2]);
    await unmount();
  });

  it("keeps the ambiguous intent across a close and reopen of the same agent", async () => {
    mockRotate.mockRejectedValue(new Error("Connection lost"));
    const { renderer, unmount } = await renderWithProviders(
      <TargetSwitcher
        render={(connection, onClose) => (
          <RotateCredentialSheet
            connection={connection}
            onClose={onClose}
            onRotated={onClose}
          />
        )}
      />,
    );
    await typeInto(getByLabel(renderer, "New credential"), "sealed-one");
    await typeInto(getByLabel(renderer, "Your Brain Buddy password"), "password");
    await pressText(renderer, "Replace credential");
    await settle();

    await pressLabel(renderer, "Close");
    await pressText(renderer, "Open first agent");
    expect(getByLabel(renderer, "New credential").props.value).toBe("");
    await typeInto(getByLabel(renderer, "New credential"), "sealed-one");
    await typeInto(getByLabel(renderer, "Your Brain Buddy password"), "password");
    await pressText(renderer, "Replace credential");
    await settle();

    expect(mockRotate.mock.calls[1][2]).toBe(mockRotate.mock.calls[0][2]);
    expect(mockRotate.mock.calls[1][1]).toEqual(mockRotate.mock.calls[0][1]);
    await unmount();
  });

  it("settles the intent once the rotation succeeds", async () => {
    mockRotate.mockResolvedValue(makeConnection({ revision: 2 }));
    const { renderer, unmount } = await renderWithProviders(
      <TargetSwitcher
        render={(connection, onClose) => (
          <RotateCredentialSheet
            connection={connection}
            onClose={onClose}
            onRotated={onClose}
          />
        )}
      />,
    );
    await typeInto(getByLabel(renderer, "New credential"), "sealed-one");
    await typeInto(getByLabel(renderer, "Your Brain Buddy password"), "password");
    await pressText(renderer, "Replace credential");
    await settle();

    await pressText(renderer, "Open first agent");
    await typeInto(getByLabel(renderer, "New credential"), "sealed-one");
    await typeInto(getByLabel(renderer, "Your Brain Buddy password"), "password");
    await pressText(renderer, "Replace credential");
    await settle();

    // A settled outcome ends the attempt. Rotating again is a second command
    // and has to be paid for with a second key.
    expect(mockRotate.mock.calls[1][2]).not.toBe(mockRotate.mock.calls[0][2]);
    await unmount();
  });
});

describe("DisconnectSheet target isolation", () => {
  it("clears the password and error when another agent becomes the target", async () => {
    mockDisconnect.mockRejectedValue(new Error("Connection lost"));
    const { renderer, unmount } = await renderWithProviders(
      <TargetSwitcher
        render={(connection, onClose) => (
          <DisconnectSheet
            connection={connection}
            onClose={onClose}
            onDisconnected={onClose}
          />
        )}
      />,
    );
    await typeInto(getByLabel(renderer, "Your Brain Buddy password"), "first-password");
    await pressText(renderer, "Disconnect and destroy the credential");
    await settle();

    await pressText(renderer, "Open second agent");

    expect(getByLabel(renderer, "Your Brain Buddy password").props.value).toBe("");
    expect(visibleText(renderer)).not.toContain("Connection lost");
    await unmount();
  });

  it("retires the held intent when the target changes and comes back", async () => {
    mockDisconnect.mockRejectedValue(new Error("Connection lost"));
    const { renderer, unmount } = await renderWithProviders(
      <TargetSwitcher
        render={(connection, onClose) => (
          <DisconnectSheet
            connection={connection}
            onClose={onClose}
            onDisconnected={onClose}
          />
        )}
      />,
    );
    await typeInto(getByLabel(renderer, "Your Brain Buddy password"), "password");
    await pressText(renderer, "Disconnect and destroy the credential");
    await settle();

    await pressText(renderer, "Open second agent");
    await pressText(renderer, "Open first agent");
    await typeInto(getByLabel(renderer, "Your Brain Buddy password"), "password");
    await pressText(renderer, "Disconnect and destroy the credential");
    await settle();

    expect(mockDisconnect.mock.calls[1][2]).not.toBe(mockDisconnect.mock.calls[0][2]);
    await unmount();
  });

  it("keeps the ambiguous intent across a close and reopen of the same agent", async () => {
    mockDisconnect.mockRejectedValue(new Error("Connection lost"));
    const { renderer, unmount } = await renderWithProviders(
      <TargetSwitcher
        render={(connection, onClose) => (
          <DisconnectSheet
            connection={connection}
            onClose={onClose}
            onDisconnected={onClose}
          />
        )}
      />,
    );
    await typeInto(getByLabel(renderer, "Your Brain Buddy password"), "password");
    await pressText(renderer, "Disconnect and destroy the credential");
    await settle();

    await pressLabel(renderer, "Close");
    await pressText(renderer, "Open first agent");
    expect(getByLabel(renderer, "Your Brain Buddy password").props.value).toBe("");
    await typeInto(getByLabel(renderer, "Your Brain Buddy password"), "password");
    await pressText(renderer, "Disconnect and destroy the credential");
    await settle();

    expect(mockDisconnect.mock.calls[1][2]).toBe(mockDisconnect.mock.calls[0][2]);
    expect(mockDisconnect.mock.calls[1][1]).toEqual(mockDisconnect.mock.calls[0][1]);
    await unmount();
  });

  it("retires the key after a definitive 4xx", async () => {
    mockDisconnect.mockRejectedValue(new ApiError("Wrong password", 400, {}));
    const { renderer, unmount } = await renderWithProviders(
      <DisconnectSheet
        connection={makeConnection()}
        onClose={jest.fn()}
        onDisconnected={jest.fn()}
      />,
    );
    await typeInto(getByLabel(renderer, "Your Brain Buddy password"), "password");
    await pressText(renderer, "Disconnect and destroy the credential");
    await settle();
    await pressText(renderer, "Disconnect and destroy the credential");
    await settle();

    expect(mockDisconnect.mock.calls[1][2]).not.toBe(mockDisconnect.mock.calls[0][2]);
    await unmount();
  });

  it("settles the intent once the disconnect succeeds", async () => {
    mockDisconnect.mockResolvedValue(makeConnection({ status: "disconnected", revision: 2 }));
    const { renderer, unmount } = await renderWithProviders(
      <TargetSwitcher
        render={(connection, onClose) => (
          <DisconnectSheet
            connection={connection}
            onClose={onClose}
            onDisconnected={onClose}
          />
        )}
      />,
    );
    await typeInto(getByLabel(renderer, "Your Brain Buddy password"), "password");
    await pressText(renderer, "Disconnect and destroy the credential");
    await settle();

    await pressText(renderer, "Open first agent");
    await typeInto(getByLabel(renderer, "Your Brain Buddy password"), "password");
    await pressText(renderer, "Disconnect and destroy the credential");
    await settle();

    expect(mockDisconnect.mock.calls[1][2]).not.toBe(mockDisconnect.mock.calls[0][2]);
    await unmount();
  });
});
