import { useEffect, useState } from "react";
import { Pressable, StyleSheet, TextInput, View } from "react-native";

import { isDefinitiveMutationFailure } from "@/api/client";
import type { AgentAuthScheme, AgentConnectionResponse } from "@/api/types";
import { useCreateAgentConnection } from "@/api/hooks";
import { BBText } from "@/components/BBText";
import { Button } from "@/components/Button";
import { ErrorBanner } from "@/components/ErrorBanner";
import { Sheet } from "@/components/Sheet";
import { colors, fonts, radii, space, type as typeScale } from "@/theme/tokens";
import { useIntentKey } from "@/utils/ids";
import { sha256 } from "js-sha256";

interface AddConnectionSheetProps {
  visible: boolean;
  onClose: () => void;
  /** Receives the saved connection. There is no secret to hand over (FR-012). */
  onCreated: (connection: AgentConnectionResponse) => void;
}

/**
 * Adds an agent the user operates, by its address plus one of exactly two
 * credential schemes (M-01-S08).
 *
 * The credential is entered masked, sent once, and never rendered again from
 * any later response — no response type can even carry it. Dismissing the sheet
 * discards everything silently: nothing was stored, nothing was sent, and the
 * four fields are cheap to re-enter, so a warning would only be noise.
 */
export function AddConnectionSheet({ visible, onClose, onCreated }: AddConnectionSheetProps) {
  const create = useCreateAgentConnection();
  const [name, setName] = useState("");
  const [endpoint, setEndpoint] = useState("");
  const [authScheme, setAuthScheme] = useState<AgentAuthScheme>("bearer");
  const [credential, setCredential] = useState("");
  const [password, setPassword] = useState("");
  const [ambiguousIntent, setAmbiguousIntent] = useState<{ fingerprint: string } | null>(null);
  const [recoveryError, setRecoveryError] = useState<string | null>(null);
  const createKey = useIntentKey();

  const clearSensitiveForm = () => {
    create.reset();
    setName("");
    setEndpoint("");
    setAuthScheme("bearer");
    setCredential("");
    setPassword("");
    setRecoveryError(null);
  };

  const settleForm = () => {
    clearSensitiveForm();
    createKey.settle();
    setAmbiguousIntent(null);
  };

  useEffect(() => {
    if (visible) {
      void Promise.resolve().then(clearSensitiveForm);
    }
    // Reset only on visibility transitions; mutation and intent helpers are stable.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible]);

  const close = () => {
    clearSensitiveForm();
    onClose();
  };

  const canSubmit =
    name.trim().length > 0 &&
    endpoint.trim().length > 0 &&
    credential.length > 0 &&
    password.length > 0;

  const submit = () => {
    const trimmedName = name.trim();
    const trimmedEndpoint = endpoint.trim();
    const intent = JSON.stringify([
      trimmedName,
      trimmedEndpoint,
      authScheme,
      credential,
      password,
    ]);
    const fingerprint = sha256(intent);
    if (ambiguousIntent && ambiguousIntent.fingerprint !== fingerprint) {
      setRecoveryError(
        "The previous save outcome is unknown. Re-enter the exact same connection details and secrets to recover it without creating a duplicate.",
      );
      return;
    }
    setRecoveryError(null);
    create.mutate(
      {
        payload: {
          name: trimmedName,
          agent_address: trimmedEndpoint,
          auth_scheme: authScheme,
          credential,
          current_password: password,
        },
        idempotencyKey: createKey.current(intent),
      },
      {
        onSuccess: (connection) => {
          settleForm();
          onCreated(connection);
        },
        onError: (error) => {
          if (isDefinitiveMutationFailure(error)) {
            createKey.settle();
            setAmbiguousIntent(null);
          } else {
            // Retain only a digest of the canonical input. The credential and
            // password leave rendered state immediately on dismissal, while a
            // retry of the exact same intent keeps the original key.
            setAmbiguousIntent({ fingerprint });
          }
        },
      },
    );
  };

  return (
    <Sheet visible={visible} onClose={close} title="Add an agent">
      <BBText variant="caption" color={colors.fg5}>
        You operate this agent. Brain Buddy relays a task to it, shows what it reports, and never
        verifies its work.
      </BBText>

      {create.isError ? <ErrorBanner error={create.error} /> : null}
      {ambiguousIntent ? (
        <BBText variant="caption" color={colors.warningFg}>
          The previous save outcome is unknown. Re-enter the exact same details and secrets to
          recover that connection with the same key; different details are blocked to avoid a
          duplicate.
        </BBText>
      ) : null}
      {recoveryError ? (
        <BBText variant="caption" color={colors.dangerFg}>
          {recoveryError}
        </BBText>
      ) : null}

      <View style={styles.field}>
        <BBText variant="label">Agent name</BBText>
        <TextInput
          style={styles.input}
          value={name}
          onChangeText={setName}
          placeholder="What you call this agent"
          placeholderTextColor={colors.fg6}
          editable={!create.isPending}
        />
      </View>

      <View style={styles.field}>
        <BBText variant="label">Agent address</BBText>
        <TextInput
          style={styles.input}
          value={endpoint}
          onChangeText={setEndpoint}
          placeholder="https://your-agent.example.com"
          placeholderTextColor={colors.fg6}
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="url"
          editable={!create.isPending}
        />
        <BBText variant="micro" color={colors.fg5}>
          Brain Buddy fetches the agent card from this address&apos;s standard well-known location.
          It must be an HTTPS destination. Loopback, link-local, metadata-service, and
          private-network addresses are refused unless your deployment enables that network class.
        </BBText>
      </View>

      <View style={styles.field}>
        <BBText variant="label">Credential scheme</BBText>
        <View style={styles.schemeRow}>
          {(
            [
              ["bearer", "Bearer token"],
              ["api_key", "API key"],
            ] as const
          ).map(([scheme, label]) => (
            <Pressable
              key={scheme}
              accessibilityRole="radio"
              accessibilityState={{
                checked: authScheme === scheme,
                disabled: create.isPending,
              }}
              accessibilityLabel={label}
              disabled={create.isPending}
              onPress={() => setAuthScheme(scheme)}
              style={[styles.scheme, authScheme === scheme ? styles.schemeChecked : null]}
            >
              <BBText variant="body">{label}</BBText>
            </Pressable>
          ))}
        </View>
        {authScheme === "api_key" ? (
          <BBText variant="micro" color={colors.fg5}>
            Read from the agent card when you test. You do not type it.
          </BBText>
        ) : null}
      </View>

      <View style={styles.field}>
        <BBText variant="label">Credential</BBText>
        <TextInput
          style={styles.input}
          value={credential}
          onChangeText={setCredential}
          placeholder="Sent as the credential"
          placeholderTextColor={colors.fg6}
          autoCapitalize="none"
          autoCorrect={false}
          secureTextEntry
          editable={!create.isPending}
        />
        <BBText variant="micro" color={colors.fg5}>
          Stored sealed and never shown again. To change it later, rotate it.
        </BBText>
      </View>

      <View style={styles.field}>
        <BBText variant="label">Your Brain Buddy password</BBText>
        <TextInput
          style={styles.input}
          value={password}
          onChangeText={setPassword}
          placeholder="Confirm it is you"
          placeholderTextColor={colors.fg6}
          autoCapitalize="none"
          autoCorrect={false}
          secureTextEntry
          editable={!create.isPending}
        />
      </View>

      <Button onPress={submit} disabled={!canSubmit} loading={create.isPending}>
        Save agent
      </Button>
    </Sheet>
  );
}

const styles = StyleSheet.create({
  field: {
    gap: space.s2,
  },
  schemeRow: {
    flexDirection: "row",
    gap: space.s3,
  },
  scheme: {
    minHeight: 44,
    justifyContent: "center",
    paddingHorizontal: space.s3,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radii.sm,
  },
  schemeChecked: {
    borderColor: colors.fg1,
    backgroundColor: colors.surfaceRaised,
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
