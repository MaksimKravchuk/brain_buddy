/**
 * Recovering a lost inbound signing secret on iOS.
 *
 * The create sheet shows that secret once. Lose it and the connection still
 * exists but can never be configured, so the only honest way out is to replace
 * it — which is a different act from replacing the outbound credential, and the
 * screen has to say so. The replacement is shown exactly once, in screen state,
 * and a retry of an ambiguous attempt must not rotate a second time.
 */

import { useState } from "react";

import { Button } from "@/components/Button";

import { ApiError } from "@/api/client";
import type { AgentConnectionSigningSecretResponse } from "@/api/types";
import { ConnectionCard } from "@/features/agents/ConnectionCard";
import { ReplaceSigningSecretSheet } from "@/features/agents/ReplaceSigningSecretSheet";
import { SigningSecretSheet } from "@/features/agents/SigningSecretSheet";
import { makeConnection } from "@/test/agentFixtures";
import {
  getByLabel,
  pressLabel,
  pressText,
  queryByText,
  renderWithProviders,
  settle,
  typeInto,
  visibleText,
} from "@/test/render";

const mockRotateSigningSecret = jest.fn();

const mockKeys = { issued: 0 };
jest.mock("expo-crypto", () => ({
  randomUUID: () => {
    mockKeys.issued += 1;
    return `idem_key_${mockKeys.issued}`;
  },
}));

jest.mock("react-native-safe-area-context", () => ({
  useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }),
}));

jest.mock("@/auth/SessionProvider", () => {
  const api = {
    rotateAgentSigningSecret: (...args: unknown[]) => mockRotateSigningSecret(...args),
  };
  return {
    useApi: () => api,
    useSession: () => ({
      api,
      serverUrl: "https://brain.example.test/api",
      accountId: "user-a",
      getIdentityEpoch: () => 1,
    }),
  };
});

function replacement(
  overrides: Partial<AgentConnectionSigningSecretResponse> = {},
): AgentConnectionSigningSecretResponse {
  return {
    ...makeConnection({ revision: 2 }),
    inbound_signing_secret: "sk-inbound-replacement",
    ...overrides,
  };
}

/** The screen's own wiring: replace, then show the result once. */
function RecoveryHarness() {
  const connection = makeConnection({ revision: 2 });
  const [open, setOpen] = useState(true);
  const [issued, setIssued] = useState<AgentConnectionSigningSecretResponse | null>(null);
  return (
    <>
      <ReplaceSigningSecretSheet
        connection={open ? connection : null}
        onClose={() => setOpen(false)}
        onReplaced={(next) => {
          setOpen(false);
          setIssued(next);
        }}
      />
      <SigningSecretSheet connection={issued} onDismiss={() => setIssued(null)} />
      {!open && !issued ? <Button onPress={() => setOpen(true)}>Reopen replacement</Button> : null}
    </>
  );
}

beforeEach(() => {
  mockKeys.issued = 0;
  mockRotateSigningSecret.mockReset();
});

describe("ConnectionCard signing-secret action", () => {
  it("014-FR-012 is not offered at all: no inbound secret exists to replace", async () => {
    const { renderer, unmount } = await renderWithProviders(
      <ConnectionCard
        connection={makeConnection()}
        onTest={jest.fn()}
        onRotate={jest.fn()}
        onDisconnect={jest.fn()}
      />,
    );

    expect(queryByText(renderer, "Replace signing secret")).toBeNull();
    await unmount();
  });
});

describe("ReplaceSigningSecretSheet", () => {
  it("sends the password and the revision the user saw, and nothing else", async () => {
    mockRotateSigningSecret.mockResolvedValue(replacement());
    const { renderer, unmount } = await renderWithProviders(<RecoveryHarness />);

    await typeInto(getByLabel(renderer, "Your Brain Buddy password"), "correct-horse");
    await pressText(renderer, "Replace signing secret");
    await settle();

    expect(mockRotateSigningSecret).toHaveBeenCalledTimes(1);
    expect(mockRotateSigningSecret.mock.calls[0][0]).toBe("conn_1");
    expect(mockRotateSigningSecret.mock.calls[0][1]).toEqual({
      current_password: "correct-horse",
      expected_revision: 2,
    });
    expect(mockRotateSigningSecret.mock.calls[0][2]).toEqual(expect.any(String));

    await unmount();
  });

  it("retries an ambiguous failure under the first attempt's key", async () => {
    mockRotateSigningSecret
      .mockRejectedValueOnce(new Error("Connection lost"))
      .mockResolvedValue(replacement());
    const { renderer, unmount } = await renderWithProviders(<RecoveryHarness />);

    await typeInto(getByLabel(renderer, "Your Brain Buddy password"), "correct-horse");
    await pressText(renderer, "Replace signing secret");
    await settle();
    await pressText(renderer, "Replace signing secret");
    await settle();

    expect(mockRotateSigningSecret).toHaveBeenCalledTimes(2);
    // The first attempt may already have rotated. A fresh key would rotate
    // again and strand the secret the first one issued.
    expect(mockRotateSigningSecret.mock.calls[1][2]).toBe(
      mockRotateSigningSecret.mock.calls[0][2],
    );

    await unmount();
  });

  it("keeps the ambiguous intent key when the sheet is closed and reopened", async () => {
    mockRotateSigningSecret
      .mockRejectedValueOnce(new Error("Connection lost"))
      .mockResolvedValue(replacement());
    const { renderer, unmount } = await renderWithProviders(<RecoveryHarness />);

    await typeInto(getByLabel(renderer, "Your Brain Buddy password"), "correct-horse");
    await pressText(renderer, "Replace signing secret");
    await settle();
    await pressLabel(renderer, "Close");
    await pressText(renderer, "Reopen replacement");
    await typeInto(getByLabel(renderer, "Your Brain Buddy password"), "correct-horse");
    await pressText(renderer, "Replace signing secret");
    await settle();

    expect(mockRotateSigningSecret).toHaveBeenCalledTimes(2);
    expect(mockRotateSigningSecret.mock.calls[1][2]).toBe(
      mockRotateSigningSecret.mock.calls[0][2],
    );
    await unmount();
  });

  it("blocks a changed password after an ambiguous failure and a reopen", async () => {
    mockRotateSigningSecret.mockRejectedValue(new Error("Connection lost"));
    const { renderer, unmount } = await renderWithProviders(<RecoveryHarness />);

    await typeInto(getByLabel(renderer, "Your Brain Buddy password"), "mistyped-horse");
    await pressText(renderer, "Replace signing secret");
    await settle();
    await pressLabel(renderer, "Close");
    await pressText(renderer, "Reopen replacement");
    await typeInto(getByLabel(renderer, "Your Brain Buddy password"), "correct-horse");
    await pressText(renderer, "Replace signing secret");
    await settle();

    expect(mockRotateSigningSecret).toHaveBeenCalledTimes(1);
    expect(mockRotateSigningSecret.mock.calls[0][1]).toEqual({
      current_password: "mistyped-horse",
      expected_revision: 2,
    });
    expect(visibleText(renderer)).toContain("previous signing-secret replacement outcome is unknown");
    await unmount();
  });

  it("retries the same password under the first key with the body frozen at mint time", async () => {
    mockRotateSigningSecret.mockRejectedValue(new Error("Connection lost"));
    const { renderer, unmount } = await renderWithProviders(<RecoveryHarness />);

    await typeInto(getByLabel(renderer, "Your Brain Buddy password"), "correct-horse");
    await pressText(renderer, "Replace signing secret");
    await settle();
    await pressLabel(renderer, "Close");
    await pressText(renderer, "Reopen replacement");
    await typeInto(getByLabel(renderer, "Your Brain Buddy password"), "correct-horse");
    await pressText(renderer, "Replace signing secret");
    await settle();

    expect(mockRotateSigningSecret.mock.calls[1][2]).toBe(
      mockRotateSigningSecret.mock.calls[0][2],
    );
    expect(mockRotateSigningSecret.mock.calls[1][1]).toEqual(
      mockRotateSigningSecret.mock.calls[0][1],
    );
    await unmount();
  });

  it("retires the key after a definitive 4xx", async () => {
    mockRotateSigningSecret.mockRejectedValue(new ApiError("Wrong password", 400, {}));
    const { renderer, unmount } = await renderWithProviders(<RecoveryHarness />);

    await typeInto(getByLabel(renderer, "Your Brain Buddy password"), "correct-horse");
    await pressText(renderer, "Replace signing secret");
    await settle();
    await pressText(renderer, "Replace signing secret");
    await settle();

    // A 4xx is a decided outcome: nothing was rotated, so holding the key would
    // pin the next attempt to an already-answered slot.
    expect(mockRotateSigningSecret.mock.calls[1][2]).not.toBe(
      mockRotateSigningSecret.mock.calls[0][2],
    );
    await unmount();
  });

  it("never puts the retained password back on screen after a reopen", async () => {
    mockRotateSigningSecret.mockRejectedValue(new Error("Connection lost"));
    const { renderer, unmount } = await renderWithProviders(<RecoveryHarness />);

    await typeInto(getByLabel(renderer, "Your Brain Buddy password"), "correct-horse");
    await pressText(renderer, "Replace signing secret");
    await settle();
    await pressLabel(renderer, "Close");
    await pressText(renderer, "Reopen replacement");

    // The frozen body is held so the retry stays at-most-once; it is not UI.
    expect(getByLabel(renderer, "Your Brain Buddy password").props.value).toBe("");
    expect(visibleText(renderer)).not.toContain("correct-horse");
    await unmount();
  });

  it("shows the replacement once and forgets it on dismiss", async () => {
    mockRotateSigningSecret.mockResolvedValue(replacement());
    const { renderer, unmount } = await renderWithProviders(<RecoveryHarness />);

    await typeInto(getByLabel(renderer, "Your Brain Buddy password"), "correct-horse");
    await pressText(renderer, "Replace signing secret");
    await settle();

    expect(visibleText(renderer)).toContain("sk-inbound-replacement");

    await pressText(renderer, "I have copied it");
    await settle();

    expect(visibleText(renderer)).not.toContain("sk-inbound-replacement");
    await unmount();
  });
});

describe("SigningSecretSheet copy", () => {
  it("never renders a blank secret and offers replacement recovery instead", async () => {
    const onReplace = jest.fn();
    const { renderer, unmount } = await renderWithProviders(
      <SigningSecretSheet
        connection={replacement({ inbound_signing_secret: "" })}
        onDismiss={jest.fn()}
        onReplace={onReplace}
      />,
    );

    expect(visibleText(renderer)).toContain("No signing secret was returned");
    expect(queryByText(renderer, "I have copied it")).toBeNull();
    await pressText(renderer, "Replace signing secret");
    expect(onReplace).toHaveBeenCalledTimes(1);

    await unmount();
  });

  it("points a user who loses it at replacing the signing secret, not the credential", async () => {
    const { renderer, unmount } = await renderWithProviders(
      <SigningSecretSheet connection={replacement()} onDismiss={jest.fn()} />,
    );

    const text = visibleText(renderer);
    expect(text).toContain("sk-inbound-replacement");
    expect(text).toMatch(/replace the signing secret/i);
    // Rotating the credential changes what Brain Buddy sends *to* the agent and
    // would leave the lost inbound secret exactly as lost.
    expect(text).not.toMatch(/rotate the credential/i);

    await unmount();
  });
});
