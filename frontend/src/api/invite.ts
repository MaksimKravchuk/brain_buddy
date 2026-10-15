import type { Completion } from "./modernAuth";
import { ApiError, getApiBaseUrl } from "./client";

/** 027 contracts/invite-handoff.md: the 403 detail for an identity with no account yet. */
export interface InviteRequired { pending: string; expiresIn: number }

export function inviteRequired(error: unknown): InviteRequired | null {
  if (!(error instanceof ApiError) || error.status !== 403) return null;
  const detail = (error.payload as { detail?: { code?: unknown; pending?: unknown; expires_in?: unknown } } | null)?.detail;
  if (detail?.code !== "INVITE_REQUIRED" || typeof detail.pending !== "string" || !detail.pending) return null;
  return { pending: detail.pending, expiresIn: typeof detail.expires_in === "number" ? detail.expires_in : 600 };
}

function retryAfterMs(header: string | null): number | undefined {
  const seconds = header === null ? NaN : Number(header);
  return Number.isFinite(seconds) && seconds >= 0 ? seconds * 1000 : undefined;
}

/** Resubmits the pending handoff with the invite code; creates the account only if the code is valid. */
export async function signupComplete(body: { pending: string; invite_code: string }): Promise<Completion> {
  const response = await fetch(`${getApiBaseUrl()}/auth/signup/complete`, {
    method: "POST", credentials: "include", cache: "no-store",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  if (!response.ok) {
    let payload: unknown = null;
    try { payload = await response.json(); } catch { /* only the status and reference are shown */ }
    throw new ApiError("Invite request failed", response.status, payload, response.headers.get("X-Correlation-ID") ?? undefined, retryAfterMs(response.headers.get("Retry-After")));
  }
  const result = await response.json() as Completion;
  if (result?.status !== "signed_in" || typeof result.user?.id !== "string") throw new Error("Invalid authentication response");
  return result;
}
