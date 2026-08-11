/**
 * M-04, rendered.
 *
 * `sheetState.test.ts` asserts what the sheet *decides*; nothing there proves a
 * value was ever drawn, labelled, focusable or tappable. That gap was real —
 * the component was written under the belief that `mobile/` cannot mount a
 * React tree — and it is what this file closes. Every assertion below is
 * something a person can perceive: visible text, an accessible name, or a
 * button that is disabled and says why.
 *
 * The clock is passed in (`now`), matching `sheetState.ts`, so every age here
 * is exact rather than flaky. One test deliberately omits it, because reading
 * the clock in an effect is the screen's own job and the only place it is
 * observable.
 */

import { act, fireEvent, render, screen } from "@testing-library/react-native";
import { useState } from "react";
import { Text } from "react-native";

import { ConflictSheet, type ConflictSheetProps } from "../ConflictSheet";
import type { PendingClassificationChange } from "../classificationTypes";
import type { NamedEntity } from "../matchExisting";
import type { ConflictServerState } from "../sheetState";

const NOW = "2026-08-11T09:41:00.000Z";
/** 14 minutes before NOW — design.md's "You changed the project 14 minutes ago". */
const CHANGED_AT = "2026-08-11T09:27:00.000Z";
/** 21 days before NOW — design.md's "as of 3 weeks ago". */
const OBSERVED_AT = "2026-07-21T09:41:00.000Z";
const CORRELATION_ID = "4f2a91c0-8e7b";

const PROJECTS: NamedEntity[] = [
  { id: "project_inbox", name: "Inbox" },
  { id: "project_q3", name: "Q3 planning" },
  { id: "project_onboarding", name: "Onboarding drop-off" },
];

const TAGS: NamedEntity[] = [
  { id: "tag_writing", name: "writing" },
  { id: "tag_deep", name: "deep-work" },
  { id: "tag_errand", name: "errand" },
];

function entry(overrides: Partial<PendingClassificationChange> = {}): PendingClassificationChange {
  return {
    taskId: "task_47",
    accountId: "acct_1",
    serverUrl: "https://bb.example.test",
    value: { projectId: "project_q3", tagIds: undefined },
    observedRevision: 4,
    originalValue: { projectId: "project_inbox", tagIds: [] },
    firstQueuedAt: CHANGED_AT,
    lastEditedAt: CHANGED_AT,
    idempotencyKey: "key-1",
    sendState: "conflicted",
    ...overrides,
  };
}

/** Someone else moved the task on to a third project while the change waited. */
const SERVER: ConflictServerState = {
  projectId: "project_onboarding",
  tagIds: [],
  revision: 5,
};

const BASE: ConflictSheetProps = {
  visible: true,
  conflict: { entry: entry(), index: 1, total: 1 },
  server: SERVER,
  reason: "stale-revision",
  names: { projects: PROJECTS, tags: TAGS },
  deviceObservedAt: OBSERVED_AT,
  correlationId: CORRELATION_ID,
  onKeepMine: () => Promise.resolve(),
  onDiscardMine: () => Promise.resolve(),
  onDismiss: () => {},
  now: NOW,
};

/**
 * Settle the sheet's first look at the clock.
 *
 * React's purity rule forbids reading the clock while rendering, so the sheet
 * reads it just after mounting and states the change without its age until
 * then. Waiting for that here is what lets a test assert the ages a person
 * actually ends up reading, whichever way the screen defers the read.
 */
async function letTheSheetReadTheClock() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

async function renderSheet(overrides: Partial<ConflictSheetProps> = {}) {
  const result = await render(<ConflictSheet {...BASE} {...overrides} />);
  await letTheSheetReadTheClock();
  return result;
}

/** The diff rows in the order a reader meets them, top to bottom. */
function rowNames(): string[] {
  return screen
    .getAllByLabelText(/^(Your phone last showed|You changed (it|them) to|Now on server):/)
    .map((row) => String(row.props.accessibilityLabel));
}

/** A promise the test settles, so the in-flight state can be looked at. */
function deferred() {
  let settle: () => void = () => {};
  let fail: (reason: unknown) => void = () => {};
  const promise = new Promise<void>((resolve, reject) => {
    settle = () => resolve();
    fail = reject;
  });
  return { promise, settle, fail };
}

const KEEP_MINE = "Keep mine, replace theirs";
const DISCARD_MINE = "Discard mine, keep the server's";

describe("006-FR-010 M-04 names all three values", () => {
  it("006-FR-010 shows the started, the intended and the server's value as labelled rows", async () => {
    await renderSheet();

    expect(screen.getByText("You changed the project 14 minutes ago")).toBeOnTheScreen();
    expect(
      screen.getByText(
        "This task was updated somewhere else before your change was sent, so it was not applied. " +
          "Choose which one to keep — nothing has been discarded yet.",
      ),
    ).toBeOnTheScreen();

    expect(screen.getByText("Your phone last showed")).toBeOnTheScreen();
    expect(screen.getByText("Inbox")).toBeOnTheScreen();
    expect(screen.getByText("You changed it to")).toBeOnTheScreen();
    expect(screen.getByText("Q3 planning")).toBeOnTheScreen();
    expect(screen.getByText("Now on server")).toBeOnTheScreen();
    expect(screen.getByText("Onboarding drop-off")).toBeOnTheScreen();

    expect(screen.getByLabelText(KEEP_MINE)).toBeOnTheScreen();
    expect(screen.getByLabelText(DISCARD_MINE)).toBeOnTheScreen();
    expect(screen.getByText(`correlation id ${CORRELATION_ID}`)).toBeOnTheScreen();
  });

  it("006-FR-010 dates the started value as what this phone showed, not as server history", async () => {
    await renderSheet();

    expect(screen.getByText("as of 3 weeks ago")).toBeOnTheScreen();
    // Read out as one sentence, so the source of the value is heard and not
    // inferred from a label sitting above it.
    expect(rowNames()).toEqual([
      "Your phone last showed: Inbox (as of 3 weeks ago)",
      "You changed it to: Q3 planning",
      "Now on server: Onboarding drop-off",
    ]);
  });

  it("006-FR-010 leaves the started value undated when nothing recorded the last read", async () => {
    await renderSheet({ deviceObservedAt: null });

    expect(screen.getByText("the value this phone was showing you")).toBeOnTheScreen();
    expect(screen.queryByText(/^as of /)).toBeNull();
    expect(rowNames()[0]).toBe(
      "Your phone last showed: Inbox (the value this phone was showing you)",
    );
  });

  it("006-FR-010 dates the rows from its own clock when the screen passes none", async () => {
    const minutesAgo = (count: number) => new Date(Date.now() - count * 60_000).toISOString();
    // A minute of slack, so a boundary crossed mid-test cannot round down.
    const weeksAgo = (count: number) =>
      new Date(Date.now() - count * 7 * 24 * 60 * 60_000 - 60_000).toISOString();

    await renderSheet({
      conflict: { entry: entry({ lastEditedAt: minutesAgo(14) }), index: 1, total: 1 },
      deviceObservedAt: weeksAgo(3),
      now: undefined,
    });

    // Not on the first frame: React's purity rule forbids reading the clock
    // during render, so the sheet states the change without its age until its
    // own effect has run. Both ages then appear together.
    expect(await screen.findByText("You changed the project 14 minutes ago")).toBeOnTheScreen();
    expect(screen.getByText("as of 3 weeks ago")).toBeOnTheScreen();
  });

  it("006-FR-010 warns that the task changed more than once when the phone was far behind", async () => {
    await renderSheet({ server: { ...SERVER, revision: 7 } });

    expect(
      screen.getByText("This task has changed more than once since your phone last saw it."),
    ).toBeOnTheScreen();
  });

  it("006-FR-010 says nothing of the kind when the task moved on exactly once", async () => {
    await renderSheet({ server: { ...SERVER, revision: 5 } });

    expect(screen.queryByText(/changed more than once/)).toBeNull();
    // The disagreement itself is still on screen; only the extra line is absent.
    expect(screen.getByText("Now on server")).toBeOnTheScreen();
  });
});

describe("006-FR-002 M-04 with Tags in the change", () => {
  const tagsOnly = entry({
    value: { projectId: undefined, tagIds: ["tag_deep", "tag_writing"] },
    originalValue: { projectId: "project_inbox", tagIds: ["tag_writing"] },
  });

  it("006-FR-002 gives a Tags conflict its own three-row diff", async () => {
    await renderSheet({
      conflict: { entry: tagsOnly, index: 1, total: 1 },
      server: { projectId: "project_inbox", tagIds: ["tag_errand"], revision: 5 },
    });

    expect(screen.getByText("You changed the Tags 14 minutes ago")).toBeOnTheScreen();
    expect(rowNames()).toEqual([
      "Your phone last showed: writing (as of 3 weeks ago)",
      // Sorted, because three sets are compared by eye and a set has no order.
      "You changed them to: deep-work, writing",
      "Now on server: errand",
    ]);
    // FR-013: Tag, never Context.
    expect(screen.queryByText(/[Cc]ontext/)).toBeNull();
  });

  it("006-FR-002 stacks one section per field when a change touched the project and the Tags", async () => {
    const both = entry({
      value: { projectId: "project_q3", tagIds: ["tag_deep", "tag_writing"] },
      originalValue: { projectId: "project_inbox", tagIds: ["tag_writing"] },
    });

    await renderSheet({
      conflict: { entry: both, index: 1, total: 1 },
      server: { projectId: "project_onboarding", tagIds: ["tag_errand"], revision: 5 },
    });

    // Each field says which and when for itself, so the title says only what
    // happened to the change as a whole.
    expect(screen.getByText("Your queued change was not applied")).toBeOnTheScreen();
    expect(screen.getByText("You changed the project 14 minutes ago")).toBeOnTheScreen();
    expect(screen.getByText("You changed the Tags 14 minutes ago")).toBeOnTheScreen();

    // Six rows, in reading order: the whole project diff, then the whole Tags
    // diff. The test renderer performs no layout, so "stacked vertically" is
    // asserted as the order and separateness of the rows — a Tag set is never
    // put beside another value.
    expect(rowNames()).toEqual([
      "Your phone last showed: Inbox (as of 3 weeks ago)",
      "You changed it to: Q3 planning",
      "Now on server: Onboarding drop-off",
      "Your phone last showed: writing (as of 3 weeks ago)",
      "You changed them to: deep-work, writing",
      "Now on server: errand",
    ]);
  });
});

describe("006-FR-008 M-04 choosing", () => {
  it("006-FR-008 shows progress on the chosen button and disables — never hides — the other", async () => {
    const keep = deferred();
    await renderSheet({ onKeepMine: () => keep.promise });

    await fireEvent.press(screen.getByLabelText(KEEP_MINE));

    // The chosen button keeps its accessible name while its label gives way to
    // the spinner, so it is still findable and still says what it is doing.
    expect(screen.getByLabelText(KEEP_MINE)).toBeDisabled();
    expect(screen.queryByText(KEEP_MINE)).toBeNull();

    // The other is disabled and still on screen: hiding it lets a second tap
    // land on whatever moves into its place.
    expect(screen.getByText(DISCARD_MINE)).toBeOnTheScreen();
    expect(screen.getByText("Waiting for the choice you made to finish")).toBeOnTheScreen();
    const other = screen.getByLabelText(
      `${DISCARD_MINE}. Waiting for the choice you made to finish`,
    );
    expect(other).toBeDisabled();

    await act(async () => {
      keep.settle();
    });

    expect(screen.getByText(KEEP_MINE)).toBeOnTheScreen();
    expect(screen.getByLabelText(DISCARD_MINE)).toBeOnTheScreen();
    expect(screen.queryByText("Waiting for the choice you made to finish")).toBeNull();
  });

  it("006-FR-012 re-offers both choices when the resolution fails, having discarded nothing", async () => {
    const keep = deferred();
    await renderSheet({ onKeepMine: () => keep.promise });

    await fireEvent.press(screen.getByLabelText(KEEP_MINE));
    await act(async () => {
      keep.fail({
        status: 409,
        payload: { message: "That task changed again.", reference_id: "corr-77" },
      });
    });

    expect(
      screen.getByText("We couldn't send your choice. Nothing has been discarded — try again."),
    ).toBeOnTheScreen();
    expect(screen.getByText("That task changed again.")).toBeOnTheScreen();
    // FR-012: the id travels with the failure, and it is the failure's own.
    expect(screen.getByText("correlation id corr-77")).toBeOnTheScreen();
    expect(screen.queryByText(`correlation id ${CORRELATION_ID}`)).toBeNull();

    // Nothing was discarded: the same three values, and both choices, are back.
    expect(rowNames()).toHaveLength(3);
    expect(screen.getByLabelText(KEEP_MINE)).not.toBeDisabled();
    expect(screen.getByLabelText(DISCARD_MINE)).not.toBeDisabled();
  });

  it("006-FR-012 keeps the rejection's own correlation id when the failure explains nothing", async () => {
    const discard = deferred();
    await renderSheet({ onDiscardMine: () => discard.promise });

    await fireEvent.press(screen.getByLabelText(DISCARD_MINE));
    await act(async () => {
      discard.fail({ status: 500 });
    });

    expect(
      screen.getByText("We couldn't send your choice. Nothing has been discarded — try again."),
    ).toBeOnTheScreen();
    // No server words to quote, so none are invented — but the sheet is still
    // reportable, on the id of the rejection that opened it.
    expect(screen.getByText(`correlation id ${CORRELATION_ID}`)).toBeOnTheScreen();
  });

  it("006-FR-008 offers only the discard when the target was deleted somewhere else", async () => {
    await renderSheet({ reason: "target-missing", server: null, missingTarget: "project" });

    expect(screen.getByText("This change can't be applied any more")).toBeOnTheScreen();
    expect(screen.getByText("Discard my change")).toBeOnTheScreen();
    // "Keep mine, replace theirs" names something that is no longer there.
    expect(screen.queryByText(KEEP_MINE)).toBeNull();
    expect(screen.queryByText(DISCARD_MINE)).toBeNull();

    // Two rows, not three: with no server state there is no third value, and
    // none is invented.
    expect(rowNames()).toEqual([
      "Your phone last showed: Inbox (as of 3 weeks ago)",
      "You changed it to: Q3 planning",
    ]);
    expect(screen.getByText(`correlation id ${CORRELATION_ID}`)).toBeOnTheScreen();
  });

  const MISSING: [string, ConflictSheetProps["missingTarget"], string][] = [
    [
      "the task itself",
      "task",
      "This task was deleted somewhere else, so there is nothing left to apply your change to. " +
        "Nothing else of yours is affected.",
    ],
    [
      "the project",
      "project",
      "The project you chose was deleted somewhere else, so your change can't be applied. " +
        "Nothing else of yours is affected.",
    ],
    [
      "the Tag",
      "tag",
      "The Tag you chose was deleted somewhere else, so your change can't be applied. " +
        "Nothing else of yours is affected.",
    ],
    [
      "one of the three, unnamed",
      undefined,
      "The task, project or Tag this change points to was deleted somewhere else, so there is " +
        "nothing left to apply it to. Nothing else of yours is affected.",
    ],
  ];

  it.each(MISSING)("006-FR-008 says %s was deleted somewhere else", async (_name, target, body) => {
    await renderSheet({ reason: "target-missing", server: null, missingTarget: target });

    expect(screen.getByText(body)).toBeOnTheScreen();
  });

  it("006-FR-008 counts the conflicts when several tasks are waiting", async () => {
    await renderSheet({ conflict: { entry: entry(), index: 2, total: 3 } });

    expect(screen.getByText("2 of 3")).toBeOnTheScreen();
    // The heading is one announcement, so the count is heard with the question.
    expect(
      screen.getByLabelText("2 of 3. You changed the project 14 minutes ago"),
    ).toBeOnTheScreen();
  });

  it("006-FR-008 says nothing about a count when this is the only conflict", async () => {
    await renderSheet();

    expect(screen.queryByText(/^\d+ of \d+$/)).toBeNull();
    expect(screen.getByLabelText("You changed the project 14 minutes ago")).toBeOnTheScreen();
  });
});

describe("006-SC-005 M-04 when there is nothing to decide", () => {
  it("006-FR-017 asks nothing when the server already holds what the change intended", async () => {
    await renderSheet({
      server: { projectId: "project_q3", tagIds: [], revision: 5 },
    });

    // The one explicit exception to SC-005: no disagreement, so no prompt at
    // all — not a prompt with one option, and not an auto-resolved one.
    expect(screen.toJSON()).toBeNull();
  });

  it("006-SC-005 shows nothing when no conflict is waiting", async () => {
    await renderSheet({ conflict: undefined });

    expect(screen.toJSON()).toBeNull();
  });

  it("006-SC-005 dismissing decides nothing, and the same prompt returns", async () => {
    function TaskScreen() {
      const [open, setOpen] = useState(true);
      return (
        <>
          <ConflictSheet {...BASE} visible={open} onDismiss={() => setOpen(false)} />
          {open ? null : <Text onPress={() => setOpen(true)}>Back on the task</Text>}
        </>
      );
    }

    await render(<TaskScreen />);
    // The scrim, standing in for Escape and for backgrounding the app.
    await fireEvent.press(screen.getByLabelText("Close"));

    expect(screen.queryByText("You changed the project 14 minutes ago")).toBeNull();
    expect(screen.queryByText(KEEP_MINE)).toBeNull();

    await fireEvent.press(screen.getByText("Back on the task"));

    // Nothing was resolved and nothing discarded: the question comes back whole.
    expect(screen.getByText("You changed the project 14 minutes ago")).toBeOnTheScreen();
    expect(rowNames()).toEqual([
      "Your phone last showed: Inbox (as of 3 weeks ago)",
      "You changed it to: Q3 planning",
      "Now on server: Onboarding drop-off",
    ]);
    expect(screen.getByLabelText(KEEP_MINE)).not.toBeDisabled();
  });
});
