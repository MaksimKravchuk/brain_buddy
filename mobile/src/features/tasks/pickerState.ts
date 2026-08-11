/**
 * M-02 and M-03 as data.
 *
 * `mobile/` has no component-render test library, so anything decided inside a
 * `.tsx` file is untestable except through the integration harness. Every row of
 * the two picker state tables in
 * `specs/006-mobile-task-classification/design.md` is therefore resolved here,
 * as a pure function over plain values, and `ProjectPicker.tsx` /
 * `TagPicker.tsx` only render what comes back.
 *
 * Two distinctions carry most of the weight:
 *
 * - **`entities: null` is not `entities: []`.** `null` means the device holds
 *   no list at all — never fetched, nothing cached. `[]` means the device has a
 *   list and it is empty. "Can't load your projects without a connection" and
 *   "No projects yet" are different sentences because they are different facts,
 *   and design.md gives them separate rows for exactly that reason.
 * - **Rows the device can offer without the list.** Clearing a project needs no
 *   fetched list, and neither does detaching a Tag the task already carries. So
 *   the "None" row and the task's own attached Tags are sourced from the task,
 *   not from the list — which is what keeps FR-001's clear and FR-002's detach
 *   reachable in M-02/M-03's "offline, never fetched" state and in their "error"
 *   state.
 *
 * Copy is exported rather than inlined so a reviewer can diff it against
 * design.md's copy column in one place. FR-013 applies to all of it: **Tag**,
 * never Context, never @context.
 */

import { matchExisting, type NamedEntity } from "./matchExisting";

/** design.md M-01/M-02/M-03 loading: "Skeleton rows after 300 ms; no spinner before that". */
export const SKELETON_DELAY_MS = 300;
/** design.md M-02/M-03 loading: "Three skeleton rows". */
export const SKELETON_ROW_COUNT = 3;

/** The fetch, narrowed to the three outcomes the pickers distinguish. */
export type ListPhase = "loading" | "loaded" | "failed";

export interface PickerListInput {
  phase: ListPhase;
  /**
   * What the device can actually offer: the server's answer, or the list read
   * back from `classificationCache`. `null` means it holds neither.
   */
  entities: readonly NamedEntity[] | null;
  /** FR-012 — the correlation id of the failed request, shown with the error. */
  correlationId?: string;
}

/** One row per state in design.md's M-02 and M-03 tables, named to match them. */
export type PickerState =
  | "default"
  | "loading"
  | "empty-first-run"
  | "empty-filtered"
  | "error"
  | "offline"
  | "offline-never-fetched";

export interface PickerRow {
  key: string;
  /** `null` is the "None" row: selecting it clears the project (FR-001, FR-003). */
  id: string | null;
  label: string;
  /** The row carries its own name; the check glyph is decorative (design.md). */
  accessibilityLabel: string;
  selected: boolean;
}

export interface PickerMessage {
  text: string;
  tone: "info" | "error";
  /** FR-012 — a failure a person sees is actionable. */
  retry: boolean;
  correlationId?: string;
}

/**
 * The create row, FR-004 and FR-016.
 *
 * Every unavailable form carries its reason as **text**: design.md forbids
 * communicating state by colour alone, and FR-016 requires the reason to be
 * readable before the row is tapped rather than after it fails.
 */
export type CreateAffordance =
  /** No list loaded, so FR-005's duplicate check cannot run — see `resolveCreate`. */
  | { kind: "hidden"; why: "no-list" }
  | { kind: "create"; name: string; label: string }
  /** FR-005 — the typed name is one the server already has. */
  | { kind: "use-existing"; entity: NamedEntity; label: string }
  /** FR-005, and the match is already this task's project / already attached. */
  | { kind: "already-chosen"; entity: NamedEntity; label: string }
  | { kind: "blocked"; label: string; reason: string; why: "offline" | "no-name" };

export interface PickerView {
  state: PickerState;
  title: string;
  message: PickerMessage | null;
  /** Shown above the search field when offline with a list to offer. */
  offlineBanner: string | null;
  search: { shown: boolean; placeholder: string };
  showSkeletons: boolean;
  skeletonRows: number;
  rows: PickerRow[];
  create: CreateAffordance;
  /**
   * design.md, focus: the pickers focus the search field, **except** in
   * "offline, never fetched", where focus goes to the message rather than an
   * empty search field with nothing to filter.
   */
  initialFocus: "search" | "message";
  footer: string;
}

/** A project or Tag the task carries, whose name the device may not know. */
export interface AttachedEntity {
  id: string;
  name?: string;
}

export interface ProjectPickerInput {
  list: PickerListInput;
  online: boolean;
  query: string;
  /** Milliseconds since the picker opened; gates the 300 ms skeleton grace. */
  elapsedMs: number;
  /** The task's project, or `null` for none. */
  selected: AttachedEntity | null;
}

export interface TagPickerInput {
  list: PickerListInput;
  online: boolean;
  query: string;
  elapsedMs: number;
  /**
   * The Tags the task carried when the picker opened — the rows, sourced from
   * the task rather than the list. They stay listed after being detached, so
   * detaching is undoable without a connection.
   */
  attached: readonly AttachedEntity[];
  /** The live selection. Starts as the attached ids and changes as they toggle. */
  selected: readonly string[];
}

export interface PickerCopy {
  title: string;
  searchPlaceholder: string;
  emptyFirstRun: string;
  offlineBanner: string;
  offlineNeverFetched: string;
  loadFailed: string;
  createBlockedOffline: string;
  createNeedsName: string;
  createPromptLabel: string;
  createLabel: (typed: string) => string;
  useExisting: (name: string) => string;
  alreadyChosen: (name: string) => string;
  /** What a row says when the device holds the id but not the name. */
  unnamed: string;
  footer: (selectedCount: number) => string;
}

export const PROJECT_COPY: PickerCopy = {
  title: "Project",
  searchPlaceholder: "Search or type a new name",
  emptyFirstRun: "No projects yet",
  offlineBanner:
    "Offline. You can pick a project that already exists; creating a new one needs a connection.",
  offlineNeverFetched: "Can't load your projects without a connection",
  loadFailed: "We couldn't load your projects.",
  createBlockedOffline: "Needs a connection — new projects are named by the server",
  createNeedsName: "Type a name to create one",
  createPromptLabel: "Create “…”",
  createLabel: (typed) => `Create “${typed}”`,
  useExisting: (name) => `Use “${name}” — it already exists`,
  alreadyChosen: (name) => `“${name}” is already this task's project`,
  unnamed: "Project — needs a connection to show its name",
  footer: () => "A task has one project, or none",
};

export const TAG_COPY: PickerCopy = {
  title: "Tags",
  searchPlaceholder: "Search Tags",
  emptyFirstRun: "No Tags yet",
  offlineBanner:
    "Offline. You can add Tags that already exist; creating a new one needs a connection.",
  offlineNeverFetched: "Can't load your Tags without a connection",
  loadFailed: "We couldn't load your Tags.",
  createBlockedOffline: "Needs a connection — new Tags are named by the server",
  createNeedsName: "Type a name to create one",
  createPromptLabel: "Create “…”",
  createLabel: (typed) => `Create “${typed}”`,
  useExisting: (name) => `Use “${name}” — it already exists`,
  alreadyChosen: (name) => `“${name}” is already attached`,
  unnamed: "Tag — needs a connection to show its name",
  footer: (count) => {
    if (count === 0) {
      return "No Tags selected";
    }
    return count === 1 ? "1 Tag selected" : `${count} Tags selected`;
  },
};

/** The "None" row's visible label. design.md M-02: "None" first, checked when unset. */
export const NONE_LABEL = "None";
/** Out of context "None" says nothing, so assistive technology hears the value. */
export const NONE_ACCESSIBILITY_LABEL = "No project";

/**
 * The same normalization `matchExisting` applies, reused for the substring
 * filter so the two agree about what a person typed.
 *
 * Duplicated rather than imported because `matchExisting.ts` is a delivered
 * module and does not export its normalizer. The case that matters: typing
 * "@home" must show the "home" row. Filtering on the raw string would hide it,
 * land on "empty (filtered to nothing)", and offer a create the server answers
 * with 409.
 */
function normalizeForSearch(value: string, stripTagPrefix: boolean): string {
  const collapse = (input: string) => input.normalize("NFKC").trim().replace(/\s+/gu, " ");
  let normalized = collapse(value);
  if (stripTagPrefix && normalized.startsWith("@")) {
    normalized = collapse(normalized.slice(1));
  }
  return normalized.toLowerCase();
}

function matchesQuery(name: string, query: string, stripTagPrefix: boolean): boolean {
  const needle = normalizeForSearch(query, stripTagPrefix);
  if (needle === "") {
    return true;
  }
  return normalizeForSearch(name, stripTagPrefix).includes(needle);
}

function entityRow(entity: NamedEntity, selected: boolean): PickerRow {
  return {
    key: entity.id,
    id: entity.id,
    label: entity.name,
    accessibilityLabel: entity.name,
    selected,
  };
}

interface ViewInput {
  copy: PickerCopy;
  list: PickerListInput;
  online: boolean;
  query: string;
  elapsedMs: number;
  stripTagPrefix: boolean;
  rows: PickerRow[];
  /** Rows that are candidate matches — "None" is not one, so it cannot mask
   *  "empty (filtered to nothing)". */
  matchableRowCount: number;
  selectedCount: number;
  isAlreadyChosen: (entity: NamedEntity) => boolean;
}

function resolveState(input: ViewInput): PickerState {
  const { list, online, query, matchableRowCount } = input;
  if (list.entities === null) {
    // Offline is the more truthful of the two: "no connection" explains the
    // absence, where "we couldn't load it" invites a retry that cannot work.
    if (!online) {
      return "offline-never-fetched";
    }
    return list.phase === "failed" ? "error" : "loading";
  }
  // A failed refresh over a cached list still has to be said. Offline says it
  // better, so it wins.
  if (list.phase === "failed" && online) {
    return "error";
  }
  if (list.entities.length === 0) {
    return "empty-first-run";
  }
  if (query.trim() !== "" && matchableRowCount === 0) {
    return "empty-filtered";
  }
  return online ? "default" : "offline";
}

function resolveMessage(state: PickerState, input: ViewInput): PickerMessage | null {
  const { copy, list } = input;
  switch (state) {
    case "error":
      return {
        text: copy.loadFailed,
        tone: "error",
        retry: true,
        ...(list.correlationId === undefined ? {} : { correlationId: list.correlationId }),
      };
    case "offline-never-fetched":
      return { text: copy.offlineNeverFetched, tone: "info", retry: false };
    case "empty-first-run":
      return { text: copy.emptyFirstRun, tone: "info", retry: false };
    default:
      // "empty (filtered to nothing)" is spoken by the create row carrying the
      // typed name, which is all design.md puts on that row.
      return null;
  }
}

function resolveCreate(input: ViewInput): CreateAffordance {
  const { copy, list, online, query, stripTagPrefix, isAlreadyChosen } = input;
  if (list.entities === null) {
    // With no list there is nothing to check the typed name against, so FR-005's
    // "offer the existing one rather than a duplicate" cannot be honoured. An
    // offered create here is a 409 waiting to happen.
    return { kind: "hidden", why: "no-list" };
  }
  const typed = query.trim();
  if (typed !== "") {
    const match = matchExisting(query, list.entities, { stripTagPrefix });
    if (match !== null) {
      // Checked before the offline block on purpose: choosing something that
      // already exists costs no connection.
      return isAlreadyChosen(match)
        ? { kind: "already-chosen", entity: match, label: copy.alreadyChosen(match.name) }
        : { kind: "use-existing", entity: match, label: copy.useExisting(match.name) };
    }
  }
  if (!online) {
    return {
      kind: "blocked",
      label: typed === "" ? copy.createPromptLabel : copy.createLabel(typed),
      reason: copy.createBlockedOffline,
      why: "offline",
    };
  }
  if (typed === "") {
    return {
      kind: "blocked",
      label: copy.createPromptLabel,
      reason: copy.createNeedsName,
      why: "no-name",
    };
  }
  return { kind: "create", name: typed, label: copy.createLabel(typed) };
}

function buildView(input: ViewInput): PickerView {
  const state = resolveState(input);
  const neverFetched = state === "offline-never-fetched";
  return {
    state,
    title: input.copy.title,
    message: resolveMessage(state, input),
    offlineBanner: !input.online && input.list.entities !== null ? input.copy.offlineBanner : null,
    search: { shown: !neverFetched, placeholder: input.copy.searchPlaceholder },
    showSkeletons: state === "loading" && input.elapsedMs >= SKELETON_DELAY_MS,
    skeletonRows: SKELETON_ROW_COUNT,
    rows: input.rows,
    create: resolveCreate(input),
    initialFocus: neverFetched ? "message" : "search",
    footer: input.copy.footer(input.selectedCount),
  };
}

/**
 * M-02 — the project picker.
 *
 * "None" comes first and carries the check when the task has no project
 * (FR-001, FR-003). It survives every state, including "offline, never
 * fetched": clearing needs no fetched list, so the absence of one must not make
 * FR-001's clear unreachable.
 */
export function buildProjectPickerView(input: ProjectPickerInput): PickerView {
  const { list, online, query, elapsedMs, selected } = input;
  const listed = list.entities ?? [];
  const known = new Set(listed.map((entity) => entity.id));
  const rows: PickerRow[] = [];

  if (matchesQuery(NONE_LABEL, query, false)) {
    rows.push({
      key: "none",
      id: null,
      label: NONE_LABEL,
      accessibilityLabel: NONE_ACCESSIBILITY_LABEL,
      selected: selected === null,
    });
  }

  let matchable = 0;
  for (const entity of listed) {
    if (matchesQuery(entity.name, query, false)) {
      rows.push(entityRow(entity, selected?.id === entity.id));
      matchable += 1;
    }
  }

  // The task's own project, when the list does not carry it: M-02's error row
  // says the current value is "still shown and still clearable", and the
  // offline-never-fetched row has no list to carry it at all.
  if (selected !== null && !known.has(selected.id)) {
    const name = selected.name ?? PROJECT_COPY.unnamed;
    if (matchesQuery(name, query, false)) {
      rows.push(entityRow({ id: selected.id, name }, true));
      matchable += 1;
    }
  }

  return buildView({
    copy: PROJECT_COPY,
    list,
    online,
    query,
    elapsedMs,
    stripTagPrefix: false,
    rows,
    matchableRowCount: matchable,
    selectedCount: selected === null ? 0 : 1,
    isAlreadyChosen: (entity) => selected?.id === entity.id,
  });
}

/**
 * M-03 — the Tag picker, multi-select.
 *
 * The task's own attached Tags are always rows, sourced from the task rather
 * than the list, and they stay listed after being detached so the detach is
 * undoable. That is what keeps FR-002 reachable on a first-ever visit that
 * happens to be offline, where the list has never been fetched.
 *
 * `stripTagPrefix` is on for every name comparison here, because the server
 * strips one leading `@` from a Tag name. Without it, typing "@home" filters to
 * nothing and offers a create that the server answers with 409.
 */
export function buildTagPickerView(input: TagPickerInput): PickerView {
  const { list, online, query, elapsedMs, attached, selected } = input;
  const listed = list.entities ?? [];
  const known = new Set(listed.map((entity) => entity.id));
  const extras: NamedEntity[] = attached
    .filter((tag) => !known.has(tag.id))
    .map((tag) => ({ id: tag.id, name: tag.name ?? TAG_COPY.unnamed }));

  const rows: PickerRow[] = [];
  for (const entity of [...listed, ...extras]) {
    if (matchesQuery(entity.name, query, true)) {
      rows.push(entityRow(entity, selected.includes(entity.id)));
    }
  }

  return buildView({
    copy: TAG_COPY,
    list,
    online,
    query,
    elapsedMs,
    stripTagPrefix: true,
    rows,
    matchableRowCount: rows.length,
    selectedCount: selected.length,
    isAlreadyChosen: (entity) => selected.includes(entity.id),
  });
}

/**
 * FR-002 — attach or detach one Tag, leaving every other Tag untouched.
 *
 * Attaching appends, so the set the task ends up with does not depend on the
 * order the person tapped (User Story 1, scenario 3), and a Tag already in the
 * set is never duplicated.
 */
export function toggleTag(selected: readonly string[], tagId: string): string[] {
  return selected.includes(tagId)
    ? selected.filter((id) => id !== tagId)
    : [...selected, tagId];
}

/** An in-flight or failed create. `idle` covers "nothing has been attempted". */
export type CreateAttempt =
  | { status: "idle" }
  | { status: "creating"; name: string }
  | { status: "failed"; name: string; error: unknown };

export interface PickerDraft<TSelection> {
  /** What is in the search field, and what "Create …" would name. */
  query: string;
  selection: TSelection;
  create: CreateAttempt;
}

export type PickerAction<TSelection> =
  | { type: "query"; value: string }
  | { type: "choose"; selection: TSelection }
  | { type: "create-start"; name: string }
  | { type: "create-failed"; error: unknown }
  | { type: "create-succeeded"; selection: TSelection }
  /** Reopened: forget the last visit entirely. */
  | { type: "reset"; selection: TSelection }
  /** The task's classification changed underneath an open picker. */
  | { type: "resync"; selection: TSelection };

export function initialDraft<TSelection>(selection: TSelection): PickerDraft<TSelection> {
  return { query: "", selection, create: { status: "idle" } };
}

/**
 * The picker's own draft state, which is where User Story 2's fourth scenario
 * lives: **a failed create changes nothing.**
 *
 * `create-failed` leaves both `query` and `selection` exactly as they were, so
 * the task's existing classification is untouched and the typed name is still
 * in the field — the person retries without retyping. Retyping a *different*
 * name clears the error, because it was about a name that is no longer there.
 *
 * While a create is in flight the draft ignores edits and choices. The server
 * assigns the new entity's identity, so a tap that lands between the request and
 * its answer would otherwise be overwritten by the create's own success.
 */
export function reducePickerDraft<TSelection>(
  draft: PickerDraft<TSelection>,
  action: PickerAction<TSelection>,
): PickerDraft<TSelection> {
  const creating = draft.create.status === "creating";
  switch (action.type) {
    case "query": {
      if (creating || action.value === draft.query) {
        return draft;
      }
      const staleError =
        draft.create.status === "failed" && draft.create.name !== action.value.trim();
      return {
        ...draft,
        query: action.value,
        create: staleError ? { status: "idle" } : draft.create,
      };
    }
    case "choose":
      return creating ? draft : { ...draft, selection: action.selection };
    case "create-start": {
      const name = action.name.trim();
      if (creating || name === "") {
        return draft;
      }
      return { ...draft, create: { status: "creating", name } };
    }
    case "create-failed": {
      if (draft.create.status !== "creating") {
        return draft;
      }
      return {
        ...draft,
        create: { status: "failed", name: draft.create.name, error: action.error },
      };
    }
    case "create-succeeded":
      return { query: "", selection: action.selection, create: { status: "idle" } };
    case "reset":
      // The sheet stays mounted while hidden, so reopening it has to re-read the
      // task rather than show the last visit's typed name and stale checks.
      return initialDraft(action.selection);
    case "resync":
      // The queue drained a change into this task, or the person's own toggle
      // came back through the props. Only the checks move: wiping the field here
      // would delete a half-typed name on every tap, which is the one thing
      // User Story 2's fourth scenario is about not doing.
      return { ...draft, selection: action.selection };
  }
}
