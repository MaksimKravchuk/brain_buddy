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

// Login and signup are the only auth requests that can install an HttpOnly
// credential in the browser. Generation fencing protects Zustand publication,
// but cannot stop a stale Set-Cookie response. Abort superseded credential-
// issuing requests before their response reaches the browser, so clearSession
// and a newer explicit auth intent also protect the cookie plane.
const credentialIssuingControllers = new Set<AbortController>();

function beginAuthOperation(): number {
  return ++authOperationGeneration;
}

function cancelCredentialIssuingOperations(): void {
  for (const controller of credentialIssuingControllers) {
    controller.abort();
  }
  credentialIssuingControllers.clear();
}

function beginCredentialIssuingOperation(): AbortController {
  cancelCredentialIssuingOperations();
  const controller = new AbortController();
  credentialIssuingControllers.add(controller);
  return controller;
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
      const controller = beginCredentialIssuingOperation();
      try {
        const user = await authApi.login(payload, controller.signal);
        publishIfCurrent(generation, epochAtStart, { user, status: "authed" });
      } catch (error) {
        // A failed explicit login is itself a resolution, not a non-event --
        // if it's still the current operation, the store must settle to a
        // truthful anon/non-loading state (advancing epoch monotonically)
        // rather than leaving whatever loading/stale state preceded it. This
        // also fences out any hydrate that started earlier: hydrate's own
        // generation is now stale, so it can never overwrite this failure
        // once it eventually settles. The caller (e.g. the login form) still
        // needs the rejection to show an error, so it is rethrown.
        publishIfCurrent(generation, epochAtStart, { user: null, status: "anon" });
        throw error;
      } finally {
        credentialIssuingControllers.delete(controller);
      }
    },

    async signup(payload) {
      const generation = beginAuthOperation();
      const epochAtStart = get().epoch;
      const controller = beginCredentialIssuingOperation();
      try {
        const user = await authApi.signup(payload, controller.signal);
        publishIfCurrent(generation, epochAtStart, { user, status: "authed" });
      } catch (error) {
        publishIfCurrent(generation, epochAtStart, { user: null, status: "anon" });
        throw error;
      } finally {
        credentialIssuingControllers.delete(controller);
      }
    },

    async logout() {
      const generation = beginAuthOperation();
      const epochAtStart = get().epoch;
      cancelCredentialIssuingOperations();
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
      cancelCredentialIssuingOperations();
      publishIfCurrent(generation, epochAtStart, { user: null, status: "anon" });
    }
  };
});

// A request-start causal auth context: both the epoch in effect and the
// shared auth-operation generation at the moment it was captured. Consumers
// outside this module (the API client's 401 handler) must fence on *both* --
// epoch alone cannot detect "a newer auth operation has begun but not yet
// published", which is exactly the window an outgoing request's 401 can land
// in. See client.ts's setAuthCausalityProvider wiring.
export interface AuthCausality {
  epoch: number;
  generation: number;
}

export function getAuthCausality(): AuthCausality {
  return { epoch: useAuthStore.getState().epoch, generation: authOperationGeneration };
}
