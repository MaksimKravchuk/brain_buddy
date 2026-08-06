import { useRouter } from "expo-router";
import { CheckCircle2, ChevronRight, Settings2, Tag as TagIcon, XCircle } from "lucide-react-native";
import { Pressable, ScrollView, StyleSheet, View } from "react-native";

import { useProjects, useTags } from "@/api/hooks";
import { BBText } from "@/components/BBText";
import { ErrorBanner } from "@/components/ErrorBanner";
import { Screen } from "@/components/Screen";
import { colors, minHitTarget, radii, space } from "@/theme/tokens";

const PROJECT_FALLBACK_COLOR = colors.brandSecondary;

export default function BrowseScreen() {
  const router = useRouter();
  const projects = useProjects();
  const tags = useTags();

  const activeProjects = (projects.data ?? []).filter((project) => project.state === "active");
  const activeTags = (tags.data ?? []).filter((tag) => tag.state === "active");

  return (
    <Screen padTop>
      <View style={styles.header}>
        <BBText variant="title">Browse</BBText>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Settings"
          onPress={() => router.push("/settings")}
          style={styles.settingsButton}
        >
          <Settings2 size={20} color={colors.fg4} strokeWidth={1.75} />
        </Pressable>
      </View>
      <ScrollView contentContainerStyle={styles.scroll}>
        {projects.isError ? <ErrorBanner error={projects.error} onRetry={() => projects.refetch()} /> : null}
        {tags.isError ? <ErrorBanner error={tags.error} onRetry={() => tags.refetch()} /> : null}

        <BBText variant="label" style={styles.sectionLabel}>
          Projects
        </BBText>
        <View style={styles.card}>
          {activeProjects.length === 0 ? (
            <View style={styles.emptyRow}>
              <BBText variant="body" color={colors.fg5}>
                No projects yet — create them on the web app.
              </BBText>
            </View>
          ) : (
            activeProjects.map((project, index) => (
              <Pressable
                key={project.id}
                accessibilityRole="button"
                onPress={() =>
                  router.push({ pathname: "/project/[id]", params: { id: project.id, name: project.name } })
                }
                style={[styles.row, index > 0 ? styles.rowBorder : null]}
              >
                <View
                  style={[styles.projectDot, { backgroundColor: project.color ?? PROJECT_FALLBACK_COLOR }]}
                />
                <BBText variant="body" weight="medium" style={styles.rowTitle} numberOfLines={1}>
                  {project.name}
                </BBText>
                <BBText variant="caption" color={colors.fg6}>
                  {project.open_task_count}
                </BBText>
                <ChevronRight size={16} color={colors.fg6} strokeWidth={2} />
              </Pressable>
            ))
          )}
        </View>

        <BBText variant="label" style={styles.sectionLabel}>
          Tags
        </BBText>
        <View style={styles.card}>
          {activeTags.length === 0 ? (
            <View style={styles.emptyRow}>
              <BBText variant="body" color={colors.fg5}>
                No tags yet — create them on the web app.
              </BBText>
            </View>
          ) : (
            activeTags.map((tag, index) => (
              <Pressable
                key={tag.id}
                accessibilityRole="button"
                onPress={() => router.push({ pathname: "/tag/[id]", params: { id: tag.id, name: tag.name } })}
                style={[styles.row, index > 0 ? styles.rowBorder : null]}
              >
                <TagIcon size={16} color={colors.fg5} strokeWidth={1.75} />
                <BBText variant="body" weight="medium" style={styles.rowTitle} numberOfLines={1}>
                  {tag.name}
                </BBText>
                <BBText variant="caption" color={colors.fg6}>
                  {tag.open_task_count}
                </BBText>
                <ChevronRight size={16} color={colors.fg6} strokeWidth={2} />
              </Pressable>
            ))
          )}
        </View>

        <BBText variant="label" style={styles.sectionLabel}>
          History
        </BBText>
        <View style={styles.card}>
          <Pressable
            accessibilityRole="button"
            onPress={() => router.push({ pathname: "/history", params: { kind: "completed" } })}
            style={styles.row}
          >
            <CheckCircle2 size={16} color={colors.success} strokeWidth={1.75} />
            <BBText variant="body" weight="medium" style={styles.rowTitle}>
              Completed
            </BBText>
            <ChevronRight size={16} color={colors.fg6} strokeWidth={2} />
          </Pressable>
          <Pressable
            accessibilityRole="button"
            onPress={() => router.push({ pathname: "/history", params: { kind: "cancelled" } })}
            style={[styles.row, styles.rowBorder]}
          >
            <XCircle size={16} color={colors.fg5} strokeWidth={1.75} />
            <BBText variant="body" weight="medium" style={styles.rowTitle}>
              Cancelled
            </BBText>
            <ChevronRight size={16} color={colors.fg6} strokeWidth={2} />
          </Pressable>
        </View>

        <BBText variant="caption" color={colors.fg5} style={styles.deferredNote}>
          Weekly review · coming later
        </BBText>
      </ScrollView>
    </Screen>
  );
}

const styles = StyleSheet.create({
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: space.s5,
    paddingTop: space.s3,
    paddingBottom: space.s3,
  },
  settingsButton: {
    width: minHitTarget,
    height: minHitTarget,
    borderRadius: radii.full,
    alignItems: "center",
    justifyContent: "center",
  },
  scroll: {
    paddingHorizontal: space.s5,
    paddingBottom: space.s8,
    gap: space.s3,
  },
  sectionLabel: {
    marginTop: space.s2,
  },
  card: {
    backgroundColor: colors.surfaceRaised,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radii.card,
    overflow: "hidden",
  },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: space.s3,
    paddingHorizontal: space.s4,
    minHeight: minHitTarget + 4,
  },
  rowBorder: {
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  rowTitle: {
    flex: 1,
    color: colors.fg1,
  },
  projectDot: {
    width: 10,
    height: 10,
    borderRadius: radii.full,
  },
  emptyRow: {
    padding: space.s4,
  },
  deferredNote: {
    textAlign: "center",
    paddingVertical: space.s2,
  },
});
