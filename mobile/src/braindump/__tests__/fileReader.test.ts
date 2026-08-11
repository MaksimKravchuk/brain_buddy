import {
  fileExists,
  openHandleCount,
  putFile,
  resetFileSystem,
} from "@/test/expoFileSystemMock";

import { openFileReader } from "../fileReader";

const URI = "file:///cache/recording.wav";

function bytes(length: number): Uint8Array {
  return Uint8Array.from({ length }, (_, index) => index % 256);
}

afterEach(() => resetFileSystem());

describe("openFileReader", () => {
  it("refuses to open a recording that is not there", () => {
    expect(() => openFileReader(URI)).toThrow("Recording file not found.");
  });

  it("reports the file size the uploader plans against", () => {
    putFile(URI, bytes(2048));

    const { reader, dispose } = openFileReader(URI);

    expect(reader.size).toBe(2048);
    dispose();
  });

  it("reads a bounded window at an arbitrary offset", async () => {
    putFile(URI, bytes(1000));
    const { reader, dispose } = openFileReader(URI);

    await expect(reader.read(0, 4)).resolves.toEqual(Uint8Array.from([0, 1, 2, 3]));
    await expect(reader.read(500, 3)).resolves.toEqual(Uint8Array.from([244, 245, 246]));

    dispose();
  });

  it("reads sequentially without re-seeking, and re-seeks when asked to jump", async () => {
    putFile(URI, bytes(100));
    const { reader, dispose } = openFileReader(URI);

    await expect(reader.read(0, 2)).resolves.toEqual(Uint8Array.from([0, 1]));
    // Continues from where the handle already is.
    await expect(reader.read(2, 2)).resolves.toEqual(Uint8Array.from([2, 3]));
    // Jumps backwards.
    await expect(reader.read(0, 2)).resolves.toEqual(Uint8Array.from([0, 1]));

    dispose();
  });

  it("returns a short read at end of file rather than padding it", async () => {
    putFile(URI, bytes(5));
    const { reader, dispose } = openFileReader(URI);

    await expect(reader.read(3, 10)).resolves.toEqual(Uint8Array.from([3, 4]));

    dispose();
  });

  it("rejects rather than throwing synchronously when the handle is gone", async () => {
    putFile(URI, bytes(10));
    const { reader, dispose } = openFileReader(URI);
    dispose();

    await expect(reader.read(0, 1)).rejects.toThrow("File handle is closed.");
  });

  it("closes the handle exactly once, even if dispose is called twice", () => {
    putFile(URI, bytes(10));
    const { dispose } = openFileReader(URI);
    expect(openHandleCount(URI)).toBe(1);

    dispose();
    dispose();

    expect(openHandleCount(URI)).toBe(0);
  });

  it("deletes the recording after a successful seal", () => {
    putFile(URI, bytes(10));
    const { dispose, deleteFile } = openFileReader(URI);

    deleteFile();

    expect(fileExists(URI)).toBe(false);
    dispose();
  });

  it("treats a failed delete as best-effort cleanup", () => {
    putFile(URI, bytes(10));
    const { dispose, deleteFile } = openFileReader(URI);
    deleteFile();

    resetFileSystem();

    expect(() => deleteFile()).not.toThrow();
    dispose();
  });
});
