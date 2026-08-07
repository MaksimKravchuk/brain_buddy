import type { PropsWithChildren } from "react";
import { StyleSheet, View, type ViewStyle } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { colors } from "@/theme/tokens";

interface ScreenProps extends PropsWithChildren {
  /** Apply the top safe-area inset (off under a navigator header). */
  padTop?: boolean;
  padBottom?: boolean;
  style?: ViewStyle;
}

/** Flat surface-base page background — never gradients, imagery, or patterns. */
export function Screen({ children, padTop = false, padBottom = false, style }: ScreenProps) {
  const insets = useSafeAreaInsets();
  return (
    <View
      style={[
        styles.root,
        padTop ? { paddingTop: insets.top } : null,
        padBottom ? { paddingBottom: insets.bottom } : null,
        style,
      ]}
    >
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: colors.surfaceBase,
  },
});
