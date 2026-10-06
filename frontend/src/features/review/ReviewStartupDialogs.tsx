/**
 * What the weekly review shows at web open (design "Entry order"): first the
 * one-time auto-park explainer D-05 while it has not been seen on any device
 * (FR-051), then "While you were away" when unseen parks exist, at most once
 * per local day (FR-015). Mounted by the shell only while `weekly_review` is
 * effective (FR-042). It also owns the browser-local review keys: the
 * startup/focus draft sweep and the sign-out cleanup (FR-052, data-model E11).
 */
import { useEffect, useState } from "react";

import type { AuthUser } from "../../api/auth";
import { getApiBaseUrl } from "../../api/client";
import type { UnseenPark } from "../../api/review";
import { useReviewState } from "../../api/reviewHooks";
import { useAuthStore } from "../../stores/authStore";
import { AutoParkExplainer } from "./AutoParkExplainer";
import { subscribeReviewLocalCleanup, sweepReviewDrafts } from "./reviewFormDrafts";
import { WhileYouWereAway } from "./WhileYouWereAway";
import { localDay, markWhileAwayShown, readWhileAwayLastShown, shouldShowWhileAway } from "./wywaPresentation";

/** Accounts whose explainer was closed without being recorded: shown again at the next web open. */
const explainerLaterThisOpen = new Set<string>();

/** Both dialogs hand focus back to the page's main heading when they close. */
function focusMainHeading(): void {
  const heading = document.querySelector<HTMLElement>("main h1");
  if (heading === null) {
    return;
  }
  if (!heading.hasAttribute("tabindex")) {
    heading.setAttribute("tabindex", "-1");
  }
  heading.focus();
}

export function ReviewStartupDialogs(): React.JSX.Element | null {
  const accountId = useAuthStore((state) => (state.user as AuthUser).id);
  const stateQuery = useReviewState();
  const [explainerLater, setExplainerLater] = useState(() => explainerLaterThisOpen.has(accountId));
  const [whileAway, setWhileAway] = useState<{ accountId: string; parks: UnseenPark[] | null } | null>(null);
  const state = stateQuery.data;

  useEffect(() => {
    const sweep = () => sweepReviewDrafts({ apiOrigin: getApiBaseUrl(), accountId });
    sweep();
    window.addEventListener("focus", sweep);
    const stopCleanup = subscribeReviewLocalCleanup();
    return () => {
      window.removeEventListener("focus", sweep);
      stopCleanup();
    };
  }, [accountId]);

  useEffect(() => {
    if (whileAway?.parks) {
      markWhileAwayShown({ apiOrigin: getApiBaseUrl(), accountId: whileAway.accountId }, localDay());
    }
  }, [whileAway]);

  if (!state) {
    return null;
  }

  if (!state.explainer_seen) {
    return explainerLater ? null : (
      <AutoParkExplainer
        state={state}
        onDone={() => {
          // Recorded: the state now says seen. Closed offline: not again this open.
          explainerLaterThisOpen.add(accountId);
          setExplainerLater(true);
          focusMainHeading();
        }}
      />
    );
  }

  // Decided once per account and web open, from the state as it first arrives.
  if (whileAway?.accountId !== accountId) {
    const show = shouldShowWhileAway({
      context: "app_open",
      hasUnseen: state.unseen_parks.length > 0,
      lastShownDay: readWhileAwayLastShown({ apiOrigin: getApiBaseUrl(), accountId }),
      today: localDay()
    });
    setWhileAway({ accountId, parks: show ? state.unseen_parks : null });
    return null;
  }

  return whileAway.parks ? (
    <WhileYouWereAway
      parks={whileAway.parks}
      onDone={() => {
        setWhileAway({ accountId, parks: null });
        focusMainHeading();
      }}
    />
  ) : null;
}
