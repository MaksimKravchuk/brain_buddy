/**
 * M-05, rendered.
 *
 * `sheetState.test.ts` asserts what this sheet decides; nothing there proves a
 * count was drawn, a button was disabled, or that the reason for it was ever
 * legible. This file asserts what the person in front of the phone gets: the
 * text on the sheet, the accessible names of the two choices, and what happens
 * to the sign-out they started.
 *
 * The transitions are driven through a stand-in parent rather than by watching
 * callbacks, because "continued" and "stayed" are things a person observes —
 * the screen they end up on — not calls a spy records.
 */

import { fireEvent, render, screen } from "@testing-library/react-native";
import { useState } from "react";
import { Text } from "react-native";

import { DiscardUnsentSheet, type DiscardUnsentSheetProps } from "../DiscardUnsentSheet";
import type { PendingClassificationChange, SendState } from "../classificationTypes";
import type { DiscardTrigger } from "../sheetState";

const QUEUED_AT = "2026-08-11T09:27:00.000Z";

function entry(
  taskId: string,
  sendState: SendState = "queued",
  overrides: Partial<PendingClassificationChange> = {},
): PendingClassificationChange {
  return {
    taskId,
    accountId: "acct_1",
    serverUrl: "https://bb.example.test",
    value: { projectId: "project_q3", tagIds: undefined },
    observedRevision: 4,
    originalValue: { projectId: "project_inbox", tagIds: [] },
    firstQueuedAt: QUEUED_AT,
    lastEditedAt: QUEUED_AT,
    idempotencyKey: `key-${taskId}`,
    sendState,
    ...overrides,
  };
}

const TWO_UNSENT = [entry("task_47"), entry("task_48")];

const BASE: DiscardUnsentSheetProps = {
  visible: true,
  queue: TWO_UNSENT,
  trigger: "sign-out",
  online: true,
  onStay: () => {},
  onContinue: () => {},
};

function renderSheet(overrides: Partial<DiscardUnsentSheetProps> = {}) {
  return render(<DiscardUnsentSheet {...BASE} {...overrides} />);
}

/** Every line of copy on the sheet, in reading order. */
function sheetText(): string[] {
  return screen.getAllByText(/\S/).map((node) => String(node.props.children));
}

const STAY_TWO = "Stay and let them send";
const DISCARD_TWO = "Discard 2 changes and continue";

/**
 * A stand-in for the screen that opens this sheet: it holds the sign-out that
 * is waiting on the answer, so "continued" and "stayed" are observable as the
 * place the person ends up rather than as a recorded call.
 */
function SignOutFlow({
  queue,
  online = true,
  trigger = "sign-out",
  error = null,
}: {
  queue: readonly PendingClassificationChange[];
  online?: boolean;
  trigger?: DiscardTrigger;
  error?: DiscardUnsentSheetProps["error"];
}) {
  const [phase, setPhase] = useState<"deciding" | "stayed" | "gone">("deciding");
  return (
    <>
      <DiscardUnsentSheet
        visible={phase === "deciding"}
        queue={queue}
        trigger={trigger}
        online={online}
        error={error}
        onStay={() => setPhase("stayed")}
        onContinue={() => setPhase("gone")}
      />
      {phase === "gone" ? <Text>Signed out</Text> : null}
      {phase === "stayed" ? <Text>Still signed in</Text> : null}
    </>
  );
}

describe("006-FR-011 M-05 what the person is told", () => {
  it("006-FR-011 states how many changes are unsent and what continuing costs", async () => {
    await renderSheet();

    expect(screen.getByText("2 changes have not been sent")).toBeOnTheScreen();
    expect(
      screen.getByText(
        "Signing out discards them, because they belong to the account and server they were " +
          "made on and cannot be sent from another. This cannot be undone.",
      ),
    ).toBeOnTheScreen();
    expect(screen.getByLabelText(STAY_TWO)).toBeOnTheScreen();
    expect(screen.getByLabelText(DISCARD_TWO)).toBeOnTheScreen();
    // The heading is announced as one thing, so the count is heard with the
    // question rather than being read off a line above it.
    expect(screen.getByLabelText("2 changes have not been sent")).toBeOnTheScreen();
  });

  it("006-SC-007 names none of the work it is about to discard", async () => {
    await renderSheet();

    // The whole of the copy, enumerated: a list added later cannot slip in as
    // an improvement, because it would show up here as an extra line.
    expect(sheetText()).toEqual([
      "2 changes have not been sent",
      "Signing out discards them, because they belong to the account and server they were " +
        "made on and cannot be sent from another. This cannot be undone.",
      STAY_TWO,
      DISCARD_TWO,
    ]);
    for (const identifier of ["task_47", "task_48", "key-task_47", "project_q3"]) {
      expect(screen.queryAllByText(new RegExp(identifier))).toHaveLength(0);
    }
  });

  it("006-FR-011 speaks in the singular about a single unsent change", async () => {
    await renderSheet({ queue: [entry("task_47")] });

    expect(screen.getByText("1 change has not been sent")).toBeOnTheScreen();
    expect(screen.getByLabelText("Stay and let it send")).toBeOnTheScreen();
    expect(screen.getByLabelText("Discard 1 change and continue")).toBeOnTheScreen();
  });

  const TRIGGERS: [DiscardTrigger, string][] = [
    ["sign-out", "Signing out discards them,"],
    ["account-change", "Switching account discards them,"],
    ["server-change", "Switching server discards them,"],
  ];

  it.each(TRIGGERS)("006-FR-011 names the transition that discards, for %s", async (trigger, opening) => {
    await renderSheet({ trigger });

    expect(screen.getByText(new RegExp(`^${opening}`))).toBeOnTheScreen();
  });

  it("006-FR-011 shows nothing at all while it is closed", async () => {
    await renderSheet({ visible: false });

    expect(screen.toJSON()).toBeNull();
  });
});

describe("006-FR-011 M-05 when a choice is unavailable", () => {
  it("006-FR-011 blocks the discard while a change is being sent, and says why in words", async () => {
    await renderSheet({ queue: [entry("task_47", "sending"), entry("task_48")] });

    const reason =
      "A change is being sent right now and can't be called back. " +
      "Discarding is available again once it finishes.";
    // The reason is text, not a greyed button: no state here is communicated
    // by colour alone.
    expect(screen.getByText(reason)).toBeOnTheScreen();
    expect(screen.getByLabelText(`${DISCARD_TWO}. ${reason}`)).toBeDisabled();

    // Staying is exactly the right thing to do, so it stays available.
    expect(screen.getByLabelText(STAY_TWO)).not.toBeDisabled();
  });

  it("006-FR-011 counts the sends it cannot call back", async () => {
    await renderSheet({ queue: [entry("task_47", "sending"), entry("task_48", "sending")] });

    expect(
      screen.getByText(
        "2 changes are being sent right now and can't be called back. " +
          "Discarding is available again once they finish.",
      ),
    ).toBeOnTheScreen();
  });

  it("006-FR-006 disables staying when there is no connection, and says why in words", async () => {
    await renderSheet({ online: false });

    expect(screen.getByText("Nothing can be sent without a connection")).toBeOnTheScreen();
    expect(
      screen.getByLabelText(`${STAY_TWO}. Nothing can be sent without a connection`),
    ).toBeDisabled();

    // Discarding is still offered — the person is not trapped on this sheet.
    expect(screen.getByLabelText(DISCARD_TWO)).not.toBeDisabled();
  });

  it("006-FR-006 keeps staying available offline while a change is genuinely in flight", async () => {
    await renderSheet({ online: false, queue: [entry("task_47", "sending"), entry("task_48")] });

    // Something is being sent, so "nothing can be sent without a connection"
    // is not true — and disabling both choices would leave no way off the sheet.
    expect(screen.queryByText("Nothing can be sent without a connection")).toBeNull();
    expect(screen.getByLabelText(STAY_TWO)).not.toBeDisabled();
    expect(
      screen.getByText(/A change is being sent right now and can't be called back\./),
    ).toBeOnTheScreen();
  });

  it("006-FR-012 keeps both choices open when the drain fails, and carries the correlation id", async () => {
    await renderSheet({
      error: { message: "The server hung up.", correlationId: "corr-31" },
    });

    expect(
      screen.getByText(
        "We couldn't send them just now. Nothing has been discarded — you can still choose.",
      ),
    ).toBeOnTheScreen();
    expect(screen.getByText("The server hung up.")).toBeOnTheScreen();
    expect(screen.getByText("correlation id corr-31")).toBeOnTheScreen();

    // The count stays, and so does the choice.
    expect(screen.getByText("2 changes have not been sent")).toBeOnTheScreen();
    expect(screen.getByLabelText(STAY_TWO)).not.toBeDisabled();
    expect(screen.getByLabelText(DISCARD_TWO)).not.toBeDisabled();
  });
});

describe("006-FR-011 M-05 what the answer does", () => {
  it("006-FR-011 proceeds with no sheet at all when nothing is waiting", async () => {
    await render(<SignOutFlow queue={[]} />);

    // A warning naming zero changes is chrome for its own sake, so the sign-out
    // the person asked for simply happens.
    expect(screen.getByText("Signed out")).toBeOnTheScreen();
    expect(screen.queryByText(/have not been sent/)).toBeNull();
    expect(screen.queryByText("All your changes have been sent")).toBeNull();
  });

  it("006-FR-011 ignores changes already discarded for age when counting", async () => {
    await render(<SignOutFlow queue={[entry("task_47", "expired")]} />);

    // FR-018 discarded it and the task screen already said so; warning again
    // about a loss that has happened would inflate the one sentence the person
    // gets. With nothing left at risk, the sign-out proceeds.
    expect(screen.getByText("Signed out")).toBeOnTheScreen();
  });

  it("006-FR-011 asks for one more tap when the queue drains to zero while it is open", async () => {
    const { rerender } = await render(<SignOutFlow queue={TWO_UNSENT} />);
    expect(screen.getByText("2 changes have not been sent")).toBeOnTheScreen();

    await rerender(<SignOutFlow queue={[]} />);

    // Completing the sign-out under someone mid-read is the one thing this
    // sheet exists to prevent, so it costs a tap instead.
    expect(screen.getByText("All your changes have been sent")).toBeOnTheScreen();
    expect(screen.getByText("Nothing is waiting on this device any more.")).toBeOnTheScreen();
    expect(screen.queryByText("Signed out")).toBeNull();

    await fireEvent.press(screen.getByText("Continue"));

    expect(screen.getByText("Signed out")).toBeOnTheScreen();
  });

  it("006-FR-011 discarding continues, and the sheet goes with it", async () => {
    await render(<SignOutFlow queue={TWO_UNSENT} />);

    await fireEvent.press(screen.getByLabelText(DISCARD_TWO));

    expect(screen.getByText("Signed out")).toBeOnTheScreen();
    expect(screen.queryByText("2 changes have not been sent")).toBeNull();
  });

  it("006-FR-011 staying cancels the sign-out so the work can still be sent", async () => {
    await render(<SignOutFlow queue={TWO_UNSENT} />);

    await fireEvent.press(screen.getByLabelText(STAY_TWO));

    expect(screen.getByText("Still signed in")).toBeOnTheScreen();
    expect(screen.queryByText("Signed out")).toBeNull();
    expect(screen.queryByText("2 changes have not been sent")).toBeNull();
  });

  it("006-FR-011 treats the scrim as staying, never as discarding", async () => {
    await render(<SignOutFlow queue={TWO_UNSENT} />);

    // Escape and the scrim are the non-destructive choice.
    await fireEvent.press(screen.getByLabelText("Close"));

    expect(screen.getByText("Still signed in")).toBeOnTheScreen();
    expect(screen.queryByText("Signed out")).toBeNull();
  });
});
