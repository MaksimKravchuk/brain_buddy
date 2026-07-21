import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors, spacing, touchTarget } from "@/design/tokens";
import { useAuth } from "./AuthProvider";

export function BootstrapRetryScreen() {
  const { retryBootstrap } = useAuth();
  return (
    <View style={styles.page}>
      <Text accessibilityRole="alert" style={styles.error}>
        Could not reach Brain Buddy. Your saved session is still here — check your connection and try again.
      </Text>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Retry connecting"
        onPress={() => void retryBootstrap()}
        style={styles.button}
      >
        <Text style={styles.buttonText}>Retry</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  page: { flex: 1, backgroundColor: colors.surface, justifyContent: "center", padding: spacing.xxl, gap: spacing.md },
  error: { color: colors.danger, fontSize: 15, textAlign: "center" },
  button: { alignItems: "center", backgroundColor: colors.primary, borderRadius: 8, justifyContent: "center", minHeight: touchTarget },
  buttonText: { color: colors.raised, fontWeight: "600" },
});
