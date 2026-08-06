import { useLocalSearchParams } from "expo-router";
import { Calendar, Check } from "lucide-react-native";
import { useEffect, useMemo, useState } from "react";
import {
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
import { ReopenSheet } from "@/features/tasks/ReopenSheet";
import { StatePicker } from "@/features/tasks/StatePicker";
import { useClassificationNames } from "@/features/tasks/useClassificationNames";
import { availableTransitions, buildTransition } from "@/lifecycle/guards";
import { colors, fonts, radii, space, type as typeScale } from "@/theme/tokens";

const STATE_LABELS: Record<string, string> = {
  inbox: "Inbox",
  next: "Next actions",
  waiting: "Waiting for",
  someday: "Someday / maybe",
  completed: "Completed",
  cancelled: "Cancelled",
};

const PRIORITIES: TaskPriority[] = ["none", "low", "medium", "high"];

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
  const { id, from } = useLocalSearchParams<{ id: string; from?: string }>();
  const query = useTask(id);
  const update = useUpdateTask(id);
  const transition = useTransitionTask(id);
  const createSubtask = useCreateSubtask(id);
  const transitionSubtask = useTransitionSubtask(id);
  const createComment = useCreateComment(id);
  const { projectName, tagNames } = useClassificationNames();
  const { me } = useSession();

  const task = query.data;

  const [title, setTitle] = useState("");
  const [details, setDetails] = useState("");
  const [dueDraft, setDueDraft] = useState("");
  const [waitingDraft, setWaitingDraft] = useState("");
  const [subtaskDraft, setSubtaskDraft] = useState("");
  const [commentDraft, setCommentDraft] = useState("");
  const [moveVisible, setMoveVisible] = useState(false);
  const [moveTarget, setMoveTarget] = useState<OpenTaskState | null>(null);
  const [moveWaitingFor, setMoveWaitingFor] = useState("");
  const [moveGuardError, setMoveGuardError] = useState<string | null>(null);
  const [reopenVisible, setReopenVisible] = useState(false);

  // Sync drafts from the server copy whenever a fresh revision arrives —
  // including after a 409 refetch (edits in progress are the user's to redo
  // deliberately; we never silently overwrite the server).
  useEffect(() => {
    if (task) {
      setTitle(task.title);
      setDetails(task.details ?? "");
      setDueDraft(task.due_date ?? "");
      setWaitingDraft(task.waiting_for ?? "");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [task?.id, task?.revision]);

  const transitions = useMemo(() => (task ? availableTransitions(task) : null), [task]);

  if (query.isLoading || !task || !transitions) {
    return (
      <Screen>
        <TopBar leading="back" title={from} />
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
  const taskTags = tagNames(task.tag_ids);
  const project = projectName(task.project_id);

  return (
    <Screen padBottom>
      <TopBar leading="back" title={from ?? STATE_LABELS[task.state]} />
      <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
        {conflict ? (
          <View style={styles.conflictCard}>
            <BBText variant="body" color={colors.warningFg}>
              This task changed elsewhere. The latest version is shown — review and retry your edit.
            </BBText>
          </View>
        ) : null}
        {update.isError && !conflict ? <ErrorBanner error={update.error} /> : null}
        {transition.isError && !conflict ? <ErrorBanner error={transition.error} /> : null}

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

        <View style={styles.chipRowIndented}>
          {task.due_date ? (
            <View style={styles.dueChip}>
              <Calendar size={11} color={colors.dueFg} strokeWidth={2} />
              <BBText variant="micro" color={colors.dueFg}>
                {dueLabel(task.due_date)}
              </BBText>
            </View>
          ) : null}
          {taskTags.map((name) => (
            <TagPill key={name} name={name} />
          ))}
          {project ? (
            <BBText variant="micro" color={colors.fg6}>
              {project}
            </BBText>
          ) : null}
          <BBText variant="micro" color={colors.fg6}>
            {STATE_LABELS[task.state]}
          </BBText>
        </View>

        <View style={styles.field}>
          <BBText variant="label">Details</BBText>
          <TextInput
            style={[styles.input, styles.detailsInput]}
            value={details}
            onChangeText={setDetails}
            multiline
            placeholder="Notes, links, context…"
            placeholderTextColor={colors.fg6}
            onEndEditing={() => {
              const next = details.trim() ? details : null;
              if ((next ?? "") !== (task.details ?? "")) {
                saveField({ details: next });
              }
            }}
          />
        </View>

        {task.state === "waiting" ? (
          <View style={styles.field}>
            <BBText variant="label">Waiting for</BBText>
            <TextInput
              style={styles.input}
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
              <BBText variant="caption" color={colors.fg5}>
                {`Waiting since ${new Date(task.waiting_since).toLocaleDateString()}`}
              </BBText>
            ) : null}
          </View>
        ) : null}

        <View style={styles.field}>
          <BBText variant="label">Due date</BBText>
          <View style={styles.chipRow}>
            <Button
              variant="secondary"
              style={styles.smallButton}
              onPress={() => {
                setDueDraft(isoDatePlus(0));
                saveField({ due_date: isoDatePlus(0) });
              }}
            >
              Today
            </Button>
            <Button
              variant="secondary"
              style={styles.smallButton}
              onPress={() => {
                setDueDraft(isoDatePlus(1));
                saveField({ due_date: isoDatePlus(1) });
              }}
            >
              Tomorrow
            </Button>
            <Button
              variant="secondary"
              style={styles.smallButton}
              onPress={() => {
                setDueDraft(isoDatePlus(7));
                saveField({ due_date: isoDatePlus(7) });
              }}
            >
              Next week
            </Button>
            {task.due_date ? (
              <Button
                variant="ghost"
                style={styles.smallButton}
                onPress={() => {
                  setDueDraft("");
                  saveField({ due_date: null });
                }}
              >
                Clear
              </Button>
            ) : null}
          </View>
          <TextInput
            style={styles.input}
            value={dueDraft}
            onChangeText={setDueDraft}
            placeholder="YYYY-MM-DD"
            placeholderTextColor={colors.fg6}
            autoCapitalize="none"
            autoCorrect={false}
            onEndEditing={() => {
              const trimmed = dueDraft.trim();
              if (!trimmed && task.due_date) {
                saveField({ due_date: null });
                return;
              }
              if (/^\d{4}-\d{2}-\d{2}$/.test(trimmed) && trimmed !== task.due_date) {
                saveField({ due_date: trimmed });
              } else if (trimmed && !/^\d{4}-\d{2}-\d{2}$/.test(trimmed)) {
                setDueDraft(task.due_date ?? "");
              }
            }}
          />
        </View>

        <View style={styles.field}>
          <BBText variant="label">Priority</BBText>
          <View style={styles.chipRow}>
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
                  }}
                  style={[styles.priorityChip, selected ? styles.priorityChipSelected : null]}
                >
                  <BBText variant="body" weight="medium" color={selected ? "#FFFFFF" : colors.fg3}>
                    {priority === "none" ? "None" : priority[0].toUpperCase() + priority.slice(1)}
                  </BBText>
                </Pressable>
              );
            })}
          </View>
        </View>

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
            <Button
              variant="destructive"
              onPress={() => runTransition("cancel")}
              loading={transition.isPending}
            >
              Cancel task
            </Button>
          ) : null}
        </View>

        <BBText variant="micro" color={colors.fg6} style={styles.metaLine}>
          {`Created ${new Date(task.created_at).toLocaleDateString()} · revision ${task.revision}`}
        </BBText>
      </ScrollView>

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
              style={styles.input}
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
  field: {
    gap: space.s2,
  },
  input: {
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
  detailsInput: {
    minHeight: 88,
    textAlignVertical: "top",
  },
  chipRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: space.s2,
  },
  dueChip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 5,
    borderRadius: radii.full,
    paddingHorizontal: space.s2,
    paddingVertical: 2,
    backgroundColor: colors.dueBg,
    borderWidth: 1,
    borderColor: colors.dueBorder,
  },
  smallButton: {
    minHeight: 36,
    paddingHorizontal: space.s3,
  },
  priorityChip: {
    minHeight: 36,
    paddingHorizontal: space.s4,
    borderRadius: radii.full,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surfaceRaised,
    alignItems: "center",
    justifyContent: "center",
  },
  priorityChipSelected: {
    backgroundColor: colors.brandPrimary,
    borderColor: colors.brandPrimary,
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
    marginTop: space.s2,
  },
  metaLine: {
    textAlign: "center",
    marginTop: space.s2,
  },
});
