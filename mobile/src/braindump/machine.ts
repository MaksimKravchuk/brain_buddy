/**
 * Pure brain-dump flow logic: consent building, poll scheduling, commit
 * gating, proposal projection. Mirrors the web client's rules in
 * `frontend/src/features/brain-dump/BrainDumpRoute.tsx` so both clients
 * speak the same protocol.
 */

import type {
  BrainDumpOperationResponse,
  BrainDumpProposal,
  BrainDumpProvidersResponse,
  BrainDumpStartRequest,
  BrainDumpStatus,
} from "../api/types";

/**
 * Build the start-operation consent from the configured provider categories.
 * Returns null when no accurate STT provider is configured — the client
 * fails closed and never records (matching the web app).
 */
export function buildConsent(
  providers: BrainDumpProvidersResponse,
  languageHints: string[] = [],
  vocabulary: string[] = [],
): BrainDumpStartRequest | null {
  if (!providers.accurate_stt) {
    return null;
  }
  const categories = [providers.accurate_stt, providers.reconciler].filter(
    (value): value is string => Boolean(value),
  );
  const unique = [...new Set(categories)];
  return {
    consent: {
      microphone: true,
      external_processing_allowed: true,
      provider: providers.accurate_stt,
      providers: unique,
      language_hints: languageHints,
      vocabulary,
    },
  };
}

/** Server statuses worth polling; everything else is settled or interactive. */
const POLLABLE: ReadonlySet<BrainDumpStatus> = new Set([
  "sealing",
  "fast_processing",
  "accurate_transcribing",
  "reconciling",
  "committing",
]);

export function isPollable(status: BrainDumpStatus): boolean {
  return POLLABLE.has(status);
}

export const INITIAL_POLL_DELAY_MS = 1500;
export const MAX_POLL_DELAY_MS = 8000;

/** 1.5s → ×2 → 8s cap, as the web client polls. */
export function nextPollDelay(previous: number | null): number {
  if (previous === null || previous <= 0) {
    return INITIAL_POLL_DELAY_MS;
  }
  return Math.min(previous * 2, MAX_POLL_DELAY_MS);
}

/**
 * Keep the operation snapshot with the highest revision — poll responses can
 * arrive out of order and must never roll the projection back.
 */
export function applyOperation(
  current: BrainDumpOperationResponse | null,
  incoming: BrainDumpOperationResponse,
): BrainDumpOperationResponse {
  if (current && current.id === incoming.id && current.revision > incoming.revision) {
    return current;
  }
  return incoming;
}

/** Active (undeleted) proposals in display order. */
export function visibleProposals(operation: BrainDumpOperationResponse): BrainDumpProposal[] {
  return operation.proposals
    .filter((proposal) => !proposal.deleted)
    .slice()
    .sort((a, b) => a.ordinal - b.ordinal);
}

export function openConflictCount(operation: BrainDumpOperationResponse): number {
  return visibleProposals(operation).reduce(
    (count, proposal) => count + (proposal.conflicts?.length ?? 0),
    0,
  );
}

/** Commit is offered only when the server says so and no conflicts remain. */
export function canCommit(operation: BrainDumpOperationResponse): boolean {
  return (
    operation.status === "awaiting_confirmation" &&
    operation.committable === true &&
    openConflictCount(operation) === 0 &&
    visibleProposals(operation).length > 0
  );
}

/** Human stage line for the processing screen, per the ADR-0002 UI contract. */
export function processingStageLabel(status: BrainDumpStatus): string {
  switch (status) {
    case "sealing":
      return "Finishing upload…";
    case "fast_processing":
      return "Catching up on your audio…";
    case "accurate_transcribing":
      return "Improving transcript…";
    case "reconciling":
      return "Reconciling tasks…";
    case "committing":
      return "Saving to inbox…";
    default:
      return "Working…";
  }
}

export interface ChunkPlanEntry {
  chunkNumber: number;
  offset: number;
  length: number;
}

/** 896 KiB keeps chunk bodies under the production proxy's 1 MiB body cap. */
export const CHUNK_BYTES = 896 * 1024;

export function planChunks(totalBytes: number, chunkBytes: number = CHUNK_BYTES): ChunkPlanEntry[] {
  if (!Number.isFinite(totalBytes) || totalBytes <= 0) {
    return [];
  }
  const plan: ChunkPlanEntry[] = [];
  let offset = 0;
  let chunkNumber = 0;
  while (offset < totalBytes) {
    const length = Math.min(chunkBytes, totalBytes - offset);
    plan.push({ chunkNumber, offset, length });
    offset += length;
    chunkNumber += 1;
  }
  return plan;
}
