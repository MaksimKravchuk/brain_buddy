import { create } from "zustand";

import { authApi, type AuthUser, type LoginPayload, type SignupPayload } from "../api/auth";

export type AuthStatus = "loading" | "authed" | "anon";

interface AuthStoreState {
  user: AuthUser | null;
  status: AuthStatus;
  /** Set when the latest login cancelled a pending account deletion. */
  deletionCancelledNotice: boolean;
  /**
   * Purge date of a just-requested account deletion. Carried here (not only
   * in router state) because clearing the session makes ProtectedRoute issue
   * its own /login redirect, which would drop router state on the floor.
   */
  deletionScheduledFor: string | null;
  hydrate: () => Promise<void>;
  /**
   * The background poll's own read of `/api/auth/me` (010-FR-009, DD-11).
   *
   * Deliberately not `hydrate()`: that one clears the session to anonymous on
   * *any* thrown failure, which is right for a cold load — otherwise an
   * unreachable backend leaves the app on "loading" forever — and wrong for a
   * poll, where an ordinary network blip would sign the member out. Here a
   * transient (non-401) failure leaves `user` and `status` exactly as they
   * were and surfaces nothing; a 401 (`me()` resolving null) clears the
   * session exactly as `hydrate()` already does.
   */
  refreshSession: () => Promise<void>;
  login: (payload: LoginPayload) => Promise<void>;
  signup: (payload: SignupPayload) => Promise<void>;
  logout: () => Promise<void>;
  clearSession: () => void;
  dismissDeletionNotice: () => void;
  scheduleDeletionNotice: (purgeAt: string) => void;
}

export const useAuthStore = create<AuthStoreState>((set) => ({
  user: null,
  status: "loading",
  deletionCancelledNotice: false,
  deletionScheduledFor: null,

  async hydrate() {
    try {
      const me = await authApi.me();
      if (me) {
        set({ user: me, status: "authed" });
      } else {
        set({ user: null, status: "anon" });
      }
    } catch {
      set({ user: null, status: "anon" });
    }
  },

  async refreshSession() {
    let me: AuthUser | null;
    try {
      me = await authApi.me();
    } catch {
      // Transient: network error, timeout, 5xx. The member did not make this
      // request, so it must not produce an error, a redirect or a sign-out.
      return;
    }
    if (me) {
      set({ user: me, status: "authed" });
    } else {
      set({ user: null, status: "anon" });
    }
  },

  async login(payload) {
    const user = await authApi.login(payload);
    set({
      user,
      status: "authed",
      deletionCancelledNotice: user.deletion_cancelled === true,
      deletionScheduledFor: null
    });
  },

  async signup(payload) {
    const user = await authApi.signup(payload);
    set({ user, status: "authed" });
  },

  async logout() {
    // Always clear local state, even if the network call fails — the user
    // asked to sign out and we shouldn't block them on a transient error.
    try {
      await authApi.logout();
    } catch {
      /* swallow: local state is the source of truth for logout UX */
    }
    set({ user: null, status: "anon" });
  },

  clearSession() {
    set({ user: null, status: "anon" });
  },

  dismissDeletionNotice() {
    set({ deletionCancelledNotice: false });
  },

  scheduleDeletionNotice(purgeAt) {
    set({ deletionScheduledFor: purgeAt });
  }
}));

/**
 * How often an already-open session re-reads its identity and flags.
 *
 * A founder-set default, not a derived requirement, so it is one named
 * constant to change. The mobile client uses the same value.
 */
export const FLAG_REFRESH_INTERVAL_MS = 15_000;

const canPoll = (): boolean =>
  useAuthStore.getState().status === "authed" &&
  (typeof document === "undefined" || document.visibilityState !== "hidden");

/**
 * Keep an already-open browser session's flags current (010-FR-009).
 *
 * A single interval plus `focus` and `visibilitychange` listeners, all driving
 * `refreshSession()`. Nothing is issued while anonymous or while the document
 * is hidden, so a backgrounded tab costs nothing and a signed-out visitor is
 * untouched — and no WebSocket or SSE stream is opened for this.
 *
 * Started once at module scope from `queryClient.ts`, next to
 * `bindAdminSession`, for the same reason: `main.tsx` never executes under
 * Vitest, so wiring it only there would leave the subscription uncovered.
 */
export function startFlagRefresh(): () => void {
  let timer: ReturnType<typeof setInterval> | null = null;

  const refresh = () => {
    if (!canPoll()) return;
    void useAuthStore.getState().refreshSession();
  };

  const start = () => {
    if (timer !== null) return;
    timer = setInterval(refresh, FLAG_REFRESH_INTERVAL_MS);
  };

  const stopTimer = () => {
    if (timer === null) return;
    clearInterval(timer);
    timer = null;
  };

  const sync = (status: AuthStatus) => {
    if (status === "authed") {
      start();
    } else {
      stopTimer();
    }
  };

  window.addEventListener("focus", refresh);
  document.addEventListener("visibilitychange", refresh);
  const unsubscribe = useAuthStore.subscribe((state) => sync(state.status));
  sync(useAuthStore.getState().status);

  return () => {
    unsubscribe();
    stopTimer();
    window.removeEventListener("focus", refresh);
    document.removeEventListener("visibilitychange", refresh);
  };
}
