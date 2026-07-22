import { create } from "zustand";

import { authApi, type AuthUser, type LoginPayload, type SignupPayload } from "../api/auth";

export type AuthStatus = "loading" | "authed" | "anon";

interface AuthStoreState {
  user: AuthUser | null;
  status: AuthStatus;
  // Monotonically increasing counter, advanced on every auth/session state
  // transition -- including a transition that resolves back to the same
  // owner identity (e.g. A -> anon -> the same A again). Owner identity
  // alone cannot distinguish that later A session from the earlier one, so
  // any code that needs to detect "the session in effect when I started has
  // since changed" (task cache publication, in-flight request/mutation
  // guards, the outgoing-401 handler) must compare epoch, not just user id.
  epoch: number;
  hydrate: () => Promise<void>;
  login: (payload: LoginPayload) => Promise<void>;
  signup: (payload: SignupPayload) => Promise<void>;
  logout: () => Promise<void>;
  clearSession: () => void;
}

// Counts hydrate() invocations (not resolutions). Lets an in-flight hydrate
// tell whether a *newer* hydrate call has since started -- which happens
// when React StrictMode (or any caller) fires hydrate() twice back-to-back.
// Distinct from `epoch`: epoch only advances on publish, so two overlapping
// hydrate calls can both capture the same epoch before either has published.
let hydrateGeneration = 0;

export const useAuthStore = create<AuthStoreState>((set, get) => ({
  user: null,
  status: "loading",
  epoch: 0,

  async hydrate() {
    const generation = ++hydrateGeneration;
    const epochAtStart = get().epoch;
    const publish = (patch: { user: AuthUser | null; status: AuthStatus }) => {
      // A newer hydrate() call has started since this one -- it is the
      // current call now, so this stale result must not publish.
      if (generation !== hydrateGeneration) {
        return;
      }
      set((state) => {
        // A login/signup/logout/clearSession (or a hydrate that already won
        // the race above) advanced the epoch while this call was in flight.
        // That later transition must win; this stale result must not
        // overwrite it, advance epoch again, or touch its successor.
        if (state.epoch !== epochAtStart) {
          return state;
        }
        return { ...patch, epoch: state.epoch + 1 };
      });
    };

    try {
      const me = await authApi.me();
      publish(me ? { user: me, status: "authed" } : { user: null, status: "anon" });
    } catch {
      publish({ user: null, status: "anon" });
    }
  },

  async login(payload) {
    const user = await authApi.login(payload);
    set((state) => ({ user, status: "authed", epoch: state.epoch + 1 }));
  },

  async signup(payload) {
    const user = await authApi.signup(payload);
    set((state) => ({ user, status: "authed", epoch: state.epoch + 1 }));
  },

  async logout() {
    // Always clear local state, even if the network call fails — the user
    // asked to sign out and we shouldn't block them on a transient error.
    try {
      await authApi.logout();
    } catch {
      /* swallow: local state is the source of truth for logout UX */
    }
    set((state) => ({ user: null, status: "anon", epoch: state.epoch + 1 }));
  },

  clearSession() {
    set((state) => ({ user: null, status: "anon", epoch: state.epoch + 1 }));
  }
}));

export function getAuthEpoch(): number {
  return useAuthStore.getState().epoch;
}
