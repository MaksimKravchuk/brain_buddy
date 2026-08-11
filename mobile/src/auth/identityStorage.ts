/**
 * What the device remembers about who is signed in, so that a cold start
 * with no connection can name its own storage keys and read its own rollout
 * flag.
 *
 * `/auth/me` is the only live source of the account id and it is exactly the
 * call that fails offline, so the id is persisted from **every** path that
 * establishes an identity — `/auth/me`, `/auth/login` and `/auth/signup`
 * (data-model.md, "Key derivation"). The opaque id only, never the email.
 *
 * Same mechanism as `config/serverUrl.ts`: AsyncStorage, no new dependency.
 * AsyncStorage rests unencrypted inside the app container, which is why
 * nothing here holds anything but an opaque id and booleans.
 */

import AsyncStorage from "@react-native-async-storage/async-storage";

import type { MeResponse } from "../api/types";
import { flagStorageKey, identityStorageKey, type FeatureFlagRecord } from "./flagResolution";

export interface PersistedIdentity {
  /** The opaque account id — the half of every device-local key that is not
   *  the server URL (FR-011, SC-007). */
  accountId: string;
  /** When this record was written. Present so the FR-018 cross-identity
   *  sweep can bound this store too, rather than leaving it the one
   *  device-local store without a retention bound. */
  savedAt: string;
  /** Set when a 401 ended the session. The identity itself survives — an
   *  involuntary end keeps unsent work (FR-011) — but the device now knows
   *  the session is over and must not resurrect it on the next offline
   *  launch (FR-019). */
  sessionRejectedAt?: string;
}

interface PersistedFlagRecord {
  flags: FeatureFlagRecord;
  savedAt: string;
}

async function readJson<T>(key: string): Promise<T | null> {
  try {
    const raw = await AsyncStorage.getItem(key);
    if (!raw) {
      return null;
    }
    const parsed: unknown = JSON.parse(raw);
    return parsed !== null && typeof parsed === "object" ? (parsed as T) : null;
  } catch {
    // A corrupted or unreadable record must not take the launch down with
    // it; an unknown identity fails closed, which is the safe direction.
    return null;
  }
}

/** Keep only booleans, so a malformed payload cannot turn a flag on. */
function sanitizeFlags(flags: Record<string, boolean> | null | undefined): FeatureFlagRecord {
  const clean: FeatureFlagRecord = {};
  for (const [name, value] of Object.entries(flags ?? {})) {
    if (typeof value === "boolean") {
      clean[name] = value;
    }
  }
  return clean;
}

export async function loadPersistedIdentity(serverUrl: string): Promise<PersistedIdentity | null> {
  const record = await readJson<PersistedIdentity>(identityStorageKey(serverUrl));
  if (!record || typeof record.accountId !== "string" || !record.accountId) {
    return null;
  }
  return record;
}

/**
 * Persist everything a `MeResponse` establishes: who this device is acting
 * as, and what the server said about their flags.
 *
 * When a **different** account signs in, the previous identity's stored keys
 * are deleted rather than left unread — identity-in-the-key closes
 * disclosure, but invisible is not erased and nothing ever reads a key it
 * will never open again (FR-011).
 */
export async function persistIdentity(
  serverUrl: string,
  profile: MeResponse,
  now: Date = new Date(),
): Promise<PersistedIdentity> {
  const previous = await loadPersistedIdentity(serverUrl);
  if (previous && previous.accountId !== profile.id) {
    await AsyncStorage.removeItem(flagStorageKey(serverUrl, previous.accountId));
  }

  const savedAt = now.toISOString();
  const identity: PersistedIdentity = { accountId: profile.id, savedAt };
  const flags: PersistedFlagRecord = { flags: sanitizeFlags(profile.feature_flags), savedAt };

  await AsyncStorage.multiSet([
    [identityStorageKey(serverUrl), JSON.stringify(identity)],
    [flagStorageKey(serverUrl, profile.id), JSON.stringify(flags)],
  ]);
  return identity;
}

/** The last flag values seen for this identity, or null when never known. */
export async function loadPersistedFlags(
  serverUrl: string,
  accountId: string,
): Promise<FeatureFlagRecord | null> {
  const record = await readJson<PersistedFlagRecord>(flagStorageKey(serverUrl, accountId));
  if (!record || record.flags === null || typeof record.flags !== "object") {
    return null;
  }
  return sanitizeFlags(record.flags as FeatureFlagRecord);
}

/**
 * Record that a 401 ended this session, keeping the identity itself.
 *
 * A no-op when nothing is persisted: there is no session to mark.
 */
export async function markSessionRejected(
  serverUrl: string,
  now: Date = new Date(),
): Promise<PersistedIdentity | null> {
  const current = await loadPersistedIdentity(serverUrl);
  if (!current) {
    return null;
  }
  const marked: PersistedIdentity = { ...current, sessionRejectedAt: now.toISOString() };
  await AsyncStorage.setItem(identityStorageKey(serverUrl), JSON.stringify(marked));
  return marked;
}

/**
 * Forget this server's identity and its flags.
 *
 * For **deliberate** transitions only — sign-out, account change, server
 * change. An involuntary session end must not reach this: it would leave the
 * queue with no identity to be offered back to on the next sign-in (FR-011,
 * SC-008). Callers must discard the queue *before* calling this, since this
 * is what makes the queue's key unnameable.
 */
export async function clearPersistedIdentity(serverUrl: string): Promise<void> {
  const current = await loadPersistedIdentity(serverUrl);
  const keys = [identityStorageKey(serverUrl)];
  if (current) {
    keys.push(flagStorageKey(serverUrl, current.accountId));
  }
  await AsyncStorage.multiRemove(keys);
}
