import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type PropsWithChildren,
} from "react";

import { createApiClient, type ApiClient } from "@/api/client";
import type { MeResponse } from "@/api/types";
import {
  currentServerUrl,
  DEFAULT_SERVER_URL,
  loadServerUrl,
  saveServerUrl,
} from "@/config/serverUrl";

import {
  TASK_CLASSIFICATION_FLAG,
  resolveFeatureFlag,
  type FeatureFlagRecord,
} from "./flagResolution";
import {
  clearPersistedIdentity,
  loadPersistedFlags,
  loadPersistedIdentity,
  markSessionRejected,
  persistIdentity,
  type PersistedIdentity,
} from "./identityStorage";
import { classifySessionFailure, resolveFailedProbe } from "./sessionOutcome";

/**
 * `signed-in-offline` is authenticated, offline, no live profile: the state
 * FR-019 requires the client to be able to hold. Without it an offline launch
 * is indistinguishable from a sign-out, and a sign-out discards the device
 * queue — so the missing state is what would destroy unsent work on the one
 * journey this feature exists for (SC-008, SC-009).
 */
export type SessionStatus = "loading" | "signed-out" | "signed-in" | "signed-in-offline";

interface SessionContextValue {
  status: SessionStatus;
  me: MeResponse | null;
  serverUrl: string;
  /**
   * The account this device is acting as, readable with no live profile.
   * Paired with `serverUrl` it is both halves of every device-local storage
   * key (FR-011, SC-007). Null whenever there is no usable session.
   */
  accountId: string | null;
  api: ApiClient;
  /** True when the account's voice_brain_dump flag is on (fail closed). */
  voiceEnabled: boolean;
  /**
   * True when the mobile task classification rollout flag's last known value
   * for **this identity** is on. Fail closed means closed when the answer has
   * never been known for this identity, not closed whenever the network is
   * down (FR-020). Exposure control only — never authorization.
   */
  taskClassificationEnabled: boolean;
  signIn(email: string, password: string): Promise<void>;
  signUp(email: string, password: string, inviteCode: string): Promise<void>;
  signOut(): Promise<void>;
  updateServerUrl(url: string): Promise<void>;
  refreshMe(): Promise<void>;
}

const SessionContext = createContext<SessionContextValue | null>(null);

/**
 * Bounded probe after a server change so a typo does not hold the screen for
 * the client's full 30 s request timeout. The launch probe keeps the default.
 */
const SERVER_CHANGE_PROBE_TIMEOUT_MS = 8_000;

export function SessionProvider({ children }: PropsWithChildren) {
  const [status, setStatus] = useState<SessionStatus>("loading");
  const [me, setMe] = useState<MeResponse | null>(null);
  const [serverUrl, setServerUrl] = useState(DEFAULT_SERVER_URL);
  const [identity, setIdentity] = useState<PersistedIdentity | null>(null);
  const [flags, setFlags] = useState<FeatureFlagRecord | null>(null);

  /**
   * Every identity transition bumps this. Anything that started under an
   * older epoch drops its result instead of writing it: a probe left in
   * flight by a server change must never sign out the session a later
   * sign-in established.
   */
  const epochRef = useRef(0);

  /** A 401 anywhere in the app: the session ended without anyone choosing it. */
  const handleUnauthorized = useCallback(async () => {
    const epoch = ++epochRef.current;
    const url = currentServerUrl();
    // Reading first gives a sign-in that raced this 401 a chance to win: if
    // the epoch moved, the newer session owns the identity and nothing here
    // is written. Should one still slip through, the cost is a signed-out
    // offline launch that the next successful `/auth/me` rewrites — the
    // fail-closed direction.
    const current = await loadPersistedIdentity(url);
    if (epochRef.current !== epoch) {
      return;
    }
    // The identity itself is kept — FR-011 keeps unsent work through an
    // involuntary end, and the queue is offered back on the next sign-in to
    // the same account. Only the marker changes.
    const marked = current ? await markSessionRejected(url) : null;
    if (epochRef.current !== epoch) {
      return;
    }
    setMe(null);
    setFlags(null);
    setIdentity(marked);
    setStatus("signed-out");
  }, []);

  const api = useMemo(
    () =>
      createApiClient({
        getBaseUrl: currentServerUrl,
        onUnauthorized: () => {
          void handleUnauthorized();
        },
      }),
    [handleUnauthorized],
  );

  /**
   * Persist and adopt every response that yields a profile — `/auth/me`,
   * `/auth/login` and `/auth/signup` alike.
   *
   * `signIn`/`signUp` set the session directly from their own responses and
   * never call the probe, so persisting only on `/auth/me` would leave a
   * fresh sign-in with no stored identity: a person who signs in, goes
   * offline and force-quits could not name their own queue key at the next
   * cold start (FR-009, FR-020).
   */
  const adoptProfile = useCallback(async (profile: MeResponse) => {
    const epoch = ++epochRef.current;
    setMe(profile);
    setFlags(profile.feature_flags ?? null);
    setStatus("signed-in");
    const record = await persistIdentity(currentServerUrl(), profile);
    if (epochRef.current !== epoch) {
      return;
    }
    setIdentity(record);
  }, []);

  const probe = useCallback(
    async (signal?: AbortSignal) => {
      const epoch = epochRef.current;
      const url = currentServerUrl();
      try {
        const profile = await api.me(signal);
        if (epochRef.current !== epoch) {
          return;
        }
        await adoptProfile(profile);
      } catch (error) {
        if (epochRef.current !== epoch) {
          // A 401 was already handled by `onUnauthorized`, or a newer
          // transition owns the session now.
          return;
        }
        const failure = classifySessionFailure(error);
        const known = await loadPersistedIdentity(url);
        if (epochRef.current !== epoch) {
          return;
        }
        setMe(null);
        setIdentity(known);
        if (resolveFailedProbe(failure, known) === "signed-in-offline" && known) {
          // Authenticated, offline, no live profile: the rollout flag, the
          // identity and the device queue all resolve from what the device
          // already holds.
          const persisted = await loadPersistedFlags(url, known.accountId);
          if (epochRef.current !== epoch) {
            return;
          }
          setFlags(persisted);
          setStatus("signed-in-offline");
          return;
        }
        setFlags(null);
        setStatus("signed-out");
      }
    },
    [api, adoptProfile],
  );

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const stored = await loadServerUrl();
      if (cancelled) {
        return;
      }
      setServerUrl(stored);
      await probe();
    })();
    return () => {
      cancelled = true;
    };
  }, [probe]);

  const signIn = useCallback(
    async (email: string, password: string) => {
      const profile = await api.login({ email: email.trim(), password });
      await adoptProfile(profile);
    },
    [api, adoptProfile],
  );

  const signUp = useCallback(
    async (email: string, password: string, inviteCode: string) => {
      const profile = await api.signup({
        email: email.trim(),
        password,
        invite_code: inviteCode.trim(),
      });
      await adoptProfile(profile);
    },
    [api, adoptProfile],
  );

  /**
   * A deliberate end. Unlike an involuntary one this forgets the identity, so
   * callers MUST discard the queue behind the FR-011 warning **before**
   * calling this — clearing the identity is what makes the queue's key
   * unnameable.
   */
  const signOut = useCallback(async () => {
    const epoch = ++epochRef.current;
    try {
      await api.logout();
    } catch {
      // Signing out locally is fine even if the network call fails.
    }
    await clearPersistedIdentity(currentServerUrl());
    if (epochRef.current !== epoch) {
      return;
    }
    setMe(null);
    setIdentity(null);
    setFlags(null);
    setStatus("signed-out");
  }, [api]);

  /**
   * A server change is a real identity transition, which is what settings
   * already tells the person it is: nothing the previous server said about
   * them is true of the new one. The previous server's identity is forgotten,
   * the session drops to signed-out, and the new server is probed — it may
   * already hold a valid cookie.
   */
  const updateServerUrl = useCallback(
    async (url: string) => {
      const previous = currentServerUrl();
      const normalized = await saveServerUrl(url);
      if (normalized === previous) {
        // Saving the URL it already had is not a transition, and treating it
        // as one would sign the person out for nothing.
        return;
      }
      const epoch = ++epochRef.current;
      await clearPersistedIdentity(previous);
      // `saveServerUrl` above already moved the live value; `config/serverUrl`
      // owns it since main #149, so there is no ref to keep in step — only the
      // rendering mirror below.
      setServerUrl(normalized);
      setMe(null);
      setIdentity(null);
      setFlags(null);
      setStatus("signed-out");
      if (epochRef.current !== epoch) {
        return;
      }
      await probe(AbortSignal.timeout(SERVER_CHANGE_PROBE_TIMEOUT_MS));
    },
    [probe],
  );

  const refreshMe = useCallback(async () => {
    await probe();
  }, [probe]);

  const value = useMemo<SessionContextValue>(() => {
    const hasSession = status === "signed-in" || status === "signed-in-offline";
    return {
      status,
      me,
      serverUrl,
      accountId: hasSession ? (me?.id ?? identity?.accountId ?? null) : null,
      api,
      voiceEnabled: resolveFeatureFlag("voice_brain_dump", me, null),
      taskClassificationEnabled: resolveFeatureFlag(TASK_CLASSIFICATION_FLAG, me, flags),
      signIn,
      signUp,
      signOut,
      updateServerUrl,
      refreshMe,
    };
  }, [
    status,
    me,
    serverUrl,
    identity,
    flags,
    api,
    signIn,
    signUp,
    signOut,
    updateServerUrl,
    refreshMe,
  ]);

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionContextValue {
  const context = useContext(SessionContext);
  if (!context) {
    throw new Error("useSession must be used inside SessionProvider");
  }
  return context;
}

export function useApi(): ApiClient {
  return useSession().api;
}
