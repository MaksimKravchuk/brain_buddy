/**
 * The browser-local drafts of one review step's text fields (FR-052), bound to
 * the account that opened the step: the same scope and 7-day expiry as the
 * decision dialog's. Once the session has switched account the step writes and
 * removes nothing, because the departing account's keys are being cleared
 * (`bindReviewLocalState`) and the next account's must never receive its text.
 */
import { useState } from "react";

import type { AuthUser } from "../../api/auth";
import { getApiBaseUrl } from "../../api/client";
import type { StepCode } from "../../api/review";
import { useAuthStore } from "../../stores/authStore";
import { loadStepDraft, removeStepDraft, removeStepDrafts, saveStepDraft } from "./reviewFormDrafts";

export interface ReviewDrafts {
  /** The draft of one item's field, or `null`. */
  load: (itemId: string, field: string) => string | null;
  /** Keep what was typed; text equal to `initial` (nothing worth keeping) removes the draft. */
  save: (itemId: string, field: string, text: string, initial?: string) => void;
  /** The field was saved or discarded. */
  clear: (itemId: string, field: string) => void;
  /** Every field of this step was discarded. */
  clearAll: () => void;
}

export function useReviewDrafts(sessionId: string, step: StepCode): ReviewDrafts {
  // The review is only reachable signed in with the flag on (FR-042).
  const [scope] = useState(() => ({ apiOrigin: getApiBaseUrl(), accountId: (useAuthStore.getState().user as AuthUser).id }));
  const owns = () => useAuthStore.getState().user?.id === scope.accountId;
  const at = (itemId: string, field: string) => ({ sessionId, step, itemId, field });
  return {
    load: (itemId, field) => loadStepDraft(scope, at(itemId, field)),
    save: (itemId, field, text, initial = "") => {
      if (owns()) {
        saveStepDraft(scope, at(itemId, field), text === initial ? "" : text);
      }
    },
    clear: (itemId, field) => {
      if (owns()) {
        removeStepDraft(scope, at(itemId, field));
      }
    },
    clearAll: () => {
      if (owns()) {
        removeStepDrafts(scope, sessionId, step);
      }
    }
  };
}
