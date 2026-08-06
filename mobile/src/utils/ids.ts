/**
 * Idempotency keys for mutating API calls.
 *
 * Every task/project/tag/brain-dump mutation requires an `Idempotency-Key`
 * header. A key identifies one logical attempt: automatic retries of the
 * same attempt reuse it; a user-initiated retry after a conflict gets a new
 * one.
 */

import * as Crypto from "expo-crypto";

export function newIdempotencyKey(): string {
  return Crypto.randomUUID();
}
