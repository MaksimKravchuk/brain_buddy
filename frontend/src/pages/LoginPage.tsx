import { Link, Navigate, useLocation } from "react-router-dom";
import { Sprout } from "lucide-react";
import { useAuthStore } from "../stores/authStore";
import { AuthEntry } from "../features/auth/AuthEntry";
import { safeAuthDestination } from "../features/auth/authFlow";

export default function LoginPage(): React.JSX.Element {
  const status = useAuthStore(state => state.status);
  const user = useAuthStore(state => state.user);
  const deletionScheduledFor = useAuthStore(state => state.deletionScheduledFor);
  const location = useLocation();
  const state = location.state as { from?: { pathname?: string; search?: string }; deletionScheduled?: string; authNotice?: string } | null;
  const destination = safeAuthDestination(state?.from ? `${state.from.pathname ?? "/"}${state.from.search ?? ""}` : "/");
  const expected = new URL(destination, "https://brainbuddy.invalid").searchParams.get("expected_owner");
  const deletionScheduled = state?.deletionScheduled ?? deletionScheduledFor;
  if (status === "authed" && (!expected || user?.id === expected)) return <Navigate to={destination} replace />;
  return <AuthLayout title="Sign in or create an account">
    {expected ? <p role="status" className="mb-4 text-sm text-slate-700">Use the account linked to this device before continuing.</p> : null}
    {state?.authNotice ? <p role="status" className="mb-4 text-sm text-slate-700">{state.authNotice}</p> : null}
    {deletionScheduled ? <p role="status" className="mb-4 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">Your account is deactivated and will be permanently deleted on {new Date(deletionScheduled).toLocaleDateString()}. Sign back in before then to cancel the deletion. Apple cleanup may still be pending or unconfirmed; your deletion date is unchanged.</p> : null}
    <AuthEntry destination={destination} />
    <p className="mt-4 text-center text-xs text-slate-500">Have a password and invite code? <Link to="/signup?invite=1" className="inline-flex min-h-11 items-center text-sky-700 underline">Create an account with an invite</Link></p>
  </AuthLayout>;
}
export function AuthLayout({ title, children }: { title: string; children: React.ReactNode }): React.JSX.Element {
  return <main className="flex min-h-screen items-center justify-center bg-surface-base px-4 py-8"><div className="w-full max-w-sm rounded-2xl border border-slate-200 bg-surface-raised p-7 shadow-raised"><div className="mb-3 flex items-center justify-center gap-2 text-subtitle font-semibold text-slate-900"><Sprout className="h-5 w-5 text-brand-primary" aria-hidden="true" /><span>Brain Buddy</span></div><h1 className="mb-5 text-center text-title font-semibold text-slate-900">{title}</h1>{children}<p className="mt-4 text-center text-xs text-slate-500"><Link to="/privacy" className="inline-flex min-h-11 items-center text-sky-700 underline focus-visible:outline-2 focus-visible:outline-sky-700">Privacy policy</Link></p></div></main>;
}
