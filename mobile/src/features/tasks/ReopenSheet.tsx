import { useEffect, useState } from "react";
import { StyleSheet, TextInput, View } from "react-native";

import type { OpenTaskState, TaskResponse, TaskTransitionRequest } from "@/api/types";
import { BBText } from "@/components/BBText";
import { Button } from "@/components/Button";
import { ErrorBanner } from "@/components/ErrorBanner";
import { Sheet } from "@/components/Sheet";
import { StatePicker } from "@/features/tasks/StatePicker";
import { buildTransition } from "@/lifecycle/guards";
import { colors, fonts, radii, space, type as typeScale } from "@/theme/tokens";

interface ReopenSheetProps {
  task: TaskResponse | null;
  onClose: () => void;
  onReopen: (payload: TaskTransitionRequest) => void;
  pending?: boolean;
  error?: unknown;
}

/** Reopen requires an explicitly chosen destination (waiting also collects waiting_for). */
export function ReopenSheet({ task, onClose, onReopen, pending = false, error }: ReopenSheetProps) {
  const [destination, setDestination] = useState<OpenTaskState | null>(null);
  const [waitingFor, setWaitingFor] = useState("");
  const [guardError, setGuardError] = useState<string | null>(null);

  useEffect(() => {
    if (task) {
      setDestination(null);
      setWaitingFor("");
      setGuardError(null);
    }
  }, [task]);

  const submit = () => {
    if (!task || !destination) {
      return;
    }
    const guard = buildTransition(task, {
      action: "reopen",
      toState: destination,
      waitingFor,
      expectedRevision: task.revision,
    });
    if (!guard.ok) {
      setGuardError(guard.reason);
      return;
    }
    setGuardError(null);
    onReopen(guard.payload);
  };

  return (
    <Sheet visible={task !== null} onClose={onClose} title="Reopen task">
      {task ? (
        <View style={styles.body}>
          <BBText variant="body" color={colors.fg4} numberOfLines={2}>
            {task.title}
          </BBText>
          <BBText variant="label">Reopen into</BBText>
          <StatePicker value={destination} onChange={setDestination} />
          {destination === "waiting" ? (
            <View style={styles.field}>
              <BBText variant="label">Waiting for</BBText>
              <TextInput
                style={styles.input}
                value={waitingFor}
                onChangeText={setWaitingFor}
                placeholder="Who or what are you waiting on?"
                placeholderTextColor={colors.fg6}
                editable={!pending}
              />
            </View>
          ) : null}
          {guardError ? (
            <BBText variant="caption" color={colors.dangerFg}>
              {guardError}
            </BBText>
          ) : null}
          {error ? <ErrorBanner error={error} /> : null}
          <Button onPress={submit} disabled={!destination} loading={pending}>
            Reopen
          </Button>
        </View>
      ) : null}
    </Sheet>
  );
}

const styles = StyleSheet.create({
  body: {
    gap: space.s3,
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
});
