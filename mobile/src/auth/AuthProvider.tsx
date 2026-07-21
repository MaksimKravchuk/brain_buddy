import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { MobileApiClient, MobileApiError, publicApiOrigin } from "@/api/client";
import type { User } from "@/api/types";
import { establishInstallMarker } from "./installMarker";
import { clearSessionToken, readSessionToken, saveSessionToken } from "./secureSession";

type AuthState = {
  user: User | null;
  ready: boolean;
  /** True once bootstrap fails for a reason that does not invalidate the stored
   * credential (offline, timeout, 5xx) — the token is preserved and retryable. */
  bootstrapError: boolean;
  api: MobileApiClient;
  signIn(email: string, password: string): Promise<void>;
  signOut(): Promise<void>;
  retryBootstrap(): Promise<void>;
};

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);
  const [bootstrapError, setBootstrapError] = useState(false);
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: false } } }));
  const api = useMemo(() => new MobileApiClient(publicApiOrigin(), readSessionToken, async () => {
    await clearSessionToken();
    client.clear();
    setUser(null);
  }), [client]);

  // A definitive 401 already cleared the credential via the client's
  // onUnauthorized callback above. Anything else (offline, DNS failure,
  // timeout, 5xx) is a transport problem, not proof the stored session is
  // invalid — keep the token and let the caller retry instead of forcing a
  // fresh sign-in.
  const isRetryableBootstrapFailure = (error: unknown): boolean =>
    !(error instanceof MobileApiError && error.status === 401);

  // Exposed for a user-triggered retry. Deliberately not the function the
  // mount effect below calls, so calling it is never mistaken for a
  // synchronous setState-in-effect call site.
  const retryBootstrap = useCallback(async () => {
    try {
      await establishInstallMarker();
      const token = await readSessionToken();
      if (token) setUser(await api.me());
      setBootstrapError(false);
    } catch (error) {
      setBootstrapError(isRetryableBootstrapFailure(error));
    } finally {
      setReady(true);
    }
  }, [api]);

  useEffect(() => {
    void (async () => {
      try {
        await establishInstallMarker();
        const token = await readSessionToken();
        if (token) setUser(await api.me());
        setBootstrapError(false);
      } catch (error) {
        setBootstrapError(isRetryableBootstrapFailure(error));
      } finally {
        setReady(true);
      }
    })();
  }, [api]);

  const value = useMemo<AuthState>(() => ({
    user, ready, bootstrapError, api,
    retryBootstrap,
    async signIn(email, password) {
      const session = await api.session(email, password);
      try { await saveSessionToken(session.session_token); } catch (error) {
        await api.logout(session.session_token).catch(() => undefined);
        throw error;
      }
      client.clear();
      setBootstrapError(false);
      setUser(session.user);
    },
    async signOut() {
      const token = await readSessionToken();
      await clearSessionToken();
      client.clear();
      setBootstrapError(false);
      setUser(null);
      if (token) await api.logout(token).catch(() => undefined);
    },
  }), [api, retryBootstrap, bootstrapError, client, ready, user]);

  return <AuthContext.Provider value={value}><QueryClientProvider client={client}>{children}</QueryClientProvider></AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const value = useContext(AuthContext);
  if (!value) throw new Error("AuthProvider is required.");
  return value;
}
