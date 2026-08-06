import { useLocalSearchParams, useRouter } from "expo-router";
import { useMemo, useState } from "react";
import { ActivityIndicator, FlatList, Pressable, StyleSheet, View } from "react-native";

import { useTaskList, useTransitionTask } from "@/api/hooks";
import type { TaskResponse } from "@/api/types";
import { BBText } from "@/components/BBText";
import { EmptyState } from "@/components/EmptyState";
import { ErrorBanner } from "@/components/ErrorBanner";
import { Screen } from "@/components/Screen";
import { TaskRow } from "@/components/TaskRow";
import { ReopenSheet } from "@/features/tasks/ReopenSheet";
import { useClassificationNames } from "@/features/tasks/useClassificationNames";
import { colors, minHitTarget, space } from "@/theme/tokens";

/**
 * Terminal-task recovery surface (completed or cancelled). Reopen always
 * asks for an explicit destination — the old state is never inferred.
 */
export default function HistoryScreen() {
  const { kind } = useLocalSearchParams<{ kind?: string }>();
  const terminalState = kind === "cancelled" ? "cancelled" : "completed";
  const router = useRouter();

  const filters = useMemo(
    () =>
      terminalState === "completed"
        ? { includeCompleted: true as const }
        : { includeCancelled: true as const },
    [terminalState],
  );
  const query = useTaskList(filters);
  const transition = useTransitionTask();
  const { projectName, tagNames } = useClassificationNames();
  const [reopening, setReopening] = useState<TaskResponse | null>(null);

  // The list API includes terminal rows alongside open ones; this surface
  // shows only the terminal slice.
  const tasks = useMemo(
    () =>
      (query.data ? query.data.pages.flatMap((page) => page.items) : []).filter(
        (task) => task.state === terminalState,
      ),
    [query.data, terminalState],
  );

  return (
    <Screen padTop>
      <View style={styles.header}>
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
        <BBText variant="title" style={styles.title}>
          {terminalState === "completed" ? "Completed" : "Cancelled"}
        </BBText>
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
          ItemSeparatorComponent={() => <View style={{ height: space.s2 }} />}
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
  header: {
    flexDirection: "row",
    alignItems: "center",
    gap: space.s3,
    paddingHorizontal: space.s5,
    paddingVertical: space.s3,
  },
  backButton: {
    minHeight: minHitTarget,
    justifyContent: "center",
  },
  title: {
    flex: 1,
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
});
