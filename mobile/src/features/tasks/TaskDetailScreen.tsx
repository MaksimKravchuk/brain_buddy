import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { router } from "expo-router";
import { useRef } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";

import { MobileApiError } from "@/api/client";
import { useAuth } from "@/auth/AuthProvider";
import { colors, spacing, touchTarget } from "@/design/tokens";

export function TaskDetailScreen({ taskId }: { taskId: string }) {
  const { api } = useAuth();
  const client = useQueryClient();
  const task = useQuery({ queryKey: ["task", taskId], queryFn: () => api.task(taskId) });
  // Retained across a failed attempt so a Retry press reuses the same command
  // identity instead of minting a fresh idempotency key per press.
  const completeKey = useRef<string | null>(null);
  const complete = useMutation({
    mutationFn: () => {
      if (!task.data) throw new Error("Task is not loaded.");
      if (!completeKey.current) completeKey.current = crypto.randomUUID();
      return api.transition(
        task.data.id,
        { action: "complete", expected_revision: task.data.revision },
        completeKey.current,
      );
    },
    onSuccess: async () => {
      completeKey.current = null;
      await client.invalidateQueries({ queryKey: ["tasks"] });
      router.back();
    },
    onError: async (error) => {
      if (error instanceof MobileApiError && error.status === 409) {
        // The task changed elsewhere: expected_revision is stale, so this exact
        // command can never succeed. Refresh and require a fresh attempt/key
        // rather than silently re-sending the same now-invalid revision.
        completeKey.current = null;
        await client.invalidateQueries({ queryKey: ["task", taskId] });
      }
    },
  });
  if (task.isLoading) return <View style={styles.page}><ActivityIndicator accessibilityLabel="Loading task" color={colors.primary} /></View>;
  if (!task.data || task.isError) return <View style={styles.page}><Text accessibilityRole="alert" style={styles.error}>This task is unavailable.</Text></View>;
  const conflict = complete.isError && complete.error instanceof MobileApiError && complete.error.status === 409;
  return <View style={styles.page}><Text style={styles.state}>{task.data.state}</Text><Text style={styles.title}>{task.data.title}</Text>{task.data.details ? <Text style={styles.details}>{task.data.details}</Text> : null}<Text style={styles.meta}>Priority: {task.data.priority}</Text><Text style={styles.meta}>Revision: {task.data.revision}</Text>
    {complete.isError ? <Text accessibilityRole="alert" style={styles.error}>{conflict ? "This task changed elsewhere. Refreshed — try again." : "Complete failed."}</Text> : null}
    <Pressable accessibilityRole="button" accessibilityLabel={complete.isError ? "Retry complete task" : undefined} onPress={() => complete.mutate()} style={styles.button}><Text style={styles.buttonText}>{complete.isError ? "Retry" : "Complete task"}</Text></Pressable>
  </View>;
}
const styles = StyleSheet.create({ page: { backgroundColor: colors.surface, flex: 1, gap: spacing.md, padding: spacing.xl }, state: { color: colors.primary, fontWeight: "700", textTransform: "uppercase" }, title: { color: colors.text, fontSize: 26, fontWeight: "600" }, details: { color: colors.text, fontSize: 16 }, meta: { color: colors.muted }, button: { alignItems: "center", backgroundColor: colors.primary, borderRadius: 8, justifyContent: "center", marginTop: spacing.lg, minHeight: touchTarget }, buttonText: { color: colors.raised, fontWeight: "700" }, error: { color: colors.danger } });
