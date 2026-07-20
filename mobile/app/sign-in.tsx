import { Redirect } from "expo-router";
import { ActivityIndicator, View } from "react-native";
import { useAuth } from "@/auth/AuthProvider";
import { SignInScreen } from "@/features/auth/SignInScreen";
export default function SignInRoute() { const { ready, user } = useAuth(); if (!ready) return <View><ActivityIndicator /></View>; return user ? <Redirect href="/tasks/next" /> : <SignInScreen />; }
