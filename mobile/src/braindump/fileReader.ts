/**
 * expo-file-system-backed ByteReader for the chunk uploader.
 *
 * Uses the SDK 57 File/FileHandle API: bounded sequential reads keep peak
 * memory at one chunk (~896 KiB) regardless of recording length.
 */

import { File } from "expo-file-system";

import type { ByteReader } from "./uploader";

export interface DisposableReader {
  reader: ByteReader;
  dispose(): void;
  /** Delete the underlying file (after a successful seal). */
  deleteFile(): void;
}

export function openFileReader(uri: string): DisposableReader {
  const file = new File(uri);
  if (!file.exists) {
    throw new Error("Recording file not found.");
  }
  const size = file.size;
  const handle = file.open();
  return {
    reader: {
      size,
      read(offset, length) {
        try {
          if (handle.offset !== offset) {
            handle.offset = offset;
          }
          const bytes = handle.readBytes(length);
          return Promise.resolve(bytes);
        } catch (error) {
          return Promise.reject(error);
        }
      },
    },
    dispose() {
      try {
        handle.close();
      } catch {
        // Already closed.
      }
    },
    deleteFile() {
      try {
        file.delete();
      } catch {
        // Best-effort cleanup; the OS cache dir is reclaimed anyway.
      }
    },
  };
}
