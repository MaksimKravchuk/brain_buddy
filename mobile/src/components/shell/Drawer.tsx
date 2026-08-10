import { usePathname, useRouter } from "expo-router";
import {
  Archive,
  ArrowRight,
  CheckCircle2,
  Clock,
  Inbox,
  RotateCcw,
  Sprout,
  XCircle,
} from "lucide-react-native";
import { useEffect, useRef, type ReactNode } from "react";
import {
  Animated,
  Easing,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useProjects, useTags } from "@/api/hooks";
import type { OpenTaskState } from "@/api/types";
import { BBText } from "@/components/BBText";
import { useTaskCounts } from "@/features/tasks/useTaskCounts";
import { colors, durations, fonts, minHitTarget, radii, space } from "@/theme/tokens";

const DRAWER_WIDTH = 300;
const PROJECT_FALLBACK_COLOR = colors.brandSecondary;

const GTD_ITEMS: {
  state: OpenTaskState;
  label: string;
  icon: (color: string) => ReactNode;
}[] = [
  { state: "inbox", label: "Inbox", icon: (c) => <Inbox size={16} color={c} strokeWidth={1.75} /> },
  {
    state: "next",
    label: "Next actions",
    icon: (c) => <ArrowRight size={16} color={c} strokeWidth={1.75} />,
  },
  {
    state: "waiting",
    label: "Waiting for",
    icon: (c) => <Clock size={16} color={c} strokeWidth={1.75} />,
  },
  {
    state: "someday",
    label: "Someday / maybe",
    icon: (c) => <Archive size={16} color={c} strokeWidth={1.75} />,
  },
];

interface DrawerProps {
  open: boolean;
  onClose: () => void;
}

function NavRow({
  icon,
  label,
  active = false,
  trailing,
  onPress,
  wrap = false,
}: {
  icon: ReactNode;
  label: string;
  active?: boolean;
  trailing?: ReactNode;
  onPress?: () => void;
  wrap?: boolean;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ selected: active }}
      onPress={onPress}
      disabled={!onPress}
      style={[styles.navRow, active ? styles.navRowActive : null]}
    >
      <View style={styles.navIcon}>{icon}</View>
      <BBText
        variant="body"
        weight="medium"
        color={active ? colors.fg1 : colors.fg3}
        numberOfLines={wrap ? 2 : 1}
        style={styles.navLabel}
      >
        {label}
      </BBText>
      {trailing}
    </Pressable>
  );
}

/** The GTD drawer: full navigation, matching the web sidebar's structure. */
export function Drawer({ open, onClose }: DrawerProps) {
  const router = useRouter();
  const pathname = usePathname();
  const insets = useSafeAreaInsets();
  const counts = useTaskCounts();
  const projects = useProjects();
  const tags = useTags();
  const slide = useRef(new Animated.Value(-DRAWER_WIDTH)).current;

  useEffect(() => {
    if (open) {
      Animated.timing(slide, {
        toValue: 0,
        duration: durations.settle,
        easing: Easing.bezier(0.22, 1, 0.36, 1),
        useNativeDriver: true,
      }).start();
    } else {
      slide.setValue(-DRAWER_WIDTH);
    }
  }, [open, slide]);

  const go = (path: Parameters<typeof router.push>[0]) => {
    onClose();
    router.push(path);
  };

  const activeProjects = (projects.data ?? []).filter((project) => project.state === "active");
  const activeTags = (tags.data ?? []).filter((tag) => tag.state === "active");

  return (
    <Modal visible={open} transparent animationType="fade" onRequestClose={onClose}>
      <Pressable accessibilityLabel="Close menu" style={styles.scrim} onPress={onClose} />
      <Animated.View
        style={[
          styles.drawer,
          { paddingTop: insets.top + space.s6, transform: [{ translateX: slide }] },
        ]}
      >
        <View style={styles.brand}>
          <Sprout size={20} color={colors.brandPrimary} strokeWidth={2} />
          <BBText style={styles.brandText}>Brain Buddy</BBText>
        </View>

        <ScrollView contentContainerStyle={styles.scroll} showsVerticalScrollIndicator={false}>
          <View style={styles.nav}>
            {GTD_ITEMS.map((item) => {
              const active = pathname === `/list/${item.state}`;
              const count = counts?.[item.state] ?? 0;
              return (
                <NavRow
                  key={item.state}
                  icon={item.icon(active ? colors.fg1 : colors.fg5)}
                  label={item.label}
                  active={active}
                  onPress={() => go(`/list/${item.state}`)}
                  trailing={
                    item.state === "inbox" && count > 0 ? (
                      <View style={styles.inboxBadge}>
                        <BBText style={styles.inboxBadgeText}>{count}</BBText>
                      </View>
                    ) : count > 0 ? (
                      <BBText variant="caption" color={colors.fg6}>
                        {count}
                      </BBText>
                    ) : undefined
                  }
                />
              );
            })}
            <NavRow
              icon={<RotateCcw size={16} color={colors.fg6} strokeWidth={1.75} />}
              label="Weekly review"
              trailing={
                <BBText variant="micro" color={colors.fg6}>
                  coming later
                </BBText>
              }
            />
          </View>

          <View style={styles.section}>
            <BBText variant="label" style={styles.sectionLabel}>
              Projects
            </BBText>
            <View style={styles.nav}>
              {activeProjects.map((project) => (
                <NavRow
                  key={project.id}
                  wrap
                  icon={
                    <View
                      style={[
                        styles.projectDot,
                        { backgroundColor: project.color ?? PROJECT_FALLBACK_COLOR },
                      ]}
                    />
                  }
                  label={project.name}
                  active={pathname === `/project/${project.id}`}
                  onPress={() =>
                    go({ pathname: "/project/[id]", params: { id: project.id, name: project.name } })
                  }
                />
              ))}
              {activeProjects.length === 0 ? (
                <BBText variant="caption" color={colors.fg6} style={styles.emptyNote}>
                  No projects yet
                </BBText>
              ) : null}
            </View>
          </View>

          <View style={styles.section}>
            <BBText variant="label" style={styles.sectionLabel}>
              Tags
            </BBText>
            <View style={styles.tagCloud}>
              {activeTags.map((tag) => {
                const active = pathname === `/tag/${tag.id}`;
                return (
                  <Pressable
                    key={tag.id}
                    accessibilityRole="button"
                    onPress={() => go({ pathname: "/tag/[id]", params: { id: tag.id, name: tag.name } })}
                    style={[styles.tagPill, active ? styles.tagPillActive : null]}
                  >
                    <BBText variant="caption" color={active ? colors.fg1 : colors.fg4}>
                      {tag.name}
                    </BBText>
                  </Pressable>
                );
              })}
              {activeTags.length === 0 ? (
                <BBText variant="caption" color={colors.fg6} style={styles.emptyNote}>
                  No tags yet
                </BBText>
              ) : null}
            </View>
          </View>

          <View style={styles.section}>
            <BBText variant="label" style={styles.sectionLabel}>
              History
            </BBText>
            <View style={styles.nav}>
              <NavRow
                icon={<CheckCircle2 size={16} color={colors.success} strokeWidth={1.75} />}
                label="Completed"
                onPress={() => go({ pathname: "/history", params: { kind: "completed" } })}
              />
              <NavRow
                icon={<XCircle size={16} color={colors.fg5} strokeWidth={1.75} />}
                label="Cancelled"
                onPress={() => go({ pathname: "/history", params: { kind: "cancelled" } })}
              />
            </View>
          </View>
        </ScrollView>
      </Animated.View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  scrim: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: "rgba(248,250,252,0.72)",
  },
  drawer: {
    position: "absolute",
    left: 0,
    top: 0,
    bottom: 0,
    width: DRAWER_WIDTH,
    backgroundColor: colors.surfaceRaised,
    borderRightWidth: 1,
    borderRightColor: colors.border,
    borderTopRightRadius: radii.xl,
    borderBottomRightRadius: radii.xl,
    paddingHorizontal: space.s3,
    paddingBottom: space.s6,
    gap: space.s5,
  },
  brand: {
    flexDirection: "row",
    alignItems: "center",
    gap: space.s2,
    paddingHorizontal: 10,
  },
  brandText: {
    fontSize: 15,
    fontFamily: fonts.semibold,
    color: colors.fg1,
  },
  scroll: {
    gap: space.s5,
    paddingBottom: space.s6,
  },
  nav: {
    gap: 2,
  },
  navRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: space.s3,
    minHeight: minHitTarget - 4,
    paddingHorizontal: 10,
    borderRadius: radii.md,
  },
  navRowActive: {
    backgroundColor: colors.surfaceSunken,
  },
  navIcon: {
    width: 20,
    alignItems: "center",
  },
  navLabel: {
    flex: 1,
  },
  inboxBadge: {
    minWidth: 20,
    height: 18,
    paddingHorizontal: 6,
    borderRadius: radii.full,
    backgroundColor: colors.brandPrimary,
    alignItems: "center",
    justifyContent: "center",
  },
  inboxBadgeText: {
    fontSize: 10,
    fontFamily: fonts.semibold,
    color: "#FFFFFF",
  },
  section: {
    gap: space.s1,
  },
  sectionLabel: {
    paddingHorizontal: 10,
    marginBottom: 6,
  },
  projectDot: {
    width: 10,
    height: 10,
    borderRadius: radii.full,
  },
  tagCloud: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: space.s2,
    paddingHorizontal: 10,
  },
  tagPill: {
    minHeight: 32,
    paddingHorizontal: space.s3,
    borderRadius: radii.full,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surfaceRaised,
    alignItems: "center",
    justifyContent: "center",
  },
  tagPillActive: {
    borderColor: colors.brandPrimary,
    backgroundColor: colors.brandPrimarySoft,
  },
  emptyNote: {
    paddingHorizontal: 10,
  },
});
