import { hasFeatureFlag } from "../../api/auth";
import { useAuthStore } from "../../stores/authStore";
import { BrainDumpRoute } from "./BrainDumpRoute";

// Rollout gate for the voice brain dump. The route is only reachable when the
// server-issued `voice_brain_dump` feature flag (from GET /api/auth/me) is true.
// Discovery, capture, and every downstream command stay unreachable while the
// flag is OFF or absent, keeping the default-OFF rollout reversible by simply
// flipping the flag server-side (no client deploy). A friendly, non-interactive
// note is shown instead so a stale entry link never dead-ends the user.
export function BrainDumpGate(): JSX.Element {
  const user = useAuthStore((state) => state.user);
  if (!hasFeatureFlag(user, "voice_brain_dump")) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-surface-base px-6 text-center">
        <section className="rounded-2xl border border-slate-200 bg-white px-8 py-10 shadow-raised">
          <p className="text-xs font-semibold uppercase tracking-[0.06em] text-brand-primary">Not available yet</p>
          <h1 className="mt-2 text-title font-semibold text-slate-900">Voice brain dump is off</h1>
          <p className="mt-2 max-w-md text-sm text-slate-600">
            This workspace does not have voice brain dump enabled yet. It will appear here once it is turned on for your account.
          </p>
        </section>
      </main>
    );
  }
  return <BrainDumpRoute />;
}
