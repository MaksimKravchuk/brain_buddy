import { useCallback, useRef } from "react";

/**
 * Caller-generated idempotency key for a mutating request.
 *
 * The server deduplicates on this value, so a retry of the *same* user intent
 * must reuse the same key. Callers whose intent is already identified by a
 * server-issued token (a hand-off manifest, for example) derive the key from
 * that token instead of calling this.
 */
export function newIdempotencyKey(action: string): string {
  return `${action}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
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
 * A transport failure or a 5xx is ambiguous: the command may well have reached
 * the server. Minting a fresh key for the retry would turn that ambiguity into
 * a second command, so the key is held until the outcome is definitive
 * (`settle`) or the user states a different intent.
 */
export function useIntentKey(action: string): IntentKey {
  const held = useRef<{ intent: string; key: string } | null>(null);

  const current = useCallback(
    (intent = "") => {
      if (!held.current || held.current.intent !== intent) {
        held.current = { intent, key: newIdempotencyKey(action) };
      }
      return held.current.key;
    },
    [action]
  );

  const settle = useCallback(() => {
    held.current = null;
  }, []);

  return { current, settle };
}
