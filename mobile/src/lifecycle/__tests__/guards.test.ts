import type { OpenTaskState, TaskState } from "../../api/types";
import { availableTransitions, buildTransition } from "../guards";

const OPEN: OpenTaskState[] = ["inbox", "next", "waiting", "someday"];
const TERMINAL: TaskState[] = ["completed", "cancelled"];

describe("availableTransitions", () => {
  it.each(OPEN)("open state %s offers complete/cancel/move but not reopen", (state) => {
    const t = availableTransitions({ state });
    expect(t.complete).toBe(true);
    expect(t.cancel).toBe(true);
    expect(t.reopen).toBe(false);
    expect(t.moveTargets).toEqual(OPEN.filter((s) => s !== state));
    expect(t.reopenTargets).toEqual([]);
  });

  it.each(TERMINAL)("terminal state %s offers only reopen with explicit destinations", (state) => {
    const t = availableTransitions({ state });
    expect(t.complete).toBe(false);
    expect(t.cancel).toBe(false);
    expect(t.reopen).toBe(true);
    expect(t.moveTargets).toEqual([]);
    expect(t.reopenTargets).toEqual(OPEN);
  });
});

describe("buildTransition", () => {
  const rev = 7;

  it.each(OPEN)("complete from %s builds a minimal payload", (state) => {
    const result = buildTransition({ state }, { action: "complete", expectedRevision: rev });
    expect(result).toEqual({ ok: true, payload: { action: "complete", expected_revision: rev } });
  });

  it.each(TERMINAL)("complete from %s is rejected", (state) => {
    expect(buildTransition({ state }, { action: "complete", expectedRevision: rev }).ok).toBe(false);
  });

  it.each(TERMINAL)("cancel from %s is rejected", (state) => {
    expect(buildTransition({ state }, { action: "cancel", expectedRevision: rev }).ok).toBe(false);
  });

  it("move requires a destination", () => {
    expect(buildTransition({ state: "inbox" }, { action: "move", expectedRevision: rev }).ok).toBe(false);
  });

  it("same-state move is rejected", () => {
    const result = buildTransition(
      { state: "next" },
      { action: "move", toState: "next", expectedRevision: rev },
    );
    expect(result.ok).toBe(false);
  });

  it("move from a terminal state is rejected", () => {
    const result = buildTransition(
      { state: "completed" },
      { action: "move", toState: "next", expectedRevision: rev },
    );
    expect(result.ok).toBe(false);
  });

  it("move to waiting requires non-blank waiting_for", () => {
    const missing = buildTransition(
      { state: "inbox" },
      { action: "move", toState: "waiting", expectedRevision: rev },
    );
    expect(missing.ok).toBe(false);
    const blank = buildTransition(
      { state: "inbox" },
      { action: "move", toState: "waiting", waitingFor: "   ", expectedRevision: rev },
    );
    expect(blank.ok).toBe(false);
    const good = buildTransition(
      { state: "inbox" },
      { action: "move", toState: "waiting", waitingFor: "  Anna — contract  ", expectedRevision: rev },
    );
    expect(good).toEqual({
      ok: true,
      payload: {
        action: "move",
        to_state: "waiting",
        waiting_for: "Anna — contract",
        expected_revision: rev,
      },
    });
  });

  it("move to a non-waiting state omits waiting_for entirely", () => {
    const result = buildTransition(
      { state: "waiting" },
      { action: "move", toState: "next", waitingFor: "stale", expectedRevision: rev },
    );
    expect(result).toEqual({
      ok: true,
      payload: { action: "move", to_state: "next", expected_revision: rev },
    });
  });

  it("reopen from an open state is rejected", () => {
    const result = buildTransition(
      { state: "inbox" },
      { action: "reopen", toState: "next", expectedRevision: rev },
    );
    expect(result.ok).toBe(false);
  });

  it("reopen requires an explicit destination", () => {
    expect(buildTransition({ state: "completed" }, { action: "reopen", expectedRevision: rev }).ok).toBe(
      false,
    );
  });

  it.each(TERMINAL)("reopen from %s to an open state builds the payload", (state) => {
    const result = buildTransition(
      { state },
      { action: "reopen", toState: "someday", expectedRevision: rev },
    );
    expect(result).toEqual({
      ok: true,
      payload: { action: "reopen", to_state: "someday", expected_revision: rev },
    });
  });

  it("reopen to waiting requires waiting_for", () => {
    const missing = buildTransition(
      { state: "cancelled" },
      { action: "reopen", toState: "waiting", expectedRevision: rev },
    );
    expect(missing.ok).toBe(false);
    const good = buildTransition(
      { state: "cancelled" },
      { action: "reopen", toState: "waiting", waitingFor: "vendor reply", expectedRevision: rev },
    );
    expect(good).toEqual({
      ok: true,
      payload: {
        action: "reopen",
        to_state: "waiting",
        waiting_for: "vendor reply",
        expected_revision: rev,
      },
    });
  });
});
