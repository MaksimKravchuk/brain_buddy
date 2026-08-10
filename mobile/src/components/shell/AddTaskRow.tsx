import { Plus } from "lucide-react-native";
import { Pressable, StyleSheet } from "react-native";

import { BBText } from "@/components/BBText";
import { colors, minHitTarget, radii, space } from "@/theme/tokens";

/** Dashed add-task affordance at the bottom of a list, per the design. */
export function AddTaskRow({ label, onPress }: { label: string; onPress: () => void }) {
  return (
    <Pressable accessibilityRole="button" onPress={onPress} style={styles.row}>
      <Plus size={16} color={colors.fg6} strokeWidth={2} />
      <BBText variant="body" color={colors.fg6}>
        {label}
      </BBText>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    marginTop: space.s3,
    paddingVertical: 13,
    paddingHorizontal: 14,
    borderWidth: 1.5,
    borderStyle: "dashed",
    borderColor: colors.fg7,
    borderRadius: radii.card,
    minHeight: minHitTarget,
    backgroundColor: "rgba(248,250,252,0.6)",
  },
});
