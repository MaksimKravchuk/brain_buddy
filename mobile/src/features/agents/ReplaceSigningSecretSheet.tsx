import { useEffect, useRef, useState } from "react";
import { StyleSheet, TextInput, View } from "react-native";
import { useQueryClient } from "@tanstack/react-query";

import type {
  AgentConnectionResponse,
  AgentConnectionSigningSecretResponse,
} from "@/api/types";
import { agentKeys } from "@/api/hooks";
import { useApi } from "@/auth/SessionProvider";
import { BBText } from "@/components/BBText";
import { Button } from "@/components/Button";
import { ErrorBanner } from "@/components/ErrorBanner";
import { Sheet } from "@/components/Sheet";
import { colors, fonts, radii, space, type as typeScale } from "@/theme/tokens";
import { useIntentKey } from "@/utils/ids";

interface ReplaceSigningSecretSheetProps {
  connection: AgentConnectionResponse | null;
  onClose: () => void;
  onReplaced: (connection: AgentConnectionSigningSecretResponse) => void;
}

/** Replaces a lost inbound signing secret; it does not touch the outbound credential. */
export function ReplaceSigningSecretSheet({
  connection,
  onClose,
  onReplaced,
}: ReplaceSigningSecretSheetProps) {
  const api = useApi();
  const queryClient = useQueryClient();
  const { current: currentIntentKey, settle: settleIntentKey } = useIntentKey();
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const intentConnectionId = useRef<string | null>(null);
  const connectionId = connection?.id;

  useEffect(() => {
    if (!connectionId) return;
    if (intentConnectionId.current !== connectionId) {
      settleIntentKey();
      intentConnectionId.current = connectionId;
    }
    setPassword("");
    setError(null);
    setPending(false);
  }, [connectionId, settleIntentKey]);

  const close = () => {
    // Closing is not evidence that an ambiguous POST did not succeed. Clear
    // password/error UI but keep the held key for reopening this same connection.
    setPassword("");
    setError(null);
    onClose();
  };

  const submit = async () => {
    if (!connection || pending || password.length === 0) return;
    setPending(true);
    setError(null);
    try {
      const replaced = await api.rotateAgentSigningSecret(
        connection.id,
        { current_password: password, expected_revision: connection.revision },
        currentIntentKey(`${connection.id}:${connection.revision}`),
      );
      settleIntentKey();
      setPassword("");
      await queryClient.invalidateQueries({ queryKey: agentKeys.root });
      onReplaced(replaced);
    } catch (caught) {
      // The failure can be ambiguous. Keep the same intent key for an explicit retry.
      setError(caught);
    } finally {
      setPending(false);
    }
  };

  return (
    <Sheet visible={connection !== null} onClose={close} title="Replace signing secret">
      {connection ? (
        <View style={styles.body}>
          <BBText variant="body" color={colors.fg4}>
            This replaces the secret your agent uses to sign reports. It does not change the
            credential Brain Buddy sends to your agent. Existing signing secrets stop working.
          </BBText>
          {error ? <ErrorBanner error={error} /> : null}
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
              editable={!pending}
            />
          </View>
          <Button onPress={() => void submit()} disabled={password.length === 0} loading={pending}>
            Replace signing secret
          </Button>
        </View>
      ) : null}
    </Sheet>
  );
}

const styles = StyleSheet.create({
  body: { gap: space.s3 },
  field: { gap: space.s2 },
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
