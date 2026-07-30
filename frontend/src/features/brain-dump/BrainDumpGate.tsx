import { useParams } from "react-router-dom";

import { hasFeatureFlag } from "../../api/auth";
import { useAuthStore } from "../../stores/authStore";
import { BrainDumpOverlay, BrainDumpOverlayHeader } from "./BrainDumpOverlay";
import { useCloseBrainDump } from "./brainDumpNavigation";
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
  const closeOverlay = useCloseBrainDump();
  const hasKnownOperation = Boolean(params.operationId) && params.operationId !== "new";

  if (hasFeatureFlag(user, "voice_brain_dump")) {
    return <BrainDumpRoute />;
  }

  if (hasKnownOperation) {
    return <BrainDumpPrivacyControls />;
  }

  return (
    <BrainDumpOverlay labelledBy="brain-dump-off-title" onClose={closeOverlay} size="narrow">
      <BrainDumpOverlayHeader
        titleId="brain-dump-off-title"
        eyebrow="Not available yet"
        title="Voice brain dump is off"
        onClose={closeOverlay}
      />
      <p className="px-5 py-4 text-sm text-slate-600 sm:px-6">
        This workspace does not have voice brain dump enabled yet. It will appear here once it is turned on for your account.
      </p>
    </BrainDumpOverlay>
  );
}
