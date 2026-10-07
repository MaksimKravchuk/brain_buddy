import { QueryClient } from "@tanstack/react-query";

import { bindAdminSession } from "./api/adminHooks";
import { bindRelaySession } from "./api/relaySession";
import { bindTaskAgentPreferenceSession } from "./features/tasks/taskAgentPreference";
import { bindCrtLastTreePreferenceSession } from "./features/crt/crtLastTreePreference";
import { bindReviewLocalState } from "./features/review/reviewFormDrafts";
import { startFlagRefresh } from "./stores/authStore";

/** The application's sole process-global cache, bound to auth before React renders. */
export const queryClient = new QueryClient();

bindRelaySession(queryClient);
bindAdminSession(queryClient);
bindTaskAgentPreferenceSession();
bindCrtLastTreePreferenceSession();
// 020-FR-052: the weekly review's browser-local keys (drafts, the
// While-you-were-away day, the last zone) are swept and cleared on sign-out
// whatever the `weekly_review` flag says and whether or not the shell is mounted.
bindReviewLocalState();
// 010-FR-009: an already-open session re-reads its flags on a bounded 15-second
// interval. Wired here rather than in `main.tsx` for the same reason as
// `bindAdminSession` above — `main.tsx` never executes under Vitest, so the
// subscription would otherwise be production-only and untested.
startFlagRefresh();
