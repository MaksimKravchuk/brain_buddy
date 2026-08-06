import { create } from "zustand";

import { authApi, type AuthUser, type LoginPayload, type SignupPayload } from "../api/auth";

export type AuthStatus = "loading" | "authed" | "anon";

interface AuthStoreState {
  user: AuthUser | null;
  status: AuthStatus;
  /** Set when the latest login cancelled a pending account deletion. */
  deletionCancelledNotice: boolean;
  hydrate: () => Promise<void>;
  login: (payload: LoginPayload) => Promise<void>;
  signup: (payload: SignupPayload) => Promise<void>;
  logout: () => Promise<void>;
  clearSession: () => void;
  dismissDeletionNotice: () => void;
}

export const useAuthStore = create<AuthStoreState>((set) => ({
  user: null,
  status: "loading",
  deletionCancelledNotice: false,

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

  async login(payload) {
    const user = await authApi.login(payload);
    set({
      user,
      status: "authed",
      deletionCancelledNotice: user.deletion_cancelled === true
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
  }
}));
