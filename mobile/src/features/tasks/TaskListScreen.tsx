import { useRouter } from "expo-router";
import { Mic, Plus } from "lucide-react-native";
import { useMemo, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  View,
} from "react-native";

import { useTaskList, useTransitionTask } from "@/api/hooks";
import type { OpenTaskState, TaskResponse } from "@/api/types";
import { useSession } from "@/auth/SessionProvider";
import { BBText } from "@/components/BBText";
import { EmptyState } from "@/components/EmptyState";
import { ErrorBanner } from "@/components/ErrorBanner";
import { Screen } from "@/components/Screen";
import { TaskRow } from "@/components/TaskRow";
import { QuickAddSheet } from "@/features/tasks/QuickAddSheet";
import { useClassificationNames } from "@/features/tasks/useClassificationNames";
import { buildTransition } from "@/lifecycle/guards";
import { colors, minHitTarget, radii, space } from "@/theme/tokens";

export interface TaskListScreenProps {
  title: string;
  state?: OpenTaskState;
  projectId?: string;
  tagId?: string;
  emptyHeadline: string;
  emptyHint?: string;
  /** Back affordance for stacked (project/tag) screens. */
  showBack?: boolean;
}

export function TaskListScreen({
  title,
  state,
  projectId,
  tagId,
  emptyHeadline,
  emptyHint,
  showBack = false,
}: TaskListScreenProps) {
  const router = useRouter();
  const { voiceEnabled } = useSession();
  const filters = useMemo(
    () => ({ state, projectId, tagId }),
    [state, projectId, tagId],
  );
  const query = useTaskList(filters);
  const transition = useTransitionTask();
  const { projectName, tagNames } = useClassificationNames();
  const [quickAddVisible, setQuickAddVisible] = useState(false);

  const tasks: TaskResponse[] = useMemo(
    () => (query.data ? query.data.pages.flatMap((page) => page.items) : []),
    [query.data],
  );
  const totalKnown = tasks.length;
  const hasMore = query.hasNextPage;

  const completeTask = (task: TaskResponse) => {
    const guard = buildTransition(task, {
      action: "complete",
      expectedRevision: task.revision,
    });
    if (guard.ok) {
      transition.mutate({ taskId: task.id, payload: guard.payload });
    }
  };

  return (
    <Screen padTop>
      <View style={styles.header}>
        {showBack ? (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Back"
            onPress={() => router.back()}
            style={styles.backButton}
          >
            <BBText variant="body" color={colors.brandPrimary}>
              Back
            </BBText>
          </Pressable>
        ) : null}
        <View style={styles.headerText}>
          <BBText variant="title">{title}</BBText>
          <BBText variant="caption">
            {hasMore ? `${totalKnown}+ tasks` : `${totalKnown} ${totalKnown === 1 ? "task" : "tasks"}`}
          </BBText>
        </View>
        <View style={styles.headerActions}>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Add task"
            onPress={() => setQuickAddVisible(true)}
            style={styles.addButton}
          >
            <Plus size={20} color={colors.fg4} strokeWidth={2} />
          </Pressable>
          {voiceEnabled ? (
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Brain dump"
              onPress={() => router.push("/brain-dump")}
              style={styles.micButton}
            >
              <Mic size={20} color="#FFFFFF" strokeWidth={2} />
            </Pressable>
          ) : null}
        </View>
      </View>

      {query.isLoading ? (
        <View style={styles.center}>
          <ActivityIndicator color={colors.brandPrimary} />
        </View>
      ) : query.isError ? (
        <View style={styles.pad}>
          <ErrorBanner error={query.error} onRetry={() => query.refetch()} />
        </View>
      ) : tasks.length === 0 ? (
        <EmptyState headline={emptyHeadline} hint={emptyHint} />
      ) : (
        <FlatList
          data={tasks}
          keyExtractor={(task) => task.id}
          contentContainerStyle={styles.list}
          ItemSeparatorComponent={() => <View style={{ height: space.s2 }} />}
          renderItem={({ item }) => (
            <TaskRow
              task={item}
              projectName={projectId ? undefined : projectName(item.project_id)}
              tagNames={tagNames(item.tag_ids)}
              onPress={() => router.push({ pathname: "/task/[id]", params: { id: item.id } })}
              onToggleComplete={() => completeTask(item)}
              completing={transition.isPending}
            />
          )}
          refreshControl={
            <RefreshControl
              refreshing={query.isRefetching && !query.isFetchingNextPage}
              onRefresh={() => query.refetch()}
              tintColor={colors.brandPrimary}
            />
          }
          onEndReachedThreshold={0.4}
          onEndReached={() => {
            if (query.hasNextPage && !query.isFetchingNextPage) {
              query.fetchNextPage();
            }
          }}
          ListFooterComponent={
            query.isFetchingNextPage ? (
              <ActivityIndicator color={colors.brandPrimary} style={styles.footer} />
            ) : null
          }
        />
      )}

      {transition.isError ? (
        <View style={styles.pad}>
          <ErrorBanner error={transition.error} />
        </View>
      ) : null}

      <QuickAddSheet
        visible={quickAddVisible}
        onClose={() => setQuickAddVisible(false)}
        defaultState={state}
        projectId={projectId}
        tagId={tagId}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  header: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: space.s5,
    paddingTop: space.s3,
    paddingBottom: space.s3,
    gap: space.s3,
  },
  backButton: {
    minHeight: minHitTarget,
    justifyContent: "center",
  },
  headerText: {
    flex: 1,
    gap: 2,
  },
  headerActions: {
    flexDirection: "row",
    alignItems: "center",
    gap: space.s3,
  },
  addButton: {
    width: minHitTarget,
    height: minHitTarget,
    borderRadius: radii.full,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surfaceRaised,
    alignItems: "center",
    justifyContent: "center",
  },
  micButton: {
    width: minHitTarget,
    height: minHitTarget,
    borderRadius: radii.full,
    backgroundColor: colors.brandPrimary,
    alignItems: "center",
    justifyContent: "center",
  },
  center: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
  },
  pad: {
    padding: space.s5,
  },
  list: {
    paddingHorizontal: space.s5,
    paddingBottom: space.s8,
  },
  footer: {
    paddingVertical: space.s4,
  },
});
