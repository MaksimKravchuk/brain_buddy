import { create } from "zustand";

import { authApi, type AuthUser, type LoginPayload, type SignupPayload } from "../api/auth";
import { cleanupCrtOwnerScope } from "../features/crt/crtDraftCoordinator";

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
  logout: () => Promise<boolean>;
  /** Immediate local boundary used by 401 handlers; cleanup is started for the captured owner. */
  clearSession: () => boolean;
  /** Fail-closed boundary for destructive transitions such as account deletion. */
  clearSessionAfterCleanup: () => Promise<boolean>;
  dismissDeletionNotice: () => void;
  scheduleDeletionNotice: (purgeAt: string) => void;
}

// Bumped by every transition (hydrate/login/signup/logout/clearSession) and
// by every `refreshSession` call itself, so a `refreshSession` result only
// applies if nothing newer — another refresh, or a real transition — has
// started since. Without this, a slow poll response can resolve after a
// logout or an A->B account switch and resurrect the wrong session, or an
// out-of-order pair of overlapping polls can let the older response clobber
// the newer one (010-FR-009).
let sessionGeneration = 0;

async function cleanupDepartingOwner(user: AuthUser | null): Promise<boolean> {
  if (!user) return true;
  const result = await cleanupCrtOwnerScope(user.id, globalThis.location?.origin ?? "");
  return result.ok;
}

function sameFeatureFlags(left: AuthUser["feature_flags"], right: AuthUser["feature_flags"]): boolean {
  const leftFlags = left ?? {};
  const rightFlags = right ?? {};
  const leftKeys = Object.keys(leftFlags);
  const rightKeys = Object.keys(rightFlags);
  return leftKeys.length === rightKeys.length && leftKeys.every((key) => leftFlags[key] === rightFlags[key]);
}

function sameAuthUser(left: AuthUser, right: AuthUser): boolean {
  return left.id === right.id &&
    left.email === right.email &&
    (left.display_name ?? null) === (right.display_name ?? null) &&
    (left.deletion_cancelled === true) === (right.deletion_cancelled === true) &&
    sameFeatureFlags(left.feature_flags, right.feature_flags);
}

export const useAuthStore = create<AuthStoreState>((set, get) => ({
  user: null,
  status: "loading",
  deletionCancelledNotice: false,
  deletionScheduledFor: null,

  async hydrate() {
    const requestGeneration = ++sessionGeneration;
    try {
      const me = await authApi.me();
      if (requestGeneration !== sessionGeneration) return;
      const current = get().user;
      if (me && current && current.id !== me.id && !(await cleanupDepartingOwner(current))) return;
      if (requestGeneration !== sessionGeneration) return;
      if (me) {
        set({ user: me, status: "authed" });
      } else if (await cleanupDepartingOwner(get().user)) {
        if (requestGeneration !== sessionGeneration) return;
        set({ user: null, status: "anon" });
      }
    } catch {
      if (requestGeneration !== sessionGeneration) return;
      if (await cleanupDepartingOwner(get().user)) {
        if (requestGeneration !== sessionGeneration) return;
        set({ user: null, status: "anon" });
      }
    }
  },

  async refreshSession() {
    const requestGeneration = ++sessionGeneration;
    let me: AuthUser | null;
    try {
      me = await authApi.me();
    } catch {
      // Transient: network error, timeout, 5xx. The member did not make this
      // request, so it must not produce an error, a redirect or a sign-out.
      return;
    }
    if (requestGeneration !== sessionGeneration) {
      // Superseded by a newer refresh or a transition while this request was
      // in flight — applying it now would apply stale (or wrong-account) data.
      return;
    }
    const current = get().user;
    if (current && me && current.id !== me.id && !(await cleanupDepartingOwner(current))) return;
    if (requestGeneration !== sessionGeneration) return;
    if (me) {
      // The poll normally returns a newly allocated object even when no account
      // or flag value changed. Retain the current identity so object-dependent
      // exposure gates do not unmount active workspaces every polling interval.
      if (current && get().status === "authed" && sameAuthUser(current, me)) return;
      set({ user: me, status: "authed" });
    } else {
      if (!(await cleanupDepartingOwner(get().user))) return;
      if (requestGeneration !== sessionGeneration) return;
      set({ user: null, status: "anon" });
    }
  },

  async login(payload) {
    const requestGeneration = ++sessionGeneration;
    if (!(await cleanupDepartingOwner(get().user))) throw new Error("Could not clear the previous account's local CRT data");
    if (requestGeneration !== sessionGeneration) return;
    const user = await authApi.login(payload);
    if (requestGeneration !== sessionGeneration) return;
    set({
      user,
      status: "authed",
      deletionCancelledNotice: user.deletion_cancelled === true,
      deletionScheduledFor: null
    });
  },

  async signup(payload) {
    const requestGeneration = ++sessionGeneration;
    if (!(await cleanupDepartingOwner(get().user))) throw new Error("Could not clear the previous account's local CRT data");
    if (requestGeneration !== sessionGeneration) return;
    const user = await authApi.signup(payload);
    if (requestGeneration !== sessionGeneration) return;
    set({ user, status: "authed" });
  },

  async logout() {
    const requestGeneration = ++sessionGeneration;
    if (!(await cleanupDepartingOwner(get().user))) return false;
    if (requestGeneration !== sessionGeneration) return false;
    // Always clear local state, even if the network call fails — the user
    // asked to sign out and we shouldn't block them on a transient error.
    try {
      await authApi.logout();
    } catch {
      /* swallow: local state is the source of truth for logout UX */
    }
    if (requestGeneration !== sessionGeneration) return false;
    set({ user: null, status: "anon" });
    return true;
  },

  clearSession() {
    const departing = get().user;
    sessionGeneration += 1;
    set({ user: null, status: "anon" });
    // 401 handlers must invalidate the session synchronously so protected
    // requests cannot continue under a revoked owner. The cleanup targets the
    // captured owner and is best-effort here; explicit logout/deletion use the
    // fail-closed async boundary below.
    if (departing) void cleanupDepartingOwner(departing).catch(() => undefined);
    return true;
  },

  async clearSessionAfterCleanup() {
    const requestGeneration = ++sessionGeneration;
    if (!(await cleanupDepartingOwner(get().user))) return false;
    if (requestGeneration !== sessionGeneration) return false;
    set({ user: null, status: "anon" });
    return true;
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
