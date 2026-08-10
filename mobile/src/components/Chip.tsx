import { StyleSheet, View } from "react-native";

import { BBText } from "@/components/BBText";
import { colors, radii, space } from "@/theme/tokens";

/** Rose due-date chip — real deadlines only, never decorative dates. */
export function DueChip({ label }: { label: string }) {
  return (
    <View style={[styles.chip, styles.due]}>
      <BBText variant="micro" color={colors.dueFg}>
        {label}
      </BBText>
    </View>
  );
}

/** Neutral tag pill as rendered inside task rows. */
export function TagPill({ name }: { name: string }) {
  return (
    <View style={[styles.chip, styles.tag]}>
      <BBText variant="caption" color={colors.tagFg}>
        {name}
      </BBText>
    </View>
  );
}

/** Amber waiting chip: "Waiting · <who>". */
export function WaitingChip({ waitingFor }: { waitingFor: string }) {
  return (
    <View style={[styles.chip, styles.waiting]}>
      <BBText variant="micro" color={colors.warningFg} numberOfLines={1}>
        {`Waiting · ${waitingFor}`}
      </BBText>
    </View>
  );
}

const PRIORITY_COLORS: Record<string, string> = {
  high: colors.danger,
  medium: colors.warning,
  low: colors.info,
};

/** Small priority dot; renders nothing for priority "none". */
export function PriorityDot({ priority }: { priority: string }) {
  const color = PRIORITY_COLORS[priority];
  if (!color) {
    return null;
  }
  return <View style={[styles.priorityDot, { backgroundColor: color }]} />;
}

const styles = StyleSheet.create({
  chip: {
    borderRadius: radii.full,
    paddingHorizontal: space.s2,
    paddingVertical: 2,
    flexShrink: 0,
  },
  due: {
    backgroundColor: colors.dueBg,
    borderWidth: 1,
    borderColor: colors.dueBorder,
  },
  tag: {
    backgroundColor: colors.tagBg,
    paddingHorizontal: 9,
  },
  waiting: {
    backgroundColor: colors.warningBg,
    borderWidth: 1,
    borderColor: colors.warningBorder,
    flexShrink: 1,
  },
  priorityDot: {
    width: 6,
    height: 6,
    borderRadius: radii.full,
  },
});
