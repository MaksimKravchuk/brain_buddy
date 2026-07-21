import { useState } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, TextInput, View } from "react-native";

import { MobileApiError } from "@/api/client";
import { useAuth } from "@/auth/AuthProvider";
import { colors, spacing, touchTarget } from "@/design/tokens";

export function SignInScreen() {
  const { signIn, logoutRevocationUnresolved, retryLogout } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retryingLogout, setRetryingLogout] = useState(false);
  const submit = async () => {
    setBusy(true); setError(null);
    try { await signIn(email, password); }
    catch (cause) {
      const reference = cause instanceof MobileApiError && cause.correlationId ? ` Reference: ${cause.correlationId}.` : "";
      setError(`We couldn't sign you in. Check your details and try again.${reference}`);
    } finally { setBusy(false); }
  };
  const retrySignOut = async () => {
    setRetryingLogout(true);
    try { await retryLogout(); } finally { setRetryingLogout(false); }
  };
  return <View style={styles.page}>
    <Text style={styles.eyebrow}>BRAIN BUDDY</Text><Text style={styles.title}>Sign in</Text>
    <Text style={styles.copy}>Use your existing account to see your canonical tasks.</Text>
    {logoutRevocationUnresolved ? <View>
      <Text accessibilityRole="alert" style={styles.error}>
        You are signed out on this device, but we could not confirm your last sign-out with the server. Try again, or sign in — it will not affect your new session.
      </Text>
      <Pressable accessibilityRole="button" accessibilityLabel="Retry sign-out" disabled={retryingLogout} onPress={() => void retrySignOut()} style={styles.retry}>
        <Text style={styles.retryText}>Retry sign-out</Text>
      </Pressable>
    </View> : null}
    <TextInput accessibilityLabel="Email" autoCapitalize="none" keyboardType="email-address" onChangeText={setEmail} style={styles.input} value={email} />
    <TextInput accessibilityLabel="Password" onChangeText={setPassword} secureTextEntry style={styles.input} value={password} />
    {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
    <Pressable accessibilityRole="button" disabled={busy} onPress={() => void submit()} style={styles.button}>
      {busy ? <ActivityIndicator color={colors.raised} /> : <Text style={styles.buttonText}>Sign in</Text>}
    </Pressable>
  </View>;
}
const styles = StyleSheet.create({ page: { flex: 1, backgroundColor: colors.surface, justifyContent: "center", padding: spacing.xxl, gap: spacing.md }, eyebrow: { color: colors.primary, fontSize: 10, fontWeight: "700", letterSpacing: 1 }, title: { color: colors.text, fontSize: 28, fontWeight: "600" }, copy: { color: colors.muted, fontSize: 15, marginBottom: spacing.md }, input: { backgroundColor: colors.raised, borderColor: colors.border, borderRadius: 8, borderWidth: 1, minHeight: touchTarget, paddingHorizontal: spacing.md }, button: { alignItems: "center", backgroundColor: colors.primary, borderRadius: 8, justifyContent: "center", minHeight: touchTarget }, buttonText: { color: colors.raised, fontWeight: "600" }, error: { color: colors.danger, fontSize: 14 }, retry: { alignSelf: "flex-start", minHeight: touchTarget, justifyContent: "center" }, retryText: { color: colors.primary, fontWeight: "700" } });
