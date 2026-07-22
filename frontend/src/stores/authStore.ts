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

// Counts auth-operation invocations (not resolutions), shared across
// hydrate, login, signup, logout, and clearSession. Lets an in-flight
// operation tell whether a *newer* auth operation of any kind has since
// started -- which happens both when React StrictMode (or any caller) fires
// hydrate() twice back-to-back, and when e.g. a slow login is still in
// flight when the user (or the 401 handler) triggers clearSession, or a
// slow logout is still in flight when a fresh login completes. Distinct
// from `epoch`: epoch only advances on publish, so two overlapping
// operations can both capture the same epoch before either has published.
let authOperationGeneration = 0;

function beginAuthOperation(): number {
  return ++authOperationGeneration;
}

export const useAuthStore = create<AuthStoreState>((set, get) => {
  // Publishes `patch` only if no newer auth operation has started since
  // `generation` was captured, and no other transition has advanced the
  // epoch since `epochAtStart` was captured. Either condition failing means
  // a later auth intent has already won; this result must not overwrite it,
  // advance epoch again, or touch its successor. Later auth intent wins
  // regardless of response ordering.
  const publishIfCurrent = (
    generation: number,
    epochAtStart: number,
    patch: { user: AuthUser | null; status: AuthStatus }
  ) => {
    if (generation !== authOperationGeneration) {
      return;
    }
    set((state) => {
      if (state.epoch !== epochAtStart) {
        return state;
      }
      return { ...patch, epoch: state.epoch + 1 };
    });
  };

  return {
    user: null,
    status: "loading",
    epoch: 0,

    async hydrate() {
      const generation = beginAuthOperation();
      const epochAtStart = get().epoch;

      try {
        const me = await authApi.me();
        publishIfCurrent(generation, epochAtStart, me ? { user: me, status: "authed" } : { user: null, status: "anon" });
      } catch {
        publishIfCurrent(generation, epochAtStart, { user: null, status: "anon" });
      }
    },

    async login(payload) {
      const generation = beginAuthOperation();
      const epochAtStart = get().epoch;
      const user = await authApi.login(payload);
      publishIfCurrent(generation, epochAtStart, { user, status: "authed" });
    },

    async signup(payload) {
      const generation = beginAuthOperation();
      const epochAtStart = get().epoch;
      const user = await authApi.signup(payload);
      publishIfCurrent(generation, epochAtStart, { user, status: "authed" });
    },

    async logout() {
      const generation = beginAuthOperation();
      const epochAtStart = get().epoch;
      // Always clear local state, even if the network call fails — the user
      // asked to sign out and we shouldn't block them on a transient error.
      try {
        await authApi.logout();
      } catch {
        /* swallow: local state is the source of truth for logout UX */
      }
      publishIfCurrent(generation, epochAtStart, { user: null, status: "anon" });
    },

    clearSession() {
      const generation = beginAuthOperation();
      const epochAtStart = get().epoch;
      publishIfCurrent(generation, epochAtStart, { user: null, status: "anon" });
    }
  };
});

export function getAuthEpoch(): number {
  return useAuthStore.getState().epoch;
}
