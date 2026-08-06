/**
 * Client-side task lifecycle guard matrix.
 *
 * Mirrors the server rules in `backend/app/modules/tasks/service.py` and
 * ADR-0006 ("the UI must not offer a command guaranteed to fail"):
 * - complete / cancel: open states only;
 * - move: open task to a *different* open state;
 * - reopen: terminal task to an explicitly named open state;
 * - any transition into waiting requires a non-blank `waiting_for`.
 *
 * The server stays authoritative; these guards only decide what the UI
 * offers and validate input before submission.
 */

import type { OpenTaskState, TaskState, TaskTransitionRequest } from "../api/types";
import { OPEN_TASK_STATES } from "../api/types";

export function isOpenState(state: TaskState): state is OpenTaskState {
  return (OPEN_TASK_STATES as TaskState[]).includes(state);
}

export interface AvailableTransitions {
  complete: boolean;
  cancel: boolean;
  reopen: boolean;
  /** Valid `move` destinations (empty for terminal tasks). */
  moveTargets: OpenTaskState[];
  /** Valid `reopen` destinations (empty for open tasks). */
  reopenTargets: OpenTaskState[];
}

export function availableTransitions(task: { state: TaskState }): AvailableTransitions {
  if (isOpenState(task.state)) {
    return {
      complete: true,
      cancel: true,
      reopen: false,
      moveTargets: OPEN_TASK_STATES.filter((state) => state !== task.state),
      reopenTargets: [],
    };
  }
  return {
    complete: false,
    cancel: false,
    reopen: true,
    moveTargets: [],
    reopenTargets: [...OPEN_TASK_STATES],
  };
}

export type GuardResult =
  | { ok: true; payload: TaskTransitionRequest }
  | { ok: false; reason: string };

export interface TransitionInput {
  action: TaskTransitionRequest["action"];
  toState?: OpenTaskState;
  waitingFor?: string | null;
  expectedRevision: number;
}

/**
 * Validate a transition against the current task state and build the exact
 * request payload (no extra keys — the backend forbids them).
 */
export function buildTransition(task: { state: TaskState }, input: TransitionInput): GuardResult {
  const { action, toState, waitingFor, expectedRevision } = input;
  const open = isOpenState(task.state);

  if (action === "complete" || action === "cancel") {
    if (!open) {
      return { ok: false, reason: `Only open tasks can be ${action}d.` };
    }
    return { ok: true, payload: { action, expected_revision: expectedRevision } };
  }

  if (action === "move") {
    if (!open) {
      return { ok: false, reason: "Only open tasks can move. Reopen this task instead." };
    }
    if (!toState) {
      return { ok: false, reason: "Choose a destination list." };
    }
    if (toState === task.state) {
      return { ok: false, reason: "The task is already in that list." };
    }
    if (toState === "waiting") {
      const trimmed = waitingFor?.trim();
      if (!trimmed) {
        return { ok: false, reason: "Waiting for requires who or what you are waiting on." };
      }
      return {
        ok: true,
        payload: { action, to_state: toState, waiting_for: trimmed, expected_revision: expectedRevision },
      };
    }
    return { ok: true, payload: { action, to_state: toState, expected_revision: expectedRevision } };
  }

  // reopen
  if (open) {
    return { ok: false, reason: "Only completed or cancelled tasks can reopen." };
  }
  if (!toState) {
    return { ok: false, reason: "Choose the list this task reopens into." };
  }
  if (toState === "waiting") {
    const trimmed = waitingFor?.trim();
    if (!trimmed) {
      return { ok: false, reason: "Waiting for requires who or what you are waiting on." };
    }
    return {
      ok: true,
      payload: { action, to_state: toState, waiting_for: trimmed, expected_revision: expectedRevision },
    };
  }
  return { ok: true, payload: { action, to_state: toState, expected_revision: expectedRevision } };
}
