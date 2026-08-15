import { QueryClient } from "@tanstack/react-query";

import { bindAdminSession } from "./api/adminHooks";
import { bindRelaySession } from "./api/relaySession";
import { startFlagRefresh } from "./stores/authStore";

/** The application's sole process-global cache, bound to auth before React renders. */
export const queryClient = new QueryClient();

bindRelaySession(queryClient);
bindAdminSession(queryClient);
// 010-FR-009: an already-open session re-reads its flags on a bounded 15-second
// interval. Wired here rather than in `main.tsx` for the same reason as
// `bindAdminSession` above — `main.tsx` never executes under Vitest, so the
// subscription would otherwise be production-only and untested.
startFlagRefresh();
