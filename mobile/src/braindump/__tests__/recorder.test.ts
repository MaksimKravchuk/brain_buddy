import { Platform } from "react-native";

import { audioEvents, audioScript, resetAudio } from "@/test/expoAudioMock";

import {
  BRAIN_DUMP_RECORDING_OPTIONS,
  MAX_RECORDING_MS,
  prepareAudioSession,
  recordingMimeType,
  releaseAudioSession,
  WARN_RECORDING_MS,
} from "../recorder";

afterEach(() => resetAudio());

describe("recording format", () => {
  it("records WAV on iOS, whose every byte prefix parses as audio", () => {
    Platform.OS = "ios";
    expect(recordingMimeType()).toBe("audio/wav");
    expect(BRAIN_DUMP_RECORDING_OPTIONS.extension).toBe(".wav");
  });

  it("falls back to m4a off iOS, where MediaRecorder cannot produce WAV", () => {
    Platform.OS = "android";
    expect(recordingMimeType()).toBe("audio/mp4");
    expect(BRAIN_DUMP_RECORDING_OPTIONS.android?.extension).toBe(".m4a");
    Platform.OS = "ios";
  });

  it("records 16 kHz mono with metering on, as the server's limits assume", () => {
    expect(BRAIN_DUMP_RECORDING_OPTIONS.sampleRate).toBe(16000);
    expect(BRAIN_DUMP_RECORDING_OPTIONS.numberOfChannels).toBe(1);
    expect(BRAIN_DUMP_RECORDING_OPTIONS.isMeteringEnabled).toBe(true);
    expect(BRAIN_DUMP_RECORDING_OPTIONS.ios?.linearPCMBitDepth).toBe(16);
  });
});

describe("client-side duration limits", () => {
  it("warns before the hard stop, and stops under the server's 1800 s cap", () => {
    expect(WARN_RECORDING_MS).toBeLessThan(MAX_RECORDING_MS);
    expect(MAX_RECORDING_MS).toBeLessThan(1800 * 1000);
  });
});

describe("prepareAudioSession", () => {
  it("asks for the mic and puts the session into recording mode", async () => {
    await expect(prepareAudioSession()).resolves.toBe(true);
    expect(audioEvents()).toEqual(["request-permission", "session-on"]);
  });

  it("reports a denied mic without touching the audio session", async () => {
    audioScript().granted = false;

    await expect(prepareAudioSession()).resolves.toBe(false);
    expect(audioEvents()).toEqual(["request-permission"]);
  });
});

describe("releaseAudioSession", () => {
  it("leaves recording mode so the mic indicator clears", async () => {
    await releaseAudioSession();
    expect(audioEvents()).toEqual(["session-off"]);
  });
});
