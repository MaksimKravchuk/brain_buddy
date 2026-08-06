import { Pressable, StyleSheet, View } from "react-native";

import { BBText } from "@/components/BBText";
import { DueChip, PriorityDot, TagPill, WaitingChip } from "@/components/Chip";
import type { TaskResponse } from "@/api/types";
import { colors, minHitTarget, radii, space } from "@/theme/tokens";

interface TaskRowProps {
  task: TaskResponse;
  projectName?: string;
  tagNames?: string[];
  onPress?: () => void;
  onToggleComplete?: () => void;
  completing?: boolean;
}

/** "before Sat" style label for a real deadline. */
export function dueLabel(dueDate: string): string {
  const due = new Date(`${dueDate}T00:00:00`);
  if (Number.isNaN(due.getTime())) {
    return dueDate;
  }
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const diffDays = Math.round((due.getTime() - today.getTime()) / 86_400_000);
  if (diffDays < 0) {
    return diffDays === -1 ? "yesterday" : "overdue";
  }
  if (diffDays === 0) {
    return "today";
  }
  if (diffDays === 1) {
    return "tomorrow";
  }
  if (diffDays < 7) {
    return due.toLocaleDateString(undefined, { weekday: "short" });
  }
  return due.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function TaskRow({
  task,
  projectName,
  tagNames = [],
  onPress,
  onToggleComplete,
  completing = false,
}: TaskRowProps) {
  const terminal = task.state === "completed" || task.state === "cancelled";
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={task.title}
      onPress={onPress}
      style={({ pressed }) => [styles.row, pressed ? styles.rowPressed : null]}
    >
      <Pressable
        accessibilityRole="checkbox"
        accessibilityState={{ checked: task.state === "completed" }}
        accessibilityLabel={task.state === "completed" ? "Reopen task" : "Complete task"}
        onPress={onToggleComplete}
        disabled={!onToggleComplete || completing}
        hitSlop={(minHitTarget - 18) / 2}
        style={[
          styles.checkbox,
          task.state === "completed" ? styles.checkboxDone : null,
          task.state === "cancelled" ? styles.checkboxCancelled : null,
        ]}
      >
        {task.state === "completed" ? <View style={styles.checkboxInner} /> : null}
      </Pressable>

      <View style={styles.main}>
        <View style={styles.titleLine}>
          <PriorityDot priority={task.priority} />
          <BBText
            variant="body"
            weight="medium"
            color={terminal ? colors.fg6 : colors.fg1}
            numberOfLines={2}
            style={[styles.title, task.state === "completed" ? styles.titleDone : null]}
          >
            {task.title}
          </BBText>
        </View>
        {(task.due_date || task.waiting_for || tagNames.length > 0) && (
          <View style={styles.chipLine}>
            {task.due_date ? <DueChip label={dueLabel(task.due_date)} /> : null}
            {task.state === "waiting" && task.waiting_for ? (
              <WaitingChip waitingFor={task.waiting_for} />
            ) : null}
            {tagNames.map((name) => (
              <TagPill key={name} name={name} />
            ))}
          </View>
        )}
      </View>

      {projectName ? (
        <BBText variant="micro" color={colors.fg6} numberOfLines={1} style={styles.project}>
          {projectName}
        </BBText>
      ) : null}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: space.s3,
    paddingVertical: space.s3,
    paddingHorizontal: space.s4,
    backgroundColor: colors.surfaceRaised,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radii.card,
    minHeight: minHitTarget + 12,
  },
  rowPressed: {
    borderColor: colors.borderHover,
  },
  checkbox: {
    width: 18,
    height: 18,
    borderRadius: radii.full,
    borderWidth: 1.5,
    borderColor: colors.fg7,
    alignItems: "center",
    justifyContent: "center",
  },
  checkboxDone: {
    borderColor: colors.success,
  },
  checkboxCancelled: {
    borderColor: colors.fg7,
    backgroundColor: colors.surfaceSunken,
  },
  checkboxInner: {
    width: 10,
    height: 10,
    borderRadius: radii.full,
    backgroundColor: colors.success,
  },
  main: {
    flex: 1,
    gap: space.s1,
  },
  titleLine: {
    flexDirection: "row",
    alignItems: "center",
    gap: space.s2,
  },
  title: {
    flexShrink: 1,
  },
  titleDone: {
    textDecorationLine: "line-through",
  },
  chipLine: {
    flexDirection: "row",
    alignItems: "center",
    gap: space.s2,
    flexWrap: "wrap",
  },
  project: {
    maxWidth: 96,
    textAlign: "right",
  },
});
