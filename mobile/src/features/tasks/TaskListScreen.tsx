import { useRouter } from "expo-router";
import { useMemo, useState } from "react";
import { ActivityIndicator, FlatList, RefreshControl, StyleSheet, View } from "react-native";

import { useTaskList, useTransitionTask } from "@/api/hooks";
import type { OpenTaskState, TaskResponse } from "@/api/types";
import { EmptyState } from "@/components/EmptyState";
import { ErrorBanner } from "@/components/ErrorBanner";
import { Screen } from "@/components/Screen";
import { TaskRow } from "@/components/TaskRow";
import { AddTaskRow } from "@/components/shell/AddTaskRow";
import { Drawer } from "@/components/shell/Drawer";
import { PaneHead } from "@/components/shell/PaneHead";
import { TopBar } from "@/components/shell/TopBar";
import { QuickAddSheet } from "@/features/tasks/QuickAddSheet";
import { useClassificationNames } from "@/features/tasks/useClassificationNames";
import { buildTransition } from "@/lifecycle/guards";
import { colors, space } from "@/theme/tokens";

export interface TaskListScreenProps {
  title: string;
  state?: OpenTaskState;
  projectId?: string;
  tagId?: string;
  emptyHeadline: string;
  emptyHint?: string;
  /** "root" = hamburger + drawer; "sub" = back chevron + centered top-bar title. */
  mode?: "root" | "sub";
}

const ADD_LABELS: Record<string, string> = {
  next: "Add a next action — or dump everything with the mic",
  inbox: "Add a task",
  waiting: "Add a task",
  someday: "Add a task",
};

export function TaskListScreen({
  title,
  state,
  projectId,
  tagId,
  emptyHeadline,
  emptyHint,
  mode = "root",
}: TaskListScreenProps) {
  const router = useRouter();
  const filters = useMemo(() => ({ state, projectId, tagId }), [state, projectId, tagId]);
  const query = useTaskList(filters);
  const transition = useTransitionTask();
  const { projectName, tagNames } = useClassificationNames();
  const [quickAddVisible, setQuickAddVisible] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const tasks: TaskResponse[] = useMemo(
    () => (query.data ? query.data.pages.flatMap((page) => page.items) : []),
    [query.data],
  );
  const totalKnown = tasks.length;
  const hasMore = query.hasNextPage;

  const countLabel = `${totalKnown}${hasMore ? "+" : ""} ${totalKnown === 1 && !hasMore ? "task" : "tasks"}`;
  const meta =
    state === "inbox"
      ? "Process these — decide the next action for each."
      : tagId
        ? `${countLabel} across your lists`
        : countLabel;

  const addLabel = projectId
    ? "Add a task to this project"
    : ADD_LABELS[state ?? "inbox"] ?? "Add a task";

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
    <Screen>
      {mode === "root" ? (
        <TopBar leading="menu" onMenu={() => setDrawerOpen(true)} showActions />
      ) : (
        <TopBar leading="back" title={title} />
      )}

      {query.isLoading ? (
        <View style={styles.center}>
          <ActivityIndicator color={colors.brandPrimary} />
        </View>
      ) : query.isError ? (
        <View style={styles.pad}>
          <ErrorBanner error={query.error} onRetry={() => query.refetch()} />
        </View>
      ) : (
        <FlatList
          data={tasks}
          keyExtractor={(task) => task.id}
          contentContainerStyle={styles.list}
          ListHeaderComponent={<PaneHead title={title} meta={meta} />}
          ItemSeparatorComponent={() => <View style={{ height: 10 }} />}
          renderItem={({ item }) => (
            <TaskRow
              task={item}
              projectName={projectId ? undefined : projectName(item.project_id)}
              tagNames={tagId ? [] : tagNames(item.tag_ids)}
              onPress={() => router.push({ pathname: "/task/[id]", params: { id: item.id, from: title } })}
              onToggleComplete={() => completeTask(item)}
              completing={transition.isPending}
            />
          )}
          ListEmptyComponent={<EmptyState headline={emptyHeadline} hint={emptyHint} />}
          ListFooterComponent={
            <>
              {query.isFetchingNextPage ? (
                <ActivityIndicator color={colors.brandPrimary} style={styles.footer} />
              ) : null}
              <AddTaskRow label={addLabel} onPress={() => setQuickAddVisible(true)} />
            </>
          }
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

      {mode === "root" ? <Drawer open={drawerOpen} onClose={() => setDrawerOpen(false)} /> : null}
    </Screen>
  );
}

const styles = StyleSheet.create({
  center: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
  },
  pad: {
    padding: space.s4,
  },
  list: {
    paddingHorizontal: space.s4,
    paddingTop: 18,
    paddingBottom: space.s8 + space.s4,
  },
  footer: {
    paddingVertical: space.s4,
  },
});
