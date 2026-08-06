import { useState } from "react";
import { StyleSheet, TextInput, View } from "react-native";

import { useCreateTask } from "@/api/hooks";
import type { OpenTaskState, TaskCreateRequest } from "@/api/types";
import { BBText } from "@/components/BBText";
import { Button } from "@/components/Button";
import { ErrorBanner } from "@/components/ErrorBanner";
import { Sheet } from "@/components/Sheet";
import { colors, fonts, radii, space, type as typeScale } from "@/theme/tokens";

interface QuickAddSheetProps {
  visible: boolean;
  onClose: () => void;
  /** State of the list the sheet was opened from; tasks land there. */
  defaultState?: OpenTaskState;
  /** Classification context (project/tag pages include it in the create). */
  projectId?: string;
  tagId?: string;
}

/**
 * One-step title capture. Waiting lists additionally collect `waiting_for`
 * before submit (the API rejects waiting tasks without it); project/tag
 * pages include their classification so the new task stays visible.
 */
export function QuickAddSheet({
  visible,
  onClose,
  defaultState,
  projectId,
  tagId,
}: QuickAddSheetProps) {
  const [title, setTitle] = useState("");
  const [waitingFor, setWaitingFor] = useState("");
  const create = useCreateTask();

  const targetState: OpenTaskState = defaultState ?? "inbox";
  const needsWaitingFor = targetState === "waiting";
  const canSubmit =
    title.trim().length > 0 && (!needsWaitingFor || waitingFor.trim().length > 0);

  const close = () => {
    create.reset();
    setTitle("");
    setWaitingFor("");
    onClose();
  };

  const submit = () => {
    const payload: TaskCreateRequest = { title: title.trim(), state: targetState };
    if (needsWaitingFor) {
      payload.waiting_for = waitingFor.trim();
    }
    if (projectId) {
      payload.project_id = projectId;
    }
    if (tagId) {
      payload.tag_ids = [tagId];
    }
    create.mutate(payload, { onSuccess: close });
  };

  return (
    <Sheet visible={visible} onClose={close} title="Add task">
      {create.isError ? <ErrorBanner error={create.error} /> : null}
      <TextInput
        style={styles.input}
        value={title}
        onChangeText={setTitle}
        placeholder={
          targetState === "next"
            ? "Add a next action — or dump everything on your mind with the mic above"
            : "What needs doing?"
        }
        placeholderTextColor={colors.fg6}
        autoFocus
        editable={!create.isPending}
        onSubmitEditing={canSubmit ? submit : undefined}
        returnKeyType="done"
      />
      {needsWaitingFor ? (
        <View style={styles.field}>
          <BBText variant="label">Waiting for</BBText>
          <TextInput
            style={styles.input}
            value={waitingFor}
            onChangeText={setWaitingFor}
            placeholder="Who or what are you waiting on?"
            placeholderTextColor={colors.fg6}
            editable={!create.isPending}
          />
          <BBText variant="caption" color={colors.fg5}>
            Waiting tasks name the person, event, or condition you are waiting on.
          </BBText>
        </View>
      ) : null}
      <Button onPress={submit} disabled={!canSubmit} loading={create.isPending}>
        {`Add to ${targetState === "someday" ? "someday / maybe" : targetState}`}
      </Button>
    </Sheet>
  );
}

const styles = StyleSheet.create({
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
  field: {
    gap: space.s2,
  },
});
