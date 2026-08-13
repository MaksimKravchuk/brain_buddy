/**
 * Every row of design.md's M-02 and M-03 state tables, asserted as data.
 *
 * `mobile/` is now covered by render tests (main added a fake-backend harness after this was written), so `ProjectPicker.tsx` and
 * `TagPicker.tsx` are evidenced only by typecheck, the Metro bundle and the
 * quickstart's manual steps. Everything they *decide* lives in `pickerState.ts`
 * and is asserted here — which is the only reason those two screens have any
 * automated coverage at all. Nothing below should be read as covering the
 * components' rendering.
 */

import {
  PROJECT_COPY,
  SKELETON_DELAY_MS,
  SKELETON_ROW_COUNT,
  TAG_COPY,
  buildProjectPickerView,
  buildTagPickerView,
  initialDraft,
  reducePickerDraft,
  toggleTag,
  type PickerListInput,
  type ProjectPickerInput,
  type TagPickerInput,
} from "../pickerState";
import type { NamedEntity } from "../matchExisting";

const PROJECTS: NamedEntity[] = [
  { id: "project_1", name: "Onboarding drop-off" },
  { id: "project_2", name: "Q3 planning" },
  { id: "project_3", name: "Personal admin" },
];

const TAGS: NamedEntity[] = [
  { id: "tag_1", name: "writing" },
  { id: "tag_2", name: "deep-work" },
  { id: "tag_3", name: "errand" },
  { id: "tag_4", name: "home" },
];

const LOADED: PickerListInput = { phase: "loaded", entities: PROJECTS };
const TAGS_LOADED: PickerListInput = { phase: "loaded", entities: TAGS };
/** The device holds no list at all — never fetched, nothing cached. */
const NEVER_FETCHED: PickerListInput = { phase: "loading", entities: null };

function projectView(overrides: Partial<ProjectPickerInput> = {}) {
  return buildProjectPickerView({
    list: LOADED,
    online: true,
    query: "",
    elapsedMs: 1_000,
    selected: null,
    ...overrides,
  });
}

function tagView(overrides: Partial<TagPickerInput> = {}) {
  return buildTagPickerView({
    list: TAGS_LOADED,
    online: true,
    query: "",
    elapsedMs: 1_000,
    attached: [],
    selected: [],
    ...overrides,
  });
}

const labels = (view: { rows: { label: string }[] }) => view.rows.map((row) => row.label);
const selectedLabels = (view: { rows: { label: string; selected: boolean }[] }) =>
  view.rows.filter((row) => row.selected).map((row) => row.label);

describe("006-FR-001 M-02 project picker, default state", () => {
  it("lists None first, then the projects in the order the server gave them", () => {
    expect(labels(projectView())).toEqual([
      "None",
      "Onboarding drop-off",
      "Q3 planning",
      "Personal admin",
    ]);
    expect(projectView().state).toBe("default");
  });

  it("checks None when the task has no project", () => {
    expect(selectedLabels(projectView())).toEqual(["None"]);
  });

  it("checks the task's project, and only it — a task carries at most one (006-FR-003)", () => {
    const view = projectView({ selected: { id: "project_2", name: "Q3 planning" } });
    expect(selectedLabels(view)).toEqual(["Q3 planning"]);
    expect(view.rows.filter((row) => row.selected)).toHaveLength(1);
  });

  it("gives the None row a null id, so choosing it clears rather than sets", () => {
    const none = projectView().rows[0];
    expect(none.id).toBeNull();
    expect(none.label).toBe("None");
  });

  it("names the None row for assistive technology, where 'None' alone says nothing", () => {
    expect(projectView().rows[0].accessibilityLabel).toBe("No project");
  });

  it("carries each row's own name as its accessible name; the check is decorative", () => {
    const view = projectView({ selected: { id: "project_2", name: "Q3 planning" } });
    for (const row of view.rows.slice(1)) {
      expect(row.accessibilityLabel).toBe(row.label);
      expect(row.accessibilityLabel).not.toContain("✓");
    }
  });

  it("says a task has one project or none, so the single-select rule is readable", () => {
    expect(projectView().footer).toBe("A task has one project, or none");
  });

  it("filters the list by what was typed", () => {
    expect(labels(projectView({ query: "q3" }))).toEqual(["Q3 planning"]);
  });
});

describe("006-FR-002 M-03 Tag picker, default state", () => {
  it("lists the Tags with checks on the attached ones, multi-select", () => {
    const view = tagView({ attached: [{ id: "tag_1" }, { id: "tag_2" }], selected: ["tag_1", "tag_2"] });
    expect(labels(view)).toEqual(["writing", "deep-work", "errand", "home"]);
    expect(selectedLabels(view)).toEqual(["writing", "deep-work"]);
    expect(view.state).toBe("default");
  });

  it("counts the selection in the footer, in Tag vocabulary and sentence case", () => {
    expect(tagView().footer).toBe("No Tags selected");
    expect(tagView({ selected: ["tag_1"] }).footer).toBe("1 Tag selected");
    expect(tagView({ selected: ["tag_1", "tag_2"] }).footer).toBe("2 Tags selected");
  });

  it("offers no None row: Tags are a set, and clearing one is detaching it", () => {
    expect(tagView().rows.every((row) => row.id !== null)).toBe(true);
  });
});

describe("006-FR-001 006-FR-002 loading: skeleton rows only after 300 ms, never a spinner", () => {
  it("is loading while nothing has been fetched and nothing is cached", () => {
    expect(projectView({ list: NEVER_FETCHED }).state).toBe("loading");
    expect(tagView({ list: NEVER_FETCHED }).state).toBe("loading");
  });

  it.each([
    ["on open", 0],
    ["a frame later", 16],
    ["one millisecond before the grace ends", SKELETON_DELAY_MS - 1],
  ])("shows nothing at all %s (%i ms)", (_when, elapsedMs) => {
    const view = projectView({ list: NEVER_FETCHED, elapsedMs });
    expect(view.showSkeletons).toBe(false);
    expect(view.message).toBeNull();
  });

  it.each([
    ["the moment the grace ends", SKELETON_DELAY_MS],
    ["after it", SKELETON_DELAY_MS + 1],
    ["much later", 5_000],
  ])("shows three skeleton rows %s (%i ms)", (_when, elapsedMs) => {
    const view = projectView({ list: NEVER_FETCHED, elapsedMs });
    expect(view.showSkeletons).toBe(true);
    expect(view.skeletonRows).toBe(SKELETON_ROW_COUNT);
  });

  it("shows three, as design.md's loading row says", () => {
    expect(SKELETON_ROW_COUNT).toBe(3);
  });

  it("never shows skeletons over a cached list, however slow the refresh is", () => {
    const view = tagView({
      list: { phase: "loading", entities: TAGS },
      elapsedMs: 60_000,
    });
    expect(view.showSkeletons).toBe(false);
    expect(labels(view)).toHaveLength(4);
  });

  it("offers no create row while loading: 006-FR-005's duplicate check has no list yet", () => {
    expect(projectView({ list: NEVER_FETCHED, query: "Q3" }).create).toEqual({
      kind: "hidden",
      why: "no-list",
    });
  });
});

describe("006-FR-004 M-02/M-03 empty, first run: the rows are present, not hidden", () => {
  const emptyProjects: PickerListInput = { phase: "loaded", entities: [] };
  const emptyTags: PickerListInput = { phase: "loaded", entities: [] };

  it("says 'No projects yet' and still offers None plus the create row", () => {
    const view = projectView({ list: emptyProjects });
    expect(view.state).toBe("empty-first-run");
    expect(view.message?.text).toBe("No projects yet");
    expect(labels(view)).toEqual(["None"]);
    expect(view.create.kind).not.toBe("hidden");
  });

  it("says 'No Tags yet' and offers the create row", () => {
    const view = tagView({ list: emptyTags });
    expect(view.state).toBe("empty-first-run");
    expect(view.message?.text).toBe("No Tags yet");
    expect(view.rows).toEqual([]);
    expect(view.create.kind).not.toBe("hidden");
  });

  it("distinguishes an empty list from no list: the two say different things", () => {
    expect(projectView({ list: emptyProjects }).message?.text).toBe("No projects yet");
    expect(projectView({ list: NEVER_FETCHED, online: false }).message?.text).toBe(
      "Can't load your projects without a connection",
    );
  });
});

describe("006-FR-005 M-02/M-03 empty, filtered to nothing", () => {
  it("offers a create row carrying the typed name when a project search matches nothing", () => {
    const view = projectView({ query: "Q4 planning" });
    expect(view.state).toBe("empty-filtered");
    expect(view.create).toEqual({
      kind: "create",
      name: "Q4 planning",
      label: "Create “Q4 planning”",
    });
  });

  it("does the same for Tags", () => {
    const view = tagView({ query: "reading" });
    expect(view.state).toBe("empty-filtered");
    expect(view.create).toEqual({ kind: "create", name: "reading", label: "Create “reading”" });
  });

  it("is not reached by a blank query, which filters nothing out", () => {
    expect(projectView({ query: "   " }).state).toBe("default");
  });

  it("does not let the None row mask a project search that matched nothing", () => {
    // "non" matches the None row, but no project — the person is still naming
    // something that does not exist.
    const view = projectView({ query: "non" });
    expect(labels(view)).toEqual(["None"]);
    expect(view.state).toBe("empty-filtered");
  });
});

describe("006-FR-012 M-02/M-03 error: the failure is actionable and carries its correlation id", () => {
  const failed: PickerListInput = {
    phase: "failed",
    entities: null,
    correlationId: "corr-7f3a",
  };

  it("states the failure, offers retry, and shows the correlation id", () => {
    const view = projectView({ list: failed });
    expect(view.state).toBe("error");
    expect(view.message).toEqual({
      text: "We couldn't load your projects.",
      tone: "error",
      retry: true,
      correlationId: "corr-7f3a",
    });
  });

  it("keeps the current project shown and still clearable when the list failed", () => {
    const view = projectView({
      list: failed,
      selected: { id: "project_2", name: "Q3 planning" },
    });
    expect(labels(view)).toEqual(["None", "Q3 planning"]);
    expect(view.rows[0].id).toBeNull();
    expect(selectedLabels(view)).toEqual(["Q3 planning"]);
  });

  it("keeps the already-attached Tags shown when the Tag list failed", () => {
    const view = tagView({
      list: { phase: "failed", entities: null, correlationId: "corr-9c1" },
      attached: [{ id: "tag_1", name: "writing" }, { id: "tag_2", name: "deep-work" }],
      selected: ["tag_1", "tag_2"],
    });
    expect(view.state).toBe("error");
    expect(labels(view)).toEqual(["writing", "deep-work"]);
    expect(selectedLabels(view)).toEqual(["writing", "deep-work"]);
    expect(view.message?.correlationId).toBe("corr-9c1");
  });

  it("offers no create row while the list is unreadable, so 006-FR-005 is never bypassed", () => {
    expect(projectView({ list: failed }).create).toEqual({ kind: "hidden", why: "no-list" });
  });

  it("still reports the failed refresh when a cached list is standing in for it", () => {
    const view = tagView({ list: { phase: "failed", entities: TAGS, correlationId: "corr-2" } });
    expect(view.state).toBe("error");
    expect(labels(view)).toHaveLength(4);
    expect(view.message?.retry).toBe(true);
  });

  it("omits the correlation id rather than inventing one when the request had none", () => {
    const view = projectView({ list: { phase: "failed", entities: null } });
    expect(view.message?.correlationId).toBeUndefined();
    expect(view.message?.retry).toBe(true);
  });
});

describe("006-SC-009 006-FR-016 M-02/M-03 offline with a list the device already holds", () => {
  it("still offers every project, from the list last stored on the device", () => {
    const view = projectView({ online: false });
    expect(view.state).toBe("offline");
    expect(labels(view)).toEqual([
      "None",
      "Onboarding drop-off",
      "Q3 planning",
      "Personal admin",
    ]);
  });

  it("still offers every Tag, and attaching one that exists needs no connection", () => {
    const view = tagView({ online: false, selected: ["tag_1"] });
    expect(view.state).toBe("offline");
    expect(labels(view)).toHaveLength(4);
    expect(selectedLabels(view)).toEqual(["writing"]);
  });

  it("disables the create row with its reason in text, before it is tapped", () => {
    const view = projectView({ online: false, query: "Q4 planning" });
    expect(view.create).toEqual({
      kind: "blocked",
      label: "Create “Q4 planning”",
      reason: "Needs a connection — new projects are named by the server",
      why: "offline",
    });
  });

  it("uses the Tag wording for Tags", () => {
    const view = tagView({ online: false, query: "reading" });
    expect(view.create).toEqual({
      kind: "blocked",
      label: "Create “reading”",
      reason: "Needs a connection — new Tags are named by the server",
      why: "offline",
    });
  });

  it("says offline in words above the list as well, never by colour alone", () => {
    expect(projectView({ online: false }).offlineBanner).toBe(
      "Offline. You can pick a project that already exists; creating a new one needs a connection.",
    );
    expect(tagView({ online: false }).offlineBanner).toBe(
      "Offline. You can add Tags that already exist; creating a new one needs a connection.",
    );
  });

  it("shows no offline banner when there is a connection", () => {
    expect(projectView().offlineBanner).toBeNull();
    expect(tagView().offlineBanner).toBeNull();
  });

  it("keeps the blocked create row visible rather than hiding it", () => {
    const view = tagView({ online: false, query: "reading" });
    expect(view.create.kind).toBe("blocked");
    expect(view.create).toHaveProperty("label");
  });
});

describe("006-FR-001 006-FR-016 M-02 offline, never fetched", () => {
  const input = { list: NEVER_FETCHED, online: false } satisfies Partial<ProjectPickerInput>;

  it("says so plainly rather than claiming the person has no projects", () => {
    const view = projectView(input);
    expect(view.state).toBe("offline-never-fetched");
    expect(view.message).toEqual({
      text: "Can't load your projects without a connection",
      tone: "info",
      retry: false,
    });
  });

  it("keeps None available: clearing a project needs no fetched list", () => {
    const view = projectView(input);
    expect(labels(view)).toEqual(["None"]);
    expect(view.rows[0].id).toBeNull();
    expect(view.rows[0].selected).toBe(true);
  });

  it("still shows the task's own project alongside None, so it can be cleared knowingly", () => {
    const view = projectView({ ...input, selected: { id: "project_2", name: "Q3 planning" } });
    expect(labels(view)).toEqual(["None", "Q3 planning"]);
    expect(selectedLabels(view)).toEqual(["Q3 planning"]);
  });

  it("says why a project's name is missing rather than showing a blank row", () => {
    const view = projectView({ ...input, selected: { id: "project_2" } });
    expect(labels(view)).toEqual(["None", "Project — needs a connection to show its name"]);
  });

  it("offers no create row at all — the empty-first-run copy would be a lie here", () => {
    expect(projectView({ ...input, query: "Q4" }).create).toEqual({
      kind: "hidden",
      why: "no-list",
    });
  });

  it("sends focus to the message, not to a search field with nothing to filter", () => {
    const view = projectView(input);
    expect(view.initialFocus).toBe("message");
    expect(view.search.shown).toBe(false);
  });

  it("focuses the search field in every other state", () => {
    for (const view of [
      projectView(),
      projectView({ online: false }),
      projectView({ list: NEVER_FETCHED }),
      projectView({ list: { phase: "failed", entities: null } }),
      tagView(),
    ]) {
      expect(view.initialFocus).toBe("search");
      expect(view.search.shown).toBe(true);
    }
  });
});

describe("006-FR-002 006-FR-016 M-03 offline, never fetched", () => {
  const attached = [
    { id: "tag_1", name: "writing" },
    { id: "tag_2", name: "deep-work" },
  ];
  const input = {
    list: NEVER_FETCHED,
    online: false,
    attached,
    selected: ["tag_1", "tag_2"],
  } satisfies Partial<TagPickerInput>;

  it("says so plainly rather than claiming the person has no Tags", () => {
    const view = tagView(input);
    expect(view.state).toBe("offline-never-fetched");
    expect(view.message?.text).toBe("Can't load your Tags without a connection");
  });

  it("lists the task's own attached Tags, sourced from the task rather than the list", () => {
    const view = tagView(input);
    expect(labels(view)).toEqual(["writing", "deep-work"]);
    expect(selectedLabels(view)).toEqual(["writing", "deep-work"]);
  });

  it("keeps a detached Tag listed, so a first-ever offline visit can undo the detach", () => {
    const view = tagView({ ...input, selected: ["tag_2"] });
    expect(labels(view)).toEqual(["writing", "deep-work"]);
    expect(selectedLabels(view)).toEqual(["deep-work"]);
  });

  it("says why a Tag's name is missing rather than showing a blank row", () => {
    const view = tagView({ ...input, attached: [{ id: "tag_9" }], selected: ["tag_9"] });
    expect(labels(view)).toEqual(["Tag — needs a connection to show its name"]);
    expect(view.rows[0].selected).toBe(true);
  });

  it("offers no create row, and sends focus to the message", () => {
    const view = tagView(input);
    expect(view.create).toEqual({ kind: "hidden", why: "no-list" });
    expect(view.initialFocus).toBe("message");
    expect(view.search.shown).toBe(false);
  });

  it("lists nothing when the task carries no Tags, and does not pretend otherwise", () => {
    const view = tagView({ list: NEVER_FETCHED, online: false, attached: [], selected: [] });
    expect(view.rows).toEqual([]);
    expect(view.message?.text).toBe("Can't load your Tags without a connection");
  });
});

describe("006-FR-005 the picker offers an existing project or Tag instead of a duplicate", () => {
  it("offers the existing project when the typed name is the same name", () => {
    const view = projectView({ query: "q3   PLANNING " });
    expect(view.create).toEqual({
      kind: "use-existing",
      entity: PROJECTS[1],
      label: "Use “Q3 planning” — it already exists",
    });
  });

  it("says the match is already this task's project rather than offering it again", () => {
    const view = projectView({
      query: "Q3 planning",
      selected: { id: "project_2", name: "Q3 planning" },
    });
    expect(view.create).toEqual({
      kind: "already-chosen",
      entity: PROJECTS[1],
      label: "“Q3 planning” is already this task's project",
    });
  });

  it("offers the existing Tag when a typed @home matches the home Tag", () => {
    // The server strips one leading @ from a Tag name, so creating "@home"
    // collides with "home" and answers 409. Without stripTagPrefix the picker
    // would filter to nothing and offer exactly that create.
    const view = tagView({ query: "@home" });
    expect(view.create).toEqual({
      kind: "use-existing",
      entity: TAGS[3],
      label: "Use “home” — it already exists",
    });
  });

  it("also shows the home row for a typed @home, rather than filtering it away", () => {
    const view = tagView({ query: "@home" });
    expect(labels(view)).toEqual(["home"]);
    expect(view.state).toBe("default");
  });

  it("says an attached Tag is already attached rather than offering it again", () => {
    const view = tagView({ query: "@home", attached: [{ id: "tag_4" }], selected: ["tag_4"] });
    expect(view.create).toEqual({
      kind: "already-chosen",
      entity: TAGS[3],
      label: "“home” is already attached",
    });
  });

  it("keeps the @ for projects, which the server does not strip", () => {
    const view = projectView({ list: { phase: "loaded", entities: [{ id: "p", name: "home" }] }, query: "@home" });
    expect(view.create.kind).toBe("create");
  });

  it("offers the existing one even offline, since choosing it needs no connection", () => {
    const view = tagView({ online: false, query: "writing" });
    expect(view.create).toEqual({
      kind: "use-existing",
      entity: TAGS[0],
      label: "Use “writing” — it already exists",
    });
  });

  it("still offers a create for a name that merely starts the same", () => {
    expect(projectView({ query: "Q3" }).create).toEqual({
      kind: "create",
      name: "Q3",
      label: "Create “Q3”",
    });
  });
});

describe("006-FR-016 the create row states its reason in text, never by colour alone", () => {
  it("asks for a name before anything has been typed", () => {
    const view = projectView();
    expect(view.create).toEqual({
      kind: "blocked",
      label: "Create “…”",
      reason: "Type a name to create one",
      why: "no-name",
    });
  });

  it("names the connection as the reason first when offline with nothing typed", () => {
    const view = tagView({ online: false });
    expect(view.create).toEqual({
      kind: "blocked",
      label: "Create “…”",
      reason: "Needs a connection — new Tags are named by the server",
      why: "offline",
    });
  });

  it("treats whitespace as nothing typed", () => {
    const view = tagView({ query: "   " });
    expect(view.create).toMatchObject({ kind: "blocked", why: "no-name" });
  });

  it("gives every blocked create row a non-empty reason a person can read", () => {
    const blocked = [
      projectView(),
      tagView(),
      projectView({ online: false }),
      tagView({ online: false, query: "reading" }),
    ];
    for (const view of blocked) {
      expect(view.create.kind).toBe("blocked");
      if (view.create.kind === "blocked") {
        expect(view.create.reason.length).toBeGreaterThan(0);
      }
    }
  });

  it("says why it is hidden in the message whenever it is hidden", () => {
    for (const view of [
      projectView({ list: NEVER_FETCHED, online: false }),
      tagView({ list: NEVER_FETCHED, online: false }),
      projectView({ list: { phase: "failed", entities: null } }),
    ]) {
      expect(view.create.kind).toBe("hidden");
      expect(view.message?.text.length ?? 0).toBeGreaterThan(0);
    }
  });
});

describe("006-FR-002 toggleTag attaches and detaches one Tag, leaving the others alone", () => {
  it("attaches by appending", () => {
    expect(toggleTag(["tag_1"], "tag_2")).toEqual(["tag_1", "tag_2"]);
  });

  it("detaches only the named Tag", () => {
    expect(toggleTag(["tag_1", "tag_2", "tag_3"], "tag_2")).toEqual(["tag_1", "tag_3"]);
  });

  it("ends with the same set whichever order the person tapped", () => {
    const oneThenTwo = toggleTag(toggleTag([], "tag_1"), "tag_2");
    const twoThenOne = toggleTag(toggleTag([], "tag_2"), "tag_1");
    expect([...oneThenTwo].sort()).toEqual([...twoThenOne].sort());
  });

  it("never duplicates a Tag the task already carries", () => {
    expect(toggleTag(["tag_1"], "tag_1")).toEqual([]);
    expect(toggleTag(toggleTag(["tag_1"], "tag_1"), "tag_1")).toEqual(["tag_1"]);
  });

  it("does not mutate the set it was given", () => {
    const before = ["tag_1"];
    toggleTag(before, "tag_2");
    expect(before).toEqual(["tag_1"]);
  });
});

describe("006-FR-004 a failed create changes nothing the person has to redo", () => {
  it("keeps the typed name and the existing classification when creation fails", () => {
    const typed = reducePickerDraft(initialDraft<string | null>("project_2"), {
      type: "query",
      value: "Q4 planning",
    });
    const sending = reducePickerDraft(typed, { type: "create-start", name: "Q4 planning" });
    const failed = reducePickerDraft(sending, { type: "create-failed", error: new Error("500") });

    expect(failed.query).toBe("Q4 planning");
    expect(failed.selection).toBe("project_2");
    expect(failed.create).toEqual({
      status: "failed",
      name: "Q4 planning",
      error: expect.any(Error),
    });
  });

  it("lets the same name be retried without retyping it", () => {
    const failed = {
      query: "Q4 planning",
      selection: null,
      create: { status: "failed" as const, name: "Q4 planning", error: new Error("500") },
    };
    const retried = reducePickerDraft(failed, { type: "create-start", name: "Q4 planning" });
    expect(retried.create).toEqual({ status: "creating", name: "Q4 planning" });
    expect(retried.query).toBe("Q4 planning");
  });

  it("clears the error once the person types a different name", () => {
    const failed = {
      query: "Q4 planning",
      selection: null,
      create: { status: "failed" as const, name: "Q4 planning", error: new Error("500") },
    };
    expect(reducePickerDraft(failed, { type: "query", value: "Q5" }).create).toEqual({
      status: "idle",
    });
  });

  it("keeps the error while the name is unchanged, so it is still explained", () => {
    const failed = {
      query: "Q4 planning",
      selection: null,
      create: { status: "failed" as const, name: "Q4 planning", error: new Error("500") },
    };
    expect(reducePickerDraft(failed, { type: "query", value: "Q4 planning" }).create.status).toBe(
      "failed",
    );
  });

  it("applies the new classification and clears the field once creation succeeds", () => {
    const sending = {
      query: "Q4 planning",
      selection: null as string | null,
      create: { status: "creating" as const, name: "Q4 planning" },
    };
    const done = reducePickerDraft(sending, {
      type: "create-succeeded",
      selection: "project_9",
    });
    expect(done).toEqual({ query: "", selection: "project_9", create: { status: "idle" } });
  });

  it("refuses to create nothing", () => {
    const draft = initialDraft<string | null>(null);
    expect(reducePickerDraft(draft, { type: "create-start", name: "   " })).toBe(draft);
  });

  it("ignores a failure reported when no create was in flight", () => {
    const draft = initialDraft<string | null>(null);
    expect(reducePickerDraft(draft, { type: "create-failed", error: new Error("x") })).toBe(draft);
  });

  it("does not let a tap land between the create request and its answer", () => {
    const sending = {
      query: "Q4 planning",
      selection: "project_2" as string | null,
      create: { status: "creating" as const, name: "Q4 planning" },
    };
    expect(reducePickerDraft(sending, { type: "choose", selection: "project_3" })).toBe(sending);
    expect(reducePickerDraft(sending, { type: "query", value: "other" })).toBe(sending);
    expect(reducePickerDraft(sending, { type: "create-start", name: "other" })).toBe(sending);
  });

  it("records a choice made while nothing is in flight", () => {
    const chosen = reducePickerDraft(initialDraft<readonly string[]>([]), {
      type: "choose",
      selection: ["tag_1"],
    });
    expect(chosen.selection).toEqual(["tag_1"]);
  });

  it("starts with an empty field and whatever the task already carries", () => {
    expect(initialDraft(["tag_1"])).toEqual({
      query: "",
      selection: ["tag_1"],
      create: { status: "idle" },
    });
  });

  it("re-reads the task on reopen rather than showing the last visit's draft", () => {
    const stale = {
      query: "Q4 planning",
      selection: "project_2" as string | null,
      create: { status: "failed" as const, name: "Q4 planning", error: new Error("500") },
    };
    expect(reducePickerDraft(stale, { type: "reset", selection: "project_7" })).toEqual({
      query: "",
      selection: "project_7",
      create: { status: "idle" },
    });
  });

  it("follows a change made underneath an open picker without deleting the typed name", () => {
    const typing = {
      query: "Q4 pla",
      selection: ["tag_1"] as readonly string[],
      create: { status: "idle" as const },
    };
    expect(reducePickerDraft(typing, { type: "resync", selection: ["tag_1", "tag_2"] })).toEqual({
      query: "Q4 pla",
      selection: ["tag_1", "tag_2"],
      create: { status: "idle" },
    });
  });

  it("leaves a failed create explained when the task changes underneath it", () => {
    const failed = {
      query: "Q4 planning",
      selection: null as string | null,
      create: { status: "failed" as const, name: "Q4 planning", error: new Error("500") },
    };
    const resynced = reducePickerDraft(failed, { type: "resync", selection: "project_7" });
    expect(resynced.create).toEqual(failed.create);
    expect(resynced.query).toBe("Q4 planning");
    expect(resynced.selection).toBe("project_7");
  });
});

describe("006-FR-013 the pickers say Tag, never Context", () => {
  const everyString = (copy: typeof TAG_COPY) => [
    copy.title,
    copy.searchPlaceholder,
    copy.emptyFirstRun,
    copy.offlineBanner,
    copy.offlineNeverFetched,
    copy.loadFailed,
    copy.createBlockedOffline,
    copy.createNeedsName,
    copy.createPromptLabel,
    copy.createLabel("x"),
    copy.useExisting("x"),
    copy.alreadyChosen("x"),
    copy.unnamed,
    copy.footer(0),
    copy.footer(1),
    copy.footer(2),
  ];

  it.each(everyString(TAG_COPY).map((text) => [text]))(
    "never says context, in either sense: %s",
    (text) => {
      expect(text.toLowerCase()).not.toContain("context");
      expect(text).not.toContain("@context");
    },
  );

  it("uses the word Tag where the copy names the thing at all", () => {
    for (const text of [
      TAG_COPY.title,
      TAG_COPY.searchPlaceholder,
      TAG_COPY.emptyFirstRun,
      TAG_COPY.offlineNeverFetched,
      TAG_COPY.loadFailed,
      TAG_COPY.createBlockedOffline,
      TAG_COPY.unnamed,
    ]) {
      expect(text).toContain("Tag");
    }
  });

  it("keeps the project copy talking about projects", () => {
    expect(PROJECT_COPY.title).toBe("Project");
    for (const text of everyString(PROJECT_COPY)) {
      expect(text.toLowerCase()).not.toContain("context");
    }
  });
});
