import { chunkSha256Hex } from "../manifest";
import { EmptyRecordingError, uploadChunks, type ByteReader } from "../uploader";

function bufferReader(bytes: Uint8Array): ByteReader {
  return {
    size: bytes.byteLength,
    read: async (offset, length) => bytes.slice(offset, offset + length),
  };
}

function makeBytes(size: number): Uint8Array {
  const bytes = new Uint8Array(size);
  for (let i = 0; i < size; i += 1) {
    bytes[i] = i % 251;
  }
  return bytes;
}

describe("uploadChunks", () => {
  it("uploads sequential chunks with correct hashes and reports progress", async () => {
    const data = makeBytes(2500);
    const puts: { chunkNumber: number; sha: string; size: number; mime: string }[] = [];
    const progress: [number, number][] = [];

    const result = await uploadChunks({
      reader: bufferReader(data),
      mimeType: "audio/wav",
      chunkBytes: 1000,
      put: async (chunkNumber, bytes, sha, mime) => {
        puts.push({ chunkNumber, sha, size: bytes.byteLength, mime });
        return {
          revision: chunkNumber + 2,
          audio_chunks: puts.map((p) => ({
            chunk_number: p.chunkNumber,
            sha256: p.sha,
            size_bytes: p.size,
          })),
        };
      },
      onProgress: (done, total) => progress.push([done, total]),
    });

    expect(result.expectedChunks).toBe(3);
    expect(puts.map((p) => p.chunkNumber)).toEqual([0, 1, 2]);
    expect(puts.map((p) => p.size)).toEqual([1000, 1000, 500]);
    expect(puts.every((p) => p.mime === "audio/wav")).toBe(true);
    expect(puts[0].sha).toBe(chunkSha256Hex(data.slice(0, 1000)));
    expect(puts[2].sha).toBe(chunkSha256Hex(data.slice(2000)));
    expect(progress).toEqual([
      [1, 3],
      [2, 3],
      [3, 3],
    ]);
    expect(result.lastOperation.revision).toBe(4);
    expect(result.lastOperation.audio_chunks).toHaveLength(3);
  });

  it("stops at the first failed chunk", async () => {
    const data = makeBytes(2500);
    let calls = 0;
    await expect(
      uploadChunks({
        reader: bufferReader(data),
        mimeType: "audio/wav",
        chunkBytes: 1000,
        put: async (chunkNumber) => {
          calls += 1;
          if (chunkNumber === 1) {
            throw new Error("network down");
          }
          return { revision: 1, audio_chunks: [] };
        },
      }),
    ).rejects.toThrow("network down");
    expect(calls).toBe(2);
  });

  it("rejects an empty recording", async () => {
    await expect(
      uploadChunks({
        reader: bufferReader(new Uint8Array(0)),
        mimeType: "audio/wav",
        put: async () => ({ revision: 1 }),
      }),
    ).rejects.toBeInstanceOf(EmptyRecordingError);
  });

  it("fails loudly on a short read", async () => {
    const truncated: ByteReader = {
      size: 1000,
      read: async () => new Uint8Array(10),
    };
    await expect(
      uploadChunks({
        reader: truncated,
        mimeType: "audio/wav",
        chunkBytes: 1000,
        put: async () => ({ revision: 1 }),
      }),
    ).rejects.toThrow("Short read");
  });
});

describe("EmptyRecordingError", () => {
  it("carries a message and a name the UI can show and branch on", () => {
    const error = new EmptyRecordingError();

    expect(error.message).toBe("The recording is empty.");
    expect(error.name).toBe("EmptyRecordingError");
  });
});
