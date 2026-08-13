import { useCallback, useEffect, useRef, useState } from "react";
import { StyleSheet, TextInput, View } from "react-native";


import { isDefinitiveMutationFailure } from "@/api/client";
import type {
  AgentConnectionResponse,
  AgentConnectionRotateSigningSecretRequest,
  AgentConnectionSigningSecretResponse,
} from "@/api/types";
import { useRotateAgentSigningSecret } from "@/api/hooks";
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

/**
 * One attempt: a key and the exact body it was minted for.
 *
 * The pair travels together so a retry can never send a different body under a
 * key the server may already have answered. `material` is what makes two
 * attempts the same command; it deliberately excludes the revision, because a
 * revision that moved under us is evidence the first attempt landed, and the
 * frozen `expected_revision` is what turns that into a 409 instead of a second
 * rotation.
 */
interface ReplaceIntent {
  material: string;
  idempotencyKey: string;
  payload: AgentConnectionRotateSigningSecretRequest;
}

/** Replaces a lost inbound signing secret; it does not touch the outbound credential. */
export function ReplaceSigningSecretSheet({
  connection,
  onClose,
  onReplaced,
}: ReplaceSigningSecretSheetProps) {
  const issuedSecret = useRef<string | null>(null);
  const rotate = useRotateAgentSigningSecret({
    onSigningSecret: (secret) => {
      issuedSecret.current = secret;
    },
  });
  const { current: currentIntentKey, settle: settleIntentKey } = useIntentKey();
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const intentConnectionId = useRef<string | null>(null);
  const heldIntent = useRef<ReplaceIntent | null>(null);
  const connectionId = connection?.id;

  const retire = useCallback(() => {
    settleIntentKey();
    heldIntent.current = null;
  }, [settleIntentKey]);

  useEffect(() => {
    if (!connectionId) return;
    if (intentConnectionId.current !== connectionId) {
      // A different connection is a different command. Nothing held for the
      // previous one may follow the user here.
      retire();
      intentConnectionId.current = connectionId;
    }
    void Promise.resolve().then(() => {
      setPassword("");
      setError(null);
      setPending(false);
    });
  }, [connectionId, retire]);

  const close = () => {
    // Closing is not evidence that an ambiguous POST did not succeed. Clear
    // password/error UI but keep the held intent for reopening this same
    // connection; it lives in a ref, so it is never rendered or logged.
    setPassword("");
    setError(null);
    onClose();
  };

  const submit = async () => {
    if (!connection || pending || password.length === 0) return;
    const material = JSON.stringify([connection.id, password]);
    if (heldIntent.current && heldIntent.current.material !== material) {
      setError(
        new Error(
          "The previous signing-secret replacement outcome is unknown. Restore the exact original password to retry safely.",
        ),
      );
      return;
    }
    const intent: ReplaceIntent =
      heldIntent.current?.material === material
        ? heldIntent.current
        : {
            material,
            idempotencyKey: currentIntentKey(material),
            payload: { current_password: password, expected_revision: connection.revision },
          };
    heldIntent.current = intent;
    setPending(true);
    setError(null);
    issuedSecret.current = null;
    try {
      const replaced = await rotate.mutateAsync({
        connectionId: connection.id,
        payload: intent.payload,
        idempotencyKey: intent.idempotencyKey,
      });
      const secret = issuedSecret.current;
      if (!secret) {
        throw new Error("The signing secret was not returned.");
      }
      retire();
      setPassword("");
      onReplaced({ ...replaced, inbound_signing_secret: secret });
    } catch (caught) {
      // Most 4xx responses are decided outcomes, but 408/429 remain ambiguous
      // because an edge may answer after forwarding the request. Hold the exact
      // key and body whenever the shared classifier cannot prove settlement.
      if (isDefinitiveMutationFailure(caught)) {
        retire();
      }
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
