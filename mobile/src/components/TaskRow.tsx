import { Calendar, Check } from "lucide-react-native";
import { Pressable, StyleSheet, View } from "react-native";

import { BBText } from "@/components/BBText";
import { PriorityDot, TagPill } from "@/components/Chip";
import type { TaskResponse } from "@/api/types";
import { colors, fonts, minHitTarget, radii, shadows, space } from "@/theme/tokens";

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
    return `before ${due.toLocaleDateString(undefined, { weekday: "short" })}`;
  }
  return due.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

/**
 * Mobile task card per the design: 22px checkbox, 15/500 title, chips wrap
 * under the title (due · tags · waiting note · project as plain text).
 */
export function TaskRow({
  task,
  projectName,
  tagNames = [],
  onPress,
  onToggleComplete,
  completing = false,
}: TaskRowProps) {
  const done = task.state === "completed";
  const cancelled = task.state === "cancelled";
  const hasMeta =
    task.due_date || (task.state === "waiting" && task.waiting_for) || tagNames.length > 0 ||
    projectName || task.priority !== "none";

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={task.title}
      onPress={onPress}
      style={({ pressed }) => [styles.card, pressed ? styles.cardPressed : null]}
    >
      <Pressable
        accessibilityRole="checkbox"
        accessibilityState={{ checked: done }}
        accessibilityLabel={done ? "Reopen task" : "Complete task"}
        onPress={onToggleComplete}
        disabled={!onToggleComplete || completing}
        hitSlop={(minHitTarget - 22) / 2}
        style={[styles.check, done ? styles.checkDone : null, cancelled ? styles.checkCancelled : null]}
      >
        {done ? <Check size={12} color="#FFFFFF" strokeWidth={3} /> : null}
      </Pressable>

      <View style={styles.body}>
        <BBText
          numberOfLines={3}
          style={[
            styles.title,
            done ? styles.titleDone : null,
            cancelled ? styles.titleCancelled : null,
          ]}
        >
          {task.title}
        </BBText>
        {hasMeta ? (
          <View style={styles.meta}>
            <PriorityDot priority={task.priority} />
            {task.due_date ? (
              <View style={styles.dueChip}>
                <Calendar size={11} color={colors.dueFg} strokeWidth={2} />
                <BBText variant="micro" color={colors.dueFg}>
                  {dueLabel(task.due_date)}
                </BBText>
              </View>
            ) : null}
            {tagNames.map((name) => (
              <TagPill key={name} name={name} />
            ))}
            {task.state === "waiting" && task.waiting_for ? (
              <BBText variant="micro" color={colors.fg6} numberOfLines={1} style={styles.note}>
                {task.waiting_for}
              </BBText>
            ) : null}
            {projectName ? (
              <BBText variant="micro" color={colors.fg6} numberOfLines={1}>
                {projectName}
              </BBText>
            ) : null}
          </View>
        ) : null}
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: space.s3,
    padding: 14,
    backgroundColor: colors.surfaceRaised,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radii.card,
    ...shadows.soft,
  },
  cardPressed: {
    borderColor: colors.borderHover,
  },
  check: {
    width: 22,
    height: 22,
    marginTop: 1,
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
  checkCancelled: {
    backgroundColor: colors.surfaceSunken,
  },
  body: {
    flex: 1,
    minWidth: 0,
  },
  title: {
    fontSize: 15,
    lineHeight: 20,
    fontFamily: fonts.medium,
    color: colors.fg1,
  },
  titleDone: {
    textDecorationLine: "line-through",
    color: colors.fg5,
  },
  titleCancelled: {
    color: colors.fg6,
  },
  meta: {
    flexDirection: "row",
    flexWrap: "wrap",
    alignItems: "center",
    gap: 6,
    marginTop: space.s2,
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
  note: {
    flexShrink: 1,
  },
});
