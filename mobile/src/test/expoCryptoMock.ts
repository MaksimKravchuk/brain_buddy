/**
 * Deterministic UUIDs for tests.
 *
 * `expo-crypto` is a native module: under jest-expo its auto-mock returns
 * `undefined`, which would silently send `Idempotency-Key: undefined` on every
 * mutation and make the header impossible to assert. This substitute hands out
 * counted v4-shaped ids instead, so a test can name the exact key it expects.
 */

let counter = 0;

export function nextUuid(): string {
  counter += 1;
  return `00000000-0000-4000-8000-${String(counter).padStart(12, "0")}`;
}

/** The nth id this mock hands out, counting from 1. */
export function uuidNumber(n: number): string {
  return `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
}

export function resetUuids(): void {
  counter = 0;
}

export function expoCryptoMock() {
  return {
    __esModule: true,
    randomUUID: () => nextUuid(),
  };
}
