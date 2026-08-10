import { fireEvent, screen, waitFor } from "@testing-library/react-native";

import { chunkSha256Hex } from "@/braindump/manifest";
import { makeOperation } from "@/test/brainDump";
import { audioEvents, audioScript } from "@/test/expoAudioMock";
import { putFile } from "@/test/expoFileSystemMock";
import { routerSpy } from "@/test/expoRouterMock";
import {
  FakeHttpError,
  installFakeBackend,
  makeMe,
  type FakeBackend,
  type RouteHandler,
} from "@/test/fakeBackend";
import { renderWithSession } from "@/test/harness";

import BrainDumpCaptureScreen from "../index";

let backend: FakeBackend;

afterEach(() => backend?.restore());

const URI = "file:///cache/recording.wav";

function voiceOn(routes: Record<string, RouteHandler> = {}) {
  return installFakeBackend({
    "GET /auth/me": () => makeMe({ feature_flags: { voice_brain_dump: true } }),
    "GET /brain-dump-providers": () => ({ accurate_stt: "whisper", reconciler: "gpt-4" }),
    ...routes,
  });
}

/** Bytes that split into exactly `chunks` upload chunks. */
function recordingOf(bytes: number): Uint8Array {
  return Uint8Array.from({ length: bytes }, (_, index) => index % 251);
}

describe("brain dump capture — availability", () => {
  it("says voice is not enabled for the account and offers no recording", async () => {
    backend = installFakeBackend({ "GET /auth/me": () => makeMe({ feature_flags: {} }) });

    await renderWithSession(<BrainDumpCaptureScreen />);

    expect(await screen.findByText("Voice capture is not enabled")).toBeOnTheScreen();
    expect(screen.queryByText("Start recording")).toBeNull();
  });

  it("says voice is unavailable when the server has no STT provider", async () => {
    backend = voiceOn({
      "GET /brain-dump-providers": () => ({ accurate_stt: null, reconciler: null }),
    });

    await renderWithSession(<BrainDumpCaptureScreen />);

    expect(await screen.findByText("Voice capture is unavailable")).toBeOnTheScreen();
    expect(screen.queryByText("Start recording")).toBeNull();
  });

  it("surfaces a provider lookup failure", async () => {
    backend = voiceOn({
      "GET /brain-dump-providers": () => new FakeHttpError(403, { message: "Voice is off for you" }),
    });

    await renderWithSession(<BrainDumpCaptureScreen />);

    expect(await screen.findByText("Voice is off for you")).toBeOnTheScreen();
  });

  it("names the providers that will see the audio before recording starts", async () => {
    backend = voiceOn();

    await renderWithSession(<BrainDumpCaptureScreen />);

    expect(
      await screen.findByText(
        "After you stop, your audio is processed by whisper and gpt-4 to propose tasks. " +
          "Nothing is saved until you confirm.",
      ),
    ).toBeOnTheScreen();
  });
});

describe("brain dump capture — recording", () => {
  it("asks for the mic, opens the operation, then records", async () => {
    backend = voiceOn({ "POST /brain-dump-operations": () => makeOperation() });

    await renderWithSession(<BrainDumpCaptureScreen />);
    await fireEvent.press(await screen.findByText("Start recording"));

    await waitFor(() => expect(screen.getByLabelText("Pause")).toBeOnTheScreen());
    expect(audioEvents()).toEqual(["request-permission", "session-on", "prepare", "record"]);
    expect(backend.callsTo("POST", "/brain-dump-operations")[0].body).toEqual({
      consent: {
        microphone: true,
        external_processing_allowed: true,
        provider: "whisper",
        providers: ["whisper", "gpt-4"],
        language_hints: ["ru", "en"],
        vocabulary: [],
      },
    });
  });

  it("stops at a denied microphone without opening an operation", async () => {
    backend = voiceOn({ "POST /brain-dump-operations": () => makeOperation() });
    audioScript().granted = false;

    await renderWithSession(<BrainDumpCaptureScreen />);
    await fireEvent.press(await screen.findByText("Start recording"));

    expect(await screen.findByText("Microphone access needed")).toBeOnTheScreen();
    expect(backend.callsTo("POST", "/brain-dump-operations")).toHaveLength(0);
  });

  it("reports a failure to open the operation as recoverable", async () => {
    backend = voiceOn({
      "POST /brain-dump-operations": () => new FakeHttpError(503, { message: "Try again shortly" }),
    });

    await renderWithSession(<BrainDumpCaptureScreen />);
    await fireEvent.press(await screen.findByText("Start recording"));

    expect(await screen.findByText("Try again shortly")).toBeOnTheScreen();
    expect(screen.getByText("Discard this dump")).toBeOnTheScreen();
  });

  it("mirrors pause and resume to the server", async () => {
    backend = voiceOn({
      "POST /brain-dump-operations": () => makeOperation({ revision: 3 }),
      "POST /brain-dump-operations/op-1/pause": () => makeOperation({ revision: 4, status: "paused" }),
      "POST /brain-dump-operations/op-1/resume": () => makeOperation({ revision: 5 }),
    });

    await renderWithSession(<BrainDumpCaptureScreen />);
    await fireEvent.press(await screen.findByText("Start recording"));

    await fireEvent.press(await screen.findByLabelText("Pause"));
    await waitFor(() =>
      expect(backend.callsTo("POST", "/brain-dump-operations/op-1/pause")).toHaveLength(1),
    );
    expect(backend.callsTo("POST", "/brain-dump-operations/op-1/pause")[0].body).toEqual({
      expected_revision: 3,
    });
    expect(screen.getByText("paused")).toBeOnTheScreen();

    await fireEvent.press(screen.getByLabelText("Resume"));
    await waitFor(() =>
      expect(backend.callsTo("POST", "/brain-dump-operations/op-1/resume")).toHaveLength(1),
    );
    // The resume carries the revision the pause response advanced to.
    expect(backend.callsTo("POST", "/brain-dump-operations/op-1/resume")[0].body).toEqual({
      expected_revision: 4,
    });
    expect(audioEvents().slice(-2)).toEqual(["pause", "record"]);
  });

  it("keeps recording when the server refuses the advisory pause", async () => {
    backend = voiceOn({
      "POST /brain-dump-operations": () => makeOperation(),
      "POST /brain-dump-operations/op-1/pause": () => new FakeHttpError(500, { message: "nope" }),
    });

    await renderWithSession(<BrainDumpCaptureScreen />);
    await fireEvent.press(await screen.findByText("Start recording"));
    await fireEvent.press(await screen.findByLabelText("Pause"));

    expect(await screen.findByText("paused")).toBeOnTheScreen();
    expect(screen.queryByText("nope")).toBeNull();
  });
});

describe("brain dump capture — stop, upload and seal", () => {
  it("uploads every chunk with its digest and seals with the manifest hash", async () => {
    const bytes = recordingOf(3);
    putFile(URI, bytes);
    const sha = chunkSha256Hex(bytes);
    backend = voiceOn({
      "POST /brain-dump-operations": () => makeOperation({ revision: 1 }),
      "PUT /brain-dump-operations/op-1/audio/0": () =>
        makeOperation({
          revision: 2,
          audio_chunks: [{ chunk_number: 0, sha256: sha, size_bytes: bytes.byteLength }],
        }),
      "POST /brain-dump-operations/op-1/seal": () =>
        makeOperation({ revision: 3, status: "sealing" }),
    });

    await renderWithSession(<BrainDumpCaptureScreen />);
    await fireEvent.press(await screen.findByText("Start recording"));
    await fireEvent.press(await screen.findByText("Stop & review"));

    await waitFor(() =>
      expect(backend.callsTo("POST", "/brain-dump-operations/op-1/seal")).toHaveLength(1),
    );
    const put = backend.callsTo("PUT", "/brain-dump-operations/op-1/audio/0")[0];
    expect(put.headers["X-Content-SHA256"]).toBe(sha);
    expect(put.headers["Content-Type"]).toBe("audio/wav");
    expect(backend.callsTo("POST", "/brain-dump-operations/op-1/seal")[0].body).toMatchObject({
      expected_revision: 2,
      expected_chunks: 1,
      manifest_hash: expect.any(String),
    });
    expect(audioEvents().slice(-2)).toEqual(["stop", "session-off"]);
  });

  it("hands off to the review screen once sealed", async () => {
    putFile(URI, recordingOf(3));
    backend = voiceOn({
      "POST /brain-dump-operations": () => makeOperation(),
      "PUT /brain-dump-operations/op-1/audio/0": () => makeOperation({ revision: 2 }),
      "POST /brain-dump-operations/op-1/seal": () => makeOperation({ revision: 3 }),
    });

    await renderWithSession(<BrainDumpCaptureScreen />);
    await fireEvent.press(await screen.findByText("Start recording"));
    await fireEvent.press(await screen.findByText("Stop & review"));

    await waitFor(() =>
      expect(routerSpy().replace).toHaveBeenCalledWith({
        pathname: "/brain-dump/[operationId]",
        params: { operationId: "op-1" },
      }),
    );
  });

  it("reports a lost recording file instead of sealing an empty dump", async () => {
    audioScript().uri = null;
    backend = voiceOn({ "POST /brain-dump-operations": () => makeOperation() });

    await renderWithSession(<BrainDumpCaptureScreen />);
    await fireEvent.press(await screen.findByText("Start recording"));
    await fireEvent.press(await screen.findByText("Stop & review"));

    expect(await screen.findByText("The recording did not produce a file.")).toBeOnTheScreen();
    expect(routerSpy().replace).not.toHaveBeenCalled();
  });

  it("retries a failed upload without re-recording, and reuses the seal key", async () => {
    const bytes = recordingOf(3);
    putFile(URI, bytes);
    let uploads = 0;
    backend = voiceOn({
      "POST /brain-dump-operations": () => makeOperation(),
      "PUT /brain-dump-operations/op-1/audio/0": () => {
        uploads += 1;
        if (uploads === 1) {
          throw new TypeError("Network request failed");
        }
        return makeOperation({ revision: 2 });
      },
      "GET /brain-dump-operations/op-1": () => makeOperation({ revision: 2, status: "recording" }),
      "POST /brain-dump-operations/op-1/seal": () => makeOperation({ revision: 3 }),
    });

    await renderWithSession(<BrainDumpCaptureScreen />);
    await fireEvent.press(await screen.findByText("Start recording"));
    await fireEvent.press(await screen.findByText("Stop & review"));

    await fireEvent.press(await screen.findByText("Retry"));

    await waitFor(() =>
      expect(backend.callsTo("POST", "/brain-dump-operations/op-1/seal")).toHaveLength(1),
    );
    // The recorder was stopped once: the retry re-used the file already on disk.
    expect(audioEvents().filter((event) => event === "stop")).toHaveLength(1);
  });

  it("recovers a lost seal response by handing off to review rather than re-uploading", async () => {
    putFile(URI, recordingOf(3));
    backend = voiceOn({
      "POST /brain-dump-operations": () => makeOperation(),
      "PUT /brain-dump-operations/op-1/audio/0": () => makeOperation({ revision: 2 }),
      "POST /brain-dump-operations/op-1/seal": () => {
        throw new TypeError("Network request failed");
      },
      // The server did accept the seal; only the response was lost.
      "GET /brain-dump-operations/op-1": () =>
        makeOperation({ revision: 4, status: "accurate_transcribing" }),
    });

    await renderWithSession(<BrainDumpCaptureScreen />);
    await fireEvent.press(await screen.findByText("Start recording"));
    await fireEvent.press(await screen.findByText("Stop & review"));
    await fireEvent.press(await screen.findByText("Retry"));

    await waitFor(() =>
      expect(routerSpy().replace).toHaveBeenCalledWith({
        pathname: "/brain-dump/[operationId]",
        params: { operationId: "op-1" },
      }),
    );
    expect(backend.callsTo("POST", "/brain-dump-operations/op-1/seal")).toHaveLength(1);
  });

  it("refuses to resurrect a cancelled dump", async () => {
    putFile(URI, recordingOf(3));
    backend = voiceOn({
      "POST /brain-dump-operations": () => makeOperation(),
      "PUT /brain-dump-operations/op-1/audio/0": () => {
        throw new TypeError("Network request failed");
      },
      "GET /brain-dump-operations/op-1": () => makeOperation({ status: "cancelled" }),
    });

    await renderWithSession(<BrainDumpCaptureScreen />);
    await fireEvent.press(await screen.findByText("Start recording"));
    await fireEvent.press(await screen.findByText("Stop & review"));
    await fireEvent.press(await screen.findByText("Retry"));

    expect(
      await screen.findByText("This dump was cancelled; nothing was saved."),
    ).toBeOnTheScreen();
    expect(screen.queryByText("Retry")).toBeNull();
  });

  it("refuses a multi-chunk m4a before uploading anything, and offers no retry", async () => {
    const { Platform } = require("react-native");
    Platform.OS = "android";
    try {
      putFile(URI, recordingOf(2 * 896 * 1024));
      backend = voiceOn({ "POST /brain-dump-operations": () => makeOperation() });

      await renderWithSession(<BrainDumpCaptureScreen />);
      await fireEvent.press(await screen.findByText("Start recording"));
      await fireEvent.press(await screen.findByText("Stop & review"));

      expect(await screen.findByText(/m4a cannot be/)).toBeOnTheScreen();
      expect(screen.queryByText("Retry")).toBeNull();
      expect(backend.callsTo("PUT", "/brain-dump-operations/op-1/audio/0")).toHaveLength(0);
    } finally {
      Platform.OS = "ios";
    }
  });
});

describe("brain dump capture — leaving", () => {
  it("cancels the operation on the server and goes back", async () => {
    backend = voiceOn({
      "POST /brain-dump-operations": () => makeOperation({ revision: 2 }),
      "POST /brain-dump-operations/op-1/cancel": () => makeOperation({ status: "cancelled" }),
    });

    await renderWithSession(<BrainDumpCaptureScreen />);
    await fireEvent.press(await screen.findByText("Start recording"));
    await fireEvent.press(await screen.findByLabelText("Discard and close"));

    await waitFor(() =>
      expect(backend.callsTo("POST", "/brain-dump-operations/op-1/cancel")).toHaveLength(1),
    );
    expect(backend.callsTo("POST", "/brain-dump-operations/op-1/cancel")[0].body).toEqual({
      expected_revision: 2,
    });
    expect(routerSpy().back).toHaveBeenCalled();
  });

  it("still leaves when the cancel call fails", async () => {
    backend = voiceOn({
      "POST /brain-dump-operations": () => makeOperation(),
      "POST /brain-dump-operations/op-1/cancel": () => new FakeHttpError(500, { message: "nope" }),
    });

    await renderWithSession(<BrainDumpCaptureScreen />);
    await fireEvent.press(await screen.findByText("Start recording"));
    await fireEvent.press(await screen.findByLabelText("Discard and close"));

    await waitFor(() => expect(routerSpy().back).toHaveBeenCalled());
  });

  it("leaves without calling the server when nothing was started", async () => {
    backend = voiceOn();

    await renderWithSession(<BrainDumpCaptureScreen />);
    await fireEvent.press(await screen.findByLabelText("Discard and close"));

    await waitFor(() => expect(routerSpy().back).toHaveBeenCalled());
    expect(backend.callsTo("POST", "/brain-dump-operations")).toHaveLength(0);
  });
});
