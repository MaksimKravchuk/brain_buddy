import { StyleSheet, View } from "react-native";

import type { AgentConnectionSigningSecretResponse } from "@/api/types";
import { BBText } from "@/components/BBText";
import { Button } from "@/components/Button";
import { Sheet } from "@/components/Sheet";
import { colors, radii, space, type as typeScale } from "@/theme/tokens";

interface SigningSecretSheetProps {
  connection: AgentConnectionSigningSecretResponse | null;
  onDismiss: () => void;
  onReplace?: (connection: AgentConnectionSigningSecretResponse) => void;
}

/**
 * The one and only place the inbound signing secret is ever rendered. It is
 * held in screen state for this sheet's lifetime, never written to the query
 * cache or storage, and cleared on dismiss.
 */
export function SigningSecretSheet({ connection, onDismiss, onReplace }: SigningSecretSheetProps) {
  const hasSecret = Boolean(connection?.inbound_signing_secret.trim());
  return (
    <Sheet visible={connection !== null} onClose={onDismiss} title="Copy the signing secret now">
      {connection ? (
        <View style={styles.body}>
          {hasSecret ? (
            <>
              <BBText variant="body" color={colors.fg3}>
                {`${connection.name} signs its reports with this secret. Brain Buddy stores it sealed and cannot show it again — if it is lost, replace the signing secret and configure the replacement.`}
              </BBText>
              <View style={styles.secretBox}>
                <BBText selectable style={styles.secret}>
                  {connection.inbound_signing_secret}
                </BBText>
              </View>
              <BBText variant="micro" color={colors.fg5}>
                Press and hold to select and copy.
              </BBText>
              <Button onPress={onDismiss}>I have copied it</Button>
            </>
          ) : (
            <>
              <BBText variant="body" color={colors.warningFg}>
                No signing secret was returned. The connection is still saved, but a blank secret
                cannot configure report signing.
              </BBText>
              {onReplace ? (
                <Button onPress={() => onReplace(connection)}>Replace signing secret</Button>
              ) : null}
              <Button variant="ghost" onPress={onDismiss}>Close</Button>
            </>
          )}
        </View>
      ) : null}
    </Sheet>
  );
}

const styles = StyleSheet.create({
  body: {
    gap: space.s3,
  },
  secretBox: {
    backgroundColor: colors.surfaceSunken,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radii.sm,
    padding: space.s3,
  },
  secret: {
    fontFamily: "Menlo",
    fontSize: typeScale.caption,
    lineHeight: Math.round(typeScale.caption * 1.5),
    color: colors.fg1,
  },
});
