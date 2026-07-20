import { Redirect, useLocalSearchParams } from "expo-router";
import { ActivityIndicator, View } from "react-native";
import { useAuth } from "@/auth/AuthProvider";
import { TaskListScreen } from "@/features/tasks/TaskListScreen";
import type { TaskState } from "@/api/types";
const allowed = new Set(["inbox", "next", "waiting", "someday"]);
export default function TaskListRoute() { const { state } = useLocalSearchParams<{ state: string }>(); const { ready, user } = useAuth(); if (!ready) return <View><ActivityIndicator /></View>; if (!user) return <Redirect href="/sign-in" />; if (!allowed.has(state)) return <Redirect href="/tasks/next" />; return <TaskListScreen state={state as Exclude<TaskState, "completed" | "cancelled">} />; }
