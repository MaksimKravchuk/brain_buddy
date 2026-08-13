/**
 * Idempotency keys for mutating API calls.
 *
 * Every task/project/tag/brain-dump mutation requires an `Idempotency-Key`
 * header. A key identifies one logical attempt: automatic retries of the
 * same attempt reuse it; a user-initiated retry after a conflict gets a new
 * one.
 */

import { useCallback, useRef } from "react";
import * as Crypto from "expo-crypto";

export { IntentSnapshotRegistry, requireIdempotencyKey } from "./intentSnapshot";

export function newIdempotencyKey(): string {
  return Crypto.randomUUID();
}

export interface IntentKey {
  /**
   * The key for the current intent, minting one on first ask.
   *
   * `intent` is whatever distinguishes one user intent from the next — the
   * message being sent, say. Asking again for the same intent returns the same
   * key, which is exactly what a retry needs.
   */
  current: (intent?: string) => string;
  /** Retire the key once the outcome is definitive; the next intent mints one. */
  settle: () => void;
}

/**
 * A key that survives a retry.
 *
 * A dropped connection or a 5xx is ambiguous: the command may well have reached
 * the server. Minting a fresh key for the retry would turn that ambiguity into
 * a second command, so the key is held until the outcome is definitive
 * (`settle`) or the user states a different intent. Mirrors
 * `frontend/src/utils/idempotency.ts`.
 */
export function useIntentKey(): IntentKey {
  const held = useRef<{ intent: string; key: string } | null>(null);

  const current = useCallback((intent = "") => {
    if (!held.current || held.current.intent !== intent) {
      held.current = { intent, key: newIdempotencyKey() };
    }
    return held.current.key;
  }, []);

  const settle = useCallback(() => {
    held.current = null;
  }, []);

  return { current, settle };
}
