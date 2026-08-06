import { useState } from "react";
import {
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  TextInput,
  View,
} from "react-native";
import { Sprout } from "lucide-react-native";

import { ApiError } from "@/api/client";
import { useSession } from "@/auth/SessionProvider";
import { BBText } from "@/components/BBText";
import { Button } from "@/components/Button";
import { ErrorBanner } from "@/components/ErrorBanner";
import { Screen } from "@/components/Screen";
import { DEFAULT_SERVER_URL } from "@/config/serverUrl";
import { colors, fonts, radii, space, type as typeScale } from "@/theme/tokens";

type Mode = "sign-in" | "sign-up";

export default function SignInScreen() {
  const { signIn, signUp, serverUrl, updateServerUrl } = useSession();
  const [mode, setMode] = useState<Mode>("sign-in");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [inviteCode, setInviteCode] = useState("");
  const [showServer, setShowServer] = useState(serverUrl !== DEFAULT_SERVER_URL);
  const [serverDraft, setServerDraft] = useState(serverUrl);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      if (showServer && serverDraft.trim() && serverDraft !== serverUrl) {
        await updateServerUrl(serverDraft);
      }
      if (mode === "sign-in") {
        await signIn(email, password);
      } else {
        await signUp(email, password, inviteCode);
      }
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  const canSubmit =
    email.trim().length > 0 &&
    password.length > 0 &&
    (mode === "sign-in" || inviteCode.trim().length > 0);

  return (
    <Screen padTop padBottom>
      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : undefined}
        style={styles.flex}
      >
        <ScrollView
          contentContainerStyle={styles.scroll}
          keyboardShouldPersistTaps="handled"
        >
          <View style={styles.logoRow}>
            <View style={styles.logoBadge}>
              <Sprout size={28} color="#FFFFFF" strokeWidth={2} />
            </View>
            <BBText variant="title">Brain Buddy</BBText>
          </View>

          <View style={styles.card}>
            <BBText variant="display">
              {mode === "sign-in" ? "Welcome back" : "Create your account"}
            </BBText>
            <BBText variant="body" color={colors.fg5}>
              {mode === "sign-in"
                ? "Sign in to your tasks and thinking space."
                : "Signup needs an invite code from your Brain Buddy admin."}
            </BBText>

            {error ? <ErrorBanner error={error} /> : null}
            {error instanceof ApiError && error.status === 429 ? (
              <BBText variant="caption" color={colors.fg5}>
                Too many attempts — wait a few minutes before trying again.
              </BBText>
            ) : null}

            <View style={styles.field}>
              <BBText variant="label">Email</BBText>
              <TextInput
                style={styles.input}
                value={email}
                onChangeText={setEmail}
                autoCapitalize="none"
                autoComplete="email"
                keyboardType="email-address"
                textContentType="emailAddress"
                placeholder="you@example.com"
                placeholderTextColor={colors.fg6}
                editable={!busy}
              />
            </View>

            <View style={styles.field}>
              <BBText variant="label">Password</BBText>
              <TextInput
                style={styles.input}
                value={password}
                onChangeText={setPassword}
                secureTextEntry
                autoComplete={mode === "sign-in" ? "current-password" : "new-password"}
                textContentType={mode === "sign-in" ? "password" : "newPassword"}
                placeholder={mode === "sign-up" ? "At least 12 characters" : "Your password"}
                placeholderTextColor={colors.fg6}
                editable={!busy}
              />
              {mode === "sign-up" ? (
                <BBText variant="caption" color={colors.fg5}>
                  At least 12 characters. Longer is better.
                </BBText>
              ) : null}
            </View>

            {mode === "sign-up" ? (
              <View style={styles.field}>
                <BBText variant="label">Invite code</BBText>
                <TextInput
                  style={styles.input}
                  value={inviteCode}
                  onChangeText={setInviteCode}
                  autoCapitalize="none"
                  autoCorrect={false}
                  placeholder="Paste your invite code"
                  placeholderTextColor={colors.fg6}
                  editable={!busy}
                />
              </View>
            ) : null}

            <Button onPress={submit} disabled={!canSubmit} loading={busy}>
              {mode === "sign-in" ? "Sign in" : "Create account"}
            </Button>

            <Pressable
              accessibilityRole="button"
              onPress={() => {
                setMode(mode === "sign-in" ? "sign-up" : "sign-in");
                setError(null);
              }}
              style={styles.switchMode}
            >
              <BBText variant="body" color={colors.brandPrimary}>
                {mode === "sign-in" ? "Have an invite code? Create an account" : "Back to sign in"}
              </BBText>
            </Pressable>
          </View>

          <Pressable
            accessibilityRole="button"
            onPress={() => setShowServer((value) => !value)}
            style={styles.serverToggle}
          >
            <BBText variant="caption" color={colors.fg5}>
              {showServer ? "Hide server settings" : "Server settings"}
            </BBText>
          </Pressable>
          {showServer ? (
            <View style={styles.field}>
              <BBText variant="label">Server URL</BBText>
              <TextInput
                style={styles.input}
                value={serverDraft}
                onChangeText={setServerDraft}
                autoCapitalize="none"
                autoCorrect={false}
                keyboardType="url"
                placeholder={DEFAULT_SERVER_URL}
                placeholderTextColor={colors.fg6}
                editable={!busy}
              />
              <BBText variant="caption" color={colors.fg5}>
                {`Default: ${DEFAULT_SERVER_URL}. For development use http://<lan-ip>:8000/api.`}
              </BBText>
            </View>
          ) : null}
        </ScrollView>
      </KeyboardAvoidingView>
    </Screen>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  scroll: {
    padding: space.s5,
    gap: space.s4,
    flexGrow: 1,
    justifyContent: "center",
  },
  logoRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: space.s3,
  },
  logoBadge: {
    width: 48,
    height: 48,
    borderRadius: radii.full,
    backgroundColor: colors.brandPrimary,
    alignItems: "center",
    justifyContent: "center",
  },
  card: {
    backgroundColor: colors.surfaceRaised,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radii.lg,
    padding: space.s5,
    gap: space.s4,
  },
  field: {
    gap: space.s2,
  },
  input: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radii.sm,
    paddingHorizontal: space.s3,
    paddingVertical: space.s3,
    fontSize: typeScale.body,
    fontFamily: fonts.regular,
    color: colors.fg1,
    backgroundColor: colors.surfaceRaised,
    minHeight: 44,
  },
  switchMode: {
    alignSelf: "center",
    minHeight: 44,
    justifyContent: "center",
  },
  serverToggle: {
    alignSelf: "center",
    minHeight: 44,
    justifyContent: "center",
  },
});
