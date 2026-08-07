import { StyleSheet, View } from "react-native";

import { ApiError } from "@/api/client";
import { BBText } from "@/components/BBText";
import { Button } from "@/components/Button";
import { colors, radii, space } from "@/theme/tokens";

interface ErrorBannerProps {
  error: unknown;
  onRetry?: () => void;
}

/**
 * Honest error surface: specific server message plus the correlation
 * reference for retry/report flows, per the product error contract.
 */
export function ErrorBanner({ error, onRetry }: ErrorBannerProps) {
  let message = "Something went wrong.";
  let reference: string | undefined;
  if (error instanceof ApiError) {
    message = error.serverMessage;
    reference = error.referenceId;
  } else if (error instanceof Error && error.message) {
    message = error.message;
  }
  return (
    <View style={styles.banner}>
      <BBText variant="body" color={colors.dangerFg}>
        {message}
      </BBText>
      {reference ? (
        <BBText variant="micro" color={colors.fg5} style={styles.reference}>
          {`ref: ${reference}`}
        </BBText>
      ) : null}
      {onRetry ? (
        <Button variant="destructive" onPress={onRetry} style={styles.retry}>
          Retry
        </Button>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  banner: {
    backgroundColor: colors.dangerBg,
    borderWidth: 1,
    borderColor: colors.dangerBorder,
    borderRadius: radii.card,
    padding: space.s4,
    gap: space.s2,
  },
  reference: {
    fontFamily: "Menlo",
  },
  retry: {
    alignSelf: "flex-start",
  },
});
