import type { BrainDumpOperationResponse, BrainDumpProposal } from "../../api/types";
import {
  applyOperation,
  buildConsent,
  canCommit,
  CHUNK_BYTES,
  isPollable,
  nextPollDelay,
  openConflictCount,
  planChunks,
  visibleProposals,
} from "../machine";

function makeOperation(
  overrides: Partial<BrainDumpOperationResponse> = {},
): BrainDumpOperationResponse {
  return {
    id: "op1",
    owner_id: "u1",
    kind: "voice_brain_dump",
    status: "awaiting_confirmation",
    consent: {
      microphone: true,
      external_processing_allowed: true,
      provider: "deterministic",
      providers: ["deterministic"],
      language_hints: [],
      vocabulary: [],
      recorded_at: "2026-01-01T00:00:00Z",
    },
    segments: [],
    proposals: [],
    committable: true,
    committed_task_ids: [],
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    revision: 1,
    ...overrides,
  };
}

function makeProposal(overrides: Partial<BrainDumpProposal> = {}): BrainDumpProposal {
  return {
    id: "p1",
    ordinal: 1,
    title: "Call the notary",
    status: "reconciled",
    source_segment_ids: [],
    deleted: false,
    user_edited: false,
    revision: 1,
    ...overrides,
  };
}

describe("buildConsent", () => {
  it("fails closed when no accurate STT provider is configured", () => {
    expect(buildConsent({ accurate_stt: null, reconciler: "openai" })).toBeNull();
  });

  it("echoes provider categories, deduplicated", () => {
    const consent = buildConsent({ accurate_stt: "deepgram", reconciler: "openai" }, ["ru", "en"]);
    expect(consent).toEqual({
      consent: {
        microphone: true,
        external_processing_allowed: true,
        provider: "deepgram",
        providers: ["deepgram", "openai"],
        language_hints: ["ru", "en"],
        vocabulary: [],
      },
    });

    const single = buildConsent({ accurate_stt: "deterministic", reconciler: "deterministic" });
    expect(single?.consent.providers).toEqual(["deterministic"]);
  });
});

describe("polling", () => {
  it("marks in-flight pipeline statuses pollable", () => {
    for (const status of [
      "sealing",
      "fast_processing",
      "accurate_transcribing",
      "reconciling",
      "committing",
    ] as const) {
      expect(isPollable(status)).toBe(true);
    }
    for (const status of [
      "recording",
      "paused",
      "awaiting_confirmation",
      "completed",
      "cancelled",
      "terminal_error",
      "retryable_error",
    ] as const) {
      expect(isPollable(status)).toBe(false);
    }
  });

  it("backs off 1.5s → x2 → 8s cap", () => {
    const first = nextPollDelay(null);
    expect(first).toBe(1500);
    const second = nextPollDelay(first);
    expect(second).toBe(3000);
    const third = nextPollDelay(second);
    expect(third).toBe(6000);
    expect(nextPollDelay(third)).toBe(8000);
    expect(nextPollDelay(8000)).toBe(8000);
  });
});

describe("applyOperation", () => {
  it("never rolls the projection back to a stale revision", () => {
    const current = makeOperation({ revision: 5 });
    const stale = makeOperation({ revision: 3 });
    expect(applyOperation(current, stale)).toBe(current);
    const newer = makeOperation({ revision: 6 });
    expect(applyOperation(current, newer)).toBe(newer);
  });

  it("always adopts a different operation id", () => {
    const current = makeOperation({ revision: 5 });
    const other = makeOperation({ id: "op2", revision: 1 });
    expect(applyOperation(current, other)).toBe(other);
  });
});

describe("proposals and commit gating", () => {
  it("hides deleted proposals and sorts by ordinal", () => {
    const operation = makeOperation({
      proposals: [
        makeProposal({ id: "b", ordinal: 2 }),
        makeProposal({ id: "gone", ordinal: 1, deleted: true }),
        makeProposal({ id: "a", ordinal: 1 }),
      ],
    });
    expect(visibleProposals(operation).map((proposal) => proposal.id)).toEqual(["a", "b"]);
  });

  it("counts conflicts on visible proposals only", () => {
    const conflict = {
      field: "title",
      current_value: "mine",
      suggested_value: "theirs",
      producer: "reconciler" as const,
      source_segment_ids: [],
    };
    const operation = makeOperation({
      proposals: [
        makeProposal({ id: "a", conflicts: [conflict] }),
        makeProposal({ id: "gone", deleted: true, conflicts: [conflict] }),
      ],
    });
    expect(openConflictCount(operation)).toBe(1);
  });

  it("gates commit on status, committable, conflicts, and proposal count", () => {
    expect(canCommit(makeOperation({ proposals: [makeProposal()] }))).toBe(true);
    expect(canCommit(makeOperation({ proposals: [] }))).toBe(false);
    expect(
      canCommit(makeOperation({ proposals: [makeProposal()], committable: false })),
    ).toBe(false);
    expect(
      canCommit(makeOperation({ proposals: [makeProposal()], status: "recording" })),
    ).toBe(false);
    const conflicted = makeProposal({
      conflicts: [
        {
          field: "title",
          current_value: "a",
          suggested_value: "b",
          producer: "reconciler",
          source_segment_ids: [],
        },
      ],
    });
    expect(canCommit(makeOperation({ proposals: [conflicted] }))).toBe(false);
  });
});

describe("planChunks", () => {
  it("splits an exact multiple into equal chunks", () => {
    const plan = planChunks(CHUNK_BYTES * 2, CHUNK_BYTES);
    expect(plan).toEqual([
      { chunkNumber: 0, offset: 0, length: CHUNK_BYTES },
      { chunkNumber: 1, offset: CHUNK_BYTES, length: CHUNK_BYTES },
    ]);
  });

  it("gives the remainder to the final chunk", () => {
    const plan = planChunks(CHUNK_BYTES + 100, CHUNK_BYTES);
    expect(plan).toHaveLength(2);
    expect(plan[1]).toEqual({ chunkNumber: 1, offset: CHUNK_BYTES, length: 100 });
  });

  it("handles sub-chunk files and rejects empty input", () => {
    expect(planChunks(10, CHUNK_BYTES)).toEqual([{ chunkNumber: 0, offset: 0, length: 10 }]);
    expect(planChunks(0)).toEqual([]);
    expect(planChunks(-5)).toEqual([]);
  });

  it("keeps every chunk under the production proxy's 1 MiB body cap", () => {
    expect(CHUNK_BYTES).toBeLessThan(1024 * 1024);
    for (const entry of planChunks(10_000_000)) {
      expect(entry.length).toBeLessThanOrEqual(CHUNK_BYTES);
    }
  });
});
