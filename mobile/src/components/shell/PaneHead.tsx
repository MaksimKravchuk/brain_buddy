import type { ReactNode } from "react";
import { StyleSheet, View } from "react-native";

import { BBText } from "@/components/BBText";
import { colors, fonts, space } from "@/theme/tokens";

interface PaneHeadProps {
  title: string;
  meta?: string;
  actions?: ReactNode;
}

/** Pane header: 22/600 title with a 12px meta line, actions right-aligned. */
export function PaneHead({ title, meta, actions }: PaneHeadProps) {
  return (
    <View style={styles.head}>
      <View style={styles.text}>
        <BBText style={styles.title}>{title}</BBText>
        {meta ? (
          <BBText variant="caption" style={styles.meta}>
            {meta}
          </BBText>
        ) : null}
      </View>
      {actions ? <View style={styles.actions}>{actions}</View> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  head: {
    flexDirection: "row",
    alignItems: "flex-end",
    gap: space.s3,
    marginBottom: space.s4,
  },
  text: {
    flex: 1,
  },
  title: {
    fontSize: 22,
    lineHeight: 28,
    letterSpacing: -0.33,
    fontFamily: fonts.semibold,
    color: colors.fg1,
  },
  meta: {
    marginTop: space.s1,
  },
  actions: {
    flexShrink: 0,
  },
});
