import { useLocalSearchParams, useRouter } from "expo-router";
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
import { useTask, useTransitionTask, useUpdateTask } from "@/api/hooks";
import type { OpenTaskState, TaskPriority, TaskUpdateRequest } from "@/api/types";
import { BBText } from "@/components/BBText";
import { Button } from "@/components/Button";
import { ErrorBanner } from "@/components/ErrorBanner";
import { Screen } from "@/components/Screen";
import { Sheet } from "@/components/Sheet";
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

export default function TaskDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const query = useTask(id);
  const update = useUpdateTask(id);
  const transition = useTransitionTask(id);
  const { projectName, tagNames } = useClassificationNames();

  const task = query.data;

  const [title, setTitle] = useState("");
  const [details, setDetails] = useState("");
  const [dueDraft, setDueDraft] = useState("");
  const [waitingDraft, setWaitingDraft] = useState("");
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

  const transitions = useMemo(
    () => (task ? availableTransitions(task) : null),
    [task],
  );

  if (query.isLoading || !task || !transitions) {
    return (
      <Screen padTop>
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
      return false;
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
    return true;
  };

  const openTask = transitions.moveTargets.length > 0;

  return (
    <Screen padBottom>
      <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
        <View style={styles.topRow}>
          <BBText variant="label">{STATE_LABELS[task.state]}</BBText>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Close"
            onPress={() => router.back()}
            style={styles.closeButton}
          >
            <BBText variant="body" color={colors.brandPrimary}>
              Done
            </BBText>
          </Pressable>
        </View>

        {conflict ? (
          <View style={styles.conflictCard}>
            <BBText variant="body" color={colors.warningFg}>
              This task changed elsewhere. The latest version is shown — review and retry your edit.
            </BBText>
          </View>
        ) : null}
        {update.isError && !conflict ? <ErrorBanner error={update.error} /> : null}
        {transition.isError && !conflict ? <ErrorBanner error={transition.error} /> : null}

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
            <Button variant="secondary" style={styles.smallButton} onPress={() => {
              setDueDraft(isoDatePlus(0));
              saveField({ due_date: isoDatePlus(0) });
            }}>
              Today
            </Button>
            <Button variant="secondary" style={styles.smallButton} onPress={() => {
              setDueDraft(isoDatePlus(1));
              saveField({ due_date: isoDatePlus(1) });
            }}>
              Tomorrow
            </Button>
            <Button variant="secondary" style={styles.smallButton} onPress={() => {
              setDueDraft(isoDatePlus(7));
              saveField({ due_date: isoDatePlus(7) });
            }}>
              Next week
            </Button>
            {task.due_date ? (
              <Button variant="ghost" style={styles.smallButton} onPress={() => {
                setDueDraft("");
                saveField({ due_date: null });
              }}>
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
                  <BBText
                    variant="body"
                    weight="medium"
                    color={selected ? "#FFFFFF" : colors.fg3}
                  >
                    {priority === "none" ? "None" : priority[0].toUpperCase() + priority.slice(1)}
                  </BBText>
                </Pressable>
              );
            })}
          </View>
        </View>

        <View style={styles.field}>
          <BBText variant="label">Organization</BBText>
          <View style={styles.card}>
            <BBText variant="body" color={colors.fg3}>
              {projectName(task.project_id)
                ? `Project · ${projectName(task.project_id)}`
                : "No project"}
            </BBText>
            <BBText variant="body" color={colors.fg3}>
              {task.tag_ids.length > 0
                ? `Tags · ${tagNames(task.tag_ids).join(", ")}`
                : "No tags"}
            </BBText>
            <BBText variant="caption" color={colors.fg5}>
              Assign projects and tags on the web app for now.
            </BBText>
          </View>
        </View>

        {task.subtasks && task.subtasks.length > 0 ? (
          <View style={styles.field}>
            <BBText variant="label">Subtasks</BBText>
            <View style={styles.card}>
              {task.subtasks.map((subtask) => (
                <BBText
                  key={subtask.id}
                  variant="body"
                  color={subtask.state === "open" ? colors.fg2 : colors.fg6}
                >
                  {`${subtask.state === "completed" ? "✓ " : subtask.state === "cancelled" ? "✕ " : "○ "}${subtask.title}`}
                </BBText>
              ))}
            </View>
          </View>
        ) : null}

        {task.comments && task.comments.length > 0 ? (
          <View style={styles.field}>
            <BBText variant="label">Comments</BBText>
            <View style={styles.card}>
              {task.comments.map((comment) => (
                <View key={comment.id} style={styles.comment}>
                  <BBText variant="body" color={colors.fg2}>
                    {comment.body}
                  </BBText>
                  <BBText variant="micro" color={colors.fg5}>
                    {new Date(comment.created_at).toLocaleString()}
                  </BBText>
                </View>
              ))}
            </View>
          </View>
        ) : null}

        <View style={styles.actions}>
          {transitions.complete ? (
            <Button
              onPress={() => runTransition("complete")}
              loading={transition.isPending}
            >
              Complete
            </Button>
          ) : null}
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

        <BBText variant="micro" color={colors.fg6} style={styles.meta}>
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
        <StatePicker
          value={moveTarget}
          onChange={setMoveTarget}
          options={transitions.moveTargets}
        />
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
          transition.mutate(
            { payload },
            { onSettled: () => setReopenVisible(false) },
          );
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
    padding: space.s5,
    gap: space.s4,
  },
  topRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  closeButton: {
    minHeight: 44,
    justifyContent: "center",
  },
  conflictCard: {
    backgroundColor: colors.warningBg,
    borderWidth: 1,
    borderColor: colors.warningBorder,
    borderRadius: radii.card,
    padding: space.s4,
  },
  titleInput: {
    fontSize: typeScale.title,
    lineHeight: Math.round(typeScale.title * 1.3),
    fontFamily: fonts.semibold,
    color: colors.fg1,
    padding: 0,
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
  card: {
    backgroundColor: colors.surfaceRaised,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radii.card,
    padding: space.s4,
    gap: space.s2,
  },
  comment: {
    gap: 2,
  },
  actions: {
    gap: space.s2,
    marginTop: space.s2,
  },
  meta: {
    textAlign: "center",
    marginTop: space.s2,
  },
});
