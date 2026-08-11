/**
 * An in-memory stand-in for expo-file-system's `File`/`FileHandle`.
 *
 * `openFileReader` is the only product code that touches it, and what matters
 * there is the bounded sequential read protocol: seek by assigning `offset`,
 * then `readBytes(length)`. This mock keeps the same contract over a buffer.
 */

interface FakeFile {
  bytes: Uint8Array;
  deleted: boolean;
  openHandles: number;
}

const files = new Map<string, FakeFile>();

/** Register a file the product code can open at `uri`. */
export function putFile(uri: string, bytes: Uint8Array): void {
  files.set(uri, { bytes, deleted: false, openHandles: 0 });
}

export function fileExists(uri: string): boolean {
  const file = files.get(uri);
  return file !== undefined && !file.deleted;
}

/** Handles opened on `uri` that were never closed. */
export function openHandleCount(uri: string): number {
  return files.get(uri)?.openHandles ?? 0;
}

export function resetFileSystem(): void {
  files.clear();
}

export function expoFileSystemMock() {
  class File {
    constructor(private readonly uri: string) {}

    get exists(): boolean {
      return fileExists(this.uri);
    }

    get size(): number {
      return files.get(this.uri)?.bytes.byteLength ?? 0;
    }

    delete(): void {
      const file = files.get(this.uri);
      if (!file) {
        throw new Error(`No such file: ${this.uri}`);
      }
      file.deleted = true;
    }

    open() {
      const file = files.get(this.uri);
      if (!file) {
        throw new Error(`No such file: ${this.uri}`);
      }
      file.openHandles += 1;
      let offset = 0;
      let closed = false;
      return {
        get offset() {
          return offset;
        },
        set offset(next: number) {
          offset = next;
        },
        readBytes(length: number): Uint8Array {
          if (closed) {
            throw new Error("File handle is closed.");
          }
          const slice = file.bytes.slice(offset, offset + length);
          offset += slice.byteLength;
          return slice;
        },
        close() {
          if (closed) {
            throw new Error("File handle is already closed.");
          }
          closed = true;
          file.openHandles -= 1;
        },
      };
    }
  }

  return { __esModule: true, File };
}
