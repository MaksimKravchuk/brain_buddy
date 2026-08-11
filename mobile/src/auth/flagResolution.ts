/**
 * Reading a server-owned rollout flag when the server cannot be reached.
 *
 * FR-020: the flag's last known value for an identity MUST be readable with
 * no connection, and fail-closed MUST mean closed when the answer has never
 * been known **for this identity** — not closed whenever the network is down.
 * The flag is resolved server-side and delivered only in `/auth/me`, so a
 * live-only read renders the flag-OFF screen on an offline cold start, which
 * is the one path the feature exists for (SC-009).
 *
 * Pure: no storage, no clock. The adapter is `identityStorage.ts`.
 */

import type { MeResponse } from "../api/types";

/**
 * The rollout flag for mobile task classification (FR-015). Server-owned,
 * default OFF, and exposure control only — never authorization.
 *
 * Must match the name added to `KNOWN_FEATURE_FLAGS` in
 * `backend/app/core/config.py`.
 */
export const TASK_CLASSIFICATION_FLAG = "mobile_task_classification";

/** The flags `/auth/me` last delivered for one identity. */
export type FeatureFlagRecord = Record<string, boolean>;

/**
 * A live profile is authoritative in both directions — a flag the server has
 * turned off is off immediately, and a flag it does not mention is off, not
 * fallen back on. The persisted answer is consulted only when there is no
 * live profile at all.
 */
export function resolveFeatureFlag(
  flag: string,
  me: MeResponse | null,
  persisted: FeatureFlagRecord | null,
): boolean {
  if (me) {
    return me.feature_flags?.[flag] === true;
  }
  return persisted?.[flag] === true;
}

const IDENTITY_KEY_PREFIX = "bb.identity";
const FLAGS_KEY_PREFIX = "bb.featureFlags";

/**
 * `encodeURIComponent` per component, as `data-model.md` prescribes — plus
 * the dot.
 *
 * The key is the sole enforcement of identity isolation (SC-007), and
 * `encodeURIComponent` deliberately leaves `.` unescaped while `.` is also
 * the separator. Without this second step
 * (`serverUrl = "https://x.test/api"`, `accountId = "b.c"`) and
 * (`serverUrl = "https://x.test/api.b"`, `accountId = "c"`) still render to
 * one key string, and a user-typed server URL always contains dots.
 */
export function encodeKeyComponent(value: string): string {
  return encodeURIComponent(value).replace(/\./g, "%2E");
}

/**
 * Where the account id for a server is remembered.
 *
 * Keyed by server alone, because the account id is what it holds: both
 * halves of the queue's own key must be readable with no connection, and
 * `/auth/me` — the only live source of the account id — is exactly the call
 * that fails offline (FR-009).
 */
export function identityStorageKey(serverUrl: string): string {
  return `${IDENTITY_KEY_PREFIX}.${encodeKeyComponent(serverUrl)}`;
}

/** Where one identity's last known flag values are remembered (FR-020). */
export function flagStorageKey(serverUrl: string, accountId: string): string {
  return `${FLAGS_KEY_PREFIX}.${encodeKeyComponent(serverUrl)}.${encodeKeyComponent(accountId)}`;
}
