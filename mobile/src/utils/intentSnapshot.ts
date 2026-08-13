import { sha256 } from "js-sha256";

/** Refuse a missing relay intent before any API or transport work starts. */
export function requireIdempotencyKey(operation: string, idempotencyKey: string): string {
  if (typeof idempotencyKey !== "string" || idempotencyKey.trim() === "") {
    throw new Error(`${operation} requires a caller-owned Idempotency-Key.`);
  }
  return idempotencyKey;
}

function canonicalJson(value: unknown): string {
  return JSON.stringify(value, (_key, item: unknown) => {
    if (item === null || typeof item !== "object" || Array.isArray(item)) {
      return item;
    }
    return Object.fromEntries(
      Object.entries(item as Record<string, unknown>).sort(([left], [right]) =>
        left < right ? -1 : left > right ? 1 : 0,
      ),
    );
  });
}

/**
 * Volatile key-to-request binding for ambiguous relay retries.
 *
 * This module intentionally has no React or Expo imports so the API client can
 * also load in the Node/tsx integration harness. Only a one-way digest of the
 * canonical request is retained: request objects (including passwords and
 * credentials) cannot later be mutated behind the key, recovered from memory,
 * or exposed in errors and logs.
 */
export class IntentSnapshotRegistry {
  private readonly held = new Map<
    string,
    { digest: string; activeRequests: number; definitivelySettled: boolean }
  >();

  hold(
    operation: string,
    idempotencyKey: string,
    request: {
      method: string;
      baseUrl: string;
      requestEpoch?: number;
      path: string;
      body?: unknown;
    },
  ): string {
    const key = requireIdempotencyKey(operation, idempotencyKey);
    const digest = sha256(canonicalJson(request));
    const previous = this.held.get(key);
    if (previous && previous.digest !== digest) {
      throw new Error(`${operation} Idempotency-Key cannot be reused with a different request.`);
    }
    if (previous) {
      previous.activeRequests += 1;
    } else {
      this.held.set(key, {
        digest,
        activeRequests: 1,
        definitivelySettled: false,
      });
    }
    return key;
  }

  settle(idempotencyKey: string): void {
    const intent = this.held.get(idempotencyKey);
    if (!intent) {
      return;
    }
    intent.activeRequests -= 1;
    intent.definitivelySettled = true;
    if (intent.activeRequests === 0) {
      this.held.delete(idempotencyKey);
    }
  }

  preserve(idempotencyKey: string): void {
    const intent = this.held.get(idempotencyKey);
    if (!intent) {
      return;
    }
    intent.activeRequests -= 1;
    if (intent.activeRequests === 0 && intent.definitivelySettled) {
      this.held.delete(idempotencyKey);
    }
  }
}
