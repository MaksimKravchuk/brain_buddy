/**
 * Post-stop chunked audio upload.
 *
 * The server requires strictly sequential chunk numbers (`chunk_number ==
 * len(audio_chunks)`), verifies `X-Content-SHA256` per chunk, and ffmpeg-
 * inspects the cumulative byte prefix — which is why recordings use WAV
 * (every prefix of a finalized WAV parses; m4a's moov atom lives at EOF).
 * Re-uploading an identical chunk is an idempotent no-op, so a retry can
 * simply run the loop again.
 *
 * Byte access is abstracted behind `ByteReader` so the exact same loop runs
 * against an expo-file-system `FileHandle` on device and plain buffers in
 * tests.
 */

import type { BrainDumpAudioChunkMeta } from "../api/types";
import { chunkSha256Hex } from "./manifest";
import { planChunks, type ChunkPlanEntry } from "./machine";

export interface ByteReader {
  readonly size: number;
  /** Read exactly `length` bytes starting at `offset`. */
  read(offset: number, length: number): Promise<Uint8Array>;
}

export interface OperationEcho {
  revision: number;
  audio_chunks?: BrainDumpAudioChunkMeta[];
}

export interface UploadChunksOptions<Op extends OperationEcho> {
  reader: ByteReader;
  mimeType: string;
  put: (chunkNumber: number, bytes: Uint8Array, sha256Hex: string, mimeType: string) => Promise<Op>;
  onProgress?: (uploadedChunks: number, totalChunks: number) => void;
  chunkBytes?: number;
}

export interface UploadChunksResult<Op extends OperationEcho> {
  expectedChunks: number;
  lastOperation: Op;
  plan: ChunkPlanEntry[];
}

export class EmptyRecordingError extends Error {
  constructor() {
    super("The recording is empty.");
    this.name = "EmptyRecordingError";
  }
}

export async function uploadChunks<Op extends OperationEcho>(
  options: UploadChunksOptions<Op>,
): Promise<UploadChunksResult<Op>> {
  const { reader, mimeType, put, onProgress, chunkBytes } = options;
  const plan = planChunks(reader.size, chunkBytes);
  if (plan.length === 0) {
    throw new EmptyRecordingError();
  }

  let lastOperation: Op | null = null;
  for (const entry of plan) {
    const bytes = await reader.read(entry.offset, entry.length);
    if (bytes.byteLength !== entry.length) {
      throw new Error(
        `Short read at chunk ${entry.chunkNumber}: expected ${entry.length}, got ${bytes.byteLength}.`,
      );
    }
    const sha = chunkSha256Hex(bytes);
    lastOperation = await put(entry.chunkNumber, bytes, sha, mimeType);
    onProgress?.(entry.chunkNumber + 1, plan.length);
  }

  return {
    expectedChunks: plan.length,
    lastOperation: lastOperation as Op,
    plan,
  };
}
