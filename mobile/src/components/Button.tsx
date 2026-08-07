import type { PropsWithChildren } from "react";
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  type StyleProp,
  type ViewStyle,
} from "react-native";

import { BBText } from "@/components/BBText";
import { colors, minHitTarget, radii, space } from "@/theme/tokens";

type Variant = "primary" | "secondary" | "ghost" | "destructive";

interface ButtonProps extends PropsWithChildren {
  onPress?: () => void;
  variant?: Variant;
  disabled?: boolean;
  loading?: boolean;
  accessibilityLabel?: string;
  style?: StyleProp<ViewStyle>;
}

const textColor: Record<Variant, string> = {
  primary: "#FFFFFF",
  secondary: colors.fg2,
  ghost: colors.fg4,
  destructive: colors.dangerFg,
};

export function Button({
  onPress,
  variant = "primary",
  disabled = false,
  loading = false,
  accessibilityLabel,
  style,
  children,
}: ButtonProps) {
  const inactive = disabled || loading;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel}
      disabled={inactive}
      onPress={onPress}
      style={({ pressed }) => [
        styles.base,
        styles[variant],
        pressed && !inactive ? styles.pressed : null,
        inactive ? styles.disabled : null,
        style,
      ]}
    >
      {loading ? (
        <ActivityIndicator size="small" color={textColor[variant]} />
      ) : typeof children === "string" ? (
        <BBText variant="body" weight="medium" color={textColor[variant]}>
          {children}
        </BBText>
      ) : (
        children
      )}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  base: {
    minHeight: minHitTarget,
    borderRadius: radii.md,
    paddingHorizontal: space.s4,
    alignItems: "center",
    justifyContent: "center",
    flexDirection: "row",
    gap: space.s2,
  },
  // Press feedback is scale only — no color change on press.
  pressed: {
    transform: [{ scale: 0.98 }],
  },
  disabled: {
    opacity: 0.5,
  },
  primary: {
    backgroundColor: colors.brandPrimary,
  },
  secondary: {
    backgroundColor: colors.surfaceRaised,
    borderWidth: 1,
    borderColor: colors.border,
  },
  ghost: {
    backgroundColor: "transparent",
  },
  destructive: {
    backgroundColor: colors.dangerBg,
    borderWidth: 1,
    borderColor: colors.dangerBorder,
  },
});
