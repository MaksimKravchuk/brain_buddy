import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { router } from "expo-router";
import { Menu, Plus } from "lucide-react-native";
import { useState } from "react";
import { ActivityIndicator, FlatList, Pressable, StyleSheet, Text, TextInput, View } from "react-native";

import type { TaskState } from "@/api/types";
import { useAuth } from "@/auth/AuthProvider";
import { colors, spacing, touchTarget } from "@/design/tokens";

const states: Exclude<TaskState, "completed" | "cancelled">[] = ["inbox", "next", "waiting", "someday"];

export function TaskListScreen({ state }: { state: Exclude<TaskState, "completed" | "cancelled"> }) {
  const { api, signOut } = useAuth();
  const client = useQueryClient();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const tasks = useInfiniteQuery({
    queryKey: ["tasks", state],
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) => api.tasks(state, pageParam),
    getNextPageParam: (page) => (page.has_more ? page.next_cursor ?? undefined : undefined),
  });
  const taskItems = Array.from(
    new Map((tasks.data?.pages.flatMap((page) => page.items) ?? []).map((task) => [task.id, task])).values(),
  );
  const capture = async () => {
    if (!draft.trim()) return;
    await api.createTask({ title: draft.trim(), state: "inbox" });
    setDraft("");
    await client.invalidateQueries({ queryKey: ["tasks"] });
  };
  const loadMore = () => {
    if (tasks.hasNextPage && !tasks.isFetchingNextPage) {
      void tasks.fetchNextPage();
    }
  };
  return <View style={styles.page}>
    <View style={styles.header}><Pressable accessibilityLabel="Open navigation" onPress={() => setDrawerOpen(!drawerOpen)} style={styles.icon}><Menu color={colors.text} /></Pressable><Text style={styles.title}>{state}</Text><Pressable accessibilityLabel="Sign out" onPress={() => void signOut()}><Text style={styles.signOut}>Sign out</Text></Pressable></View>
    {drawerOpen ? <View style={styles.drawer}>{states.map((item) => <Pressable key={item} onPress={() => router.replace(`/tasks/${item}`)} style={styles.drawerRow}><Text style={item === state ? styles.active : styles.drawerText}>{item}</Text></Pressable>)}</View> : null}
    <View style={styles.capture}><TextInput accessibilityLabel="Capture a task" onChangeText={setDraft} placeholder="Capture a task" style={styles.input} value={draft} /><Pressable accessibilityLabel="Add task" onPress={() => void capture()} style={styles.add}><Plus color={colors.raised} /></Pressable></View>
    {tasks.isLoading ? <ActivityIndicator accessibilityLabel="Loading tasks" color={colors.primary} /> : null}
    {tasks.isError && !tasks.data ? <View><Text accessibilityRole="alert" style={styles.error}>Tasks could not be refreshed.</Text><Pressable accessibilityRole="button" accessibilityLabel="Retry tasks" onPress={() => void tasks.refetch()} style={styles.retry}><Text style={styles.retryText}>Retry</Text></Pressable></View> : null}
    <FlatList data={taskItems} keyExtractor={(item) => item.id} testID="task-list" onEndReached={loadMore} onEndReachedThreshold={0.5} onRefresh={() => void tasks.refetch()} refreshing={tasks.isRefetching} contentContainerStyle={styles.list} ListEmptyComponent={!tasks.isLoading && !tasks.isError ? <Text style={styles.empty}>Nothing here yet.</Text> : null} ListFooterComponent={tasks.isFetchingNextPage ? <ActivityIndicator accessibilityLabel="Loading more tasks" color={colors.primary} /> : tasks.isFetchNextPageError ? <Pressable accessibilityRole="button" accessibilityLabel="Retry loading more tasks" onPress={loadMore} style={styles.retry}><Text style={styles.retryText}>Retry loading more tasks</Text></Pressable> : null} renderItem={({ item }) => <Pressable accessibilityRole="button" onPress={() => router.push(`/tasks/detail/${item.id}`)} style={styles.card}><Text style={styles.cardTitle}>{item.title}</Text><Text style={styles.cardMeta}>{item.priority} priority · revision {item.revision}</Text></Pressable>} />
  </View>;
}
const styles = StyleSheet.create({ page: { flex: 1, backgroundColor: colors.surface, padding: spacing.lg, gap: spacing.md }, header: { alignItems: "center", flexDirection: "row", justifyContent: "space-between" }, title: { color: colors.text, fontSize: 24, fontWeight: "600", textTransform: "capitalize" }, icon: { justifyContent: "center", minHeight: touchTarget, minWidth: touchTarget }, signOut: { color: colors.muted }, drawer: { backgroundColor: colors.raised, borderColor: colors.border, borderRadius: 8, borderWidth: 1 }, drawerRow: { minHeight: touchTarget, justifyContent: "center", paddingHorizontal: spacing.md }, drawerText: { color: colors.text }, active: { color: colors.primary, fontWeight: "700" }, capture: { flexDirection: "row", gap: spacing.sm }, input: { backgroundColor: colors.raised, borderColor: colors.border, borderRadius: 8, borderWidth: 1, flex: 1, minHeight: touchTarget, paddingHorizontal: spacing.md }, add: { alignItems: "center", backgroundColor: colors.primary, borderRadius: 8, justifyContent: "center", minHeight: touchTarget, minWidth: touchTarget }, list: { gap: spacing.sm, paddingBottom: spacing.xxl }, card: { backgroundColor: colors.raised, borderColor: colors.border, borderRadius: 8, borderWidth: 1, padding: spacing.lg }, cardTitle: { color: colors.text, fontSize: 16, fontWeight: "600" }, cardMeta: { color: colors.muted, fontSize: 12, marginTop: spacing.xs }, empty: { color: colors.muted, textAlign: "center", marginTop: spacing.xxl }, error: { color: colors.danger }, retry: { alignSelf: "flex-start", minHeight: touchTarget, justifyContent: "center" }, retryText: { color: colors.primary, fontWeight: "700" } });
