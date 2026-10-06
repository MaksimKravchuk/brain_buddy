import { modernAuthApi, type Provider, type ProviderStart, type ProviderComplete, type ClientProof, type AuthAction, type RecentProof } from "../../api/modernAuth";
import { useAuthStore } from "../../stores/authStore";
import type { Completion } from "../../api/modernAuth";

const PENDING_KEY = "brainbuddy.auth.provider-attempt";
const TOKEN = /^[A-Za-z0-9_-]{43}$/;
export interface PendingProvider { attemptId: string; state: string; verifier: string; purpose: ProviderStart["purpose"]; expectedOwner?: string; action?: AuthAction; destination: string; expiresAt: number }
let recentConfirmation: { owner: string; action: AuthAction; proof: RecentProof } | null = null;

export function safeAuthDestination(candidate: unknown): string {
  if (typeof candidate !== "string" || !candidate.startsWith("/") || candidate.startsWith("//") || candidate.includes("\\")) return "/";
  const url = new URL(candidate, "https://brainbuddy.invalid");
  const fixed = ["/", "/settings/account", "/settings/account/delete", "/settings/agents", "/admin", "/cli/authorize"];
  const workspace = /^\/(tasks\/(inbox|next|waiting|someday|completed|cancelled)|projects\/[A-Za-z0-9_-]+|tags\/[A-Za-z0-9_-]+)(\/[A-Za-z0-9_-]+)?$/;
  if (!fixed.includes(url.pathname) && !workspace.test(url.pathname)) return "/";
  const owner = url.searchParams.get("expected_owner");
  return url.pathname + (url.pathname.startsWith("/settings/account") && owner && /^[A-Za-z0-9_-]{1,128}$/.test(owner) ? `?expected_owner=${encodeURIComponent(owner)}` : "");
}
function base64url(bytes: Uint8Array): string { return btoa(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, ""); }
export async function createClientProof(): Promise<ClientProof> {
  const verifier = base64url(crypto.getRandomValues(new Uint8Array(32)));
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  return { verifier, challenge: base64url(new Uint8Array(digest)) };
}
export function saveProviderAttempt(attempt: PendingProvider): void { sessionStorage.setItem(PENDING_KEY, JSON.stringify(attempt)); }
export function takeProviderCallback(): { request: ProviderComplete; pending: PendingProvider } {
  const fragment = window.location.hash.slice(1);
  window.history.replaceState(window.history.state, "", "/auth/complete");
  const stored = sessionStorage.getItem(PENDING_KEY); sessionStorage.removeItem(PENDING_KEY);
  const params = new URLSearchParams(fragment);
  if (params.size !== 3 || ["attempt", "state", "grant"].some(key => params.getAll(key).length !== 1 || !TOKEN.test(params.get(key) ?? "")) || !stored) throw new Error("This sign-in attempt is invalid or has expired. Start again.");
  const pending = JSON.parse(stored) as PendingProvider;
  if (!TOKEN.test(pending.verifier) || !Number.isFinite(pending.expiresAt) || pending.expiresAt <= Date.now() || pending.expiresAt > Date.now() + 600000 || pending.attemptId !== params.get("attempt") || pending.state !== params.get("state") || !["login", "link", "reauth"].includes(pending.purpose)) throw new Error("This sign-in attempt is invalid or has expired. Start again.");
  return { pending, request: { attempt_id: pending.attemptId, state: pending.state, handoff_code: params.get("grant") ?? "", client_verifier: pending.verifier } };
}
export async function startBrowserProvider(provider: Provider, options: Omit<ProviderStart, "client" | "client_challenge">, destination = "/"): Promise<void> {
  const proof = await createClientProof();
  const started = await modernAuthApi.startProvider(provider, { ...options, client: "web", client_challenge: proof.challenge });
  if (!started.authorization_url || !TOKEN.test(started.attempt_id) || !TOKEN.test(started.state)) throw new Error("Provider is unavailable");
  const url = new URL(started.authorization_url);
  if (url.protocol !== "https:" || url.username || url.password || !["accounts.google.com", "appleid.apple.com"].includes(url.hostname)) throw new Error("Invalid provider destination");
  saveProviderAttempt({ attemptId: started.attempt_id, state: started.state, verifier: proof.verifier, purpose: options.purpose, expectedOwner: options.expected_account_id, action: options.action, destination: safeAuthDestination(destination), expiresAt: Date.now() + 600000 });
  window.location.assign(url.href);
}
export function assertActingOwner(owner: string): void { if (useAuthStore.getState().user?.id !== owner) throw new Error("Use the account linked to this action. Sign in again before continuing."); }
export function rememberConfirmation(owner: string, action: AuthAction, proof: RecentProof): void { assertActingOwner(owner); recentConfirmation = { owner, action, proof }; }
export function takeConfirmation(owner: string, action: AuthAction): RecentProof | null {
  const saved = recentConfirmation; recentConfirmation = null;
  return saved?.owner === owner && saved.action === action && Date.parse(saved.proof.expires_at) > Date.now() ? saved.proof : null;
}
export async function acceptSignedIn(result: Completion): Promise<void> {
  if (result.status !== "signed_in") throw new Error("This outcome does not establish a session");
  await useAuthStore.getState().hydrate();
  if (useAuthStore.getState().user?.id !== result.user.id) throw new Error("We couldn't confirm sign-in. Start a fresh attempt.");
  if (result.deletion_cancelled || result.user.deletion_cancelled) useAuthStore.setState({ deletionCancelledNotice: true, deletionScheduledFor: null });
}
