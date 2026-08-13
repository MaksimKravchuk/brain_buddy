import { useEffect, useRef, useState } from "react";
import { StyleSheet, TextInput, View } from "react-native";

import { isDefinitiveMutationFailure } from "@/api/client";
import { useDisconnectAgentConnection } from "@/api/hooks";
import type { AgentConnectionDisconnectRequest, AgentConnectionResponse } from "@/api/types";
import { BBText } from "@/components/BBText";
import { Button } from "@/components/Button";
import { ErrorBanner } from "@/components/ErrorBanner";
import { Sheet } from "@/components/Sheet";
import { colors, fonts, radii, space, type as typeScale } from "@/theme/tokens";
import { useIntentKey } from "@/utils/ids";

interface DisconnectSheetProps {
  connection: AgentConnectionResponse | null;
  onClose: () => void;
  onDisconnected: () => void;
}

interface DisconnectIntent {
  material: string;
  idempotencyKey: string;
  payload: AgentConnectionDisconnectRequest;
}

/**
 * Destroys the credential. The confirmation says plainly that this does not
 * cancel work already accepted by the external agent (FR-016) — if the user
 * wants that, cancellation has to be requested and confirmed first.
 */
export function DisconnectSheet({ connection, onClose, onDisconnected }: DisconnectSheetProps) {
  const disconnect = useDisconnectAgentConnection();
  const [password, setPassword] = useState("");
  const [intentConflict, setIntentConflict] = useState<string | null>(null);
  const intentKey = useIntentKey();
  const heldIntent = useRef<DisconnectIntent | null>(null);
  const intentConnectionId = useRef<string | null>(null);
  const connectionId = connection?.id;
  const resetDisconnect = disconnect.reset;
  const settleIntentKey = intentKey.settle;

  // Retargeting arrives as a prop change on a sheet that is still holding the
  // previous agent's password and intent. Closing (`connection === null`) is
  // not a retarget and must leave the held intent alone.
  useEffect(() => {
    if (!connectionId || intentConnectionId.current === connectionId) return;
    intentConnectionId.current = connectionId;
    setPassword("");
    setIntentConflict(null);
    resetDisconnect();
    settleIntentKey();
    heldIntent.current = null;
  }, [connectionId, resetDisconnect, settleIntentKey]);

  const close = () => {
    // Clear what is on screen; keep the held intent, because closing says
    // nothing about whether an ambiguous POST reached the server.
    setPassword("");
    onClose();
  };

  const submit = () => {
    if (!connection) {
      return;
    }
    const material = JSON.stringify([connection.id, password]);
    if (heldIntent.current && heldIntent.current.material !== material) {
      setIntentConflict(
        "The previous disconnect outcome is unknown. Restore the exact original password to retry safely.",
      );
      return;
    }
    setIntentConflict(null);
    const intent = heldIntent.current?.material === material
      ? heldIntent.current
      : {
          material,
          idempotencyKey: intentKey.current(material),
          payload: { current_password: password, expected_revision: connection.revision },
        };
    heldIntent.current = intent;
    disconnect.mutate(
      {
        connectionId: connection.id,
        payload: intent.payload,
        idempotencyKey: intent.idempotencyKey,
      },
      {
        onSuccess: () => {
          intentKey.settle();
          heldIntent.current = null;
          setPassword("");
          onDisconnected();
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
    <Sheet visible={connection !== null} onClose={close} title="Disconnect this agent">
      {connection ? (
        <View style={styles.body}>
          <View style={styles.warning}>
            <BBText variant="body" weight="medium" color={colors.warningFg}>
              Disconnecting does not cancel work the agent already accepted.
            </BBText>
            <BBText variant="caption" color={colors.warningFg}>
              {`If ${connection.name} supports cancellation and you want its current runs stopped, request cancellation and wait for the agent to confirm it before disconnecting.`}
            </BBText>
          </View>

          <BBText variant="caption" color={colors.fg4}>
            {`Brain Buddy destroys the stored credential, stops polling, and refuses new hand-offs and replies through ${connection.name}. Active runs become "Connection disconnected". Existing run history stays, redacted, until it expires.`}
          </BBText>

          {disconnect.isError ? <ErrorBanner error={disconnect.error} /> : null}
          {intentConflict ? (
            <BBText variant="caption" color={colors.warningFg}>{intentConflict}</BBText>
          ) : null}

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
              editable={!disconnect.isPending}
            />
          </View>

          <Button
            variant="destructive"
            onPress={submit}
            disabled={password.length === 0}
            loading={disconnect.isPending}
          >
            Disconnect and destroy the credential
          </Button>
          <Button variant="ghost" onPress={close} disabled={disconnect.isPending}>
            Keep this agent connected
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
  warning: {
    backgroundColor: colors.warningBg,
    borderWidth: 1,
    borderColor: colors.warningBorder,
    borderRadius: radii.card,
    padding: space.s4,
    gap: space.s2,
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
