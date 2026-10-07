/**
 * D-05 — the one-time auto-park explainer at the first web open (FR-051).
 *
 * The M-26 content as a modal dialog: the threshold rule, that an undecided
 * task moves to Someday 7 days later and comes back in one click, that this
 * is the only thing the app moves on its own (FR-018), and the date before
 * which nothing already in Next moves (FR-016). "Got it", Close and Escape
 * all record it as seen with the browser's time zone; offline nothing can be
 * recorded, so Close leaves it for the next open. Never shown once seen.
 */
import { useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";
import { useId, useLayoutEffect, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";

import { describeReviewError, newIdempotencyKey, type ReviewSettings, type ReviewState, type ThresholdDays } from "../../api/review";
import { reviewKeys, useAcknowledgeExplainer, useOnlineStatus, useReviewClock, useUpdateReviewSettings } from "../../api/reviewHooks";
import { formatReviewDate } from "./formulation";
import { ThresholdControl } from "./ReviewSettingsSection";

const DAY_MS = 86_400_000;
const focusableSelector = 'button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function AutoParkExplainer({
  state,
  onDone,
  timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone
}: {
  state: ReviewState;
  /** The dialog is finished (recorded, or closed offline). */
  onDone: () => void;
  /** The browser's IANA zone, sent with the acknowledgement (http §5). */
  timeZone?: string;
}): React.JSX.Element | null {
  const headingId = useId();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const sectionRef = useRef<HTMLElement>(null);
  const queryClient = useQueryClient();
  const online = useOnlineStatus();
  const now = useReviewClock();
  const acknowledgeMutation = useAcknowledgeExplainer();
  const settingsMutation = useUpdateReviewSettings();
  const [threshold, setThreshold] = useState<ThresholdDays>(state.settings.threshold_days);
  const [changing, setChanging] = useState(false);
  const [failure, setFailure] = useState<{ referenceId: string | undefined } | null>(null);
  // A retried acknowledgement resends the same request under the same key (a safe replay).
  const [acknowledgeKey] = useState(newIdempotencyKey);
  // A settings attempt is keyed by its threshold and the revision it was sent
  // against, as in D-04: the same change replays its key, any other gets a new one.
  const settingsAttempt = useRef<{ threshold: ThresholdDays; revision: number; key: string } | null>(null);
  // What the last successful PUT returned, until the review state catches up.
  const savedSettings = useRef<ReviewSettings | null>(null);

  useLayoutEffect(() => {
    headingRef.current?.focus();
  }, []);

  if (state.explainer_seen) {
    return null;
  }

  const pending = acknowledgeMutation.isPending || settingsMutation.isPending;

  /** The settings as the server last told us: a saved PUT wins until the state query has caught up. */
  const serverSettings = (): ReviewSettings => {
    const saved = savedSettings.current;
    return saved !== null && saved.revision > state.settings.revision ? saved : state.settings;
  };

  const saveThreshold = async (): Promise<void> => {
    const server = serverSettings();
    if (threshold === server.threshold_days) {
      return;
    }
    const previous = settingsAttempt.current;
    const key = previous?.threshold === threshold && previous.revision === server.revision ? previous.key : newIdempotencyKey();
    settingsAttempt.current = { threshold, revision: server.revision, key };
    try {
      savedSettings.current = await settingsMutation.mutateAsync({
        body: { threshold_days: threshold, expected_revision: server.revision },
        idempotencyKey: key
      });
      settingsAttempt.current = null;
    } catch (error) {
      // A refused change (changed elsewhere, or anything else) re-reads the
      // state, so Retry is sent against the current revision.
      void queryClient.invalidateQueries({ queryKey: reviewKeys.state() });
      throw error;
    }
  };

  const record = async () => {
    setFailure(null);
    try {
      await saveThreshold();
      await acknowledgeMutation.mutateAsync({ timeZone, idempotencyKey: acknowledgeKey });
      onDone();
    } catch (error) {
      setFailure({ referenceId: describeReviewError(error).referenceId });
    }
  };

  /** Close and Escape: seen when it can be recorded, otherwise shown again next time. */
  const dismiss = () => {
    if (pending) {
      return;
    }
    if (online) {
      void record();
    } else {
      onDone();
    }
  };

  const onKeyDown = (event: ReactKeyboardEvent<HTMLElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      dismiss();
      return;
    }
    if (event.key !== "Tab") {
      return;
    }
    const focusable = Array.from((sectionRef.current as HTMLElement).querySelectorAll<HTMLElement>(focusableSelector));
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const active = document.activeElement as HTMLElement;
    if (event.shiftKey && (active === first || !focusable.includes(active))) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
  };

  const graceUntil = state.grace_until ?? new Date(now.getTime() + 14 * DAY_MS).toISOString();
  const floor = formatReviewDate(new Date(now.getTime() + 7 * DAY_MS).toISOString());

  return (
    <div className="fixed inset-0 z-[150] flex items-stretch justify-center bg-slate-50/80 backdrop-blur-xs sm:items-center sm:p-6">
      <section
        ref={sectionRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={headingId}
        onKeyDown={onKeyDown}
        className="relative flex h-full w-full flex-col overflow-y-auto bg-white shadow-floating sm:h-auto sm:max-h-[calc(100vh-48px)] sm:w-[480px] sm:rounded-[20px] sm:border sm:border-slate-200"
      >
        <header className="flex items-start gap-3 px-5 pb-2 pt-5">
          <h2 id={headingId} ref={headingRef} tabIndex={-1} className="m-0 flex-1 text-[20px] font-semibold leading-[1.3] text-slate-900 outline-hidden">
            How Next stays fresh
          </h2>
          <button
            type="button"
            aria-label="Close"
            disabled={pending}
            className="-mr-1.5 -mt-1 inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-slate-500 hover:bg-surface-sunken hover:text-slate-900"
            onClick={dismiss}
          >
            <X className="h-4 w-4" aria-hidden />
          </button>
        </header>
        <div className="flex flex-col gap-3 px-5 pb-5 text-sm leading-relaxed text-slate-700">
          <p className="m-0">
            <strong className="font-semibold text-slate-900">When a task stalls.</strong>{" "}
            {`If a next action keeps the same wording for ${threshold} days, it asks for a decision.`}
          </p>
          <p className="m-0">
            <strong className="font-semibold text-slate-900">If it stays undecided.</strong>{" "}
            7 days later it moves to Someday / maybe. Nothing is deleted, and you can bring it back in one click. It&apos;s the only thing the app moves on its own.
          </p>
          <p className="m-0">
            <strong className="font-semibold text-slate-900">Your tasks get time.</strong>{" "}
            {`Tasks already in Next won't move before ${formatReviewDate(graceUntil)}.`}
          </p>
          {changing ? (
            <div className="flex flex-col gap-2 rounded-xl border border-slate-200 p-3">
              <ThresholdControl
                value={threshold}
                disabled={pending}
                onChange={setThreshold}
              />
              {threshold !== state.settings.threshold_days ? (
                <p className="m-0 text-xs text-slate-600">
                  {`Markers in Next update now. Because of this change, nothing moves to Someday before ${floor}.`}
                </p>
              ) : null}
            </div>
          ) : null}
          {!online ? <p role="status" className="m-0 rounded-lg bg-slate-50 px-3 py-2 text-slate-700">You&apos;re offline. Try again when you&apos;re back online.</p> : null}
          {failure ? (
            <div role="alert" className="flex flex-wrap items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-amber-900">
              <span>Couldn&apos;t save that you&apos;ve seen this. Try again.</span>
              {failure.referenceId ? <span className="text-xs">Ref {failure.referenceId}</span> : null}
              <button type="button" className="min-h-11 rounded-lg px-3 font-semibold hover:bg-amber-100" onClick={() => void record()}>
                Retry
              </button>
            </div>
          ) : null}
          <div className="mt-1 flex flex-wrap justify-end gap-2">
            {changing ? null : (
              <button
                type="button"
                className="min-h-11 rounded-lg border border-slate-200 px-4 font-medium text-slate-700 hover:border-slate-300"
                onClick={() => setChanging(true)}
              >
                Change the number of days
              </button>
            )}
            <button
              type="button"
              disabled={!online || pending}
              className="min-h-11 rounded-lg bg-sky-700 px-5 font-semibold text-white hover:bg-sky-800 disabled:opacity-50"
              onClick={() => void record()}
            >
              Got it
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}
