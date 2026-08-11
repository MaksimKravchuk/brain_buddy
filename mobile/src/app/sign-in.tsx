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
import { loadPersistedIdentity } from "@/auth/identityStorage";
import { useSession } from "@/auth/SessionProvider";
import { BBText } from "@/components/BBText";
import { Button } from "@/components/Button";
import { ErrorBanner } from "@/components/ErrorBanner";
import { Screen } from "@/components/Screen";
import { DEFAULT_SERVER_URL } from "@/config/serverUrl";
import { clearIdentityStores, loadQueue } from "@/features/tasks/classificationQueue.storage";
import type { PendingClassificationChange } from "@/features/tasks/classificationTypes";
import { DiscardUnsentSheet } from "@/features/tasks/DiscardUnsentSheet";
import type { ClassificationIdentity } from "@/features/tasks/storageKeys";
import {
  performIdentityTransition,
  planIdentityTransition,
  resolveIdentity,
} from "@/features/tasks/taskScreenState";
import { colors, fonts, radii, space, type as typeScale } from "@/theme/tokens";

type Mode = "sign-in" | "sign-up";

/** The server change waiting on M-05's answer. */
interface PendingDiscard {
  identity: ClassificationIdentity;
  queue: PendingClassificationChange[];
}

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
  const [pendingDiscard, setPendingDiscard] = useState<PendingDiscard | null>(null);

  const changingServer =
    showServer && serverDraft.trim() !== "" && serverDraft !== serverUrl;

  const runSubmit = async (withServerChange: boolean) => {
    setBusy(true);
    setError(null);
    try {
      if (withServerChange) {
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

  /**
   * FR-011 — the second and last call site of the discard gate.
   *
   * A server change is a deliberate identity transition here exactly as it is
   * in Settings, and `updateServerUrl` clears the previous server's persisted
   * identity: the warning and the discard therefore run **before** it, never
   * after, or the key the queue lives under stops being nameable.
   *
   * The identity comes from storage rather than from the session, because on
   * this screen there is no session. A device whose token expired holds its
   * identity and its unsent work still — FR-011 keeps both through an
   * involuntary end — so "signed out" here does not mean "nothing to lose".
   *
   * Returns true when the sign-in may go ahead now.
   */
  const clearServerChange = async (): Promise<boolean> => {
    const persisted = await loadPersistedIdentity(serverUrl);
    const identity = resolveIdentity({
      status: "signed-in",
      accountId: persisted?.accountId ?? null,
      serverUrl,
    });
    if (!identity) {
      return true;
    }
    const queue = await loadQueue(identity);
    if (!planIdentityTransition(queue, "server-change").needsWarning) {
      // FR-011 clears the cached project and Tag lists even with an empty
      // queue, where no sheet is shown at all.
      await clearIdentityStores(identity);
      return true;
    }
    setPendingDiscard({ identity, queue });
    return false;
  };

  const submit = async () => {
    if (changingServer && !(await clearServerChange())) {
      // M-05 is up; the sheet's own answer resumes or cancels this.
      return;
    }
    await runSubmit(changingServer);
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

            <Button
              onPress={() => {
                void submit();
              }}
              disabled={!canSubmit}
              loading={busy}
            >
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

      {/* M-05 — the count, and which action discards it. Never a list. */}
      <DiscardUnsentSheet
        visible={pendingDiscard !== null}
        queue={pendingDiscard?.queue ?? []}
        trigger="server-change"
        // Not a connectivity claim: "Stay and let them send" here cancels the
        // server change, which is precisely what keeps the queue sendable — so
        // it must stay available. Nobody is signed in on this screen, so a
        // drain is not what is being offered.
        online
        onStay={() => setPendingDiscard(null)}
        onContinue={() => {
          const current = pendingDiscard;
          if (!current) {
            return;
          }
          setPendingDiscard(null);
          void performIdentityTransition({
            discard: () => clearIdentityStores(current.identity),
            transition: () => runSubmit(true),
          }).catch((failure: unknown) => {
            // Nothing was discarded and the server was not changed. Surfacing
            // it on the form is enough here: the sign-in itself never ran.
            setError(failure);
          });
        }}
      />
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
