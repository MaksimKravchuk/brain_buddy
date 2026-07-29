import { useParams } from "react-router-dom";

import { hasFeatureFlag } from "../../api/auth";
import { useAuthStore } from "../../stores/authStore";
import { BrainDumpPrivacyControls } from "./BrainDumpPrivacyControls";
import { BrainDumpRoute } from "./BrainDumpRoute";

// Rollout gate for the voice brain dump. New capture is only reachable when the
// server-issued `voice_brain_dump` feature flag (from GET /api/auth/me) is true,
// keeping the default-OFF rollout reversible by flipping the flag server-side
// (no client deploy).
//
// The flag gates *new capture*, not the owner's standing rights over an
// operation they already started: the backend keeps read/status, consent
// withdrawal, raw-audio deletion, and cancel reachable with the flag OFF
// (US2 scenario 4). So when OFF we still surface a capture-free privacy-controls
// screen for any existing operation the URL references — the only operation
// reference the client recovers across reloads. Only when there is no such
// operation do we fall back to the friendly "off" notice.
export function BrainDumpGate(): JSX.Element {
  const user = useAuthStore((state) => state.user);
  const params = useParams();
  const hasKnownOperation = Boolean(params.operationId) && params.operationId !== "new";

  if (hasFeatureFlag(user, "voice_brain_dump")) {
    return <BrainDumpRoute />;
  }

  if (hasKnownOperation) {
    return <BrainDumpPrivacyControls />;
  }

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
