import { useRouter } from "expo-router";
import { Mic, Pause, Play, Square, X } from "lucide-react-native";
import { useEffect } from "react";
import { ActivityIndicator, Pressable, StyleSheet, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useSession } from "@/auth/SessionProvider";
import { BBText } from "@/components/BBText";
import { Button } from "@/components/Button";
import { ErrorBanner } from "@/components/ErrorBanner";
import { Screen } from "@/components/Screen";
import { PulsingMic } from "@/components/braindump/PulsingMic";
import { Waveform } from "@/components/braindump/Waveform";
import { MAX_RECORDING_MS, WARN_RECORDING_MS } from "@/braindump/recorder";
import { useBrainDumpCapture } from "@/braindump/useBrainDumpCapture";
import { colors, fonts, minHitTarget, radii, space } from "@/theme/tokens";

function formatDuration(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

export default function BrainDumpCaptureScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
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
    ? [capture.providers.accurate_stt, capture.providers.reconciler].filter(Boolean).join(" and ")
    : "";

  return (
    <Screen>
      {/* Head row: mic badge · recording timer · close */}
      <View style={[styles.head, { paddingTop: insets.top + space.s3 }]}>
        <View style={styles.micBadge}>
          <Mic size={16} color="#FFFFFF" strokeWidth={2} />
        </View>
        {recording ? (
          <View style={styles.rec}>
            <View style={styles.recDot} />
            <BBText style={styles.recText}>{formatDuration(capture.durationMillis)}</BBText>
            {paused ? (
              <BBText variant="caption" color={colors.fg5}>
                paused
              </BBText>
            ) : null}
          </View>
        ) : (
          <BBText style={styles.headTitle}>Brain dump</BBText>
        )}
        <View style={styles.headSpacer} />
        {recording ? (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={paused ? "Resume" : "Pause"}
            onPress={paused ? capture.resume : capture.pause}
            style={styles.iconButton}
          >
            {paused ? (
              <Play size={18} color={colors.fg4} strokeWidth={2} />
            ) : (
              <Pause size={18} color={colors.fg4} strokeWidth={2} />
            )}
          </Pressable>
        ) : null}
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Discard and close"
          onPress={leave}
          style={styles.iconButton}
        >
          <X size={18} color={colors.fg4} strokeWidth={2} />
        </Pressable>
      </View>

      {/* Middle */}
      <View style={styles.middle}>
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
            <PulsingMic active={!paused} size={64} />
            {capture.durationMillis >= WARN_RECORDING_MS ? (
              <BBText variant="caption" color={colors.warningFg}>
                Recording stops automatically at 28 minutes.
              </BBText>
            ) : null}
            <BBText variant="caption" color={colors.fg5} style={styles.centerText}>
              Recording locally — uploads when you stop.
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
            <ErrorBanner
              error={phase.error}
              onRetry={
                phase.recoverable
                  ? async () => {
                      const operationId = await capture.retryUpload();
                      if (operationId) {
                        router.replace({
                          pathname: "/brain-dump/[operationId]",
                          params: { operationId },
                        });
                      }
                    }
                  : undefined
              }
            />
            <Button variant="ghost" onPress={leave}>
              Discard this dump
            </Button>
          </View>
        ) : null}
      </View>

      {/* Bottom sheet */}
      {capture.consentAvailable && (phase.kind === "idle" || phase.kind === "starting" || recording) ? (
        <View style={[styles.sheet, { paddingBottom: insets.bottom + space.s5 }]}>
          {recording ? (
            <>
              <BBText variant="caption" color={colors.fg5} style={styles.centerText}>
                Tasks are proposed after you stop — you review them before anything is saved.
              </BBText>
              <Waveform metering={capture.metering} active={!paused} />
              <Button onPress={stop} style={styles.sheetButton}>
                <View style={styles.buttonInner}>
                  <Square size={14} color="#FFFFFF" strokeWidth={2} fill="#FFFFFF" />
                  <BBText variant="body" weight="medium" color="#FFFFFF">
                    Stop & review
                  </BBText>
                </View>
              </Button>
            </>
          ) : (
            <Button
              onPress={capture.start}
              loading={phase.kind === "starting"}
              style={styles.sheetButton}
            >
              Start recording
            </Button>
          )}
          <BBText variant="caption" color={colors.fg5}>
            Nothing is saved until you stop
          </BBText>
        </View>
      ) : null}
    </Screen>
  );
}

const styles = StyleSheet.create({
  head: {
    flexDirection: "row",
    alignItems: "center",
    gap: space.s3,
    paddingHorizontal: space.s4,
    paddingBottom: space.s2,
  },
  micBadge: {
    width: 36,
    height: 36,
    borderRadius: radii.full,
    backgroundColor: colors.brandPrimary,
    alignItems: "center",
    justifyContent: "center",
  },
  headTitle: {
    fontSize: 15,
    fontFamily: fonts.semibold,
    color: colors.fg1,
  },
  headSpacer: {
    flex: 1,
  },
  rec: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
  },
  recDot: {
    width: 6,
    height: 6,
    borderRadius: radii.full,
    backgroundColor: colors.recording,
  },
  recText: {
    fontSize: 12,
    fontFamily: fonts.semibold,
    color: colors.recording,
    fontVariant: ["tabular-nums"],
  },
  iconButton: {
    width: minHitTarget,
    height: minHitTarget,
    margin: -space.s2,
    alignItems: "center",
    justifyContent: "center",
  },
  middle: {
    flex: 1,
    justifyContent: "center",
    paddingHorizontal: space.s4,
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
  sheet: {
    alignItems: "center",
    gap: space.s3,
    paddingTop: 14,
    paddingHorizontal: space.s4,
    backgroundColor: "rgba(255,255,255,0.9)",
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  sheetButton: {
    alignSelf: "stretch",
    minHeight: 46,
  },
  buttonInner: {
    flexDirection: "row",
    alignItems: "center",
    gap: space.s2,
  },
});
