import { useRouter } from "expo-router";
import { ChevronLeft, Menu, Mic } from "lucide-react-native";
import type { ReactNode } from "react";
import { Pressable, StyleSheet, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useSession } from "@/auth/SessionProvider";
import { BBText } from "@/components/BBText";
import { colors, fonts, minHitTarget, radii, space } from "@/theme/tokens";

interface TopBarProps {
  /** "menu" shows the hamburger; "back" shows the chevron. */
  leading: "menu" | "back";
  onMenu?: () => void;
  /** Centered 15/600 title — back views only, per the design. */
  title?: string;
  /** Mic + avatar on list views; hidden on back views. */
  showActions?: boolean;
  trailing?: ReactNode;
}

function initialsFrom(email: string | undefined): string {
  if (!email) {
    return "·";
  }
  const name = email.split("@")[0];
  const parts = name.split(/[._-]+/).filter(Boolean);
  const letters =
    parts.length >= 2 ? parts[0][0] + parts[1][0] : name.slice(0, 2);
  return letters.toUpperCase();
}

/** In-app top bar under the status bar: white/90, hairline bottom border. */
export function TopBar({ leading, onMenu, title, showActions = false, trailing }: TopBarProps) {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { me, voiceEnabled } = useSession();

  return (
    <View style={[styles.bar, { paddingTop: insets.top + space.s2 }]}>
      {leading === "menu" ? (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Menu"
          onPress={onMenu}
          style={styles.iconButton}
        >
          <Menu size={20} color={colors.fg4} strokeWidth={2} />
        </Pressable>
      ) : (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Back"
          onPress={() => router.back()}
          style={styles.iconButton}
        >
          <ChevronLeft size={20} color={colors.fg4} strokeWidth={2} />
        </Pressable>
      )}

      {title ? (
        <BBText style={styles.title} numberOfLines={1}>
          {title}
        </BBText>
      ) : null}

      <View style={styles.right}>
        {trailing}
        {showActions ? (
          <>
            {voiceEnabled ? (
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="Brain dump"
                onPress={() => router.push("/brain-dump")}
                style={styles.iconButton}
              >
                <Mic size={18} color={colors.fg4} strokeWidth={2} />
              </Pressable>
            ) : null}
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Account"
              onPress={() => router.push("/settings")}
              style={styles.avatar}
            >
              <BBText style={styles.avatarText}>{initialsFrom(me?.email)}</BBText>
            </Pressable>
          </>
        ) : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  bar: {
    flexDirection: "row",
    alignItems: "center",
    gap: space.s2,
    paddingHorizontal: space.s4,
    paddingBottom: space.s2,
    backgroundColor: "rgba(255,255,255,0.9)",
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    zIndex: 5,
  },
  iconButton: {
    width: minHitTarget,
    height: minHitTarget,
    margin: -space.s2,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 10,
  },
  title: {
    fontSize: 15,
    fontFamily: fonts.semibold,
    color: colors.fg1,
    flexShrink: 1,
  },
  right: {
    marginLeft: "auto",
    flexDirection: "row",
    alignItems: "center",
    gap: space.s2,
  },
  avatar: {
    width: 32,
    height: 32,
    borderRadius: radii.full,
    backgroundColor: "#E0F2FE",
    alignItems: "center",
    justifyContent: "center",
  },
  avatarText: {
    fontSize: 12,
    fontFamily: fonts.semibold,
    color: "#0369A1",
  },
});
