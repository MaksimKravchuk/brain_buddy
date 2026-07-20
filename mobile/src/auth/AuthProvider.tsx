import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createContext, useContext, useEffect, useMemo, useState } from "react";

import { MobileApiClient, publicApiOrigin } from "@/api/client";
import type { User } from "@/api/types";
import { establishInstallMarker } from "./installMarker";
import { clearSessionToken, readSessionToken, saveSessionToken } from "./secureSession";

type AuthState = {
  user: User | null;
  ready: boolean;
  api: MobileApiClient;
  signIn(email: string, password: string): Promise<void>;
  signOut(): Promise<void>;
};

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: false } } }));
  const api = useMemo(() => new MobileApiClient(publicApiOrigin(), readSessionToken, async () => {
    await clearSessionToken();
    client.clear();
    setUser(null);
  }), [client]);

  useEffect(() => {
    void (async () => {
      try {
        await establishInstallMarker();
        const token = await readSessionToken();
        if (token) setUser(await api.me());
      } catch {
        await clearSessionToken();
        client.clear();
        setUser(null);
      } finally {
        setReady(true);
      }
    })();
  }, [api, client]);

  const value = useMemo<AuthState>(() => ({
    user, ready, api,
    async signIn(email, password) {
      const session = await api.session(email, password);
      try { await saveSessionToken(session.session_token); } catch (error) {
        await api.logout(session.session_token).catch(() => undefined);
        throw error;
      }
      client.clear();
      setUser(session.user);
    },
    async signOut() {
      const token = await readSessionToken();
      await clearSessionToken();
      client.clear();
      setUser(null);
      if (token) await api.logout(token).catch(() => undefined);
    },
  }), [api, client, ready, user]);

  return <AuthContext.Provider value={value}><QueryClientProvider client={client}>{children}</QueryClientProvider></AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const value = useContext(AuthContext);
  if (!value) throw new Error("AuthProvider is required.");
  return value;
}
