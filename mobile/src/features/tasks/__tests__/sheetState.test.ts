/**
 * Every row of design.md's M-04 and M-05 state tables, asserted as data.
 *
 * `mobile/` installs no React renderer, so `ConflictSheet.tsx` and
 * `DiscardUnsentSheet.tsx` are evidenced only by typecheck, the Metro bundle
 * and the quickstart's manual steps. Everything those two screens *decide*
 * lives in `sheetState.ts` and is asserted here — which is the only reason
 * either sheet has any automated coverage at all. **Nothing below should be
 * read as covering the components' rendering**: no assertion here proves a
 * button was drawn, focused, or tappable. The picker lane made the same
 * statement for the same reason.
 */

import type { PendingClassificationChange, SendState } from "../classificationTypes";
import type { NamedEntity } from "../matchExisting";
import {
  CONFLICT_COPY,
  DISCARD_COPY,
  buildConflictView,
  buildDiscardUnsentView,
  countUnsent,
  formatAge,
  type ConflictNames,
  type ConflictPromptView,
  type ConflictServerState,
  type ConflictViewInput,
  type DiscardUnsentPromptView,
  type DiscardUnsentViewInput,
} from "../sheetState";

const NOW = "2026-08-11T09:41:00.000Z";
/** 14 minutes before NOW — the mock's "You changed the project 14 minutes ago". */
const CHANGED_AT = "2026-08-11T09:27:00.000Z";
/** 21 days before NOW — the mock's "as of 3 weeks ago". */
const OBSERVED_AT = "2026-07-21T09:41:00.000Z";

const PROJECTS: NamedEntity[] = [
  { id: "project_inbox", name: "Inbox" },
  { id: "project_q3", name: "Q3 planning" },
  { id: "project_onboarding", name: "Onboarding drop-off" },
];

const TAGS: NamedEntity[] = [
  { id: "tag_writing", name: "writing" },
  { id: "tag_deep", name: "deep-work" },
  { id: "tag_errand", name: "errand" },
  { id: "tag_home", name: "home" },
];

const NAMES: ConflictNames = { projects: PROJECTS, tags: TAGS };

function entry(overrides: Partial<PendingClassificationChange> = {}): PendingClassificationChange {
  return {
    taskId: "task_47",
    accountId: "acct_1",
    serverUrl: "https://bb.example.com",
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

const SERVER: ConflictServerState = {
  projectId: "project_onboarding",
  tagIds: [],
  revision: 5,
};

function conflictView(overrides: Partial<ConflictViewInput> = {}) {
  return buildConflictView({
    entry: entry(),
    server: SERVER,
    reason: "stale-revision",
    names: NAMES,
    deviceObservedAt: OBSERVED_AT,
    now: NOW,
    correlationId: "4f2a91c0-8e7b",
    ...overrides,
  });
}

/** Narrows, and fails loudly rather than silently skipping every assertion. */
function prompt(view: ReturnType<typeof buildConflictView>): ConflictPromptView {
  if (view.kind !== "prompt") {
    throw new Error(`expected a prompt, got ${view.kind} (${view.reason})`);
  }
  return view;
}

const rowOf = (view: ConflictPromptView, section: number, key: string) => {
  const row = view.sections[section].rows.find((candidate) => candidate.key === key);
  if (!row) {
    throw new Error(`no ${key} row in section ${section}`);
  }
  return row;
};

// ---------------------------------------------------------------- M-04 default

describe("006-FR-010 M-04 names all three values, not two", () => {
  it("labels the started value as what the DEVICE last showed, never as server history", () => {
    const view = prompt(conflictView());

    expect(view.sections).toHaveLength(1);
    expect(view.sections[0].rows.map((row) => row.key)).toEqual(["device", "yours", "server"]);
    expect(rowOf(view, 0, "device").label).toBe("Your phone last showed");
    expect(rowOf(view, 0, "device").value).toBe("Inbox");
  });

  it("dates the device's value, so a stale cache cannot tell a confident false story", () => {
    const view = prompt(conflictView());

    expect(rowOf(view, 0, "device").note).toBe("as of 3 weeks ago");
    expect(rowOf(view, 0, "device").accessibilityLabel).toBe(
      "Your phone last showed: Inbox (as of 3 weeks ago)",
    );
  });

  it("claims no age when the device cannot say when it last read the task", () => {
    // The queue entry records no observation time, so an unsupplied one must not
    // be back-filled from `firstQueuedAt`: that would claim the phone's
    // knowledge is 14 minutes old when it may be three weeks old.
    const view = prompt(conflictView({ deviceObservedAt: null }));

    expect(rowOf(view, 0, "device").note).toBe(CONFLICT_COPY.deviceRowUndatedNote);
    expect(rowOf(view, 0, "device").note).not.toContain("ago");
  });

  it("names what the person set and what the server holds now", () => {
    const view = prompt(conflictView());

    expect(rowOf(view, 0, "yours")).toMatchObject({
      label: "You changed it to",
      value: "Q3 planning",
    });
    expect(rowOf(view, 0, "server")).toMatchObject({
      label: "Now on server",
      value: "Onboarding drop-off",
    });
  });

  it("says when the change was made, because no other surface ever said it was pending", () => {
    expect(prompt(conflictView()).title).toBe("You changed the project 14 minutes ago");
  });

  it("states that nothing has been discarded yet (SC-005)", () => {
    expect(prompt(conflictView()).body).toBe(CONFLICT_COPY.staleRevisionBody);
    expect(prompt(conflictView()).body).toContain("nothing has been discarded yet");
  });

  it("offers exactly two explicit choices, the person's own work first", () => {
    const view = prompt(conflictView());

    expect(view.buttons.map((button) => button.choice)).toEqual(["keep-mine", "discard"]);
    expect(view.buttons.map((button) => button.label)).toEqual([
      "Keep mine, replace theirs",
      "Discard mine, keep the server's",
    ]);
  });

  it("renders a cleared project as None rather than as an empty value", () => {
    const view = prompt(
      conflictView({
        entry: entry({ value: { projectId: null, tagIds: undefined } }),
      }),
    );

    expect(rowOf(view, 0, "yours").value).toBe("None");
  });

  it("says so when the device holds the id but not the name", () => {
    const view = prompt(conflictView({ names: { projects: null, tags: null } }));

    expect(rowOf(view, 0, "device").value).toBe(CONFLICT_COPY.unnamedProject);
    expect(rowOf(view, 0, "server").value).toBe(CONFLICT_COPY.unnamedProject);
  });
});

// -------------------------------------------------- M-04 Tags and both fields

describe("006-FR-002 M-04 Tags conflict", () => {
  const tagsEntry = entry({
    value: { projectId: undefined, tagIds: ["tag_deep", "tag_writing"] },
    originalValue: { projectId: "project_inbox", tagIds: ["tag_writing"] },
  });
  const tagsServer: ConflictServerState = {
    projectId: "project_inbox",
    tagIds: ["tag_errand", "tag_writing"],
    revision: 5,
  };

  it("gives the Tag change its own three-row diff", () => {
    const view = prompt(conflictView({ entry: tagsEntry, server: tagsServer }));

    expect(view.sections).toHaveLength(1);
    expect(view.sections[0].field).toBe("tags");
    expect(view.sections[0].rows.map((row) => row.value)).toEqual([
      "writing",
      "deep-work, writing",
      "errand, writing",
    ]);
  });

  it("agrees grammatically with a set", () => {
    const view = prompt(conflictView({ entry: tagsEntry, server: tagsServer }));

    expect(rowOf(view, 0, "yours").label).toBe("You changed them to");
  });

  it("titles the sheet with the Tag change and its age", () => {
    expect(prompt(conflictView({ entry: tagsEntry, server: tagsServer })).title).toBe(
      "You changed the Tags 14 minutes ago",
    );
  });

  it("names an emptied set rather than showing a blank row", () => {
    const view = prompt(
      conflictView({
        entry: entry({
          value: { projectId: undefined, tagIds: [] },
          originalValue: { projectId: null, tagIds: ["tag_home"] },
        }),
        server: { projectId: null, tagIds: ["tag_home"], revision: 5 },
      }),
    );

    expect(rowOf(view, 0, "yours").value).toBe("No Tags");
  });

  it("counts the Tags it cannot name instead of listing blanks", () => {
    const view = prompt(
      conflictView({
        entry: entry({
          value: { projectId: undefined, tagIds: ["tag_writing", "tag_unknown", "tag_other"] },
          originalValue: { projectId: null, tagIds: [] },
        }),
        server: { projectId: null, tagIds: [], revision: 5 },
      }),
    );

    expect(rowOf(view, 0, "yours").value).toBe("writing, and 2 more this phone can't name yet");
  });

  it("uses the term Tag and never Context (FR-013)", () => {
    const serialized = JSON.stringify(conflictView({ entry: tagsEntry, server: tagsServer }));

    expect(serialized).toContain("Tags");
    expect(serialized).not.toMatch(/context/i);
  });
});

describe("006-FR-010 M-04 both fields changed", () => {
  const bothEntry = entry({
    value: { projectId: "project_q3", tagIds: ["tag_deep"] },
    originalValue: { projectId: "project_inbox", tagIds: ["tag_writing"] },
  });
  const bothServer: ConflictServerState = {
    projectId: "project_onboarding",
    tagIds: ["tag_errand"],
    revision: 5,
  };

  it("stacks one section per changed field, each with its own three rows", () => {
    const view = prompt(conflictView({ entry: bothEntry, server: bothServer }));

    expect(view.sections.map((section) => section.field)).toEqual(["project", "tags"]);
    for (const section of view.sections) {
      expect(section.rows.map((row) => row.key)).toEqual(["device", "yours", "server"]);
    }
  });

  it("gives each field its own heading line, so neither diff is unlabelled", () => {
    const view = prompt(conflictView({ entry: bothEntry, server: bothServer }));

    expect(view.sections.map((section) => section.heading)).toEqual([
      "You changed the project 14 minutes ago",
      "You changed the Tags 14 minutes ago",
    ]);
  });

  it("does not repeat a field's sentence as both the title and its heading", () => {
    // One changed field: the title already is that sentence.
    expect(prompt(conflictView()).sections[0].heading).toBeNull();
    expect(prompt(conflictView({ entry: bothEntry, server: bothServer })).title).toBe(
      CONFLICT_COPY.multiFieldTitle,
    );
  });

  it("never lays three Tag sets out side by side — the rows are vertical, always three", () => {
    const view = prompt(conflictView({ entry: bothEntry, server: bothServer }));
    const tags = view.sections[1];

    expect(tags.rows).toHaveLength(3);
    expect(tags.rows.map((row) => row.value)).toEqual(["writing", "deep-work", "errand"]);
  });
});

// ----------------------------------------------------- M-04 device far behind

describe("006-SC-005 M-04 the device was far behind", () => {
  it("says the task changed more than once when the revision gap exceeds one", () => {
    const view = prompt(conflictView({ server: { ...SERVER, revision: 7 } }));

    expect(view.multiChangeNotice).toBe(
      "This task has changed more than once since your phone last saw it.",
    );
  });

  it("stays silent on a single intervening change, which is the ordinary case", () => {
    expect(prompt(conflictView({ server: { ...SERVER, revision: 5 } })).multiChangeNotice).toBeNull();
  });

  it("claims nothing about how far behind the device is when the server state is unknown", () => {
    expect(prompt(conflictView({ server: null, reason: "target-missing" })).multiChangeNotice).toBeNull();
  });
});

// --------------------------------------------------------- M-04 already applied

describe("006-FR-017 M-04 already applied", () => {
  it("puts no prompt to the person when the server already holds what the entry intended", () => {
    const view = conflictView({
      server: { projectId: "project_q3", tagIds: [], revision: 9 },
    });

    expect(view.kind).toBe("no-prompt");
    expect(view.reason).toBe("already-applied");
  });

  it("compares Tags as a set, so a reordered set is still already applied", () => {
    const view = conflictView({
      entry: entry({
        value: { projectId: undefined, tagIds: ["tag_writing", "tag_deep"] },
      }),
      server: { projectId: "project_inbox", tagIds: ["tag_deep", "tag_writing"], revision: 9 },
    });

    expect(view.kind).toBe("no-prompt");
  });

  it("prefers what the server actually holds over the reason the drain reported", () => {
    const view = conflictView({
      reason: "stale-revision",
      server: { projectId: "project_q3", tagIds: [], revision: 9 },
    });

    expect(view.kind).toBe("no-prompt");
  });

  it("puts no prompt up for an entry that changed nothing", () => {
    const view = conflictView({
      entry: entry({ value: { projectId: undefined, tagIds: undefined } }),
    });

    expect(view).toEqual({ kind: "no-prompt", reason: "nothing-changed" });
  });
});

// ------------------------------------------------------------- M-04 in flight

describe("006-FR-008 M-04 while the resolution is being sent", () => {
  const sending = conflictView({ resolution: { status: "sending", choice: "keep-mine" } });

  it("shows progress on the chosen button", () => {
    const view = prompt(sending);

    expect(view.buttons[0]).toMatchObject({ choice: "keep-mine", busy: true, disabled: true });
  });

  it("disables the other choice rather than hiding it, so a double tap cannot start a second resolution", () => {
    const view = prompt(sending);

    expect(view.buttons).toHaveLength(2);
    expect(view.buttons[1]).toMatchObject({ choice: "discard", busy: false, disabled: true });
    // Disabled is not communicated by colour alone: the button says why.
    expect(view.buttons[1].reason).toBe(CONFLICT_COPY.waitingOnChoice);
  });

  it("re-enables both only when the attempt errors", () => {
    const view = prompt(
      conflictView({ resolution: { status: "failed", choice: "keep-mine" } }),
    );

    expect(view.buttons.map((button) => button.disabled)).toEqual([false, false]);
    expect(view.buttons.map((button) => button.busy)).toEqual([false, false]);
  });
});

describe("006-FR-012 M-04 the resolution itself failed", () => {
  const failed = conflictView({
    resolution: { status: "failed", choice: "discard", correlationId: "9b31de40-1122" },
  });

  it("keeps the sheet open with nothing discarded, and offers the retry", () => {
    const view = prompt(failed);

    expect(view.error?.text).toBe(CONFLICT_COPY.resolutionFailed);
    expect(view.error?.text).toContain("Nothing has been discarded");
    expect(view.buttons.every((button) => !button.disabled)).toBe(true);
  });

  it("carries the correlation id of the failed attempt, preferring it over the rejection's", () => {
    expect(prompt(failed).correlationLine).toBe("correlation id 9b31de40-1122");
  });

  it("carries the rejection's correlation id even when nothing has failed since", () => {
    expect(prompt(conflictView()).correlationLine).toBe("correlation id 4f2a91c0-8e7b");
  });

  it("invents no reference when the client never captured one", () => {
    expect(prompt(conflictView({ correlationId: undefined })).correlationLine).toBeNull();
  });
});

// -------------------------------------------------------- M-04 several tasks

describe("006-FR-008 M-04 several conflicted tasks", () => {
  it("shows which of the queued sheets this is", () => {
    expect(prompt(conflictView({ index: 1, total: 3 })).progressLabel).toBe("1 of 3");
  });

  it("says nothing about a queue of one", () => {
    expect(prompt(conflictView({ index: 1, total: 1 })).progressLabel).toBeNull();
  });
});

// ------------------------------------------------------- M-04 target missing

describe("006-FR-008 M-04 the target was deleted elsewhere", () => {
  const missing = conflictView({ reason: "target-missing", server: null });

  it("offers only Discard — replacing theirs is meaningless when the target is gone", () => {
    const view = prompt(missing);

    expect(view.buttons.map((button) => button.choice)).toEqual(["discard"]);
    expect(view.buttons[0].label).toBe("Discard my change");
  });

  it("still names what was changed and when, because no other surface ever did", () => {
    const view = prompt(missing);

    expect(view.sections[0].heading).toBe("You changed the project 14 minutes ago");
    expect(view.sections[0].rows.map((row) => row.key)).toEqual(["device", "yours"]);
  });

  it("names which target is gone when the rejection said", () => {
    expect(prompt(conflictView({ reason: "target-missing", server: null, missingTarget: "project" })).body).toBe(
      CONFLICT_COPY.missingProjectBody,
    );
    expect(prompt(conflictView({ reason: "target-missing", server: null, missingTarget: "task" })).body).toBe(
      CONFLICT_COPY.missingTaskBody,
    );
    expect(prompt(missing).body).toBe(CONFLICT_COPY.missingUnknownBody);
  });

  it("drops the server row rather than inventing a value for a target that is gone", () => {
    const view = prompt(missing);

    expect(view.sections[0].rows.some((row) => row.key === "server")).toBe(false);
  });
});

// ------------------------------------------------ M-04 focus, escape, dismiss

describe("006-SC-005 M-04 focus and dismissal", () => {
  it("focuses the heading, so no destructive action is one keypress from a confirm", () => {
    expect(prompt(conflictView()).initialFocus).toBe("heading");
  });

  it("makes Escape a dismissal and never a resolution", () => {
    const view = prompt(conflictView());

    expect(view.escapeAction).toBe("dismiss");
    expect(["keep-mine", "discard"]).not.toContain(view.escapeAction);
  });

  it("decides nothing on its own when the connection drops with the sheet open", () => {
    // Offline is not an input: the view is a function of the entry and the last
    // server answer, so losing the connection cannot change what it offers.
    expect(prompt(conflictView())).toEqual(prompt(conflictView()));
  });
});

// -------------------------------------------------------------- M-05 default

function discardView(overrides: Partial<DiscardUnsentViewInput> = {}) {
  return buildDiscardUnsentView({
    queue: [entry({ sendState: "queued" }), entry({ taskId: "task_48", sendState: "queued" })],
    trigger: "sign-out",
    online: true,
    ...overrides,
  });
}

function discardPrompt(
  view: ReturnType<typeof buildDiscardUnsentView>,
): DiscardUnsentPromptView {
  if (view.kind !== "prompt") {
    throw new Error(`expected a prompt, got ${view.kind} (${view.reason})`);
  }
  return view;
}

describe("006-FR-011 M-05 the count, and only the count", () => {
  it("states how many changes have not been sent", () => {
    const view = discardPrompt(discardView());

    expect(view.count).toBe(2);
    expect(view.title).toBe("2 changes have not been sent");
  });

  it("reads as one change rather than as a count of one", () => {
    const view = discardPrompt(discardView({ queue: [entry({ sendState: "queued" })] }));

    expect(view.title).toBe("1 change has not been sent");
    expect(view.discard.label).toBe("Discard 1 change and continue");
    expect(view.stay.label).toBe("Stay and let it send");
  });

  it("never names the changes — the count is the whole of what the person is told", () => {
    // The sign-off decision, recorded in design.md, and the reason this is a
    // test rather than a comment: adding a list later would be a quiet reversal
    // of a human decision.
    const serialized = JSON.stringify(discardView());

    for (const identifier of ["task_47", "task_48", "project_q3", "project_inbox", "key-1"]) {
      expect(serialized).not.toContain(identifier);
    }
  });

  it("says which action discards them, and that it cannot be undone", () => {
    expect(discardPrompt(discardView()).body).toBe(DISCARD_COPY.body("sign-out", 2));
    expect(discardPrompt(discardView()).body).toContain("This cannot be undone.");
    expect(discardPrompt(discardView({ trigger: "server-change" })).body).toContain(
      "Switching server discards them",
    );
    expect(discardPrompt(discardView({ trigger: "account-change" })).body).toContain(
      "Switching account discards them",
    );
  });

  it("puts the non-destructive choice first and marks only the discard destructive", () => {
    const view = discardPrompt(discardView());

    expect(view.stay.action).toBe("stay");
    expect(view.stay.variant).toBe("secondary");
    expect(view.discard.variant).toBe("destructive");
  });
});

describe("006-FR-011 M-05 the count is live", () => {
  it("decrements as the queue drains rather than showing a stale number", () => {
    const before = discardPrompt(discardView());
    const after = discardPrompt(discardView({ queue: [entry({ sendState: "queued" })] }));

    expect(before.count).toBe(2);
    expect(after.count).toBe(1);
  });

  it("counts only the still-unsent, so a partly drained queue is reported honestly", () => {
    const states: SendState[] = ["queued", "sending", "conflicted", "expired"];
    const queue = states.map((sendState, index) =>
      entry({ taskId: `task_${index}`, sendState }),
    );

    // `expired` is not unsent work — FR-018 already discarded it, and the M-01
    // notice is what says so. Counting it here would warn twice about one loss.
    expect(countUnsent(queue)).toBe(3);
  });

  it("never appears on an empty queue: the action simply proceeds", () => {
    expect(buildDiscardUnsentView({ queue: [], trigger: "sign-out", online: true })).toEqual({
      kind: "no-prompt",
      reason: "queue-empty",
      proceed: true,
    });
  });

  it("never appears when everything left has already expired", () => {
    const view = discardPrompt.bind(null, discardView({ queue: [entry({ sendState: "expired" })] }));

    expect(view).toThrow(/no-prompt/);
  });
});

describe("006-FR-011 M-05 discard is blocked while a send is in flight", () => {
  const inFlight = discardView({
    queue: [entry({ sendState: "sending" }), entry({ taskId: "task_48", sendState: "queued" })],
  });

  it("disables the discard, because updateTask takes no AbortSignal and cannot be called back", () => {
    const view = discardPrompt(inFlight);

    expect(view.discard.disabled).toBe(true);
  });

  it("states the reason in text, never by colour alone", () => {
    const view = discardPrompt(inFlight);

    expect(view.discard.reason).toBe(DISCARD_COPY.discardBlockedSending(1));
    expect(view.discard.reason).toContain("can't be called back");
  });

  it("leaves the discard available the moment nothing is in flight", () => {
    const view = discardPrompt(discardView());

    expect(view.discard.disabled).toBe(false);
    expect(view.discard.reason).toBeNull();
  });
});

describe("006-FR-006 M-05 offline", () => {
  it("disables 'Stay and let them send' with its reason in text", () => {
    const view = discardPrompt(discardView({ online: false }));

    expect(view.stay.disabled).toBe(true);
    expect(view.stay.reason).toBe("Nothing can be sent without a connection");
  });

  it("leaves discarding available offline", () => {
    const view = discardPrompt(discardView({ online: false }));

    expect(view.discard.disabled).toBe(false);
  });

  it("keeps staying available when something is genuinely in flight, so the sheet is never a dead end", () => {
    // Offline plus an in-flight send would otherwise disable both choices at
    // once: the discard because the request cannot be called back, the stay
    // because nothing can be sent. Something *is* being sent, so the stay's
    // stated reason is simply not true here.
    const view = discardPrompt(
      discardView({ online: false, queue: [entry({ sendState: "sending" })] }),
    );

    expect(view.stay.disabled).toBe(false);
    expect(view.discard.disabled).toBe(true);
  });
});

describe("006-FR-012 M-05 the drain failed while the person was deciding", () => {
  const failed = discardView({
    error: { message: "We couldn't reach the server.", correlationId: "77c1aa20-3f5e" },
  });

  it("keeps the count and lets the person still choose", () => {
    const view = discardPrompt(failed);

    expect(view.count).toBe(2);
    expect(view.discard.disabled).toBe(false);
    expect(view.stay.disabled).toBe(false);
  });

  it("carries the correlation id of the failure, and the server's own words with it", () => {
    const view = discardPrompt(failed);

    expect(view.error?.text).toBe(DISCARD_COPY.drainFailed);
    expect(view.error?.detail).toBe("We couldn't reach the server.");
    expect(view.correlationLine).toBe("correlation id 77c1aa20-3f5e");
  });

  it("still says something actionable when the failure carried no message", () => {
    const view = discardPrompt(discardView({ error: { correlationId: "abc" } }));

    expect(view.error?.text).toBe(DISCARD_COPY.drainFailed);
    expect(view.error?.detail).toBeNull();
  });
});

describe("006-SC-007 M-05 focus and escape", () => {
  it("focuses the heading rather than either button", () => {
    expect(discardPrompt(discardView()).initialFocus).toBe("heading");
  });

  it("makes Escape cancel the identity transition, never the discard", () => {
    const view = discardPrompt(discardView());

    expect(view.escapeAction).toBe("cancel");
  });

  it("keeps Escape non-destructive even when the stay button is disabled offline", () => {
    expect(discardPrompt(discardView({ online: false })).escapeAction).toBe("cancel");
  });

  it("uses the term Tag and never Context (FR-013)", () => {
    expect(JSON.stringify(discardView())).not.toMatch(/context/i);
  });
});

// ------------------------------------------------------------------ the clock

describe("006-FR-010 relative ages are read from an argument, never from the clock", () => {
  it.each([
    ["2026-08-11T09:40:31.000Z", "just now"],
    ["2026-08-11T09:40:00.000Z", "1 minute ago"],
    ["2026-08-11T09:27:00.000Z", "14 minutes ago"],
    ["2026-08-11T08:41:00.000Z", "1 hour ago"],
    ["2026-08-11T00:41:00.000Z", "9 hours ago"],
    ["2026-08-10T09:41:00.000Z", "1 day ago"],
    ["2026-08-06T09:41:00.000Z", "5 days ago"],
    ["2026-08-04T09:41:00.000Z", "1 week ago"],
    ["2026-07-21T09:41:00.000Z", "3 weeks ago"],
  ])("reads %s as %s", (instant, expected) => {
    expect(formatAge(instant, NOW)).toBe(expected);
  });

  it("clamps a device clock that ran ahead rather than saying 'in 3 hours'", () => {
    expect(formatAge("2026-08-11T12:41:00.000Z", NOW)).toBe("just now");
  });

  it("returns null rather than inventing an age for an unparsable timestamp", () => {
    expect(formatAge("not-a-date", NOW)).toBeNull();
  });

  it("claims no age before the screen has a clock, rather than defaulting to now", () => {
    // React's purity rule forbids reading the clock during render, so a sheet
    // has none until its first effect runs. `just now` against a change made
    // three weeks ago is exactly the false story M-04 exists to prevent.
    expect(formatAge(CHANGED_AT, null)).toBeNull();

    const view = prompt(conflictView({ now: null }));

    expect(view.title).toBe("You changed the project");
    expect(rowOf(view, 0, "device").note).toBe(CONFLICT_COPY.deviceRowUndatedNote);
  });

  it("drops the age from the title rather than the fact of the change", () => {
    const view = prompt(conflictView({ entry: entry({ lastEditedAt: "not-a-date" }) }));

    expect(view.title).toBe("You changed the project");
  });
});
