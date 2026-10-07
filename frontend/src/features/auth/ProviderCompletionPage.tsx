import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { modernAuthApi, type Challenge } from "../../api/modernAuth";
import { AuthLayout } from "../../pages/LoginPage";
import { AuthEntry } from "./AuthEntry";
import { useAuthStore } from "../../stores/authStore";
import { acceptSignedIn, assertActingOwner, rememberConfirmation, safeAuthDestination, takeProviderCallback, type PendingProvider } from "./authFlow";

async function waitForSessionHydration(): Promise<void> {
  if (useAuthStore.getState().status !== "loading") return;
  await new Promise<void>((resolve, reject) => {
    const timeout = window.setTimeout(() => { unsubscribe(); reject(new Error("Session lookup timed out")); }, 10_000);
    const settled = () => {
      if (useAuthStore.getState().status === "loading") return;
      window.clearTimeout(timeout); unsubscribe(); resolve();
    };
    const unsubscribe = useAuthStore.subscribe(settled);
    // App may supersede this lookup; wait for the store's settled state.
    void useAuthStore.getState().hydrate().then(settled, () => { window.clearTimeout(timeout); unsubscribe(); reject(new Error("Session lookup failed")); });
  });
}

export function ProviderCompletionPage(): React.JSX.Element {
  const started = useRef(false);
  const navigate = useNavigate();
  const [message, setMessage] = useState("Completing sign-in…");
  const [failed, setFailed] = useState(false);
  const [destination, setDestination] = useState("/login");
  const [mailbox, setMailbox] = useState<{ challenge: Challenge; verifier: string } | null>(null);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    let pending: PendingProvider | undefined;
    void (async () => {
      const parsed = takeProviderCallback(); pending = parsed.pending;
      if (pending.expectedOwner) await waitForSessionHydration();
      if (pending.expectedOwner) assertActingOwner(pending.expectedOwner);
      const result = await modernAuthApi.completeProvider(parsed.request);
      if (pending.expectedOwner) assertActingOwner(pending.expectedOwner);
      if (result.status === "signed_in" && pending.purpose === "login") {
        await acceptSignedIn(result); navigate(safeAuthDestination(pending.destination), { replace: true });
      } else if (result.status === "verify_mailbox" && pending.purpose === "login") {
        setDestination(safeAuthDestination(pending.destination)); setMailbox({ challenge: result, verifier: parsed.request.client_verifier });
      } else if (result.status === "existing_account_required") {
        setMessage("Connect to your existing account. Sign in first, then connect this method from Settings. Matching emails don't merge accounts."); setDestination("/login"); setFailed(true);
      } else if (result.status === "linked" && pending.purpose === "link" && result.user.id === pending.expectedOwner) {
        navigate(safeAuthDestination(pending.destination), { replace: true });
      } else if (result.status === "reauthenticated" && pending.purpose === "reauth" && pending.expectedOwner && pending.action) {
        rememberConfirmation(pending.expectedOwner, pending.action, result); navigate(safeAuthDestination(pending.destination), { replace: true });
      } else throw new Error("Wrong authentication outcome");
    })().catch(() => {
      setMessage(pending?.purpose === "link" ? "We couldn't confirm whether linking finished. Reconnect and check your sign-in methods. Start a fresh link only if needed." : "We couldn't confirm whether this finished. Sign in again with a fresh proof if needed.");
      setDestination(pending?.expectedOwner ? `/settings/account?expected_owner=${encodeURIComponent(pending.expectedOwner)}` : "/login"); setFailed(true);
    });
  }, [navigate]);
  return <AuthLayout title={mailbox ? "Check your email" : "Complete sign-in"}>{mailbox ? <AuthEntry destination={destination} initialCode={mailbox} /> : <><p role={failed ? "alert" : "status"}>{message}</p>{failed ? <Link className="mt-4 inline-flex min-h-11 items-center text-sky-700 underline" to={destination}>{destination.startsWith("/settings/account") ? "Check your sign-in methods" : "Back to sign in"}</Link> : null}</>}</AuthLayout>;
}
