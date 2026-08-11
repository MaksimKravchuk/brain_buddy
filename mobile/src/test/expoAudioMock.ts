/**
 * A scriptable stand-in for expo-audio's recorder.
 *
 * The real module talks to AVAudioSession. What the product code owes the
 * device is a specific *sequence* of calls — prepare, record, pause, record,
 * stop — plus honouring a denied permission, and that is what this records.
 */

export interface RecorderScript {
  /** Value of `recorder.uri` after `stop()`; null models a lost file. */
  uri: string | null;
  granted: boolean;
  isRecording: boolean;
  durationMillis: number;
  metering?: number;
  /** Set to make the named recorder call reject. */
  failOn: Partial<Record<"prepare" | "record" | "stop", Error>>;
}

const script: RecorderScript = {
  uri: "file:///cache/recording.wav",
  granted: true,
  isRecording: false,
  durationMillis: 0,
  metering: undefined,
  failOn: {},
};

const events: string[] = [];

export function audioScript(): RecorderScript {
  return script;
}

/** Recorder and session calls in the order the product code made them. */
export function audioEvents(): string[] {
  return [...events];
}

export function resetAudio(): void {
  script.uri = "file:///cache/recording.wav";
  script.granted = true;
  script.isRecording = false;
  script.durationMillis = 0;
  script.metering = undefined;
  script.failOn = {};
  events.length = 0;
}

function note(event: string): void {
  events.push(event);
}

export function expoAudioMock() {
  const recorder = {
    get uri() {
      return script.uri;
    },
    prepareToRecordAsync: async () => {
      note("prepare");
      if (script.failOn.prepare) {
        throw script.failOn.prepare;
      }
    },
    record: () => {
      note("record");
      if (script.failOn.record) {
        throw script.failOn.record;
      }
      script.isRecording = true;
    },
    pause: () => {
      note("pause");
      script.isRecording = false;
    },
    stop: async () => {
      note("stop");
      if (script.failOn.stop) {
        throw script.failOn.stop;
      }
      script.isRecording = false;
    },
  };

  return {
    __esModule: true,
    AudioQuality: { MAX: 127 },
    IOSOutputFormat: { LINEARPCM: "lpcm" },
    useAudioRecorder: () => recorder,
    useAudioRecorderState: () => ({
      isRecording: script.isRecording,
      durationMillis: script.durationMillis,
      metering: script.metering,
    }),
    requestRecordingPermissionsAsync: async () => {
      note("request-permission");
      return { granted: script.granted, canAskAgain: true, status: script.granted ? "granted" : "denied" };
    },
    setAudioModeAsync: async (mode: { allowsRecording?: boolean }) => {
      note(mode.allowsRecording ? "session-on" : "session-off");
    },
  };
}
