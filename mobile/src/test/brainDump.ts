/** Brain-dump fixtures shared by the capture and review tests. */

import type {
  BrainDumpAudioChunkMeta,
  BrainDumpOperationResponse,
  BrainDumpProposal,
  BrainDumpStatus,
} from "@/api/types";

export function makeProposal(overrides: Partial<BrainDumpProposal> = {}): BrainDumpProposal {
  return {
    id: "prop-1",
    ordinal: 1,
    title: "Call the notary",
    status: "ready_to_review",
    source_segment_ids: [],
    deleted: false,
    user_edited: false,
    revision: 1,
    ...overrides,
  };
}

export function makeOperation(
  overrides: Partial<BrainDumpOperationResponse> = {},
): BrainDumpOperationResponse {
  return {
    id: "op-1",
    owner_id: "user-1",
    kind: "voice_brain_dump",
    status: "recording" as BrainDumpStatus,
    consent: {
      microphone: true,
      external_processing_allowed: true,
      provider: "whisper",
      providers: ["whisper", "gpt"],
      language_hints: ["ru", "en"],
      vocabulary: [],
      recorded_at: "2026-01-01T00:00:00Z",
    },
    segments: [],
    proposals: [],
    revision: 1,
    ...overrides,
  } as BrainDumpOperationResponse;
}

/** The chunk metadata the server echoes back after a successful PUT. */
export function chunkMeta(chunkNumber: number, sha256: string, size: number): BrainDumpAudioChunkMeta {
  return { chunk_number: chunkNumber, sha256, size_bytes: size };
}
