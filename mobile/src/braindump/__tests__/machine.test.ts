import type { BrainDumpOperationResponse, BrainDumpProposal } from "../../api/types";
import {
  applyOperation,
  buildConsent,
  canCommit,
  CHUNK_BYTES,
  heardTranscript,
  INITIAL_POLL_DELAY_MS,
  isPollable,
  nextPollDelay,
  openConflictCount,
  planChunks,
  processingStageLabel,
  visibleProposals,
  type BrainDumpSegment,
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

/**
 * Cases the mutation campaign found unguarded: each one is a mutation that
 * changed behaviour without failing a test.
 */
describe("buildConsent edges", () => {
  it("defaults the language hints to none rather than inventing any", () => {
    const consent = buildConsent({ accurate_stt: "whisper", reconciler: null });

    expect(consent?.consent.language_hints).toEqual([]);
    expect(consent?.consent.vocabulary).toEqual([]);
  });

  it("drops an absent reconciler from the provider list instead of listing null", () => {
    const consent = buildConsent({ accurate_stt: "whisper", reconciler: null });

    expect(consent?.consent.providers).toEqual(["whisper"]);
  });
});

describe("nextPollDelay edges", () => {
  it("restarts from the initial delay for a zero or negative previous delay", () => {
    expect(nextPollDelay(0)).toBe(INITIAL_POLL_DELAY_MS);
    expect(nextPollDelay(-500)).toBe(INITIAL_POLL_DELAY_MS);
  });
});

describe("visibleProposals ordering", () => {
  it("does not reorder the caller's array while sorting its own copy", () => {
    const proposals = [
      makeProposal({ id: "b", ordinal: 2 }),
      makeProposal({ id: "a", ordinal: 1 }),
    ];
    const input = [...proposals];

    const visible = visibleProposals(makeOperation({ proposals: input }));

    expect(visible.map((item) => item.id)).toEqual(["a", "b"]);
    expect(input).toEqual(proposals);
  });
});

describe("heardTranscript", () => {
  function makeSegment(overrides: Partial<BrainDumpSegment> & { id: string }): BrainDumpSegment {
    return {
      sequence: 1,
      text: overrides.id,
      stability: "stable",
      created_at: "2026-01-01T00:00:00Z",
      ...overrides,
    };
  }

  it("keeps settled utterances no later segment supersedes, in spoken order", () => {
    const heard = heardTranscript([
      makeSegment({ id: "s2", sequence: 2 }),
      makeSegment({ id: "s1", sequence: 1, provider_role: "browser_preview" }),
      makeSegment({ id: "s3", sequence: 3, stability: "interim" }),
      makeSegment({ id: "s4", sequence: 4, provider_role: "accurate", supersedes_segment_ids: ["s1"] }),
      makeSegment({ id: "s5", sequence: 5, supersedes_segment_ids: [] }),
    ]);

    expect(heard.map((segment) => segment.id)).toEqual(["s2", "s4", "s5"]);
  });

  it("does not reorder the caller's array while sorting its own copy", () => {
    const segments = [makeSegment({ id: "b", sequence: 2 }), makeSegment({ id: "a", sequence: 1 })];
    const input = [...segments];

    expect(heardTranscript(input).map((segment) => segment.id)).toEqual(["a", "b"]);
    expect(input).toEqual(segments);
    expect(heardTranscript([])).toEqual([]);
  });
});

describe("planChunks edges", () => {
  it("plans nothing for an empty or impossible size", () => {
    expect(planChunks(0)).toEqual([]);
    expect(planChunks(-1)).toEqual([]);
    expect(planChunks(Number.NaN)).toEqual([]);
    expect(planChunks(Number.POSITIVE_INFINITY)).toEqual([]);
  });
});

describe("processingStageLabel coverage", () => {
  it("names every pollable stage, and falls back for anything else", () => {
    expect(processingStageLabel("sealing")).toBe("Finishing upload…");
    expect(processingStageLabel("fast_processing")).toBe("Catching up on your audio…");
    expect(processingStageLabel("accurate_transcribing")).toBe("Improving transcript…");
    expect(processingStageLabel("reconciling")).toBe("Reconciling tasks…");
    expect(processingStageLabel("committing")).toBe("Saving to inbox…");
    expect(processingStageLabel("awaiting_confirmation")).toBe("Working…");
  });
});
