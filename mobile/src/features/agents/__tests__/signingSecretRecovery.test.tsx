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
import type { ReactTestInstance, ReactTestRenderer } from "react-test-renderer";

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

jest.mock("@/auth/SessionProvider", () => ({
  useApi: () => ({
    rotateAgentSigningSecret: (...args: unknown[]) => mockRotateSigningSecret(...args),
  }),
}));

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

function pressableFor(renderer: ReactTestRenderer, text: string): ReactTestInstance | null {
  let node = queryByText(renderer, text);
  while (node && typeof node.props?.onPress !== "function") {
    node = node.parent ?? null;
  }
  return node;
}

beforeEach(() => {
  mockKeys.issued = 0;
  mockRotateSigningSecret.mockReset();
});

describe("ConnectionCard signing-secret action", () => {
  it("offers the replacement on a live connection", async () => {
    const onReplaceSigningSecret = jest.fn();
    const { renderer, unmount } = await renderWithProviders(
      <ConnectionCard
        connection={makeConnection()}
        onTest={jest.fn()}
        onRotate={jest.fn()}
        onReplaceSigningSecret={onReplaceSigningSecret}
        onDisconnect={jest.fn()}
      />,
    );

    await pressText(renderer, "Replace signing secret");

    expect(onReplaceSigningSecret).toHaveBeenCalledTimes(1);
    await unmount();
  });

  it("does not offer it on a disconnected connection, whose secret is already gone", async () => {
    const { renderer, unmount } = await renderWithProviders(
      <ConnectionCard
        connection={makeConnection({ status: "disconnected", ready_for_handoff: false })}
        onTest={jest.fn()}
        onRotate={jest.fn()}
        onReplaceSigningSecret={jest.fn()}
        onDisconnect={jest.fn()}
      />,
    );

    expect(pressableFor(renderer, "Replace signing secret")?.props.disabled).toBe(true);
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
