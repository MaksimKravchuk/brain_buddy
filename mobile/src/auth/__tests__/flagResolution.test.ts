/**
 * 006-FR-020 — the rollout flag's last known value for an identity must be
 * readable with no connection, and fail-closed must mean closed when the
 * answer was never known for this identity, not closed whenever the network
 * is down.
 *
 * The flag is resolved server-side and delivered only in `/auth/me`, so
 * reading it live renders the flag-OFF screen on an offline cold start — the
 * one path the feature exists for.
 */

import type { MeResponse } from "../../api/types";
import {
  TASK_CLASSIFICATION_FLAG,
  flagStorageKey,
  identityStorageKey,
  resolveFeatureFlag,
} from "../flagResolution";

function profile(flags: Record<string, boolean>): MeResponse {
  return { id: "acct-1", email: "person@example.test", feature_flags: flags };
}

describe("resolveFeatureFlag", () => {
  it("006-FR-020 resolves true from persisted state when there is no live profile", () => {
    expect(
      resolveFeatureFlag(TASK_CLASSIFICATION_FLAG, null, { [TASK_CLASSIFICATION_FLAG]: true }),
    ).toBe(true);
  });

  it("006-FR-020 resolves false when the answer was never known for this identity", () => {
    // Never fetched at all, and fetched-but-this-flag-absent, are the same
    // thing: no answer has ever been given for this identity.
    expect(resolveFeatureFlag(TASK_CLASSIFICATION_FLAG, null, null)).toBe(false);
    expect(resolveFeatureFlag(TASK_CLASSIFICATION_FLAG, null, {})).toBe(false);
  });

  it("006-FR-020 lets a live profile win over the persisted answer in both directions", () => {
    expect(
      resolveFeatureFlag(
        TASK_CLASSIFICATION_FLAG,
        profile({ [TASK_CLASSIFICATION_FLAG]: false }),
        { [TASK_CLASSIFICATION_FLAG]: true },
      ),
    ).toBe(false);
    expect(
      resolveFeatureFlag(TASK_CLASSIFICATION_FLAG, profile({ [TASK_CLASSIFICATION_FLAG]: true }), {
        [TASK_CLASSIFICATION_FLAG]: false,
      }),
    ).toBe(true);
  });

  it("006-FR-015 defaults OFF when nothing is known at all", () => {
    expect(resolveFeatureFlag(TASK_CLASSIFICATION_FLAG, profile({}), null)).toBe(false);
    expect(resolveFeatureFlag(TASK_CLASSIFICATION_FLAG, null, null)).toBe(false);
  });

  it("006-FR-015 never lets another flag's answer stand in for this one", () => {
    expect(resolveFeatureFlag(TASK_CLASSIFICATION_FLAG, null, { voice_brain_dump: true })).toBe(
      false,
    );
    expect(
      resolveFeatureFlag(TASK_CLASSIFICATION_FLAG, profile({ voice_brain_dump: true }), null),
    ).toBe(false);
  });

  it("006-FR-015 closes a live profile that does not carry the flag rather than falling back", () => {
    // A live answer exists for this identity; the flag simply is not on. The
    // persisted value is last-known-*offline*, not a second opinion to prefer
    // when the live one is inconvenient.
    expect(
      resolveFeatureFlag(TASK_CLASSIFICATION_FLAG, profile({}), {
        [TASK_CLASSIFICATION_FLAG]: true,
      }),
    ).toBe(false);
  });

  it("006-FR-015 treats a non-boolean stored value as never known", () => {
    const corrupted = { [TASK_CLASSIFICATION_FLAG]: "true" } as unknown as Record<string, boolean>;
    expect(resolveFeatureFlag(TASK_CLASSIFICATION_FLAG, null, corrupted)).toBe(false);
  });
});

describe("storage keys", () => {
  it("006-FR-020 escapes each component so two identities can never render to one key", () => {
    // Naive concatenation collides here: "…/api" + "." + "b.c" and
    // "…/api.b" + "." + "c" are the same string, and the key is the sole
    // enforcement of the isolation (SC-007). serverUrl is user-typed and
    // always contains dots.
    expect(flagStorageKey("https://x.test/api", "b.c")).not.toBe(
      flagStorageKey("https://x.test/api.b", "c"),
    );
    expect(identityStorageKey("https://x.test/api.b")).not.toBe(
      identityStorageKey("https://x.test/api"),
    );
  });

  it("006-FR-020 keeps distinct identities on distinct keys", () => {
    const a = flagStorageKey("https://x.test/api", "acct-1");
    const b = flagStorageKey("https://x.test/api", "acct-2");
    const c = flagStorageKey("https://y.test/api", "acct-1");
    expect(new Set([a, b, c]).size).toBe(3);
  });

  it("006-FR-020 is stable for the same identity, so a cold start reads what a warm run wrote", () => {
    expect(flagStorageKey("https://x.test/api", "acct-1")).toBe(
      flagStorageKey("https://x.test/api", "acct-1"),
    );
    expect(identityStorageKey("https://x.test/api")).toBe(identityStorageKey("https://x.test/api"));
  });

  it("006-FR-009 keys the identity pointer by server alone — the account id is what it holds", () => {
    // Both halves of the queue's key must be readable with no connection.
    // `serverUrl` already is; the account id has to be found from it.
    expect(identityStorageKey("https://x.test/api")).toContain("bb.identity.");
    expect(identityStorageKey("https://x.test/api")).not.toContain("acct");
  });
});
