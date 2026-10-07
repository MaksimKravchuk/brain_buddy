import { useRef, useState } from "react";
import { ApiError } from "../../api/client";

export function authError(error: unknown, fallback = "Couldn't complete this request. Try again or use another method."): string {
  if (error instanceof ApiError) {
    if (error.status === 429) return "Too many attempts. Try again in a few minutes, or use another method.";
    if (error.status === 404) return "Use the account linked to this action. Sign in again before continuing.";
    const payload = error.payload as { detail?: { code?: string } } | null;
    if (payload?.detail?.code === "last_method") return "Add another way to sign in before removing this one.";
    if (error.status === 409) return "Couldn't update this method. Check your sign-in methods before trying again.";
    return fallback + (error.correlationId ? ` Reference: ${error.correlationId}` : "");
  }
  return fallback;
}
export function useAuthOperation() {
  const locked = useRef(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async (operation: () => Promise<void>, fallback?: string) => {
    if (locked.current) return;
    locked.current = true; setBusy(true); setError(null);
    try { await operation(); } catch (caught) { setError(authError(caught, fallback)); }
    finally { locked.current = false; setBusy(false); }
  };
  return { busy, error, setError, run };
}
