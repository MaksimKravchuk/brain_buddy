import { Link, Navigate, useLocation } from "react-router-dom";
import { useState } from "react";
import { CarryOnMark } from "../components/brand/CarryOnMark";
import { useAuthStore } from "../stores/authStore";
import { AuthEntry } from "../features/auth/AuthEntry";
import { ensureAnonymousSignIn, safeAuthDestination } from "../features/auth/authFlow";
import { useAuthOperation } from "../features/auth/authOperation";
import { Button } from "../components/ui/Button";

export default function LoginPage(): React.JSX.Element {
  const session = useAuthStore();
  const { status, user, deletionScheduledFor } = session;
  const [confirmedSession, setConfirmedSession] = useState<typeof session | null>(null);
  const switchAccount = useAuthOperation();
  const location = useLocation();
  const state = location.state as { from?: { pathname?: string; search?: string }; deletionScheduled?: string; authNotice?: string } | null;
  const destination = safeAuthDestination(state?.from ? `${state.from.pathname ?? "/"}${state.from.search ?? ""}` : "/");
  const expected = new URL(destination, "https://brainbuddy.invalid").searchParams.get("expected_owner");
  const deletionScheduled = state?.deletionScheduled ?? deletionScheduledFor;
  const beforeSignIn = async () => {
    try {
      if (useAuthStore.getState() !== confirmedSession) throw new Error("Session changed");
      await ensureAnonymousSignIn();
      if (useAuthStore.getState() !== confirmedSession) throw new Error("Session changed");
    } catch (caught) {
      setConfirmedSession(null);
      switchAccount.setError("Your browser session changed or couldn't be checked. Sign out again before using the linked account.");
      throw caught;
    }
  };
  if (status === "authed" && (!expected || user?.id === expected)) return <Navigate to={destination} replace />;
  return <AuthLayout title="Sign in or create an account" lede="Your lists are on every device you sign in on.">
    {expected ? <p role="status" className="mb-4 text-co-meta text-ink-muted">Use the account linked to this device before continuing.</p> : null}
    {state?.authNotice ? <p role="status" className="mb-4 text-co-meta text-ink-muted">{state.authNotice}</p> : null}
    {deletionScheduled ? <p role="status" className="mb-4 rounded-card bg-card px-3 py-2 text-co-meta text-warning">Your account is deactivated and will be permanently deleted on {new Date(deletionScheduled).toLocaleDateString()}. Sign back in before then to cancel the deletion. Apple cleanup may still be pending or unconfirmed; your deletion date is unchanged.</p> : null}
    {expected && status === "loading" ? <p role="status">Checking your current account…</p> : expected && (status !== "anon" || confirmedSession !== session || switchAccount.busy || switchAccount.error) ? <div className="flex flex-col gap-4">
      <p className="text-co-meta text-ink-muted">First sign out of this browser before using the account linked to your device.</p>
      {switchAccount.error ? <p role="alert" className="text-co-meta text-danger">{switchAccount.error}</p> : null}
      <Button className="min-h-11" disabled={switchAccount.busy} onClick={() => void switchAccount.run(async () => {
        if (useAuthStore.getState() !== session) throw new Error("Session changed");
        if (!(await session.logout({ requireServerConfirmation: true }))) throw new Error("Sign-out was not completed");
        const confirmed = useAuthStore.getState();
        if (confirmed.status !== "anon") throw new Error("Session changed");
        setConfirmedSession(confirmed);
      }, "Couldn't confirm sign-out. Try again before signing in to the linked account.")}>Sign out and use linked account</Button>
    </div> : <>
      <AuthEntry destination={destination} beforeSignIn={expected ? beforeSignIn : undefined} />
      <p className="mt-4 text-center text-co-meta text-ink-muted">Have a password and invite code? <Link to="/signup?invite=1" className="inline-flex min-h-11 items-center text-ink underline focus-visible:outline-2 focus-visible:outline-focus">Create an account with an invite</Link></p>
    </>}
  </AuthLayout>;
}
export function AuthLayout({ title, lede, children }: { title: string; lede?: string; children: React.ReactNode }): React.JSX.Element {
  return <main className="min-h-screen bg-ground px-6 py-8 text-ink">
    <div className="flex items-center gap-2 font-voice text-xl text-ink"><CarryOnMark className="h-[26px] w-[26px] text-ink" /><span>Carry On</span></div>
    <div className="mx-auto mt-12 w-full max-w-[420px] rounded-card co-glass-dense p-6 sm:mt-16">
      <h1 className="font-voice text-2xl text-ink">{title}</h1>
      {lede ? <p className="mt-1 mb-4 text-co-meta text-ink-muted">{lede}</p> : <div className="mb-4" />}
      {children}
      <p className="mt-2 text-center text-co-meta text-ink-muted"><Link to="/privacy" className="inline-flex min-h-11 items-center underline focus-visible:outline-2 focus-visible:outline-focus">Privacy policy</Link></p>
    </div>
  </main>;
}
