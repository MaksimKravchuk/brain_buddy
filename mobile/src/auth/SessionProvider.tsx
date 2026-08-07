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

import { ApiError, createApiClient, type ApiClient } from "@/api/client";
import type { MeResponse } from "@/api/types";
import { DEFAULT_SERVER_URL, loadServerUrl, saveServerUrl } from "@/config/serverUrl";

export type SessionStatus = "loading" | "signed-out" | "signed-in";

interface SessionContextValue {
  status: SessionStatus;
  me: MeResponse | null;
  serverUrl: string;
  api: ApiClient;
  /** True when the account's voice_brain_dump flag is on (fail closed). */
  voiceEnabled: boolean;
  signIn(email: string, password: string): Promise<void>;
  signUp(email: string, password: string, inviteCode: string): Promise<void>;
  signOut(): Promise<void>;
  updateServerUrl(url: string): Promise<void>;
  refreshMe(): Promise<void>;
}

const SessionContext = createContext<SessionContextValue | null>(null);

export function SessionProvider({ children }: PropsWithChildren) {
  const [status, setStatus] = useState<SessionStatus>("loading");
  const [me, setMe] = useState<MeResponse | null>(null);
  const [serverUrl, setServerUrl] = useState(DEFAULT_SERVER_URL);
  const serverUrlRef = useRef(serverUrl);
  serverUrlRef.current = serverUrl;

  const api = useMemo(
    () =>
      createApiClient({
        getBaseUrl: () => serverUrlRef.current,
        onUnauthorized: () => {
          setMe(null);
          setStatus("signed-out");
        },
      }),
    [],
  );

  const probe = useCallback(async () => {
    try {
      const profile = await api.me();
      setMe(profile);
      setStatus("signed-in");
    } catch (error) {
      setMe(null);
      setStatus("signed-out");
      if (!(error instanceof ApiError)) {
        // Network failure (offline / cold start): still land on sign-in,
        // which shows the reachable-server state honestly.
      }
    }
  }, [api]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const stored = await loadServerUrl();
      if (cancelled) {
        return;
      }
      setServerUrl(stored);
      serverUrlRef.current = stored;
      await probe();
    })();
    return () => {
      cancelled = true;
    };
  }, [probe]);

  const signIn = useCallback(
    async (email: string, password: string) => {
      const profile = await api.login({ email: email.trim(), password });
      setMe(profile);
      setStatus("signed-in");
    },
    [api],
  );

  const signUp = useCallback(
    async (email: string, password: string, inviteCode: string) => {
      const profile = await api.signup({
        email: email.trim(),
        password,
        invite_code: inviteCode.trim(),
      });
      setMe(profile);
      setStatus("signed-in");
    },
    [api],
  );

  const signOut = useCallback(async () => {
    try {
      await api.logout();
    } catch {
      // Signing out locally is fine even if the network call fails.
    }
    setMe(null);
    setStatus("signed-out");
  }, [api]);

  const updateServerUrl = useCallback(async (url: string) => {
    const normalized = await saveServerUrl(url);
    serverUrlRef.current = normalized;
    setServerUrl(normalized);
  }, []);

  const value = useMemo<SessionContextValue>(
    () => ({
      status,
      me,
      serverUrl,
      api,
      voiceEnabled: me?.feature_flags?.voice_brain_dump === true,
      signIn,
      signUp,
      signOut,
      updateServerUrl,
      refreshMe: probe,
    }),
    [status, me, serverUrl, api, signIn, signUp, signOut, updateServerUrl, probe],
  );

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
