/**
 * Why a session probe failed, and what that failure means for the session.
 *
 * FR-019: the client MUST distinguish an authentication rejection from a
 * failure to reach the server, and MUST end the session only on the former.
 * Treating them alike makes an offline launch indistinguishable from a
 * sign-out — the path that would discard the device queue on exactly the
 * journey the feature exists for (SC-008).
 *
 * These rules live here rather than inside `SessionProvider` because
 * `mobile/` has no component-render test library: left in the provider they
 * would have no testable home at all.
 */

import { ApiError } from "../api/client";

export type SessionFailure = "unauthenticated" | "unreachable" | "other";

export type SessionResolution = "signed-out" | "signed-in-offline";

/** The part of the persisted identity this decision needs. */
export interface KnownIdentity {
  accountId: string;
  /** Set when a 401 already ended this session; see `resolveFailedProbe`. */
  sessionRejectedAt?: string;
}

/**
 * Names carried by an aborted or timed-out request. The client arms
 * `AbortSignal.timeout(30_000)` on every call, so a bad connection surfaces
 * as one of these far more often than as a refusal — and neither says
 * anything about whether the session is still valid.
 */
const UNREACHABLE_ERROR_NAMES = new Set(["TimeoutError", "AbortError"]);

function errorName(error: unknown): string | null {
  const name = (error as { name?: unknown } | null | undefined)?.name;
  return typeof name === "string" ? name : null;
}

/**
 * `unauthenticated` — the server answered and rejected the credentials.
 * `unreachable` — the request never got an answer.
 * `other` — the server answered with something that is not a rejection.
 *
 * Anything unrecognised is `other`: claiming `unreachable` would assert
 * something about the network the value does not support.
 */
export function classifySessionFailure(error: unknown): SessionFailure {
  if (error instanceof ApiError) {
    return error.status === 401 ? "unauthenticated" : "other";
  }
  const name = errorName(error);
  if (error instanceof TypeError || name === "TypeError") {
    // React Native's fetch throws `TypeError: Network request failed` when it
    // cannot reach the host; undici (Node) throws `TypeError: fetch failed`.
    return "unreachable";
  }
  if (name !== null && UNREACHABLE_ERROR_NAMES.has(name)) {
    return "unreachable";
  }
  return "other";
}

/**
 * What a failed `/auth/me` resolves to, given what the device already knows.
 *
 * Only an authentication rejection ends the session. Everything else falls
 * back to the persisted identity, which is what makes "authenticated,
 * offline, no live profile" representable instead of collapsing onto
 * signed-out.
 */
export function resolveFailedProbe(
  failure: SessionFailure,
  identity: KnownIdentity | null,
): SessionResolution {
  if (failure === "unauthenticated") {
    return "signed-out";
  }
  if (!identity) {
    // Nothing was ever persisted for this server, so there is no session to
    // carry offline — fail closed onto the sign-in screen.
    return "signed-out";
  }
  if (identity.sessionRejectedAt) {
    // A 401 seen while online is knowledge. A later offline launch must not
    // resurrect a session the device already learned was over.
    return "signed-out";
  }
  return "signed-in-offline";
}
