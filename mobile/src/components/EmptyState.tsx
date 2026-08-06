import type { PropsWithChildren } from "react";
import { StyleSheet, View } from "react-native";

import { BBText } from "@/components/BBText";
import { colors, space } from "@/theme/tokens";

interface EmptyStateProps extends PropsWithChildren {
  headline: string;
  hint?: string;
}

/** One-line headline + plain-language hint + a single CTA — never a wall of text. */
export function EmptyState({ headline, hint, children }: EmptyStateProps) {
  return (
    <View style={styles.root}>
      <BBText variant="display" style={styles.headline}>
        {headline}
      </BBText>
      {hint ? (
        <BBText variant="body" color={colors.fg5} style={styles.hint}>
          {hint}
        </BBText>
      ) : null}
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  root: {
    alignItems: "center",
    paddingHorizontal: space.s6,
    paddingVertical: space.s8,
    gap: space.s3,
  },
  headline: {
    textAlign: "center",
  },
  hint: {
    textAlign: "center",
  },
});
