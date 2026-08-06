import {
  Inter_400Regular,
  Inter_500Medium,
  Inter_600SemiBold,
  Inter_700Bold,
  useFonts,
} from "@expo-google-fonts/inter";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Stack, useRouter, useSegments } from "expo-router";
import * as SplashScreen from "expo-splash-screen";
import { StatusBar } from "expo-status-bar";
import { useEffect } from "react";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { ApiError } from "@/api/client";
import { SessionProvider, useSession } from "@/auth/SessionProvider";
import { colors } from "@/theme/tokens";

SplashScreen.preventAutoHideAsync();

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      retry: (failureCount, error) => {
        // Never retry client errors (401/404/409/422); one retry for the rest
        // (network blips, Fly cold starts).
        if (error instanceof ApiError && error.status < 500) {
          return false;
        }
        return failureCount < 1;
      },
    },
  },
});

function AuthGate({ children }: { children: React.ReactNode }) {
  const { status } = useSession();
  const segments = useSegments();
  const router = useRouter();

  useEffect(() => {
    if (status === "loading") {
      return;
    }
    SplashScreen.hideAsync();
    const onSignIn = segments[0] === "sign-in";
    if (status === "signed-out" && !onSignIn) {
      router.replace("/sign-in");
    } else if (status === "signed-in" && onSignIn) {
      router.replace("/");
    }
  }, [status, segments, router]);

  return <>{children}</>;
}

export default function RootLayout() {
  const [fontsLoaded] = useFonts({
    Inter_400Regular,
    Inter_500Medium,
    Inter_600SemiBold,
    Inter_700Bold,
  });

  if (!fontsLoaded) {
    return null;
  }

  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <SafeAreaProvider>
        <QueryClientProvider client={queryClient}>
          <SessionProvider>
            <AuthGate>
              <StatusBar style="dark" />
              <Stack
                screenOptions={{
                  headerShown: false,
                  contentStyle: { backgroundColor: colors.surfaceBase },
                }}
              >
                <Stack.Screen name="(tabs)" />
                <Stack.Screen name="sign-in" />
                <Stack.Screen name="task/[id]" options={{ presentation: "modal" }} />
                <Stack.Screen name="brain-dump/index" options={{ presentation: "fullScreenModal" }} />
                <Stack.Screen
                  name="brain-dump/[operationId]"
                  options={{ presentation: "fullScreenModal", gestureEnabled: false }}
                />
                <Stack.Screen name="settings" options={{ presentation: "modal" }} />
              </Stack>
            </AuthGate>
          </SessionProvider>
        </QueryClientProvider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}
