import { useQuery, useQueryClient } from "@tanstack/react-query";
import { router } from "expo-router";
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";

import { useAuth } from "@/auth/AuthProvider";
import { colors, spacing, touchTarget } from "@/design/tokens";

export function TaskDetailScreen({ taskId }: { taskId: string }) {
  const { api } = useAuth();
  const client = useQueryClient();
  const task = useQuery({ queryKey: ["task", taskId], queryFn: () => api.task(taskId) });
  const complete = async () => {
    if (!task.data) return;
    await api.transition(task.data.id, { action: "complete", expected_revision: task.data.revision });
    await client.invalidateQueries({ queryKey: ["tasks"] });
    router.back();
  };
  if (task.isLoading) return <View style={styles.page}><ActivityIndicator accessibilityLabel="Loading task" color={colors.primary} /></View>;
  if (!task.data || task.isError) return <View style={styles.page}><Text accessibilityRole="alert" style={styles.error}>This task is unavailable.</Text></View>;
  return <View style={styles.page}><Text style={styles.state}>{task.data.state}</Text><Text style={styles.title}>{task.data.title}</Text>{task.data.details ? <Text style={styles.details}>{task.data.details}</Text> : null}<Text style={styles.meta}>Priority: {task.data.priority}</Text><Text style={styles.meta}>Revision: {task.data.revision}</Text><Pressable accessibilityRole="button" onPress={() => void complete()} style={styles.button}><Text style={styles.buttonText}>Complete task</Text></Pressable></View>;
}
const styles = StyleSheet.create({ page: { backgroundColor: colors.surface, flex: 1, gap: spacing.md, padding: spacing.xl }, state: { color: colors.primary, fontWeight: "700", textTransform: "uppercase" }, title: { color: colors.text, fontSize: 26, fontWeight: "600" }, details: { color: colors.text, fontSize: 16 }, meta: { color: colors.muted }, button: { alignItems: "center", backgroundColor: colors.primary, borderRadius: 8, justifyContent: "center", marginTop: spacing.lg, minHeight: touchTarget }, buttonText: { color: colors.raised, fontWeight: "700" }, error: { color: colors.danger } });
