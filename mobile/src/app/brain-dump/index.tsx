import { useRouter } from "expo-router";
import { Pause, Play, Square } from "lucide-react-native";
import { useEffect } from "react";
import { ActivityIndicator, Pressable, StyleSheet, View } from "react-native";

import { useSession } from "@/auth/SessionProvider";
import { BBText } from "@/components/BBText";
import { Button } from "@/components/Button";
import { ErrorBanner } from "@/components/ErrorBanner";
import { Screen } from "@/components/Screen";
import { PulsingMic } from "@/components/braindump/PulsingMic";
import { Waveform } from "@/components/braindump/Waveform";
import { MAX_RECORDING_MS, WARN_RECORDING_MS } from "@/braindump/recorder";
import { useBrainDumpCapture } from "@/braindump/useBrainDumpCapture";
import { colors, minHitTarget, radii, space } from "@/theme/tokens";

function formatDuration(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

export default function BrainDumpCaptureScreen() {
  const router = useRouter();
  const { voiceEnabled } = useSession();
  const capture = useBrainDumpCapture();
  const { phase } = capture;

  const recording = phase.kind === "recording";
  const paused = recording && phase.paused;

  // Hard stop under the server's 30-minute limit.
  useEffect(() => {
    if (recording && !paused && capture.durationMillis >= MAX_RECORDING_MS) {
      capture.stopAndSeal().then((operationId) => {
        if (operationId) {
          router.replace({ pathname: "/brain-dump/[operationId]", params: { operationId } });
        }
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recording, paused, capture.durationMillis]);

  const stop = async () => {
    const operationId = await capture.stopAndSeal();
    if (operationId) {
      router.replace({ pathname: "/brain-dump/[operationId]", params: { operationId } });
    }
  };

  const leave = async () => {
    await capture.cancel();
    router.back();
  };

  const providerLine = capture.providers
    ? [capture.providers.accurate_stt, capture.providers.reconciler]
        .filter(Boolean)
        .join(" and ")
    : "";

  return (
    <Screen padTop padBottom>
      <View style={styles.header}>
        <Pressable accessibilityRole="button" onPress={leave} style={styles.headerButton}>
          <BBText variant="body" color={colors.brandPrimary}>
            {phase.kind === "idle" ? "Close" : "Cancel"}
          </BBText>
        </Pressable>
        <BBText variant="subtitle">Brain dump</BBText>
        <View style={styles.headerButton} />
      </View>

      <View style={styles.body}>
        {!voiceEnabled ? (
          <View style={styles.card}>
            <BBText variant="title">Voice capture is not enabled</BBText>
            <BBText variant="body" color={colors.fg5}>
              Your account does not have the voice brain dump enabled yet.
            </BBText>
          </View>
        ) : capture.providersLoading ? (
          <ActivityIndicator color={colors.brandPrimary} />
        ) : capture.providersError ? (
          <ErrorBanner error={capture.providersError} />
        ) : !capture.consentAvailable ? (
          <View style={styles.card}>
            <BBText variant="title">Voice capture is unavailable</BBText>
            <BBText variant="body" color={colors.fg5}>
              No speech-to-text provider is configured on the server, so recording is disabled.
            </BBText>
          </View>
        ) : phase.kind === "idle" || phase.kind === "starting" ? (
          <View style={styles.centerBlock}>
            <PulsingMic active={false} />
            <BBText variant="display" style={styles.centerText}>
              Dump everything on your mind
            </BBText>
            <BBText variant="body" color={colors.fg5} style={styles.centerText}>
              Speak freely — tasks are proposed after you stop, and you review them before anything
              lands in your inbox.
            </BBText>
            <View style={styles.card}>
              <BBText variant="caption" color={colors.fg5}>
                {`After you stop, your audio is processed by ${providerLine} to propose tasks. Nothing is saved until you confirm.`}
              </BBText>
            </View>
            <Button onPress={capture.start} loading={phase.kind === "starting"}>
              Start recording
            </Button>
          </View>
        ) : phase.kind === "unavailable" ? (
          <View style={styles.card}>
            <BBText variant="title">
              {phase.reason === "mic-denied" ? "Microphone access needed" : "Voice capture unavailable"}
            </BBText>
            <BBText variant="body" color={colors.fg5}>
              {phase.reason === "mic-denied"
                ? "Allow microphone access in Settings to record a brain dump."
                : "Voice capture is not available for this account right now."}
            </BBText>
          </View>
        ) : recording ? (
          <View style={styles.centerBlock}>
            <PulsingMic active={!paused} />
            <View style={styles.recRow}>
              <View style={styles.recDot} />
              <BBText variant="body" weight="medium" color={colors.recording}>
                {formatDuration(capture.durationMillis)}
              </BBText>
              {paused ? (
                <BBText variant="body" color={colors.fg5}>
                  · paused
                </BBText>
              ) : null}
            </View>
            <Waveform metering={capture.metering} active={!paused} />
            {capture.durationMillis >= WARN_RECORDING_MS ? (
              <BBText variant="caption" color={colors.warningFg}>
                Recording stops automatically at 28 minutes.
              </BBText>
            ) : null}
            <BBText variant="caption" color={colors.fg5}>
              Recording locally — uploads when you stop. Nothing is saved until you confirm.
            </BBText>

            <View style={styles.controls}>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={paused ? "Resume" : "Pause"}
                onPress={paused ? capture.resume : capture.pause}
                style={styles.secondaryControl}
              >
                {paused ? (
                  <Play size={22} color={colors.fg3} strokeWidth={2} />
                ) : (
                  <Pause size={22} color={colors.fg3} strokeWidth={2} />
                )}
              </Pressable>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="Stop and review"
                onPress={stop}
                style={styles.stopControl}
              >
                <Square size={20} color="#FFFFFF" strokeWidth={2} fill="#FFFFFF" />
              </Pressable>
            </View>
            <BBText variant="body" weight="medium" color={colors.fg3}>
              Stop & review
            </BBText>
          </View>
        ) : phase.kind === "uploading" ? (
          <View style={styles.centerBlock}>
            <ActivityIndicator color={colors.brandPrimary} size="large" />
            <BBText variant="subtitle">
              {phase.total > 0
                ? `Uploading audio · chunk ${phase.uploaded} of ${phase.total}`
                : "Preparing upload…"}
            </BBText>
            <BBText variant="caption" color={colors.fg5}>
              Keep the app open while the recording uploads.
            </BBText>
          </View>
        ) : phase.kind === "sealing" ? (
          <View style={styles.centerBlock}>
            <ActivityIndicator color={colors.brandPrimary} size="large" />
            <BBText variant="subtitle">Finishing upload…</BBText>
          </View>
        ) : phase.kind === "error" ? (
          <View style={styles.centerBlock}>
            <ErrorBanner error={phase.error} onRetry={capture.retryUpload} />
            <Button variant="ghost" onPress={leave}>
              Discard this dump
            </Button>
          </View>
        ) : null}
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: space.s5,
    paddingVertical: space.s3,
  },
  headerButton: {
    minWidth: 64,
    minHeight: minHitTarget,
    justifyContent: "center",
  },
  body: {
    flex: 1,
    paddingHorizontal: space.s5,
    justifyContent: "center",
  },
  centerBlock: {
    alignItems: "center",
    gap: space.s4,
  },
  centerText: {
    textAlign: "center",
  },
  card: {
    backgroundColor: colors.surfaceRaised,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radii.card,
    padding: space.s4,
    gap: space.s2,
  },
  recRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: space.s2,
  },
  recDot: {
    width: 7,
    height: 7,
    borderRadius: radii.full,
    backgroundColor: colors.recording,
  },
  controls: {
    flexDirection: "row",
    alignItems: "center",
    gap: space.s5,
    marginTop: space.s2,
  },
  secondaryControl: {
    width: 56,
    height: 56,
    borderRadius: radii.full,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surfaceRaised,
    alignItems: "center",
    justifyContent: "center",
  },
  stopControl: {
    width: 72,
    height: 72,
    borderRadius: radii.full,
    backgroundColor: colors.recording,
    alignItems: "center",
    justifyContent: "center",
  },
});
