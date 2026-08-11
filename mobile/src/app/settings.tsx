import { useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { ScrollView, StyleSheet, TextInput, View } from "react-native";

import { useSession } from "@/auth/SessionProvider";
import { BBText } from "@/components/BBText";
import { Button } from "@/components/Button";
import { Screen } from "@/components/Screen";
import { DEFAULT_SERVER_URL, currentServerUrl, normalizeServerUrl } from "@/config/serverUrl";
import { clearIdentityStores, loadQueue } from "@/features/tasks/classificationQueue.storage";
import type { PendingClassificationChange } from "@/features/tasks/classificationTypes";
import { DiscardUnsentSheet } from "@/features/tasks/DiscardUnsentSheet";
import type { ClassificationIdentity } from "@/features/tasks/storageKeys";
import {
  performIdentityTransition,
  planIdentityTransition,
  resolveIdentity,
  type IdentityTransitionKind,
} from "@/features/tasks/taskScreenState";
import { colors, fonts, radii, space, type as typeScale } from "@/theme/tokens";

/** The transition waiting on M-05's answer, with everything it needs to finish. */
interface PendingTransition {
  kind: IdentityTransitionKind;
  identity: ClassificationIdentity;
  queue: PendingClassificationChange[];
  run: () => Promise<void>;
}

export default function SettingsScreen() {
  const router = useRouter();
  const { me, status, accountId, serverUrl, updateServerUrl, signOut, voiceEnabled } =
    useSession();
  const [serverDraft, setServerDraft] = useState(serverUrl);
  const [saved, setSaved] = useState(false);
  const [pending, setPending] = useState<PendingTransition | null>(null);
  const [discardError, setDiscardError] = useState<{ message: string } | null>(null);

  /**
   * FR-011 — the gate in front of both deliberate identity transitions.
   *
   * The ordering is the whole point and is asserted in
   * `features/tasks/__tests__/taskScreenState.test.ts`: the warning and the
   * discard run **before** `signOut()` / `updateServerUrl()`, never after. Both
   * of those clear the persisted identity, and the persisted identity is both
   * halves of the queue's storage key — discarding afterwards discards nothing,
   * it strands the work under a key nothing can name.
   *
   * The cached project and Tag lists go **even when the queue is empty** and no
   * sheet is therefore shown. Those hold the names the person wrote, which is
   * the most disclosing thing this feature stores on the device.
   */
  const gate = useCallback(
    async (kind: IdentityTransitionKind, run: () => Promise<void>) => {
      const identity = resolveIdentity({ status, accountId, serverUrl });
      if (!identity) {
        // Nothing on the device is nameable under this session, so there is
        // nothing to discard and nothing to warn about.
        await run();
        return;
      }
      const queue = await loadQueue(identity);
      if (!planIdentityTransition(queue, kind).needsWarning) {
        await performIdentityTransition({
          discard: () => clearIdentityStores(identity),
          transition: run,
        });
        return;
      }
      setPending({ kind, identity, queue, run });
    },
    [status, accountId, serverUrl],
  );

  const confirmSaved = () => {
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  /**
   * FR-011 — the comparison has to happen **before** the gate, not inside
   * `updateServerUrl`.
   *
   * `updateServerUrl` does nothing when the normalized URL is unchanged, so by
   * the time it declines there is nothing left to decline: the person has
   * already been warned that continuing discards their unsent work, and
   * continuing has already discarded it. With an empty queue no sheet appears
   * at all and the discard is silent — the cached project and Tag lists go for
   * a save that changed nothing. Normalized, because that is the comparison
   * `updateServerUrl` itself makes: a trailing slash is the same server.
   */
  const saveServer = async () => {
    if (normalizeServerUrl(serverDraft) === currentServerUrl()) {
      confirmSaved();
      return;
    }
    await gate("server-change", async () => {
      await updateServerUrl(serverDraft);
      confirmSaved();
    });
  };

  const signOutWithGate = async () => {
    await gate("sign-out", async () => {
      await signOut();
      router.back();
    });
  };

  return (
    <Screen padTop padBottom>
      <ScrollView contentContainerStyle={styles.scroll}>
        <BBText variant="title">Settings</BBText>

        <BBText variant="label">Account</BBText>
        <View style={styles.card}>
          <BBText variant="body" weight="medium" color={colors.fg1}>
            {me?.email ?? "Not signed in"}
          </BBText>
          <BBText variant="caption" color={colors.fg5}>
            {voiceEnabled
              ? "Voice brain dump is enabled for this account."
              : "Voice brain dump is not enabled for this account."}
          </BBText>
        </View>

        <BBText variant="label">Server</BBText>
        <View style={styles.card}>
          <TextInput
            style={styles.input}
            value={serverDraft}
            onChangeText={setServerDraft}
            autoCapitalize="none"
            autoCorrect={false}
            keyboardType="url"
            placeholder={DEFAULT_SERVER_URL}
            placeholderTextColor={colors.fg6}
          />
          <BBText variant="caption" color={colors.fg5}>
            Changing the server signs you out of the current one.
          </BBText>
          <Button
            variant="secondary"
            onPress={() => {
              void saveServer();
            }}
          >
            {saved ? "Saved" : "Save server URL"}
          </Button>
        </View>

        <Button
          variant="destructive"
          onPress={() => {
            void signOutWithGate();
          }}
        >
          Sign out
        </Button>
      </ScrollView>

      {/* M-05 — the count, and which action discards it. Never a list. */}
      <DiscardUnsentSheet
        visible={pending !== null}
        queue={pending?.queue ?? []}
        trigger={pending?.kind ?? "sign-out"}
        // Settings is reached with a live session, and `mobile/` has no NetInfo
        // to ask; the drain itself is what discovers a lost connection.
        online={status === "signed-in"}
        error={discardError}
        onStay={() => {
          setPending(null);
          setDiscardError(null);
        }}
        onContinue={() => {
          const current = pending;
          if (!current) {
            return;
          }
          setDiscardError(null);
          setPending(null);
          void performIdentityTransition({
            discard: () => clearIdentityStores(current.identity),
            transition: current.run,
          }).catch((failure: unknown) => {
            // FR-012 / M-05 "error": nothing was discarded and nothing
            // transitioned, so the choice goes back to the person rather than
            // leaving them with a button that silently did nothing.
            setDiscardError({
              message: failure instanceof Error ? failure.message : "Something went wrong.",
            });
            setPending(current);
          });
        }}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  scroll: {
    padding: space.s5,
    gap: space.s3,
  },
  card: {
    backgroundColor: colors.surfaceRaised,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radii.card,
    padding: space.s4,
    gap: space.s3,
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
});
