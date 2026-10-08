/**
 * The /review entry (design D-03, M-11): in the order of "Entry order of the
 * review" the auto-park explainer, onboarding, While you were away and restart
 * mode come first; then the resume card for a review open on any device, the
 * Quick / Full picker, and the last counted review, which is how a review
 * finished on the iPhone becomes visible here (SC-007).
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { newIdempotencyKey, reviewApi } from "../../api/review";
import type { LastCountedReview, ReviewMode, ReviewSession, ReviewState, SessionStartRequest } from "../../api/review";
import { getReviewCacheScope, reviewKeys } from "../../api/reviewHooks";
import type { AuthUser } from "../../api/auth";
import { useAuthStore } from "../../stores/authStore";
import { AutoParkExplainer } from "./AutoParkExplainer";
import { formatReviewDate, formatReviewTime } from "./formulation";
import { decisionCount, lastReviewText } from "./lastReview";
import { OnboardingDialog } from "./OnboardingDialog";
import { ReviewFrame } from "./ReviewShell";
import { RestartStep } from "./steps/RestartStep";
import { buttonClass, CountsGrid, FailureBanner, primaryButtonClass } from "./steps/stepParts";
import { useStepAction } from "./steps/useStepAction";
import { useLeaveGuard } from "./useLeaveGuard";
import { WhileYouWereAway } from "./WhileYouWereAway";
import { localDay } from "./wywaPresentation";

const DAY_MS = 86_400_000;
const ORIGINS = { ios: "iPhone", web: "the web", macos: "Mac" } as const;
const MODES: ReadonlyArray<{ mode: ReviewMode; label: string; time: string; about: string }> = [
  { mode: "quick", label: "Quick", time: "about 5 min", about: "Wins of the week, Inbox, tasks that ask for a decision, summary." },
  { mode: "full", label: "Full", time: "about 20 min", about: "Get clear, get current, get creative: wins, mind sweep, Inbox, decisions, the rest of Next, Waiting, projects, Someday, upcoming dates, summary." }
];

function startedText(session: ReviewSession): string {
  const day = localDay(new Date(session.started_at)) === localDay() ? "today" : formatReviewDate(session.started_at);
  return `${day} at ${formatReviewTime(session.started_at)}`;
}

export function ReviewEntry({ state, onStart }: { state: ReviewState; onStart: (session: ReviewSession) => void }): React.JSX.Element {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const accountId = useAuthStore((store) => (store.user as AuthUser).id);
  const action = useStepAction();
  const [explainerDone, setExplainerDone] = useState(false);
  const [onboardingClosed, setOnboardingClosed] = useState(false);
  const [awayDone, setAwayDone] = useState(false);
  const [restartDone, setRestartDone] = useState(false);
  // A restart release or its Undo on its way holds Close, so its answer, failure and Undo stay on screen (FR-048).
  const [restartSettling, setRestartSettling] = useState(false);
  const closeRef = useRef<HTMLButtonElement>(null);

  const open = state.open_session;
  const last = state.last_counted_review;
  const overlay =
    !state.explainer_seen && !explainerDone
      ? "explainer"
      : state.settings.onboarded_at === null && !onboardingClosed
        ? "onboarding"
        : state.unseen_parks.length > 0 && !awayDone
          ? "away"
          : null;

  // A partial review may have been closed by the 7-day idle rule; its end and last activity tell.
  const closedCandidate = open === null && last?.status === "partial" ? last : null;
  const closedQuery = useQuery({
    queryKey: ["review-closed", getReviewCacheScope(accountId), closedCandidate?.session_id],
    queryFn: ({ signal }) => reviewApi.getSession((closedCandidate as LastCountedReview).session_id, signal),
    enabled: closedCandidate !== null,
    retry: false,
    staleTime: Infinity
  });
  const closed = closedQuery.data;
  const closedAfterAWeek =
    closed !== undefined &&
    closed.ended_at !== null &&
    Date.parse(closed.ended_at) - Date.parse(closed.last_activity_at) >= 7 * DAY_MS &&
    Date.parse(state.server_now) - Date.parse(closed.ended_at) < 14 * DAY_MS;

  const start = (mode: ReviewMode) => {
    const body: SessionStartRequest = { mode, entry: state.restart_mode ? "restart" : "sidebar", origin: "web", replace_open: open !== null };
    const key = newIdempotencyKey();
    void action.run(
      mode,
      mode,
      async () => {
        try {
          onStart(await reviewApi.startSession(body, key));
        } finally {
          // The state shows the new review, or the open one another device started meanwhile.
          void queryClient.invalidateQueries({ queryKey: reviewKeys.all });
        }
      },
      "Couldn't start the review."
    );
  };

  const showRestart = state.restart_mode && !restartDone;
  const restartHolds = showRestart && restartSettling;

  // While a restart release or its Undo is on its way, browser Back goes nowhere (the entry is put back),
  // in-app links are not followed, and a tab close or reload gets the browser's warning (FR-048).
  const guard = useLeaveGuard({
    dirty: restartHolds,
    active: restartHolds,
    onBack: () => guard.rearm(),
    onNavigate: () => undefined
  });
  const stepCodes = open ? Object.keys(open.steps) : [];

  return (
    <ReviewFrame
      title="Weekly review"
      recap={lastReviewText(state)}
      actions={
        <button
          ref={closeRef}
          type="button"
          disabled={restartHolds}
          className={`${buttonClass} border-transparent bg-transparent text-sky-700`}
          onClick={() => navigate("/tasks/next")}
        >
          Close
        </button>
      }
    >
      <main className="flex justify-center px-5 py-6 md:px-10">
        <div className="flex w-full max-w-[600px] flex-col gap-3.5">
          {showRestart ? (
            <RestartStep state={state} onContinue={() => setRestartDone(true)} onSettlingChange={setRestartSettling} />
          ) : (
            <>
              <h1 className="m-0 text-2xl font-semibold text-slate-900">{open ? "Pick up where you left off?" : "How much time do you have?"}</h1>
              {closedAfterAWeek ? (
                <p className="m-0 text-sm text-slate-600">{`Your review from ${formatReviewDate((closed as ReviewSession).started_at)} was closed after a week without activity. Its ${decisionCount((closed as ReviewSession).counts)} decisions are kept.`}</p>
              ) : null}
              {open ? (
                <>
                  <div className="flex items-center gap-4 rounded-[14px] border-[1.5px] border-sky-500 bg-sky-50 p-4">
                    <div className="flex flex-1 flex-col">
                      <b className="text-[15px] text-slate-900">{`${open.mode === "quick" ? "Quick" : "Full"} review · step ${stepCodes.indexOf(open.current_step as string) + 1} of ${stepCodes.length}`}</b>
                      <span className="text-sm text-slate-700">{`Started ${startedText(open)} on ${ORIGINS[open.origin]}. ${decisionCount(open.counts)} decisions made so far.`}</span>
                    </div>
                    <button type="button" className={primaryButtonClass} onClick={() => onStart(open)}>
                      Continue
                    </button>
                  </div>
                  <p className="m-0 mt-2 text-[10px] font-semibold uppercase tracking-[0.06em] text-slate-500">Or start a new one</p>
                </>
              ) : null}
              {action.failure ? <FailureBanner failure={action.failure} online={action.online} /> : null}
              {MODES.map(({ mode, label, time, about }) => (
                <button
                  key={mode}
                  type="button"
                  disabled={action.disabled}
                  className="flex w-full flex-col gap-1.5 rounded-[14px] border border-slate-200 bg-white p-4 text-left hover:border-slate-300 hover:shadow-raised disabled:opacity-60"
                  onClick={() => start(mode)}
                >
                  <span className="flex items-baseline justify-between text-[17px] font-semibold text-slate-900">
                    {action.pending === mode ? "Starting…" : label}
                    <span className="text-[13px] font-medium text-slate-500">{time}</span>
                  </span>
                  <span className="text-[13px] leading-relaxed text-slate-600">{about}</span>
                </button>
              ))}
              <p className="m-0 text-xs text-slate-500">Skip any step. Stop any time; what you&apos;ve done is kept and you can continue on any device.</p>
              {last && open === null ? (
                <section aria-label="Last review" className="flex flex-col gap-2 rounded-xl border border-slate-200 bg-white p-4">
                  <p className="m-0 text-xs font-semibold text-slate-600">{`Last review${last.ended_at ? ` · ${formatReviewDate(last.ended_at)}` : ""} · on ${ORIGINS[last.origin]}`}</p>
                  <CountsGrid counts={last.counts} label="Last review counts" />
                  {last.clear_start ? <p className="m-0 text-xs text-slate-600">{`Clear start: ${last.clear_start === "yes" ? "Yes" : "Not really"}`}</p> : null}
                </section>
              ) : null}
            </>
          )}
        </div>
      </main>
      {overlay === "explainer" ? <AutoParkExplainer state={state} onDone={() => setExplainerDone(true)} /> : null}
      {overlay === "onboarding" ? (
        <OnboardingDialog
          state={state}
          onClose={(saved) => {
            setOnboardingClosed(true);
            if (!saved) {
              closeRef.current?.focus();
            }
          }}
        />
      ) : null}
      {overlay === "away" ? <WhileYouWereAway parks={state.unseen_parks} onDone={() => setAwayDone(true)} /> : null}
    </ReviewFrame>
  );
}
