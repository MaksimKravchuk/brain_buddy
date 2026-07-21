import { Redirect } from "expo-router";
import { ActivityIndicator, View } from "react-native";
import { useAuth } from "@/auth/AuthProvider";
import { BootstrapRetryScreen } from "@/auth/BootstrapRetryScreen";
import { SignInScreen } from "@/features/auth/SignInScreen";
export default function SignInRoute() { const { ready, user, bootstrapError } = useAuth(); if (!ready) return <View><ActivityIndicator /></View>; if (user) return <Redirect href="/tasks/next" />; return bootstrapError ? <BootstrapRetryScreen /> : <SignInScreen />; }
