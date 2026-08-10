/**
 * Brain-dump audio chunk hashing and seal-manifest computation.
 *
 * Must stay byte-identical with the backend:
 * `backend/app/workflows/voice_brain_dump/service.py::_brain_dump_manifest_hash`
 * hashes `json.dumps([...], sort_keys=True, separators=(",", ":"))` of the
 * ordered chunk metadata. The key order `chunk_number < sha256 < size_bytes`
 * is already alphabetical, so building the objects in that literal order and
 * using `JSON.stringify` produces the same bytes (the web client relies on
 * the same fact in `frontend/src/features/brain-dump/BrainDumpRoute.tsx`).
 *
 * Pure JS (js-sha256) so the exact same code runs on-device (Hermes), under
 * Jest, and in the Node integration suite.
 */

import { sha256 } from "js-sha256";

import type { BrainDumpAudioChunkMeta } from "../api/types";

/** Lowercase hex SHA-256 of a chunk's raw bytes (the X-Content-SHA256 header). */
export function chunkSha256Hex(bytes: Uint8Array): string {
  return sha256(bytes);
}

/**
 * Compute the seal `manifest_hash` from the server-echoed `audio_chunks`
 * metadata. Chunks at or beyond `expectedChunks` are excluded, matching the
 * web client (the server rejects such a seal anyway).
 */
export function manifestHash(chunks: BrainDumpAudioChunkMeta[], expectedChunks: number): string {
  const ordered = chunks
    // `filter` already returns a fresh array, so sorting in place here cannot
    // reach the caller's.
    .filter((chunk) => chunk.chunk_number < expectedChunks)
    .sort((a, b) => a.chunk_number - b.chunk_number)
    .map((chunk) => ({
      chunk_number: chunk.chunk_number,
      sha256: chunk.sha256,
      size_bytes: chunk.size_bytes,
    }));
  // js-sha256 UTF-8-encodes string input; the JSON here is ASCII-only anyway.
  return sha256(JSON.stringify(ordered));
}
