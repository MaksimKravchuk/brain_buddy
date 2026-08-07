import { Pressable, StyleSheet, View } from "react-native";

import type { OpenTaskState } from "@/api/types";
import { BBText } from "@/components/BBText";
import { colors, minHitTarget, radii, space } from "@/theme/tokens";

const LABELS: Record<OpenTaskState, string> = {
  inbox: "Inbox",
  next: "Next",
  waiting: "Waiting",
  someday: "Someday",
};

interface StatePickerProps {
  value: OpenTaskState | null;
  onChange: (state: OpenTaskState) => void;
  /** States to offer; defaults to all four open lists. */
  options?: OpenTaskState[];
}

export function StatePicker({ value, onChange, options }: StatePickerProps) {
  const states = options ?? (Object.keys(LABELS) as OpenTaskState[]);
  return (
    <View style={styles.row}>
      {states.map((state) => {
        const selected = value === state;
        return (
          <Pressable
            key={state}
            accessibilityRole="button"
            accessibilityState={{ selected }}
            onPress={() => onChange(state)}
            style={[styles.option, selected ? styles.optionSelected : null]}
          >
            <BBText
              variant="body"
              weight="medium"
              color={selected ? "#FFFFFF" : colors.fg3}
            >
              {LABELS[state]}
            </BBText>
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: space.s2,
  },
  option: {
    minHeight: minHitTarget - 8,
    paddingHorizontal: space.s4,
    borderRadius: radii.full,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surfaceRaised,
    alignItems: "center",
    justifyContent: "center",
  },
  optionSelected: {
    backgroundColor: colors.brandPrimary,
    borderColor: colors.brandPrimary,
  },
});
