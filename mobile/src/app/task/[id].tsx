import { useLocalSearchParams } from "expo-router";
import { Calendar, Check, ChevronRight, Flag } from "lucide-react-native";
import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AccessibilityInfo,
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  TextInput,
  View,
} from "react-native";

import { ApiError } from "@/api/client";
import {
  useCreateComment,
  useCreateSubtask,
  useProjects,
  useTags,
  useTask,
  useTransitionSubtask,
  useTransitionTask,
  useUpdateTask,
} from "@/api/hooks";
import type { OpenTaskState, TaskPriority, TaskUpdateRequest } from "@/api/types";
import { useSession } from "@/auth/SessionProvider";
import { BBText } from "@/components/BBText";
import { Button } from "@/components/Button";
import { TagPill } from "@/components/Chip";
import { ErrorBanner } from "@/components/ErrorBanner";
import { Screen } from "@/components/Screen";
import { Sheet } from "@/components/Sheet";
import { TopBar } from "@/components/shell/TopBar";
import { dueLabel } from "@/components/TaskRow";
import type { ClassificationValue } from "@/features/tasks/classificationTypes";
import type { DecisionReason } from "@/features/tasks/conflictDecision";
import { ConflictSheet } from "@/features/tasks/ConflictSheet";
import type { NamedEntity } from "@/features/tasks/matchExisting";
import { ProjectPicker } from "@/features/tasks/ProjectPicker";
import { ReopenSheet } from "@/features/tasks/ReopenSheet";
import { StatePicker } from "@/features/tasks/StatePicker";
import { TagPicker } from "@/features/tasks/TagPicker";
import {
  LAST_SYNCED_TICK_MS,
  PRIORITY_LABELS,
  accountNoticeKey,
  attachedEntities,
  buildClassificationEdit,
  buildExpiredNotice,
  buildLastSyncedFooter,
  buildMetadataChips,
  buildMetadataRows,
  hasDismissedAccountNotice,
  rememberAccountNoticeDismissed,
  resolveAccountExpiryNotice,
  resolveClassificationAvailability,
  resolveClassificationSurface,
  resolveListPhase,
  resolveOnline,
  rowUsesClassificationQueue,
  servedFromCache,
  shouldAnnounceLastSynced,
  type LastSyncedFooter,
  type MetadataInput,
  type MetadataRowId,
} from "@/features/tasks/taskScreenState";
import { useClassificationNames } from "@/features/tasks/useClassificationNames";
import {
  conflictServerState,
  effectiveClassification,
  useClassificationQueue,
  type ClassificationApiPort,
} from "@/features/tasks/useClassificationQueue";
import { availableTransitions, buildTransition } from "@/lifecycle/guards";
import { colors, fonts, minHitTarget, radii, space, type as typeScale } from "@/theme/tokens";
import { classifySessionFailure } from "@/auth/sessionOutcome";
import { useServerDraft } from "@/utils/useServerDraft";
import { newIdempotencyKey } from "@/utils/ids";

const STATE_LABELS: Record<string, string> = {
  inbox: "Inbox",
  next: "Next actions",
  waiting: "Waiting for",
  someday: "Someday / maybe",
  completed: "Completed",
  cancelled: "Cancelled",
};

const PRIORITIES: TaskPriority[] = ["none", "low", "medium", "high"];
const PRIORITY_COLORS: Record<string, string> = {
  high: colors.danger,
  medium: colors.warning,
  low: colors.info,
};

function isoDatePlus(days: number): string {
  const date = new Date();
  date.setDate(date.getDate() + days);
  return date.toISOString().slice(0, 10);
}

/** "2h" / "3d" style relative timestamp for comments. */
function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) {
    return "";
  }
  const minutes = Math.max(0, Math.round((Date.now() - then) / 60_000));
  if (minutes < 1) {
    return "now";
  }
  if (minutes < 60) {
    return `${minutes}m`;
  }
  const hours = Math.round(minutes / 60);
  if (hours < 24) {
    return `${hours}h`;
  }
  const days = Math.round(hours / 24);
  if (days < 7) {
    return `${days}d`;
  }
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function ownInitials(email: string | undefined): string {
  if (!email) {
    return "·";
  }
  const name = email.split("@")[0];
  const parts = name.split(/[._-]+/).filter(Boolean);
  return (parts.length >= 2 ? parts[0][0] + parts[1][0] : name.slice(0, 2)).toUpperCase();
}

export default function TaskDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string; from?: string }>();
  const query = useTask(id);
  const update = useUpdateTask(id);
  const transition = useTransitionTask(id);
  const createSubtask = useCreateSubtask(id);
  const transitionSubtask = useTransitionSubtask(id);
  const createComment = useCreateComment(id);
  const { projectName, tagNames } = useClassificationNames();
  const projects = useProjects();
  const tags = useTags();
  const { me, api, status, accountId, serverUrl, taskClassificationEnabled } = useSession();

  const task = query.data;

  // Drafts follow the server copy until the user types, and follow it again on
  // every fresh revision — including after a 409 refetch. `useServerDraft`
  // landed on main while this feature was in flight; it replaces the effect
  // that used to do this by hand, and the eslint-disable that came with it.
  const revision = task ? `${task.id}:${task.revision}` : "";
  const [title, setTitle] = useServerDraft(task?.title ?? "", revision);
  const [details, setDetails] = useServerDraft(task?.details ?? "", revision);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [dueDraft, setDueDraft] = useServerDraft(task?.due_date ?? "", revision);
  const [waitingDraft, setWaitingDraft] = useServerDraft(task?.waiting_for ?? "", revision);
  const [subtaskDraft, setSubtaskDraft] = useState("");
  const [commentDraft, setCommentDraft] = useState("");
  const [dueVisible, setDueVisible] = useState(false);
  const [priorityVisible, setPriorityVisible] = useState(false);
  const [moveVisible, setMoveVisible] = useState(false);
  const [moveTarget, setMoveTarget] = useState<OpenTaskState | null>(null);
  const [moveWaitingFor, setMoveWaitingFor] = useState("");
  const [moveGuardError, setMoveGuardError] = useState<string | null>(null);
  const [reopenVisible, setReopenVisible] = useState(false);
  const [projectPickerVisible, setProjectPickerVisible] = useState(false);
  const [tagPickerVisible, setTagPickerVisible] = useState(false);
  const [accountNoticeDismissed, setAccountNoticeDismissed] = useState(false);
  // M-04 "dismissed": which question was set aside, by the key that identifies
  // it. Deliberately nothing more durable — see the sheet below.
  const [dismissedConflict, setDismissedConflict] = useState<string | null>(null);
  // SC-004's footer is the only thing on this screen that ages, so the clock is
  // read here and passed down; nothing in `taskScreenState` reads it itself.
  const [now, setNow] = useState(() => Date.now());

  const transitions = useMemo(() => (task ? availableTransitions(task) : null), [task]);
  const taskOpen = (transitions?.moveTargets.length ?? 0) > 0;

  /**
   * FR-015 / SC-009 — which presentation this screen carries, and whether the
   * device queue can be named at all. Every input resolves from persisted
   * state, so an offline cold start reaches the same screen a live session
   * does. Every rule behind it is asserted in
   * `features/tasks/__tests__/taskScreenState.test.ts`.
   */
  const surface = useMemo(
    () =>
      resolveClassificationSurface({
        status,
        taskClassificationEnabled,
        accountId,
        serverUrl,
        taskOpen,
      }),
    [status, taskClassificationEnabled, accountId, serverUrl, taskOpen],
  );

  // A narrow port rather than the client itself, so nothing in the queue hook
  // imports the session.
  const classificationApi = useMemo<ClassificationApiPort>(
    () => ({
      getTask: (taskId, signal) => api.getTask(taskId, signal),
      updateTask: (taskId, payload, idempotencyKey) =>
        api.updateTask(taskId, payload, idempotencyKey),
    }),
    [api],
  );

  const refetchTask = query.refetch;
  const queue = useClassificationQueue({
    identity: surface.identity,
    api: classificationApi,
    enabled: surface.queueEnabled,
    onSynced: () => {
      void refetchTask();
    },
  });

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), LAST_SYNCED_TICK_MS);
    return () => clearInterval(timer);
  }, []);

  const footer = useMemo(
    () => buildLastSyncedFooter(queue.lastSyncedAt, now),
    [queue.lastSyncedAt, now],
  );
  const announcedFooter = useRef<LastSyncedFooter | null>(null);
  useEffect(() => {
    // design.md: the footer is a live region that announces only when the time
    // changes materially, never on every tick — and never on first paint, where
    // it is read as part of the screen the person just opened.
    if (shouldAnnounceLastSynced(announcedFooter.current, footer)) {
      AccessibilityInfo.announceForAccessibility(footer.label);
    }
    announcedFooter.current = footer;
  }, [footer]);

  // Reading the per-run dismissal latch is a derivation from the identity key,
  // so it happens during render. In an effect it cascaded a render on every
  // pass, which is what `react-hooks/set-state-in-effect` is there to stop.
  const noticeKey = accountNoticeKey(surface.identity);
  const [noticeKeyRead, setNoticeKeyRead] = useState(noticeKey);
  if (noticeKeyRead !== noticeKey) {
    setNoticeKeyRead(noticeKey);
    setAccountNoticeDismissed(hasDismissedAccountNotice(noticeKey));
  }
  const dismissAccountNotice = useCallback(() => {
    rememberAccountNoticeDismissed(noticeKey);
    setAccountNoticeDismissed(true);
  }, [noticeKey]);

  if (query.isLoading || !task || !transitions) {
    return (
      <Screen>
        <TopBar leading="back" />
        <View style={styles.center}>
          {query.isError ? (
            <ErrorBanner error={query.error} onRetry={() => query.refetch()} />
          ) : (
            <ActivityIndicator color={colors.brandPrimary} />
          )}
        </View>
      </Screen>
    );
  }

  const saveField = (payload: Omit<TaskUpdateRequest, "expected_revision">) => {
    update.mutate({ ...payload, expected_revision: task.revision });
  };

  const conflict =
    (update.isError && update.error instanceof ApiError && update.error.status === 409) ||
    (transition.isError && transition.error instanceof ApiError && transition.error.status === 409);

  const runTransition = (
    action: "complete" | "cancel" | "move",
    toState?: OpenTaskState,
    waitingFor?: string,
  ) => {
    const guard = buildTransition(task, {
      action,
      toState,
      waitingFor,
      expectedRevision: task.revision,
    });
    if (!guard.ok) {
      setMoveGuardError(guard.reason);
      return;
    }
    setMoveGuardError(null);
    transition.mutate(
      { payload: guard.payload },
      {
        onSuccess: () => {
          setMoveVisible(false);
          setMoveTarget(null);
          setMoveWaitingFor("");
        },
      },
    );
  };

  const done = task.state === "completed";
  const openTask = transitions.moveTargets.length > 0;
  const hasDetails = Boolean(task.details?.trim());
  const showDetailsEditor = detailsOpen || hasDetails;

  // FR-007: the row shows the queued value if there is one and the server's
  // otherwise, with no marker either way. Everything below reads `effective`,
  // so a change made offline is presented exactly like one the server has.
  const serverClassification = { projectId: task.project_id, tagIds: task.tag_ids };
  const pendingEntry = queue.pendingFor(task.id);
  const effective = effectiveClassification(serverClassification, pendingEntry);
  const project = projectName(effective.projectId);
  const taskTags = tagNames(effective.tagIds);

  const metadata: MetadataInput = {
    projectId: effective.projectId,
    projectName: project,
    tagIds: effective.tagIds,
    tagNames: taskTags,
    dueLabel: task.due_date ? dueLabel(task.due_date) : null,
    priority: task.priority,
  };
  const metadataRows = surface.presentation === "rows" ? buildMetadataRows(metadata) : null;
  // FR-009. Until the device has read the queue it cannot know what this
  // identity already has waiting, and an edit made first would be persisted
  // over it. The two rows the queue owns wait, and say why.
  const classification = resolveClassificationAvailability({
    queueEnabled: surface.queueEnabled,
    queueReady: queue.ready,
    // A read that failed withholds them just the same; only the sentence
    // changes, because there is no longer a wait to describe.
    queueReadFailed: queue.readFailed,
  });
  const metadataChips =
    surface.presentation === "chips"
      ? buildMetadataChips({ ...metadata, openTask, stateLabel: STATE_LABELS[task.state] })
      : null;

  // FR-018 / SC-003. The per-task notice names the field and what it reverted
  // to; the account-level one carries the total for the sweeps whose tasks this
  // person may never reopen.
  const expiredNotice = buildExpiredNotice(
    queue.expiredNoticeFor(task.id, serverClassification),
    { project: projectName, tags: tagNames },
    now,
  );
  const accountNotice = resolveAccountExpiryNotice({
    expiredTotal: queue.expiredTotal,
    taskNoticeShown: expiredNotice !== null,
    dismissed: accountNoticeDismissed,
  });

  // `mobile/` installs no NetInfo, so connectivity is inferred from what
  // answered the list requests — see `resolveOnline`.
  const projectsFromCache = servedFromCache(projects.data);
  const tagsFromCache = servedFromCache(tags.data);
  const online = resolveOnline({
    status,
    fromCache: projectsFromCache || tagsFromCache,
    // Only an unreachable server means offline. An HTTP error from a server we
    // did reach keeps `online` true, so the picker renders its error state
    // with a Retry instead of a dead "no connection" message.
    listUnreachable:
      classifySessionFailure(projects.error) === "unreachable" ||
      classifySessionFailure(tags.error) === "unreachable",
    hasServerData:
      (projects.data !== undefined && !projectsFromCache) ||
      (tags.data !== undefined && !tagsFromCache),
  });

  // When the device last read this task from the server — not when the change
  // was made. It dates M-04's "your phone last showed" row; guessing it would
  // be the falsehood that row exists to prevent (FR-010).
  const enqueueClassification = (value: Partial<ClassificationValue>) =>
    queue.enqueue(
      buildClassificationEdit(
        task.id,
        task.revision,
        effective,
        value,
        query.dataUpdatedAt > 0 ? new Date(query.dataUpdatedAt).toISOString() : null,
      ),
    );

  const createProject = async (name: string): Promise<NamedEntity> => {
    // FR-004 — created and attached in one action. A rejection leaves the
    // task's classification untouched, which is what the picker relies on.
    const created = await api.createProject({ name }, newIdempotencyKey());
    await enqueueClassification({ projectId: created.id });
    void projects.refetch();
    return { id: created.id, name: created.name };
  };

  const createTag = async (name: string): Promise<NamedEntity> => {
    const created = await api.createTag({ name }, newIdempotencyKey());
    await enqueueClassification({ tagIds: [...effective.tagIds, created.id] });
    void tags.refetch();
    return { id: created.id, name: created.name };
  };

  const openMetadataRow = (rowId: MetadataRowId) => {
    if (rowId === "project") {
      setProjectPickerVisible(true);
    } else if (rowId === "tags") {
      setTagPickerVisible(true);
    } else if (rowId === "due") {
      setDueVisible(true);
    } else {
      setPriorityVisible(true);
    }
  };

  // M-04 belongs to the task it is about: `server` below is this task's own
  // state, so a conflict queued against another task waits for that screen.
  const queuedConflict =
    queue.conflict && queue.conflict.entry.taskId === task.id ? queue.conflict : undefined;
  // M-04 "dismissed": the question is set aside, not answered. Keyed by the
  // entry, so the next question — including this one re-presented against a
  // fresh revision, which mints a new key — is asked rather than swallowed.
  const conflictAsked =
    queuedConflict !== undefined && dismissedConflict !== queuedConflict.entry.idempotencyKey;
  // What M-04 states the server holds now. The re-read that parked the entry is
  // the only thing on this device that has seen it: a conflicted pass settles
  // nothing, so nothing refetches the copy this screen loaded. "Now on server"
  // is the row "Keep mine, replace theirs" replaces, so it is stated from that
  // read — and from this screen's copy only for an entry parked without one.
  const loadedServerState = { ...serverClassification, revision: task.revision };
  const conflictServer = queuedConflict
    ? conflictServerState(queuedConflict.entry, loadedServerState)
    : loadedServerState;

  const expiredNoticeCard = expiredNotice ? (
    <View style={styles.noticeCard}>
      <View accessible accessibilityRole="text" accessibilityLabel={expiredNotice.accessibilityLabel}>
        {expiredNotice.lines.map((line) => (
          <BBText key={line} variant="caption" color={colors.warningFg}>
            {line}
          </BBText>
        ))}
      </View>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={expiredNotice.dismissLabel}
        onPress={() => void queue.dismissExpiredNotice(task.id)}
        style={styles.noticeDismiss}
      >
        <BBText variant="caption" weight="medium" color={colors.warningFg}>
          {expiredNotice.dismissLabel}
        </BBText>
      </Pressable>
    </View>
  ) : null;

  return (
    <Screen padBottom>
      <TopBar leading="back" />
      <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
        {/* FR-018, account level: one dismiss-once notice with the total, on
            whichever task screen opens next after a sweep. */}
        {accountNotice ? (
          <View style={styles.noticeCard}>
            <BBText variant="caption" color={colors.warningFg}>
              {accountNotice.message}
            </BBText>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={accountNotice.dismissLabel}
              onPress={dismissAccountNotice}
              style={styles.noticeDismiss}
            >
              <BBText variant="caption" weight="medium" color={colors.warningFg}>
                {accountNotice.dismissLabel}
              </BBText>
            </Pressable>
          </View>
        ) : null}
        {conflict ? (
          <View style={styles.conflictCard}>
            <BBText variant="body" color={colors.warningFg}>
              This task changed elsewhere. The latest version is shown — review and retry your edit.
            </BBText>
          </View>
        ) : null}
        {update.isError && !conflict ? <ErrorBanner error={update.error} /> : null}
        {transition.isError && !conflict ? <ErrorBanner error={transition.error} /> : null}

        {/* Title */}
        <View style={styles.checkRow}>
          <Pressable
            accessibilityRole="checkbox"
            accessibilityState={{ checked: done }}
            accessibilityLabel={done ? "Reopen task" : "Complete task"}
            onPress={() => {
              if (transitions.complete) {
                runTransition("complete");
              } else if (transitions.reopen) {
                setReopenVisible(true);
              }
            }}
            hitSlop={11}
            style={[styles.check, done ? styles.checkDone : null]}
          >
            {done ? <Check size={12} color="#FFFFFF" strokeWidth={3} /> : null}
          </Pressable>
          <TextInput
            style={styles.titleInput}
            value={title}
            onChangeText={setTitle}
            multiline
            editable={openTask}
            placeholder="Task title"
            placeholderTextColor={colors.fg6}
            onEndEditing={() => {
              const trimmed = title.trim();
              if (trimmed && trimmed !== task.title) {
                saveField({ title: trimmed });
              } else {
                setTitle(task.title);
              }
            }}
          />
        </View>

        {/* M-01 — four labelled rows, muted placeholders when unset rather than
            hidden rows. The chevron is decorative: the row carries the name and
            the current value (design.md, accessible names). */}
        {metadataRows ? (
          <View style={styles.metaRows}>
            {metadataRows.map((row) => {
              const withheld = !classification.available && rowUsesClassificationQueue(row.id);
              return (
                <Fragment key={row.id}>
                  <Pressable
                    accessibilityRole="button"
                    // The reason is part of the name, so it is heard rather than
                    // inferred from the row looking greyed (design.md).
                    accessibilityLabel={
                      withheld
                        ? `${row.accessibilityLabel}. ${classification.reason}`
                        : row.accessibilityLabel
                    }
                    accessibilityState={{ disabled: withheld }}
                    disabled={withheld}
                    onPress={() => openMetadataRow(row.id)}
                    style={[styles.metaRow, withheld ? styles.metaRowWithheld : null]}
                  >
                    <BBText variant="micro" color={colors.fg5} style={styles.metaRowLabel}>
                      {row.label}
                    </BBText>
                    <View style={styles.metaRowValue}>
                      {row.pills.length > 0 ? (
                        row.pills.map((pill) =>
                          row.id === "project" ? (
                            <View key={pill} style={styles.projectPill}>
                              <BBText variant="caption" color={colors.brandPrimary}>
                                {pill}
                              </BBText>
                            </View>
                          ) : (
                            <TagPill key={pill} name={pill} />
                          ),
                        )
                      ) : (
                        <BBText
                          variant="body"
                          color={row.placeholder ? colors.fg6 : colors.fg2}
                          numberOfLines={1}
                        >
                          {row.value}
                        </BBText>
                      )}
                    </View>
                    <View
                      accessibilityElementsHidden
                      importantForAccessibility="no-hide-descendants"
                    >
                      <ChevronRight size={18} color={colors.fg6} strokeWidth={2} />
                    </View>
                  </Pressable>
                  {/* One sentence for the two rows it explains, under the later
                      of them, so it is read as being about both. */}
                  {withheld && row.id === "tags" ? (
                    <BBText variant="micro" color={colors.fg5}>
                      {classification.reason}
                    </BBText>
                  ) : null}
                  {/* FR-018: the notice names the field and what it reverted to,
                      and its labelled Dismiss sits in tab order right after the
                      row it explains. */}
                  {expiredNotice?.anchor === row.id ? expiredNoticeCard : null}
                </Fragment>
              );
            })}
          </View>
        ) : null}

        {/* M-01c — with the rollout flag off this is today's chip row exactly:
            values shown, no controls this feature added, no disabled rows. */}
        {metadataChips ? (
          <View style={styles.chipRowIndented}>
            {metadataChips.map((chip) => {
              if (chip.kind === "due") {
                return (
                  <Pressable
                    key={chip.key}
                    accessibilityRole="button"
                    accessibilityLabel={chip.accessibilityLabel}
                    disabled={chip.disabled}
                    onPress={() => setDueVisible(true)}
                    style={styles.dueChip}
                  >
                    <Calendar size={11} color={colors.dueFg} strokeWidth={2} />
                    <BBText variant="micro" color={colors.dueFg}>
                      {chip.label}
                    </BBText>
                  </Pressable>
                );
              }
              if (chip.kind === "add-due") {
                return (
                  <Pressable
                    key={chip.key}
                    accessibilityRole="button"
                    accessibilityLabel={chip.accessibilityLabel}
                    onPress={() => setDueVisible(true)}
                    style={styles.addChip}
                  >
                    <Calendar size={11} color={colors.fg6} strokeWidth={2} />
                    <BBText variant="micro" color={colors.fg6}>
                      {chip.label}
                    </BBText>
                  </Pressable>
                );
              }
              if (chip.kind === "priority") {
                return (
                  <Pressable
                    key={chip.key}
                    accessibilityRole="button"
                    accessibilityLabel={chip.accessibilityLabel}
                    disabled={chip.disabled}
                    onPress={() => setPriorityVisible(true)}
                    style={styles.neutralChip}
                  >
                    <View
                      style={[
                        styles.priorityDot,
                        { backgroundColor: PRIORITY_COLORS[chip.priority] },
                      ]}
                    />
                    <BBText variant="micro" color={colors.fg4}>
                      {chip.label}
                    </BBText>
                  </Pressable>
                );
              }
              if (chip.kind === "add-priority") {
                return (
                  <Pressable
                    key={chip.key}
                    accessibilityRole="button"
                    accessibilityLabel={chip.accessibilityLabel}
                    onPress={() => setPriorityVisible(true)}
                    style={styles.addChip}
                  >
                    <Flag size={11} color={colors.fg6} strokeWidth={2} />
                    <BBText variant="micro" color={colors.fg6}>
                      {chip.label}
                    </BBText>
                  </Pressable>
                );
              }
              if (chip.kind === "tag") {
                return <TagPill key={chip.key} name={chip.label} />;
              }
              return (
                <BBText key={chip.key} variant="micro" color={colors.fg6}>
                  {chip.label}
                </BBText>
              );
            })}
          </View>
        ) : null}
        {/* The chip presentation has no row to anchor to, so the notice follows
            the chips. FR-018 is a MUST regardless of which presentation the
            screen is carrying — a completed task can hold a dropped change too. */}
        {metadataChips ? expiredNoticeCard : null}

        {task.state === "waiting" ? (
          <View style={styles.waitingBlock}>
            <BBText variant="label">Waiting for</BBText>
            <TextInput
              style={styles.waitingInput}
              value={waitingDraft}
              onChangeText={setWaitingDraft}
              placeholder="Who or what are you waiting on?"
              placeholderTextColor={colors.fg6}
              onEndEditing={() => {
                const trimmed = waitingDraft.trim();
                if (trimmed && trimmed !== task.waiting_for) {
                  saveField({ waiting_for: trimmed });
                } else if (!trimmed) {
                  setWaitingDraft(task.waiting_for ?? "");
                }
              }}
            />
            {task.waiting_since ? (
              <BBText variant="micro" color={colors.fg5}>
                {`Since ${new Date(task.waiting_since).toLocaleDateString()}`}
              </BBText>
            ) : null}
          </View>
        ) : null}

        <View style={styles.divider} />

        {/* Details: quiet — text when present, ghost affordance when not */}
        {showDetailsEditor ? (
          <View style={styles.field}>
            <BBText variant="label">Details</BBText>
            <TextInput
              style={styles.detailsInput}
              value={details}
              onChangeText={setDetails}
              multiline
              autoFocus={detailsOpen && !hasDetails}
              editable={openTask}
              placeholder="Notes, links, context…"
              placeholderTextColor={colors.fg6}
              onEndEditing={() => {
                const next = details.trim() ? details : null;
                if ((next ?? "") !== (task.details ?? "")) {
                  saveField({ details: next });
                }
                if (!next) {
                  setDetailsOpen(false);
                }
              }}
            />
          </View>
        ) : openTask ? (
          <Pressable
            accessibilityRole="button"
            onPress={() => setDetailsOpen(true)}
            style={styles.ghostAdd}
          >
            <BBText variant="caption" color={colors.fg6}>
              Add details…
            </BBText>
          </Pressable>
        ) : null}

        {/* Subtasks */}
        <View style={styles.field}>
          <BBText variant="label">Subtasks</BBText>
          {(task.subtasks ?? []).map((subtask) => {
            const subDone = subtask.state === "completed";
            const subCancelled = subtask.state === "cancelled";
            return (
              <View key={subtask.id} style={styles.subtaskRow}>
                <Pressable
                  accessibilityRole="checkbox"
                  accessibilityState={{ checked: subDone }}
                  accessibilityLabel={subDone ? "Reopen subtask" : "Complete subtask"}
                  disabled={!openTask || subCancelled || transitionSubtask.isPending}
                  onPress={() =>
                    transitionSubtask.mutate({
                      subtaskId: subtask.id,
                      action: subDone ? "reopen" : "complete",
                      expectedRevision: subtask.revision,
                    })
                  }
                  hitSlop={12}
                  style={[styles.subtaskCheck, subDone ? styles.subtaskCheckDone : null]}
                >
                  {subDone ? <Check size={10} color="#FFFFFF" strokeWidth={3} /> : null}
                </Pressable>
                <BBText
                  variant="body"
                  color={subtask.state === "open" ? colors.fg2 : colors.fg6}
                  style={[styles.subtaskTitle, subDone ? styles.subtaskDone : null]}
                >
                  {subtask.title}
                </BBText>
              </View>
            );
          })}
          {openTask ? (
            <TextInput
              style={styles.addInput}
              value={subtaskDraft}
              onChangeText={setSubtaskDraft}
              placeholder="Add a subtask"
              placeholderTextColor={colors.fg6}
              editable={!createSubtask.isPending}
              onSubmitEditing={() => {
                const trimmed = subtaskDraft.trim();
                if (trimmed) {
                  createSubtask.mutate(trimmed, { onSuccess: () => setSubtaskDraft("") });
                }
              }}
              returnKeyType="done"
            />
          ) : null}
          {createSubtask.isError ? <ErrorBanner error={createSubtask.error} /> : null}
          {transitionSubtask.isError ? <ErrorBanner error={transitionSubtask.error} /> : null}
        </View>

        {/* Comments */}
        <View style={styles.field}>
          <BBText variant="label">Comments</BBText>
          {(task.comments ?? []).map((comment) => (
            <View key={comment.id} style={styles.comment}>
              <View style={styles.commentAvatar}>
                <BBText style={styles.commentAvatarText}>{ownInitials(me?.email)}</BBText>
              </View>
              <View style={styles.commentBody}>
                <BBText variant="micro" color={colors.fg5}>
                  {relativeTime(comment.created_at)}
                  {comment.edited_at ? " · edited" : ""}
                </BBText>
                <BBText variant="body" color={colors.fg2}>
                  {comment.body}
                </BBText>
              </View>
            </View>
          ))}
          {openTask ? (
            <TextInput
              style={styles.addInput}
              value={commentDraft}
              onChangeText={setCommentDraft}
              placeholder="Add a comment"
              placeholderTextColor={colors.fg6}
              editable={!createComment.isPending}
              multiline
              blurOnSubmit
              onSubmitEditing={() => {
                const trimmed = commentDraft.trim();
                if (trimmed) {
                  createComment.mutate(trimmed, { onSuccess: () => setCommentDraft("") });
                }
              }}
              returnKeyType="done"
            />
          ) : null}
          {createComment.isError ? <ErrorBanner error={createComment.error} /> : null}
        </View>

        {/* Quiet footer actions */}
        <View style={styles.actions}>
          {openTask ? (
            <Button variant="secondary" onPress={() => setMoveVisible(true)}>
              Move to…
            </Button>
          ) : null}
          {transitions.reopen ? (
            <Button variant="secondary" onPress={() => setReopenVisible(true)}>
              Reopen…
            </Button>
          ) : null}
          {transitions.cancel ? (
            <Pressable
              accessibilityRole="button"
              onPress={() => runTransition("cancel")}
              disabled={transition.isPending}
              style={styles.cancelAction}
            >
              <BBText variant="caption" weight="medium" color={colors.dangerFg}>
                Cancel task
              </BBText>
            </Pressable>
          ) : null}
        </View>

        <BBText variant="micro" color={colors.fg6} style={styles.metaLine}>
          {`Created ${new Date(task.created_at).toLocaleDateString()} · revision ${task.revision}`}
        </BBText>

        {/* SC-004 / FR-007 — how current the screen is, said once for the whole
            screen. Words, never a coloured dot, and never per-change. */}
        {surface.queueEnabled ? (
          <View
            accessible
            accessibilityRole="text"
            accessibilityLabel={footer.accessibilityLabel}
            accessibilityLiveRegion="polite"
            style={styles.syncFooter}
          >
            <BBText variant="micro" color={colors.fg5}>
              {footer.label}
            </BBText>
          </View>
        ) : null}
      </ScrollView>

      {/* Due date sheet */}
      <Sheet visible={dueVisible} onClose={() => setDueVisible(false)} title="Due date">
        <View style={styles.sheetChipRow}>
          {(
            [
              ["Today", isoDatePlus(0)],
              ["Tomorrow", isoDatePlus(1)],
              ["Next week", isoDatePlus(7)],
            ] as const
          ).map(([label, value]) => (
            <Button
              key={label}
              variant="secondary"
              style={styles.sheetChip}
              onPress={() => {
                setDueDraft(value);
                saveField({ due_date: value });
                setDueVisible(false);
              }}
            >
              {label}
            </Button>
          ))}
        </View>
        <TextInput
          style={styles.sheetInput}
          value={dueDraft}
          onChangeText={setDueDraft}
          placeholder="YYYY-MM-DD"
          placeholderTextColor={colors.fg6}
          autoCapitalize="none"
          autoCorrect={false}
          onSubmitEditing={() => {
            const trimmed = dueDraft.trim();
            if (/^\d{4}-\d{2}-\d{2}$/.test(trimmed) && trimmed !== task.due_date) {
              saveField({ due_date: trimmed });
              setDueVisible(false);
            }
          }}
          returnKeyType="done"
        />
        {task.due_date ? (
          <Button
            variant="ghost"
            onPress={() => {
              setDueDraft("");
              saveField({ due_date: null });
              setDueVisible(false);
            }}
          >
            Clear due date
          </Button>
        ) : null}
      </Sheet>

      {/* Priority sheet */}
      <Sheet visible={priorityVisible} onClose={() => setPriorityVisible(false)} title="Priority">
        <View style={styles.sheetChipRow}>
          {PRIORITIES.map((priority) => {
            const selected = task.priority === priority;
            return (
              <Pressable
                key={priority}
                accessibilityRole="button"
                accessibilityState={{ selected }}
                onPress={() => {
                  if (!selected) {
                    saveField({ priority });
                  }
                  setPriorityVisible(false);
                }}
                style={[styles.priorityOption, selected ? styles.priorityOptionSelected : null]}
              >
                <BBText variant="body" weight="medium" color={selected ? "#FFFFFF" : colors.fg3}>
                  {PRIORITY_LABELS[priority]}
                </BBText>
              </Pressable>
            );
          })}
        </View>
      </Sheet>

      {/* Move sheet */}
      <Sheet
        visible={moveVisible}
        onClose={() => {
          setMoveVisible(false);
          setMoveGuardError(null);
        }}
        title="Move to"
      >
        <StatePicker value={moveTarget} onChange={setMoveTarget} options={transitions.moveTargets} />
        {moveTarget === "waiting" ? (
          <View style={styles.field}>
            <BBText variant="label">Waiting for</BBText>
            <TextInput
              style={styles.sheetInput}
              value={moveWaitingFor}
              onChangeText={setMoveWaitingFor}
              placeholder="Who or what are you waiting on?"
              placeholderTextColor={colors.fg6}
            />
          </View>
        ) : null}
        {moveGuardError ? (
          <BBText variant="caption" color={colors.dangerFg}>
            {moveGuardError}
          </BBText>
        ) : null}
        <Button
          onPress={() => {
            if (moveTarget) {
              runTransition("move", moveTarget, moveWaitingFor);
            }
          }}
          disabled={!moveTarget}
          loading={transition.isPending}
        >
          Move
        </Button>
      </Sheet>

      <ReopenSheet
        task={reopenVisible ? task : null}
        onClose={() => setReopenVisible(false)}
        onReopen={(payload) => {
          transition.mutate({ payload }, { onSettled: () => setReopenVisible(false) });
        }}
        pending={transition.isPending}
        error={transition.isError ? transition.error : null}
      />

      {/* M-02 / M-03. Mounted only where the rows are, so the flag-off screen
          carries none of this feature's controls at all. */}
      {surface.presentation === "rows" ? (
        <>
          <ProjectPicker
            visible={projectPickerVisible}
            onClose={() => setProjectPickerVisible(false)}
            value={
              effective.projectId === null
                ? null
                : { id: effective.projectId, ...(project === undefined ? {} : { name: project }) }
            }
            onSelect={(projectId) => {
              void enqueueClassification({ projectId });
            }}
            onCreate={createProject}
            projects={projects.data ?? null}
            listPhase={resolveListPhase({
              pending: projects.isPending,
              failed: projects.isError,
              hasData: projects.data !== undefined,
            })}
            online={online}
            onRetry={() => {
              void projects.refetch();
            }}
          />
          <TagPicker
            visible={tagPickerVisible}
            onClose={() => setTagPickerVisible(false)}
            attached={attachedEntities(effective.tagIds, tags.data ?? null)}
            onChange={(tagIds) => {
              void enqueueClassification({ tagIds });
            }}
            onCreate={createTag}
            tags={tags.data ?? null}
            listPhase={resolveListPhase({
              pending: tags.isPending,
              failed: tags.isError,
              hasData: tags.data !== undefined,
            })}
            online={online}
            onRetry={() => {
              void tags.refetch();
            }}
          />
        </>
      ) : null}

      {/* M-04 — SC-005: nothing is resolved without the person choosing. */}
      <ConflictSheet
        visible={conflictAsked}
        conflict={queuedConflict}
        server={conflictServer}
        // The entry now carries why it was parked, so a 404 on a deleted
        // target gets the discard-only sheet instead of being offered "Keep
        // mine, replace theirs" for something that no longer exists. Falls
        // back to a stale revision only for an entry parked before the reason
        // was recorded.
        reason={(queue.conflict?.entry.conflictReason as DecisionReason) ?? "stale-revision"}
        names={{ projects: projects.data ?? null, tags: tags.data ?? null }}
        deviceObservedAt={queue.lastSyncedAt}
        onKeepMine={() => queue.keepMine(task.revision)}
        onDiscardMine={() => queue.discardMine(task.revision)}
        onDismiss={() => {
          // "Not yet answered": nothing is resolved and nothing discarded, and
          // the entry stays exactly as it is. Only this screen, for as long as
          // it is open, stops asking — so the sheet returns on the next visit,
          // which M-04 makes the only reminder there is. Leaving the sheet up
          // instead would trap the person on a question they may not be able
          // to answer yet: the scrim and the platform back gesture would both
          // do nothing.
          setDismissedConflict(queuedConflict?.entry.idempotencyKey ?? null);
        }}
        now={now}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  center: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    padding: space.s5,
  },
  scroll: {
    padding: space.s4,
    paddingTop: 18,
    gap: space.s4,
  },
  conflictCard: {
    backgroundColor: colors.warningBg,
    borderWidth: 1,
    borderColor: colors.warningBorder,
    borderRadius: radii.card,
    padding: space.s4,
  },
  checkRow: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: space.s3,
    marginBottom: -space.s2,
  },
  check: {
    width: 22,
    height: 22,
    marginTop: 3,
    borderRadius: radii.full,
    borderWidth: 1.5,
    borderColor: colors.fg7,
    backgroundColor: colors.surfaceRaised,
    alignItems: "center",
    justifyContent: "center",
  },
  checkDone: {
    backgroundColor: colors.brandPrimary,
    borderColor: colors.brandPrimary,
  },
  titleInput: {
    flex: 1,
    fontSize: typeScale.title,
    lineHeight: Math.round(typeScale.title * 1.3),
    letterSpacing: -0.3,
    fontFamily: fonts.semibold,
    color: colors.fg1,
    padding: 0,
  },
  chipRowIndented: {
    flexDirection: "row",
    flexWrap: "wrap",
    alignItems: "center",
    gap: 6,
    paddingLeft: 34,
  },
  metaRows: {
    gap: space.s2,
  },
  // 52 px per design.md's mobile viability note; comfortably over the 44 pt
  // minimum for the whole row, which is the tap target.
  metaRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: space.s2,
    minHeight: 52,
    paddingHorizontal: 14,
    paddingVertical: space.s2,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radii.md,
    backgroundColor: colors.surfaceRaised,
  },
  // Muted as well as unavailable — never *instead of* the sentence beneath.
  metaRowWithheld: {
    backgroundColor: colors.surfaceSunken,
  },
  metaRowLabel: {
    width: 64,
    textTransform: "uppercase",
    letterSpacing: 0.4,
  },
  metaRowValue: {
    flex: 1,
    flexDirection: "row",
    flexWrap: "wrap",
    alignItems: "center",
    gap: 4,
  },
  projectPill: {
    borderRadius: radii.full,
    paddingHorizontal: 9,
    paddingVertical: 2,
    backgroundColor: colors.brandPrimarySoft,
  },
  noticeCard: {
    backgroundColor: colors.warningBg,
    borderWidth: 1,
    borderColor: colors.warningBorder,
    borderRadius: radii.md,
    padding: space.s3,
    gap: space.s2,
  },
  noticeDismiss: {
    alignSelf: "flex-start",
    minHeight: minHitTarget,
    justifyContent: "center",
    paddingHorizontal: space.s3,
    borderWidth: 1,
    borderColor: colors.warningBorder,
    borderRadius: radii.sm,
  },
  syncFooter: {
    alignItems: "center",
    paddingTop: space.s2,
  },
  dueChip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 5,
    borderRadius: radii.full,
    paddingHorizontal: space.s2,
    paddingVertical: 3,
    backgroundColor: colors.dueBg,
    borderWidth: 1,
    borderColor: colors.dueBorder,
  },
  addChip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 5,
    height: 24,
    paddingHorizontal: space.s2,
    borderRadius: radii.full,
    borderWidth: 1.5,
    borderStyle: "dashed",
    borderColor: colors.fg7,
  },
  neutralChip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 5,
    height: 24,
    paddingHorizontal: 9,
    borderRadius: radii.full,
    backgroundColor: colors.tagBg,
  },
  priorityDot: {
    width: 7,
    height: 7,
    borderRadius: radii.full,
  },
  waitingBlock: {
    gap: space.s2,
    paddingLeft: 34,
  },
  waitingInput: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radii.sm,
    paddingHorizontal: space.s3,
    paddingVertical: space.s2,
    fontSize: typeScale.body,
    fontFamily: fonts.regular,
    color: colors.fg1,
    backgroundColor: colors.surfaceRaised,
    minHeight: 40,
  },
  divider: {
    height: 1,
    backgroundColor: colors.border,
  },
  field: {
    gap: space.s2,
  },
  ghostAdd: {
    minHeight: 32,
    justifyContent: "center",
  },
  detailsInput: {
    fontSize: typeScale.body,
    lineHeight: Math.round(typeScale.body * 1.5),
    fontFamily: fonts.regular,
    color: colors.fg2,
    padding: 0,
    minHeight: 24,
    textAlignVertical: "top",
  },
  subtaskRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: space.s2,
    minHeight: 32,
  },
  subtaskCheck: {
    width: 18,
    height: 18,
    borderRadius: radii.full,
    borderWidth: 1.5,
    borderColor: colors.fg7,
    backgroundColor: colors.surfaceRaised,
    alignItems: "center",
    justifyContent: "center",
  },
  subtaskCheckDone: {
    backgroundColor: colors.brandPrimary,
    borderColor: colors.brandPrimary,
  },
  subtaskTitle: {
    flex: 1,
  },
  subtaskDone: {
    textDecorationLine: "line-through",
  },
  addInput: {
    borderWidth: 1.5,
    borderStyle: "dashed",
    borderColor: colors.fg7,
    borderRadius: 12,
    paddingHorizontal: space.s3,
    paddingVertical: 11,
    fontSize: typeScale.body,
    fontFamily: fonts.regular,
    color: colors.fg1,
    minHeight: 44,
    marginTop: space.s1,
  },
  comment: {
    flexDirection: "row",
    gap: space.s2,
    alignItems: "flex-start",
  },
  commentAvatar: {
    width: 26,
    height: 26,
    borderRadius: radii.full,
    backgroundColor: "#E0F2FE",
    alignItems: "center",
    justifyContent: "center",
    marginTop: 1,
  },
  commentAvatarText: {
    fontSize: 10,
    fontFamily: fonts.semibold,
    color: "#0369A1",
  },
  commentBody: {
    flex: 1,
    gap: 2,
  },
  actions: {
    gap: space.s2,
    marginTop: space.s3,
  },
  cancelAction: {
    minHeight: 44,
    alignItems: "center",
    justifyContent: "center",
  },
  metaLine: {
    textAlign: "center",
    marginTop: space.s1,
  },
  sheetChipRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: space.s2,
  },
  sheetChip: {
    minHeight: 40,
    paddingHorizontal: space.s4,
  },
  sheetInput: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radii.sm,
    paddingHorizontal: space.s3,
    paddingVertical: space.s3,
    fontSize: typeScale.body,
    fontFamily: fonts.regular,
    color: colors.fg1,
    backgroundColor: colors.surfaceRaised,
    minHeight: 44,
  },
  priorityOption: {
    minHeight: 44,
    paddingHorizontal: space.s5,
    borderRadius: radii.full,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surfaceRaised,
    alignItems: "center",
    justifyContent: "center",
  },
  priorityOptionSelected: {
    backgroundColor: colors.brandPrimary,
    borderColor: colors.brandPrimary,
  },
});
