import type { AuthUser } from "./auth";
import type { AccountDeleteResponse } from "./accountTypes";
import { ApiError, getApiBaseUrl, notifyUnauthorized } from "./client";
import { parseAttachmentFilename } from "./account";

export type Provider = "google" | "apple";
export type AuthAction = "verify_email" | "change_email" | "link:google" | "link:apple" | "unlink:google" | "unlink:apple" | "password" | "export" | "delete";
export type EmailPurpose = "login" | "recover" | "verify_email" | "change_email" | "reauth" | "provider_mailbox";
export interface Methods { password: boolean; google: boolean; apple: boolean; email: boolean; web_account_origin: string | null }
export interface Challenge { challenge_id: string; expires_at: string; resend_at: string; message: string }
export interface ClientProof { verifier: string; challenge: string }
export interface EmailRequest { email: string; purpose: EmailPurpose; client: "web"; client_challenge: string; expected_account_id?: string; action?: AuthAction; recent_proof?: string; provider_attempt_id?: string }
export interface EmailVerify { challenge_id: string; client_verifier: string; code: string; recent_proof?: string }
export interface ProviderStart { purpose: "login" | "link" | "reauth"; client: "web"; client_challenge: string; action?: AuthAction; expected_account_id?: string; recent_proof?: string }
export interface ProviderStarted { attempt_id: string; state: string; nonce: string; authorization_url: string | null }
export interface ProviderComplete { attempt_id: string; state: string; handoff_code: string; client_verifier: string }
export interface RecentProof { status: "reauthenticated"; recent_proof: string; expires_at: string }
export type Completion =
  | { status: "signed_in"; user: AuthUser; deletion_cancelled: boolean }
  | { status: "linked" | "verified_email" | "changed_email"; user: AuthUser }
  | { status: "reset_ready"; reset_grant: string; expires_at: string }
  | RecentProof
  | (Challenge & { status: "verify_mailbox" })
  | { status: "existing_account_required"; message: string };
export interface ConnectedMethod { method: "password" | "email" | Provider; state: "active" | "disabled"; usable: boolean; connected_at: string | null }
export interface AccountMethods { account_id: string; email: string; email_verified: boolean; email_delivery: "available" | "disabled" | "unconfigured"; has_password: boolean; methods: ConnectedMethod[] }
export interface AccountAction { recent_proof: string; expected_account_id: string }

// Auth errors deliberately avoid the generic client's network-error telemetry:
// an upstream exception must never put a credential or callback URL in logs.
async function send(path: string, body?: unknown): Promise<Response> {
  const response = await fetch(`${getApiBaseUrl()}${path}`, {
    method: body === undefined ? "GET" : "POST", credentials: "include",
    cache: "no-store", headers: body === undefined ? { Accept: "application/json" } : { Accept: "application/json", "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body)
  });
  if (!response.ok) {
    if (response.status === 401 && path.startsWith("/account/")) notifyUnauthorized();
    let payload: unknown = null;
    try { payload = await response.json(); } catch { /* only safe references are displayed */ }
    throw new ApiError("Authentication request failed", response.status, payload, response.headers.get("X-Correlation-ID") ?? undefined);
  }
  return response;
}
async function request<T>(path: string, body?: unknown): Promise<T> {
  const response = await send(path, body);
  return response.status === 204 ? undefined as T : await response.json() as T;
}
function completion(value: Completion): Completion {
  if (!value || typeof value !== "object" || !["signed_in", "linked", "verified_email", "changed_email", "reset_ready", "reauthenticated", "verify_mailbox", "existing_account_required"].includes(value.status)) throw new Error("Invalid authentication response");
  if (["signed_in", "linked", "verified_email", "changed_email"].includes(value.status) && (!("user" in value) || !value.user || typeof value.user.id !== "string" || typeof value.user.email !== "string")) throw new Error("Invalid account response");
  if (value.status === "reset_ready" || value.status === "reauthenticated") {
    const grant = value.status === "reset_ready" ? value.reset_grant : value.recent_proof;
    if (typeof grant !== "string" || !grant || !Number.isFinite(Date.parse(value.expires_at))) throw new Error("Invalid grant response");
  }
  if (value.status === "verify_mailbox" && (typeof value.challenge_id !== "string" || !Number.isFinite(Date.parse(value.expires_at)) || !Number.isFinite(Date.parse(value.resend_at)))) throw new Error("Invalid mailbox response");
  return value;
}
export const modernAuthApi = {
  async methods(): Promise<Methods> {
    const result = await request<Methods>("/auth/methods?client=web");
    if (![result.password, result.google, result.apple, result.email].every(value => typeof value === "boolean")) throw new Error("Invalid methods response");
    return result;
  },
  requestEmail: (body: EmailRequest) => request<Challenge>("/auth/email/request", body),
  resendEmail: (body: { challenge_id: string; client_verifier: string }) => request<Challenge>("/auth/email/resend", body),
  verifyEmail: async (body: EmailVerify) => completion(await request<Completion>("/auth/email/verify", body)),
  resetPassword: (body: { reset_grant: string; client_verifier: string; new_password: string }) => request<void>("/auth/recovery/reset", body),
  confirmPassword: (body: { current_password: string; action: AuthAction; expected_account_id: string }) => request<RecentProof>("/auth/confirm/password", body),
  startProvider: (provider: Provider, body: ProviderStart) => request<ProviderStarted>(`/auth/providers/${provider}/start`, body),
  completeProvider: async (body: ProviderComplete) => completion(await request<Completion>("/auth/providers/complete", body)),
  accountMethods: () => request<AccountMethods>("/account/auth-methods"),
  unlink: (provider: Provider, body: AccountAction) => request<{ methods: AccountMethods; signed_out: boolean }>(`/account/auth-methods/${provider}/unlink`, body),
  setPassword: (body: AccountAction & { new_password: string }) => request<void>("/account/auth-password", body),
  deleteAccount: (body: AccountAction) => request<AccountDeleteResponse>("/account/auth-delete", body),
  async exportAccount(body: AccountAction): Promise<string> {
    const response = await send("/account/auth-export", body);
    const blob = await response.blob();
    const filename = parseAttachmentFilename(response.headers.get("Content-Disposition")).replace(/[/\\]/g, "_");
    const url = URL.createObjectURL(blob);
    try {
      const anchor = document.createElement("a"); anchor.href = url; anchor.download = filename;
      document.body.appendChild(anchor); anchor.click(); anchor.remove();
    } finally { URL.revokeObjectURL(url); }
    return filename;
  }
};
