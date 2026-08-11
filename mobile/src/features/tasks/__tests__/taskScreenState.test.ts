/**
 * M-01 / M-01b / M-01c as data — feature 006, T046, T047, T051, T063–T066.
 *
 * `mobile/` installs no React renderer, so a rule that lives inside
 * `app/task/[id].tsx` has no evidence at all. Every decision the task screen
 * takes therefore lives in `taskScreenState.ts` and is asserted here; the
 * screen itself renders what these functions return and holds no rule of its
 * own. No coverage is claimed for the rendering.
 *
 * `now` is always an argument (plan.md's clock rule for this feature), so every
 * boundary below is exact rather than flaky.
 */

import type { PendingClassificationChange } from "../classificationTypes";
import {
  ACCOUNT_EXPIRY_DISMISS_LABEL,
  CACHED_LIST_REVISION,
  DUE_ROW_PLACEHOLDER,
  EXPIRY_DISMISS_LABEL,
  PROJECT_ROW_PLACEHOLDER,
  TAGS_ROW_PLACEHOLDER,
  UNNAMED_PROJECT,
  UNNAMED_TAGS,
  attachedEntities,
  buildClassificationEdit,
  buildExpiredNotice,
  buildLastSyncedFooter,
  buildMetadataChips,
  buildMetadataRows,
  accountNoticeKey,
  hasDismissedAccountNotice,
  performIdentityTransition,
  planIdentityTransition,
  rememberAccountNoticeDismissed,
  resetAccountNoticeDismissals,
  resolveAccountExpiryNotice,
  resolveClassificationSurface,
  resolveIdentity,
  resolveListPhase,
  resolveOnline,
  servedFromCache,
  shouldAnnounceLastSynced,
  type MetadataInput,
  type SessionStatusLike,
} from "../taskScreenState";
import { describeExpiredChange, effectiveClassification } from "../useClassificationQueue";

/**
 * `useClassificationQueue` reaches AsyncStorage transitively, and the two
 * helpers borrowed from it here are the real ones on purpose: the notice this
 * file asserts must be built from the payload the queue actually produces, not
 * from a hand-written stand-in that could drift away from it.
 */
jest.mock("@react-native-async-storage/async-storage", () => {
  const store = new Map<string, string>();
  return {
    __esModule: true,
    default: {
      getItem: jest.fn(async (key: string) => store.get(key) ?? null),
      setItem: jest.fn(async (key: string, value: string) => {
        store.set(key, value);
      }),
      removeItem: jest.fn(async (key: string) => {
        store.delete(key);
      }),
      multiSet: jest.fn(async () => undefined),
      multiRemove: jest.fn(async () => undefined),
      getAllKeys: jest.fn(async () => Array.from(store.keys())),
      clear: jest.fn(async () => {
        store.clear();
      }),
    },
  };
});

const NOW = Date.parse("2026-08-11T12:00:00.000Z");
const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

const ago = (milliseconds: number): string => new Date(NOW - milliseconds).toISOString();

/** A metadata input with nothing set; each case overrides only what it is about. */
const emptyMetadata: MetadataInput = {
  projectId: null,
  projectName: undefined,
  tagIds: [],
  tagNames: [],
  dueLabel: null,
  priority: "none",
};

const classified: MetadataInput = {
  projectId: "p1",
  projectName: "Onboarding drop-off",
  tagIds: ["t1", "t2"],
  tagNames: ["deep-work", "writing"],
  dueLabel: "before Fri",
  priority: "medium",
};

function rowById(input: MetadataInput, id: "project" | "tags" | "due" | "priority") {
  const row = buildMetadataRows(input).find((candidate) => candidate.id === id);
  if (!row) {
    throw new Error(`no ${id} row`);
  }
  return row;
}

function entry(overrides: Partial<PendingClassificationChange> = {}): PendingClassificationChange {
  return {
    taskId: "task-1",
    accountId: "acc-1",
    serverUrl: "https://api.example.test/api",
    value: { projectId: "p9", tagIds: undefined },
    observedRevision: 4,
    originalValue: { projectId: "p1", tagIds: ["t1"] },
    firstQueuedAt: ago(31 * DAY),
    lastEditedAt: ago(31 * DAY),
    idempotencyKey: "key-1",
    sendState: "queued",
    ...overrides,
  };
}

// --------------------------------------------------------------- T046 the rows

describe("006-FR-001 the Project row is present with a muted placeholder when unset", () => {
  it("006-FR-001 shows the placeholder rather than hiding the row", () => {
    const row = rowById(emptyMetadata, "project");
    expect(row.value).toBe(PROJECT_ROW_PLACEHOLDER);
    expect(row.placeholder).toBe(true);
    expect(row.pills).toEqual([]);
  });

  it("006-FR-001 shows the project as a pill and as the row's own value once set", () => {
    const row = rowById(classified, "project");
    expect(row.placeholder).toBe(false);
    expect(row.value).toBe("Onboarding drop-off");
    expect(row.pills).toEqual(["Onboarding drop-off"]);
  });

  it("006-FR-001 says so rather than showing a blank row when the id has no name", () => {
    // Offline, never cached: the device holds the id and cannot resolve it.
    const row = rowById({ ...emptyMetadata, projectId: "p1" }, "project");
    expect(row.value).toBe(UNNAMED_PROJECT);
    expect(row.placeholder).toBe(false);
  });
});

describe("006-FR-002 the Tags row is present with a muted placeholder when unset", () => {
  it("006-FR-002 shows the placeholder rather than hiding the row", () => {
    const row = rowById(emptyMetadata, "tags");
    expect(row.value).toBe(TAGS_ROW_PLACEHOLDER);
    expect(row.placeholder).toBe(true);
  });

  it("006-FR-002 lists every attached Tag as its own pill", () => {
    expect(rowById(classified, "tags").pills).toEqual(["deep-work", "writing"]);
  });

  it("006-FR-002 counts the Tags it cannot name instead of dropping them silently", () => {
    const row = rowById(
      { ...emptyMetadata, tagIds: ["t1", "t2", "t3"], tagNames: ["deep-work"] },
      "tags",
    );
    expect(row.pills).toEqual(["deep-work"]);
    expect(row.value).toBe("deep-work +2");
  });

  it("006-FR-002 says a connection is needed when it can name none of them", () => {
    const row = rowById({ ...emptyMetadata, tagIds: ["t1"], tagNames: [] }, "tags");
    expect(row.value).toBe(UNNAMED_TAGS);
    expect(row.placeholder).toBe(false);
  });
});

describe("006-FR-001 all four rows are always present, in M-01's order", () => {
  it("006-FR-001 draws Project, Tags, Due and Priority even with nothing set", () => {
    expect(buildMetadataRows(emptyMetadata).map((row) => row.id)).toEqual([
      "project",
      "tags",
      "due",
      "priority",
    ]);
  });

  it("006-FR-001 places the muted placeholder on Due and Priority too", () => {
    expect(rowById(emptyMetadata, "due")).toMatchObject({
      value: DUE_ROW_PLACEHOLDER,
      placeholder: true,
    });
    // "None" is a real priority value, so it is shown — muted, because it is
    // the unset one.
    expect(rowById(emptyMetadata, "priority")).toMatchObject({
      value: "None",
      placeholder: true,
    });
  });

  it("006-FR-001 gives every row an accessible name carrying its value", () => {
    // design.md: the chevron is decorative and hidden from assistive tech; the
    // row itself carries the name and the current value.
    expect(rowById(classified, "project").accessibilityLabel).toBe(
      "Project, Onboarding drop-off",
    );
    expect(rowById(classified, "tags").accessibilityLabel).toBe("Tags, deep-work, writing");
    expect(rowById(emptyMetadata, "project").accessibilityLabel).toBe("Project, none set");
    expect(rowById(emptyMetadata, "tags").accessibilityLabel).toBe("Tags, none set");
  });
});

describe("006-FR-013 the vocabulary is Tag, never Context", () => {
  it("006-FR-013 uses Tag in every string this module can produce for the Tags row", () => {
    const strings = [
      TAGS_ROW_PLACEHOLDER,
      UNNAMED_TAGS,
      rowById(emptyMetadata, "tags").label,
      rowById(emptyMetadata, "tags").accessibilityLabel,
    ].join(" ");
    expect(strings).not.toMatch(/context/i);
    expect(TAGS_ROW_PLACEHOLDER).toMatch(/Tags/);
  });
});

// ------------------------------------------------- T047 the flag-OFF fallback

describe("006-FR-015 with the flag OFF the screen keeps today's chip presentation", () => {
  const chips = (input: MetadataInput, openTask: boolean) =>
    buildMetadataChips({ ...input, openTask, stateLabel: "Completed" });

  it("006-FR-015 draws today's chips, not rows, for a classified open task", () => {
    expect(chips(classified, true)).toEqual([
      {
        key: "due",
        kind: "due",
        label: "before Fri",
        accessibilityLabel: "Change due date",
        disabled: false,
      },
      {
        key: "priority",
        kind: "priority",
        label: "Medium",
        priority: "medium",
        accessibilityLabel: "Change priority",
        disabled: false,
      },
      { key: "tag:deep-work", kind: "tag", label: "deep-work" },
      { key: "tag:writing", kind: "tag", label: "writing" },
      { key: "project", kind: "project", label: "Onboarding drop-off" },
    ]);
  });

  it("006-FR-015 offers today's add-affordances when the values are unset", () => {
    expect(chips(emptyMetadata, true)).toEqual([
      { key: "due", kind: "add-due", label: "Add date", accessibilityLabel: "Add due date" },
      {
        key: "priority",
        kind: "add-priority",
        label: "Priority",
        accessibilityLabel: "Set priority",
      },
    ]);
  });

  it("006-FR-015 omits unset chips entirely on a closed task and names the state", () => {
    // Today's screen exactly: no empty rows, no disabled add affordances.
    expect(chips(emptyMetadata, false)).toEqual([
      { key: "state", kind: "state", label: "Completed" },
    ]);
  });

  it("006-FR-015 keeps set chips visible but disabled on a closed task", () => {
    const result = chips(classified, false);
    expect(result[0]).toMatchObject({ kind: "due", disabled: true });
    expect(result[1]).toMatchObject({ kind: "priority", disabled: true });
    expect(result[result.length - 1]).toEqual({
      key: "state",
      kind: "state",
      label: "Completed",
    });
  });

  it("006-FR-015 shows no project chip when the device cannot name it", () => {
    // Parity with today's screen, which renders `projectName(id)` and so shows
    // nothing at all when the name is unresolved.
    const result = chips({ ...emptyMetadata, projectId: "p1" }, true);
    expect(result.some((chip) => chip.kind === "project")).toBe(false);
  });
});

// --------------------------------------------------- FR-007, no marker at all

describe("006-FR-007 a queued value is presented exactly like a delivered one", () => {
  const server = { projectId: "p1", tagIds: ["t1"] };

  it("006-FR-007 builds identical rows whether the value came from the queue or the server", () => {
    const queued = effectiveClassification(server, entry({ value: { projectId: "p9", tagIds: undefined } }));
    const delivered = effectiveClassification({ projectId: "p9", tagIds: ["t1"] }, undefined);
    expect(queued).toEqual(delivered);

    const names = { p9: "Q3 planning" } as Record<string, string>;
    const toInput = (state: { projectId: string | null; tagIds: string[] }): MetadataInput => ({
      projectId: state.projectId,
      projectName: state.projectId ? names[state.projectId] : undefined,
      tagIds: state.tagIds,
      tagNames: ["deep-work"],
      dueLabel: "before Fri",
      priority: "none",
    });
    expect(buildMetadataRows(toInput(queued))).toEqual(buildMetadataRows(toInput(delivered)));
  });

  it("006-FR-007 exposes no per-change marker on any row", () => {
    for (const row of buildMetadataRows(classified)) {
      expect(Object.keys(row).join(",")).not.toMatch(/pending|unsent|dirty|queued|sync/i);
    }
  });
});

// ------------------------------------------------------------ T051 the footer

describe("006-SC-004 the last-synced footer is words, and announces only on material change", () => {
  it("006-SC-004 reads as the design's own example", () => {
    expect(buildLastSyncedFooter(ago(14 * MINUTE), NOW).label).toBe("Last synced 14 minutes ago");
  });

  it("006-SC-004 says so rather than inventing an age before the first sync", () => {
    expect(buildLastSyncedFooter(null, NOW).label).toBe("Not synced yet");
  });

  it("006-SC-004 carries the whole footer as its accessible name", () => {
    const footer = buildLastSyncedFooter(ago(14 * MINUTE), NOW);
    expect(footer.accessibilityLabel).toBe("Last synced 14 minutes ago");
    expect(footer.bucket).toBe("minutes");
  });

  it("006-SC-004 never announces on first paint — the footer is read with the screen", () => {
    expect(shouldAnnounceLastSynced(null, buildLastSyncedFooter(ago(14 * MINUTE), NOW))).toBe(
      false,
    );
  });

  it("006-SC-004 stays silent across a tick that does not change the words", () => {
    const before = buildLastSyncedFooter(ago(14 * MINUTE), NOW);
    const after = buildLastSyncedFooter(ago(14 * MINUTE), NOW + 30_000);
    expect(after.label).toBe(before.label);
    expect(shouldAnnounceLastSynced(before, after)).toBe(false);
  });

  it("006-SC-004 announces when the words change, in the same bucket or across one", () => {
    const before = buildLastSyncedFooter(ago(14 * MINUTE), NOW);
    expect(shouldAnnounceLastSynced(before, buildLastSyncedFooter(ago(15 * MINUTE), NOW))).toBe(
      true,
    );
    expect(shouldAnnounceLastSynced(before, buildLastSyncedFooter(ago(2 * HOUR), NOW))).toBe(true);
  });

  it("006-FR-007 says nothing about individual changes", () => {
    for (const elapsed of [0, MINUTE, HOUR, 40 * DAY]) {
      expect(buildLastSyncedFooter(ago(elapsed), NOW).label).not.toMatch(
        /unsent|pending|change/i,
      );
    }
  });
});

// ---------------------------------------------------- T065 the per-task notice

describe("006-FR-018 the expired-change notice names the field and what it reverted to", () => {
  const names = {
    project: (id: string | null) => (id === "p1" ? "Onboarding drop-off" : undefined),
    tags: (ids: readonly string[]) =>
      ids.map((id) => (id === "t1" ? "deep-work" : "writing")).filter(Boolean),
  };

  const noticeFor = (
    overrides: Partial<PendingClassificationChange>,
    server: { projectId: string | null; tagIds: string[] } | null = null,
  ) =>
    buildExpiredNotice(
      describeExpiredChange(entry({ sendState: "expired", ...overrides }), server),
      names,
      NOW,
    );

  it("006-SC-003 writes design.md's own sentence", () => {
    const view = noticeFor({}, { projectId: "p1", tagIds: [] });
    expect(view?.lines).toEqual([
      "Your change to Project from 31 days ago was not sent and has been discarded. " +
        "This now shows Onboarding drop-off.",
    ]);
  });

  it("006-FR-018 never reads as a count — a task holds at most one coalesced entry", () => {
    const view = noticeFor({}, { projectId: "p1", tagIds: [] });
    expect(view?.lines.join(" ")).not.toMatch(/\d+ changes?/);
  });

  it("006-FR-018 offers a labelled Dismiss button, never an icon alone", () => {
    expect(noticeFor({}, { projectId: "p1", tagIds: [] })?.dismissLabel).toBe("Dismiss");
    expect(EXPIRY_DISMISS_LABEL).toBe("Dismiss");
  });

  it("006-FR-018 anchors the notice to the row it explains, so Dismiss follows it", () => {
    expect(noticeFor({}, { projectId: "p1", tagIds: [] })?.anchor).toBe("project");
    expect(
      noticeFor(
        { value: { projectId: undefined, tagIds: ["t9"] } },
        { projectId: null, tagIds: ["t1"] },
      )?.anchor,
    ).toBe("tags");
    // A change that touched both anchors under the later of the two rows.
    expect(
      noticeFor(
        { value: { projectId: "p9", tagIds: ["t9"] } },
        { projectId: "p1", tagIds: ["t1"] },
      )?.anchor,
    ).toBe("tags");
  });

  it("006-FR-018 names a cleared project as no project rather than as nothing", () => {
    expect(noticeFor({}, { projectId: null, tagIds: [] })?.lines[0]).toContain(
      "This now shows no project.",
    );
  });

  it("006-FR-013 names Tags as Tags, and lists what the row now shows", () => {
    const view = noticeFor(
      { value: { projectId: undefined, tagIds: ["t9"] } },
      { projectId: null, tagIds: ["t1", "t2"] },
    );
    expect(view?.lines[0]).toBe(
      "Your change to Tags from 31 days ago was not sent and has been discarded. " +
        "This now shows deep-work and writing.",
    );
    expect(view?.lines.join(" ")).not.toMatch(/context/i);
  });

  it("006-FR-018 says no Tags when the row reverted to an empty set", () => {
    expect(
      noticeFor(
        { value: { projectId: undefined, tagIds: ["t9"] } },
        { projectId: null, tagIds: [] },
      )?.lines[0],
    ).toContain("This now shows no Tags.");
  });

  it("006-FR-018 drops the second sentence rather than naming a value it cannot resolve", () => {
    const view = noticeFor({}, { projectId: "unknown-project", tagIds: [] });
    expect(view?.lines).toEqual([
      "Your change to Project from 31 days ago was not sent and has been discarded.",
    ]);
  });

  it("006-FR-018 writes one line per changed field of the one entry", () => {
    const view = noticeFor(
      { value: { projectId: "p9", tagIds: ["t9"] } },
      { projectId: "p1", tagIds: ["t1"] },
    );
    expect(view?.lines).toHaveLength(2);
    expect(view?.accessibilityLabel).toBe(view?.lines.join(" "));
  });

  it.each<[string, number, string]>([
    ["the 30-day bound itself", 30 * DAY, "30 days ago"],
    ["design.md's 31 days", 31 * DAY, "31 days ago"],
    ["a single day, singular", DAY, "1 day ago"],
    ["hours, when a clock skew expired it early", 3 * HOUR, "3 hours ago"],
    ["a single hour, singular", HOUR, "1 hour ago"],
    ["less than an hour", 5 * MINUTE, "earlier today"],
  ])("006-FR-018 dates the change: %s", (_why, elapsed, expected) => {
    const view = noticeFor({ lastEditedAt: ago(elapsed) }, { projectId: "p1", tagIds: [] });
    expect(view?.lines[0]).toContain(`from ${expected} was not sent`);
  });

  it("006-FR-018 has nothing to show for an entry that has not expired", () => {
    expect(buildExpiredNotice(null, names, NOW)).toBeNull();
    expect(
      buildExpiredNotice(describeExpiredChange(entry(), null), names, NOW),
    ).toBeNull();
  });
});

// --------------------------------------------- T066 the account-level notice

describe("006-FR-018 the account-level notice tells the person the total, once", () => {
  beforeEach(() => resetAccountNoticeDismissals());

  it("006-FR-018 writes design.md's own sentence for several", () => {
    expect(
      resolveAccountExpiryNotice({ expiredTotal: 3, taskNoticeShown: false, dismissed: false }),
    ).toEqual({
      total: 3,
      message: "3 changes older than 30 days were not sent and have been discarded",
      dismissLabel: ACCOUNT_EXPIRY_DISMISS_LABEL,
    });
  });

  it("006-FR-018 agrees with itself for exactly one", () => {
    expect(
      resolveAccountExpiryNotice({ expiredTotal: 1, taskNoticeShown: false, dismissed: false })
        ?.message,
    ).toBe("1 change older than 30 days was not sent and has been discarded");
  });

  it("006-FR-018 shows nothing when the sweep dropped nothing", () => {
    expect(
      resolveAccountExpiryNotice({ expiredTotal: 0, taskNoticeShown: false, dismissed: false }),
    ).toBeNull();
  });

  it("006-FR-018 does not say the same thing twice on a screen already naming the only one", () => {
    expect(
      resolveAccountExpiryNotice({ expiredTotal: 1, taskNoticeShown: true, dismissed: false }),
    ).toBeNull();
    // With more than one, the rest are still unaccounted for and must be told.
    expect(
      resolveAccountExpiryNotice({ expiredTotal: 3, taskNoticeShown: true, dismissed: false })
        ?.total,
    ).toBe(3);
  });

  it("006-FR-018 stays dismissed once dismissed", () => {
    expect(
      resolveAccountExpiryNotice({ expiredTotal: 3, taskNoticeShown: false, dismissed: true }),
    ).toBeNull();
  });

  it("006-SC-007 remembers the dismissal per identity, never across identities", () => {
    const mine = accountNoticeKey({ serverUrl: "https://a.test/api", accountId: "acc-1" });
    const theirs = accountNoticeKey({ serverUrl: "https://a.test/api", accountId: "acc-2" });
    const otherServer = accountNoticeKey({ serverUrl: "https://b.test/api", accountId: "acc-1" });
    expect(hasDismissedAccountNotice(mine)).toBe(false);
    rememberAccountNoticeDismissed(mine);
    expect(hasDismissedAccountNotice(mine)).toBe(true);
    expect(hasDismissedAccountNotice(theirs)).toBe(false);
    expect(hasDismissedAccountNotice(otherServer)).toBe(false);
  });

  it("006-SC-007 has no key, and so no dismissal, with no identity", () => {
    expect(accountNoticeKey(null)).toBeNull();
    rememberAccountNoticeDismissed(null);
    expect(hasDismissedAccountNotice(null)).toBe(false);
  });
});

// ------------------------------------------- T063 / T064 identity transitions

describe("006-FR-011 a deliberate identity transition is gated on the discard warning", () => {
  it("006-FR-011 warns when there is unsent work, for both transitions", () => {
    const queue = [entry(), entry({ idempotencyKey: "key-2", taskId: "task-2" })];
    expect(planIdentityTransition(queue, "sign-out")).toEqual({
      kind: "sign-out",
      unsentCount: 2,
      needsWarning: true,
    });
    expect(planIdentityTransition(queue, "server-change").needsWarning).toBe(true);
  });

  it("006-FR-011 shows no sheet at all when the queue is empty — the action proceeds", () => {
    expect(planIdentityTransition([], "sign-out")).toEqual({
      kind: "sign-out",
      unsentCount: 0,
      needsWarning: false,
    });
  });

  it("006-FR-018 does not count an expired entry as unsent — it is already discarded", () => {
    const queue = [entry({ sendState: "expired" }), entry({ idempotencyKey: "k2" })];
    expect(planIdentityTransition(queue, "sign-out").unsentCount).toBe(1);
  });

  it("006-FR-011 counts an in-flight and a conflicted entry as still unsent", () => {
    const queue = [
      entry({ sendState: "sending" }),
      entry({ idempotencyKey: "k2", sendState: "conflicted" }),
    ];
    expect(planIdentityTransition(queue, "server-change").unsentCount).toBe(2);
  });

  it("006-FR-011 discards BEFORE the transition — clearing identity unnames the queue", () => {
    const order: string[] = [];
    return performIdentityTransition({
      discard: async () => {
        order.push("discard:start");
        await Promise.resolve();
        order.push("discard:end");
      },
      transition: async () => {
        order.push("transition:start");
      },
    }).then(() => {
      expect(order).toEqual(["discard:start", "discard:end", "transition:start"]);
    });
  });

  it("006-FR-011 does not transition when the discard failed", async () => {
    const transition = jest.fn(async () => {});
    await expect(
      performIdentityTransition({
        discard: async () => {
          throw new Error("storage unavailable");
        },
        transition,
      }),
    ).rejects.toThrow("storage unavailable");
    // Signing out anyway would strand the queue under a key nothing can name.
    expect(transition).not.toHaveBeenCalled();
  });
});

// -------------------------------------------- SC-009 the offline cold start

describe("006-SC-009 an offline cold start reaches a usable classification screen", () => {
  const base = {
    taskClassificationEnabled: true,
    accountId: "acc-1",
    serverUrl: "https://api.example.test/api",
    taskOpen: true,
  };

  it("006-SC-009 offers the rows with the flag and the identity read from the device", () => {
    // `signed-in-offline`: authenticated, no live profile. The flag came from
    // persisted flags and the account id from persisted identity, so the queue
    // key is nameable with no connection at all.
    expect(resolveClassificationSurface({ ...base, status: "signed-in-offline" })).toEqual({
      presentation: "rows",
      identity: { serverUrl: base.serverUrl, accountId: "acc-1" },
      queueEnabled: true,
      reason: "ok",
    });
  });

  it("006-SC-009 is the same surface as a live session — offline is not a lesser screen", () => {
    expect(resolveClassificationSurface({ ...base, status: "signed-in-offline" })).toEqual(
      resolveClassificationSurface({ ...base, status: "signed-in" }),
    );
  });

  it("006-FR-015 falls back to today's chips with the flag off, with no queue at all", () => {
    expect(
      resolveClassificationSurface({
        ...base,
        status: "signed-in-offline",
        taskClassificationEnabled: false,
      }),
    ).toEqual({ presentation: "chips", identity: null, queueEnabled: false, reason: "flag-off" });
  });

  it.each<[string, SessionStatusLike, string | null]>([
    ["still probing", "loading", "acc-1"],
    ["signed out", "signed-out", "acc-1"],
    ["signed in with no account id to name the key", "signed-in", null],
  ])("006-SC-007 offers no editable surface when %s", (_why, status, accountId) => {
    const surface = resolveClassificationSurface({ ...base, status, accountId });
    expect(surface.presentation).toBe("chips");
    expect(surface.identity).toBeNull();
    expect(surface.queueEnabled).toBe(false);
    expect(surface.reason).toBe("no-session");
  });

  it("006-SC-007 refuses a blank server url rather than sharing one key", () => {
    const surface = resolveClassificationSurface({
      ...base,
      status: "signed-in",
      serverUrl: "   ",
    });
    expect(surface.identity).toBeNull();
    expect(surface.reason).toBe("no-session");
  });

  it("006-SC-007 names the identity for both signed-in states and for neither other", () => {
    const identity = { serverUrl: base.serverUrl, accountId: "acc-1" };
    expect(resolveIdentity({ ...identity, status: "signed-in" })).toEqual(identity);
    expect(resolveIdentity({ ...identity, status: "signed-in-offline" })).toEqual(identity);
    expect(resolveIdentity({ ...identity, status: "signed-out" })).toBeNull();
    expect(resolveIdentity({ ...identity, status: "loading" })).toBeNull();
    expect(resolveIdentity({ ...identity, status: "signed-in", accountId: "" })).toBeNull();
    expect(resolveIdentity({ ...identity, status: "signed-in", serverUrl: "" })).toBeNull();
  });

  it("006-FR-018 keeps the queue running on a closed task, but shows today's chips", () => {
    // Nothing on a completed task can be classified, so rows with placeholders
    // nobody can act on would be a lie — but the footer and the expiry notice
    // still have to work, so the queue stays enabled.
    expect(
      resolveClassificationSurface({ ...base, status: "signed-in", taskOpen: false }),
    ).toEqual({
      presentation: "chips",
      identity: { serverUrl: base.serverUrl, accountId: "acc-1" },
      queueEnabled: true,
      reason: "task-closed",
    });
  });
});

// ------------------------------------------------ the picker's own inputs

describe("006-SC-009 the pickers are fed from what the device holds", () => {
  it("006-FR-002 names the Tags it can and keeps the ones it cannot, so detach stays reachable", () => {
    expect(attachedEntities(["t1", "t2"], [{ id: "t1", name: "deep-work" }])).toEqual([
      { id: "t1", name: "deep-work" },
      { id: "t2" },
    ]);
  });

  it("006-FR-002 holds nothing at all as a list of ids, never as an empty selection", () => {
    expect(attachedEntities(["t1"], null)).toEqual([{ id: "t1" }]);
    expect(attachedEntities([], null)).toEqual([]);
  });

  it.each<[string, { pending: boolean; failed: boolean; hasData: boolean }, string]>([
    ["nothing fetched yet", { pending: true, failed: false, hasData: false }, "loading"],
    ["the list arrived", { pending: false, failed: false, hasData: true }, "loaded"],
    ["the fetch failed with nothing to answer with", { pending: false, failed: true, hasData: false }, "failed"],
    ["a refetch failed but the device still holds a list", { pending: false, failed: true, hasData: true }, "loaded"],
  ])("006-SC-009 the list phase when %s", (_why, input, expected) => {
    expect(resolveListPhase(input)).toBe(expected);
  });

  it("006-SC-009 reads a cache fallback as offline — mobile has no NetInfo to ask", () => {
    // `api/hooks.ts` projects a cache fallback with this revision, because the
    // device cannot know the revision of a list it read back from its own store.
    expect(servedFromCache([{ revision: CACHED_LIST_REVISION }])).toBe(true);
    expect(servedFromCache([{ revision: 7 }])).toBe(false);
    expect(servedFromCache(undefined)).toBe(false);
    expect(servedFromCache(null)).toBe(false);
  });

  it.each<
    [string, { status: "signed-in" | "signed-in-offline"; fromCache: boolean; listFailed: boolean; hasServerData: boolean }, boolean]
  >([
    ["the server answered just now", { status: "signed-in", fromCache: false, listFailed: false, hasServerData: true }, true],
    ["the device answered from its cache", { status: "signed-in", fromCache: true, listFailed: false, hasServerData: false }, false],
    ["the fetch failed outright", { status: "signed-in", fromCache: false, listFailed: true, hasServerData: false }, false],
    ["the launch probe failed and nothing has loaded", { status: "signed-in-offline", fromCache: false, listFailed: false, hasServerData: false }, false],
    ["the launch probe failed but the list has since come from the server", { status: "signed-in-offline", fromCache: false, listFailed: false, hasServerData: true }, true],
  ])("006-FR-016 online when %s", (_why, input, expected) => {
    expect(resolveOnline(input)).toBe(expected);
  });
});

describe("006-FR-010 an edit records what the DEVICE was showing, not the server's value", () => {
  it("006-FR-001 clears the project with an explicit null rather than an omission", () => {
    const edit = buildClassificationEdit(
      "task-1",
      4,
      { projectId: "p1", tagIds: ["t1"] },
      { projectId: null },
    );
    expect(edit).toEqual({
      taskId: "task-1",
      observedRevision: 4,
      displayedValue: { projectId: "p1", tagIds: ["t1"] },
      value: { projectId: null },
    });
    expect("projectId" in edit.value).toBe(true);
  });

  it("006-FR-002 sends the whole intended Tag set, not a delta", () => {
    const edit = buildClassificationEdit("task-1", 4, { projectId: null, tagIds: ["t1"] }, {
      tagIds: ["t1", "t2"],
    });
    expect(edit.value).toEqual({ tagIds: ["t1", "t2"] });
    expect("projectId" in edit.value).toBe(false);
  });

  it("006-FR-010 copies the displayed value, so a later render cannot rewrite it", () => {
    const displayed = { projectId: "p1", tagIds: ["t1"] };
    const edit = buildClassificationEdit("task-1", 4, displayed, { projectId: "p9" });
    displayed.tagIds.push("t2");
    expect(edit.displayedValue.tagIds).toEqual(["t1"]);
  });
});
