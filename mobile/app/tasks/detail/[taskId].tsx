import { Redirect, useLocalSearchParams } from "expo-router";
import { ActivityIndicator, View } from "react-native";
import { useAuth } from "@/auth/AuthProvider";
import { TaskDetailScreen } from "@/features/tasks/TaskDetailScreen";
export default function TaskDetailRoute() { const { taskId } = useLocalSearchParams<{ taskId: string }>(); const { ready, user } = useAuth(); if (!ready) return <View><ActivityIndicator /></View>; if (!user) return <Redirect href="/sign-in" />; return typeof taskId === "string" ? <TaskDetailScreen taskId={taskId} /> : <Redirect href="/tasks/next" />; }
