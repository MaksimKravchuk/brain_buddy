import { useLocalSearchParams } from "expo-router";
import { useMemo, useState } from "react";
import { ActivityIndicator, FlatList, StyleSheet, View } from "react-native";

import { useTaskList, useTransitionTask } from "@/api/hooks";
import type { TaskResponse, TaskState } from "@/api/types";
import { EmptyState } from "@/components/EmptyState";
import { ErrorBanner } from "@/components/ErrorBanner";
import { Screen } from "@/components/Screen";
import { TaskRow } from "@/components/TaskRow";
import { PaneHead } from "@/components/shell/PaneHead";
import { TopBar } from "@/components/shell/TopBar";
import { ReopenSheet } from "@/features/tasks/ReopenSheet";
import { useClassificationNames } from "@/features/tasks/useClassificationNames";
import { colors, space } from "@/theme/tokens";

/**
 * Terminal-task recovery surface (completed or cancelled). Reopen always
 * asks for an explicit destination — the old state is never inferred.
 */
export default function HistoryScreen() {
  const { kind } = useLocalSearchParams<{ kind?: string }>();
  const terminalState: TaskState = kind === "cancelled" ? "cancelled" : "completed";

  // `state=<terminal>` alone narrows the list to exactly that state
  // server-side, so pagination walks only terminal rows — never open tasks
  // that would otherwise fill pages ahead of them.
  const filters = useMemo(() => ({ state: terminalState }), [terminalState]);
  const query = useTaskList(filters);
  const transition = useTransitionTask();
  const { projectName, tagNames } = useClassificationNames();
  const [reopening, setReopening] = useState<TaskResponse | null>(null);

  const tasks = useMemo(
    () => (query.data ? query.data.pages.flatMap((page) => page.items) : []),
    [query.data],
  );

  const title = terminalState === "completed" ? "Completed" : "Cancelled";

  return (
    <Screen>
      <TopBar leading="back" title={title} />

      {query.isLoading ? (
        <View style={styles.center}>
          <ActivityIndicator color={colors.brandPrimary} />
        </View>
      ) : query.isError ? (
        <View style={styles.pad}>
          <ErrorBanner error={query.error} onRetry={() => query.refetch()} />
        </View>
      ) : tasks.length === 0 ? (
        <EmptyState
          headline={terminalState === "completed" ? "Nothing completed yet" : "Nothing cancelled"}
          hint={
            terminalState === "completed"
              ? "Finished tasks stay here with their history."
              : "Tasks you decide not to do stay reviewable here."
          }
        />
      ) : (
        <FlatList
          data={tasks}
          keyExtractor={(task) => task.id}
          contentContainerStyle={styles.list}
          ListHeaderComponent={
            <PaneHead
              title={title}
              meta={
                terminalState === "completed"
                  ? "Finished tasks stay here with their history."
                  : "Tasks you decided not to do stay reviewable here."
              }
            />
          }
          ItemSeparatorComponent={() => <View style={{ height: 10 }} />}
          renderItem={({ item }) => (
            <TaskRow
              task={item}
              projectName={projectName(item.project_id)}
              tagNames={tagNames(item.tag_ids)}
              onPress={() => setReopening(item)}
              onToggleComplete={() => setReopening(item)}
            />
          )}
          onEndReachedThreshold={0.4}
          onEndReached={() => {
            if (query.hasNextPage && !query.isFetchingNextPage) {
              query.fetchNextPage();
            }
          }}
          ListFooterComponent={
            query.isFetchingNextPage ? (
              <ActivityIndicator color={colors.brandPrimary} style={styles.pad} />
            ) : null
          }
        />
      )}

      <ReopenSheet
        task={reopening}
        onClose={() => setReopening(null)}
        onReopen={(payload) => {
          if (reopening) {
            transition.mutate(
              { taskId: reopening.id, payload },
              { onSettled: () => setReopening(null) },
            );
          }
        }}
        pending={transition.isPending}
        error={transition.isError ? transition.error : null}
      />
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
    padding: space.s5,
  },
  list: {
    paddingHorizontal: space.s4,
    paddingTop: 18,
    paddingBottom: space.s8,
  },
});
