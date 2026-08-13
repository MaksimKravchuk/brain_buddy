import { useEffect, useRef, useState } from "react";
import { StyleSheet, TextInput, View } from "react-native";

import { isDefinitiveMutationFailure } from "@/api/client";
import { useRotateAgentCredential } from "@/api/hooks";
import type { AgentConnectionResponse, AgentConnectionRotateRequest } from "@/api/types";
import { BBText } from "@/components/BBText";
import { Button } from "@/components/Button";
import { ErrorBanner } from "@/components/ErrorBanner";
import { Sheet } from "@/components/Sheet";
import { colors, fonts, radii, space, type as typeScale } from "@/theme/tokens";
import { useIntentKey } from "@/utils/ids";

interface RotateCredentialSheetProps {
  connection: AgentConnectionResponse | null;
  onClose: () => void;
  onRotated: () => void;
}

interface RotateIntent {
  material: string;
  idempotencyKey: string;
  payload: AgentConnectionRotateRequest;
}

/** Replaces the sealed credential. The old one is destroyed, not returned. */
export function RotateCredentialSheet({
  connection,
  onClose,
  onRotated,
}: RotateCredentialSheetProps) {
  const rotate = useRotateAgentCredential();
  const [credential, setCredential] = useState("");
  const [password, setPassword] = useState("");
  const [intentConflict, setIntentConflict] = useState<string | null>(null);
  const intentKey = useIntentKey();
  const heldIntent = useRef<RotateIntent | null>(null);
  const intentConnectionId = useRef<string | null>(null);
  const connectionId = connection?.id;
  const resetRotate = rotate.reset;
  const settleIntentKey = intentKey.settle;

  // The screen keeps one sheet mounted and swaps the target in, so retargeting
  // arrives as a prop change with the previous agent's secret still in state.
  // Closing goes through `connection === null`, which is not a retarget: the
  // held intent has to survive that so an ambiguous attempt stays retryable.
  useEffect(() => {
    if (!connectionId || intentConnectionId.current === connectionId) return;
    intentConnectionId.current = connectionId;
    setCredential("");
    setPassword("");
    setIntentConflict(null);
    resetRotate();
    settleIntentKey();
    heldIntent.current = null;
  }, [connectionId, resetRotate, settleIntentKey]);

  const close = () => {
    // Clear what is on screen; keep the held intent, because closing says
    // nothing about whether an ambiguous POST reached the server.
    setCredential("");
    setPassword("");
    onClose();
  };

  const submit = () => {
    if (!connection) {
      return;
    }
    const material = JSON.stringify([connection.id, credential, password]);
    if (heldIntent.current && heldIntent.current.material !== material) {
      setIntentConflict(
        "The previous credential change outcome is unknown. Restore the exact original values to retry safely.",
      );
      return;
    }
    setIntentConflict(null);
    const intent = heldIntent.current?.material === material
      ? heldIntent.current
      : {
          material,
          idempotencyKey: intentKey.current(material),
          payload: {
            credential,
            current_password: password,
            expected_revision: connection.revision,
          },
        };
    heldIntent.current = intent;
    rotate.mutate(
      {
        connectionId: connection.id,
        payload: intent.payload,
        idempotencyKey: intent.idempotencyKey,
      },
      {
        onSuccess: () => {
          intentKey.settle();
          heldIntent.current = null;
          setCredential("");
          setPassword("");
          onRotated();
        },
        onError: (error) => {
          if (isDefinitiveMutationFailure(error)) {
            intentKey.settle();
            heldIntent.current = null;
          }
        },
      },
    );
  };

  return (
    <Sheet visible={connection !== null} onClose={close} title="Rotate credential">
      {connection ? (
        <View style={styles.body}>
          <BBText variant="body" color={colors.fg4}>
            {`${connection.name} will authenticate with the new value from the next request onward. Test the connection afterwards.`}
          </BBText>

          {rotate.isError ? <ErrorBanner error={rotate.error} /> : null}
          {intentConflict ? (
            <BBText variant="caption" color={colors.warningFg}>{intentConflict}</BBText>
          ) : null}

          <View style={styles.field}>
            <BBText variant="label">New credential</BBText>
            <TextInput
              accessibilityLabel="New credential"
              style={styles.input}
              value={credential}
              onChangeText={setCredential}
              placeholder={`Sent as ${connection.auth_header_name}`}
              placeholderTextColor={colors.fg6}
              autoCapitalize="none"
              autoCorrect={false}
              secureTextEntry
              editable={!rotate.isPending}
            />
          </View>

          <View style={styles.field}>
            <BBText variant="label">Your Brain Buddy password</BBText>
            <TextInput
              accessibilityLabel="Your Brain Buddy password"
              style={styles.input}
              value={password}
              onChangeText={setPassword}
              placeholder="Confirm it is you"
              placeholderTextColor={colors.fg6}
              autoCapitalize="none"
              autoCorrect={false}
              secureTextEntry
              editable={!rotate.isPending}
            />
          </View>

          <Button
            onPress={submit}
            disabled={credential.length === 0 || password.length === 0}
            loading={rotate.isPending}
          >
            Replace credential
          </Button>
        </View>
      ) : null}
    </Sheet>
  );
}

const styles = StyleSheet.create({
  body: {
    gap: space.s3,
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
});
