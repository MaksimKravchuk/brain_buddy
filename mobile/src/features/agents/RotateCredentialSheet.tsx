import { useEffect, useState } from "react";
import { StyleSheet, TextInput, View } from "react-native";

import { useRotateAgentCredential } from "@/api/hooks";
import type { AgentConnectionResponse } from "@/api/types";
import { BBText } from "@/components/BBText";
import { Button } from "@/components/Button";
import { ErrorBanner } from "@/components/ErrorBanner";
import { Sheet } from "@/components/Sheet";
import { colors, fonts, radii, space, type as typeScale } from "@/theme/tokens";

interface RotateCredentialSheetProps {
  connection: AgentConnectionResponse | null;
  onClose: () => void;
  onRotated: () => void;
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

  useEffect(() => {
    if (connection) {
      rotate.reset();
      setCredential("");
      setPassword("");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connection?.id]);

  const submit = () => {
    if (!connection) {
      return;
    }
    rotate.mutate(
      {
        connectionId: connection.id,
        payload: {
          credential,
          current_password: password,
          expected_revision: connection.revision,
        },
      },
      {
        onSuccess: () => {
          setCredential("");
          setPassword("");
          onRotated();
        },
      },
    );
  };

  return (
    <Sheet visible={connection !== null} onClose={onClose} title="Rotate credential">
      {connection ? (
        <View style={styles.body}>
          <BBText variant="body" color={colors.fg4}>
            {`${connection.name} will authenticate with the new value from the next request onward. Test the connection afterwards.`}
          </BBText>

          {rotate.isError ? <ErrorBanner error={rotate.error} /> : null}

          <View style={styles.field}>
            <BBText variant="label">New credential</BBText>
            <TextInput
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
