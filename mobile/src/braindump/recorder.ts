/**
 * Recording configuration for the brain dump.
 *
 * iOS records WAV (LINEARPCM 16 kHz mono 16-bit): every byte-prefix of a
 * finalized WAV parses as audio, which the server's cumulative-prefix
 * inspection requires for multi-chunk uploads, and it stays well within the
 * 100 MiB / 30 min operation limits (~32 KB/s).
 *
 * Android's MediaRecorder cannot produce WAV, so it falls back to AAC/m4a —
 * chunkable only as a single chunk; long Android recordings are therefore
 * capped harder. iOS is the v1 target platform.
 */

import {
  AudioQuality,
  IOSOutputFormat,
  requestRecordingPermissionsAsync,
  setAudioModeAsync,
  type RecordingOptions,
} from "expo-audio";
import { Platform } from "react-native";

export const BRAIN_DUMP_RECORDING_OPTIONS: RecordingOptions = {
  extension: ".wav",
  sampleRate: 16000,
  numberOfChannels: 1,
  bitRate: 256000,
  isMeteringEnabled: true,
  android: {
    extension: ".m4a",
    outputFormat: "mpeg4",
    audioEncoder: "aac",
  },
  ios: {
    outputFormat: IOSOutputFormat.LINEARPCM,
    audioQuality: AudioQuality.MAX,
    linearPCMBitDepth: 16,
    linearPCMIsBigEndian: false,
    linearPCMIsFloat: false,
  },
  web: {},
};

export function recordingMimeType(): string {
  return Platform.OS === "ios" ? "audio/wav" : "audio/mp4";
}

/** Ask for mic permission and put the audio session into recording mode. */
export async function prepareAudioSession(): Promise<boolean> {
  const permission = await requestRecordingPermissionsAsync();
  if (!permission.granted) {
    return false;
  }
  await setAudioModeAsync({
    allowsRecording: true,
    playsInSilentMode: true,
  });
  return true;
}

/** Leave recording mode (frees the mic indicator). */
export async function releaseAudioSession(): Promise<void> {
  try {
    await setAudioModeAsync({ allowsRecording: false, playsInSilentMode: true });
  } catch {
    // Best-effort: never block navigation on audio-session teardown.
  }
}

/** Client-side safety limits under the server's 1800 s duration cap. */
export const MAX_RECORDING_MS = 28 * 60 * 1000;
export const WARN_RECORDING_MS = 25 * 60 * 1000;
