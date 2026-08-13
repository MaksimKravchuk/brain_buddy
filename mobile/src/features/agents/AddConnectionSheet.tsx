import { useEffect, useRef, useState } from "react";
import { StyleSheet, TextInput, View } from "react-native";

import { isDefinitiveMutationFailure } from "@/api/client";
import type { AgentConnectionCreatedResponse } from "@/api/types";
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
  /** Receives the 201 body so the signing secret can be shown exactly once. */
  onCreated: (connection: AgentConnectionCreatedResponse) => void;
}

const DEFAULT_AUTH_HEADER = "X-Agent-Key";

/**
 * Adds an agent the user operates. The credential is entered masked, sent
 * once, and never rendered again from any later response — no response type
 * can even carry it.
 */
export function AddConnectionSheet({ visible, onClose, onCreated }: AddConnectionSheetProps) {
  const issuedSecret = useRef<string | null>(null);
  const create = useCreateAgentConnection({
    onSigningSecret: (secret) => {
      issuedSecret.current = secret;
    },
  });
  const [name, setName] = useState("");
  const [endpoint, setEndpoint] = useState("");
  const [authHeader, setAuthHeader] = useState(DEFAULT_AUTH_HEADER);
  const [credential, setCredential] = useState("");
  const [password, setPassword] = useState("");
  const [ambiguousIntent, setAmbiguousIntent] = useState<{ fingerprint: string } | null>(null);
  const [recoveryError, setRecoveryError] = useState<string | null>(null);
  const createKey = useIntentKey();

  const clearSensitiveForm = () => {
    create.reset();
    issuedSecret.current = null;
    setName("");
    setEndpoint("");
    setAuthHeader(DEFAULT_AUTH_HEADER);
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
    authHeader.trim().length > 0 &&
    credential.length > 0 &&
    password.length > 0;

  const submit = () => {
    const trimmedName = name.trim();
    const trimmedEndpoint = endpoint.trim();
    const trimmedAuthHeader = authHeader.trim();
    const intent = JSON.stringify([
      trimmedName,
      trimmedEndpoint,
      trimmedAuthHeader,
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
          endpoint_url: trimmedEndpoint,
          auth_header_name: trimmedAuthHeader,
          credential,
          current_password: password,
        },
        idempotencyKey: createKey.current(intent),
      },
      {
        onSuccess: (connection) => {
          const secret = issuedSecret.current;
          if (!secret) {
            setRecoveryError("No signing secret was returned. Replace it before connecting your agent.");
            return;
          }
          const created = { ...connection, inbound_signing_secret: secret };
          settleForm();
          onCreated(created);
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
        <BBText variant="label">Endpoint URL</BBText>
        <TextInput
          style={styles.input}
          value={endpoint}
          onChangeText={setEndpoint}
          placeholder="https://your-agent.example.com/brain-buddy"
          placeholderTextColor={colors.fg6}
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="url"
          editable={!create.isPending}
        />
        <BBText variant="micro" color={colors.fg5}>
          Must be an HTTPS destination. Loopback, link-local, metadata-service, and private-network
          addresses are refused unless your deployment enables that network class.
        </BBText>
      </View>

      <View style={styles.field}>
        <BBText variant="label">Auth header name</BBText>
        <TextInput
          style={styles.input}
          value={authHeader}
          onChangeText={setAuthHeader}
          placeholder={DEFAULT_AUTH_HEADER}
          placeholderTextColor={colors.fg6}
          autoCapitalize="none"
          autoCorrect={false}
          editable={!create.isPending}
        />
      </View>

      <View style={styles.field}>
        <BBText variant="label">Credential</BBText>
        <TextInput
          style={styles.input}
          value={credential}
          onChangeText={setCredential}
          placeholder="Sent as the auth header value"
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
