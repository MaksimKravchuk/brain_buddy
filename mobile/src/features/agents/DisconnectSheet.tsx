import { useEffect, useState } from "react";
import { StyleSheet, TextInput, View } from "react-native";

import { useDisconnectAgentConnection } from "@/api/hooks";
import type { AgentConnectionResponse } from "@/api/types";
import { BBText } from "@/components/BBText";
import { Button } from "@/components/Button";
import { ErrorBanner } from "@/components/ErrorBanner";
import { Sheet } from "@/components/Sheet";
import { colors, fonts, radii, space, type as typeScale } from "@/theme/tokens";

interface DisconnectSheetProps {
  connection: AgentConnectionResponse | null;
  onClose: () => void;
  onDisconnected: () => void;
}

/**
 * Destroys the credential. The confirmation says plainly that this does not
 * cancel work already accepted by the external agent (FR-016) — if the user
 * wants that, cancellation has to be requested and confirmed first.
 */
export function DisconnectSheet({ connection, onClose, onDisconnected }: DisconnectSheetProps) {
  const disconnect = useDisconnectAgentConnection();
  const [password, setPassword] = useState("");

  useEffect(() => {
    if (connection) {
      disconnect.reset();
      setPassword("");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connection?.id]);

  const submit = () => {
    if (!connection) {
      return;
    }
    disconnect.mutate(
      {
        connectionId: connection.id,
        payload: { current_password: password, expected_revision: connection.revision },
      },
      {
        onSuccess: () => {
          setPassword("");
          onDisconnected();
        },
      },
    );
  };

  return (
    <Sheet visible={connection !== null} onClose={onClose} title="Disconnect this agent">
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
          <Button variant="ghost" onPress={onClose} disabled={disconnect.isPending}>
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
