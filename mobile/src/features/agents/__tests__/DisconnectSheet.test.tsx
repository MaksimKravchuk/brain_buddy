/**
 * M-01-S21: the disconnect confirmation on iOS.
 *
 * This sheet destroys a credential and the only record of where a connection
 * pointed. Every assertion here exists so that outcome can only follow from
 * someone deliberately choosing it — never from a stray gesture, and never
 * from a sentence that understated what was about to be erased.
 *
 * 014-FR-016, AC-022, AC-024.
 */

import type { ReactTestInstance, ReactTestRenderer } from "react-test-renderer";

import { DisconnectSheet } from "@/features/agents/DisconnectSheet";
import { makeConnection } from "@/test/agentFixtures";
import {
  getByLabel,
  pressText,
  renderWithProviders,
  settle,
  typeInto,
  visibleText,
} from "@/test/render";

const mockDisconnect = jest.fn();

jest.mock("expo-crypto", () => ({ randomUUID: () => "idem_key_disconnect" }));

jest.mock("react-native-safe-area-context", () => ({
  useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }),
}));

jest.mock("@/auth/SessionProvider", () => {
  const api = {
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
  mockDisconnect.mockReset();
});

/**
 * The destructive action's own pressable.
 *
 * Found by position rather than by its label, because a button in flight
 * renders a spinner in place of its text — and "in flight" is exactly the
 * state these assertions are about.
 */
function destructiveAction(renderer: ReactTestRenderer): ReactTestInstance {
  const buttons = renderer.root.findAll(
    (node) => node.props?.accessibilityRole === "button",
    { deep: true },
  );
  const last = buttons[buttons.length - 1];
  if (!last) {
    throw new Error("The sheet rendered no actions at all.");
  }
  return last;
}

/** The order the two actions appear in, top to bottom. */
function actionOrder(renderer: { toJSON: () => unknown }): string[] {
  const text = visibleText(renderer as never);
  return ["Keep it connected", "Disconnect and destroy the credential"].sort(
    (a, b) => text.indexOf(a) - text.indexOf(b),
  );
}

describe("014-FR-016 DisconnectSheet", () => {
  it("says exactly what is erased, in the same words as the desktop dialog", async () => {
    const { renderer, unmount } = await renderWithProviders(
      <DisconnectSheet
        connection={makeConnection()}
        onClose={jest.fn()}
        onDisconnected={jest.fn()}
      />,
    );

    const text = visibleText(renderer);
    expect(text).toContain(
      "The stored credential and the agent-card summary Brain Buddy discovered",
    );
    expect(text).toContain("card fingerprint");
    expect(text).toContain("interface");
    // AC-022: disconnecting stops future work, it does not undo accepted work.
    expect(text).toContain("Disconnecting does not cancel work the agent already accepted.");

    await unmount();
  });

  it("puts the destructive action below the safe one", async () => {
    // On a sheet the thumb rests near the bottom, so the action that destroys
    // a credential is the one furthest from an accidental tap.
    const { renderer, unmount } = await renderWithProviders(
      <DisconnectSheet
        connection={makeConnection()}
        onClose={jest.fn()}
        onDisconnected={jest.fn()}
      />,
    );

    expect(actionOrder(renderer)).toEqual([
      "Keep it connected",
      "Disconnect and destroy the credential",
    ]);

    await unmount();
  });

  it("requires the password before the destructive action can be taken", async () => {
    mockDisconnect.mockResolvedValue(makeConnection({ status: "disconnected" }));
    const { renderer, unmount } = await renderWithProviders(
      <DisconnectSheet
        connection={makeConnection()}
        onClose={jest.fn()}
        onDisconnected={jest.fn()}
      />,
    );

    // Announced unavailable, not merely dimmed: a screen-reader user is the
    // one most likely to press a control that only *looks* inert.
    expect(destructiveAction(renderer).props.accessibilityState).toEqual(
      expect.objectContaining({ disabled: true }),
    );

    await typeInto(getByLabel(renderer, "Your Brain Buddy password"), "hunter2hunter2");
    expect(destructiveAction(renderer).props.accessibilityState).toEqual(
      expect.objectContaining({ disabled: false }),
    );
    await pressText(renderer, "Disconnect and destroy the credential");
    await settle();
    expect(mockDisconnect).toHaveBeenCalledTimes(1);

    await unmount();
  });

  it("states the disabled accessibility state while the request is in flight", async () => {
    // Stated, not merely implied: a dimmed control with no announced state is
    // invisible to a screen reader, which is exactly the user most likely to
    // press it again.
    const releases: { resolve: (() => void) | null } = { resolve: null };
    mockDisconnect.mockImplementation(
      () =>
        new Promise((resolve) => {
          releases.resolve = () => resolve(makeConnection({ status: "disconnected" }));
        }),
    );
    const { renderer, unmount } = await renderWithProviders(
      <DisconnectSheet
        connection={makeConnection()}
        onClose={jest.fn()}
        onDisconnected={jest.fn()}
      />,
    );

    await typeInto(getByLabel(renderer, "Your Brain Buddy password"), "hunter2hunter2");
    await pressText(renderer, "Disconnect and destroy the credential");

    // Exactly one control announces itself busy, and it also announces itself
    // unavailable — a dimmed control with no announced state is invisible to a
    // screen reader, which is the user most likely to press it again.
    const busy = renderer.root
      .findAll((node) => node.props?.accessibilityState?.busy === true, { deep: true })
      .map((node) => node.props.accessibilityState);
    expect(busy.length).toBeGreaterThan(0);
    for (const state of busy) {
      expect(state).toEqual(expect.objectContaining({ disabled: true, busy: true }));
    }

    releases.resolve?.();
    await settle();
    await unmount();
  });

  it("does not decide on a stray gesture", async () => {
    // Dismissing the sheet is not a decision either way: nothing is sent, and
    // the password on screen is cleared rather than left waiting for a tap.
    const onClose = jest.fn();
    const onDisconnected = jest.fn();
    const { renderer, unmount } = await renderWithProviders(
      <DisconnectSheet
        connection={makeConnection()}
        onClose={onClose}
        onDisconnected={onDisconnected}
      />,
    );

    await typeInto(getByLabel(renderer, "Your Brain Buddy password"), "hunter2hunter2");
    await pressText(renderer, "Keep it connected");
    await settle();

    expect(mockDisconnect).not.toHaveBeenCalled();
    expect(onDisconnected).not.toHaveBeenCalled();
    expect(onClose).toHaveBeenCalledTimes(1);

    await unmount();
  });
});
