/**
 * M-12 / D-03 onboarding on the web (FR-016, FR-035): why the review exists,
 * the stall rule and auto-park with the grace date, and the review day, time
 * and threshold. Continue saves them with `onboarded: true` and the browser's
 * zone; Escape and Close save nothing, so it comes back next time.
 */
import { useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";

import { describeReviewError, newIdempotencyKey, reviewApi, THRESHOLD_OPTIONS } from "../../api/review";
import type { ReviewSettingsUpdate, ReviewState, ThresholdDays } from "../../api/review";
import { refreshAfterReviewWrite, reviewKeys, settleForAccount, useOnlineStatus } from "../../api/reviewHooks";
import { trapTab } from "./focusTrap";
import { Ref } from "./steps/stepParts";
import { formatReviewDate } from "./formulation";

const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const HOURS = Array.from({ length: 24 }, (_, hour) => `${String(hour).padStart(2, "0")}:00`);
const selectClass = "min-h-11 rounded-lg border border-slate-300 bg-white px-3 text-base text-slate-900 sm:text-sm";

export function OnboardingDialog({
  state,
  onClose,
  timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone
}: {
  state: ReviewState;
  /** `true` once the settings were saved; `false` after Escape or Close (nothing saved). */
  onClose: (saved: boolean) => void;
  /** The browser's IANA zone, saved with the settings (FR-035). */
  timeZone?: string;
}): React.JSX.Element {
  const headingId = useId();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const sectionRef = useRef<HTMLElement>(null);
  const queryClient = useQueryClient();
  const online = useOnlineStatus();
  const [day, setDay] = useState(state.settings.review_weekday);
  const [time, setTime] = useState(state.settings.review_time);
  const [threshold, setThreshold] = useState<ThresholdDays>(state.settings.threshold_days);
  const [pending, setPending] = useState(false);
  const [failure, setFailure] = useState<{ referenceId: string | undefined } | null>(null);
  // The same request replays its key; any other gets a new one.
  const attempt = useRef<{ body: string; key: string } | null>(null);

  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  const times = HOURS.includes(time) ? HOURS : [...HOURS, time].sort();

  const save = async () => {
    const body: ReviewSettingsUpdate = {
      onboarded: true,
      threshold_days: threshold,
      review_weekday: day,
      review_time: time,
      time_zone: timeZone,
      expected_revision: state.settings.revision
    };
    const sent = JSON.stringify(body);
    if (attempt.current?.body !== sent) {
      attempt.current = { body: sent, key: newIdempotencyKey() };
    }
    const key = attempt.current.key;
    setPending(true);
    setFailure(null);
    const settled = await settleForAccount(() => reviewApi.updateSettings(body, key));
    if (settled === null) {
      return;
    }
    setPending(false);
    if (!settled.ok) {
      // A stale revision is the likely cause: read the state again before Retry.
      refreshAfterReviewWrite(queryClient, settled.scope);
      setFailure({ referenceId: describeReviewError(settled.error).referenceId });
      return;
    }
    queryClient.setQueryData<ReviewState>(reviewKeys.state(settled.scope), (current) => current && { ...current, settings: settled.value });
    refreshAfterReviewWrite(queryClient, settled.scope);
    onClose(true);
  };

  const onKeyDown = (event: ReactKeyboardEvent<HTMLElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      onClose(false);
    } else if (event.key === "Tab") {
      trapTab(event, sectionRef.current as HTMLElement);
    }
  };

  return (
    <div className="fixed inset-0 z-[150] flex items-stretch justify-center bg-slate-50/80 backdrop-blur-xs sm:items-center sm:p-6">
      <section
        ref={sectionRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={headingId}
        onKeyDown={onKeyDown}
        className="relative flex h-full w-full flex-col gap-3 overflow-y-auto bg-white p-5 shadow-floating sm:h-auto sm:max-h-[calc(100vh-48px)] sm:w-[560px] sm:rounded-[20px] sm:border sm:border-slate-200"
      >
        <div className="flex items-start gap-3">
          <h2 id={headingId} ref={headingRef} tabIndex={-1} className="m-0 flex-1 text-[20px] font-semibold leading-[1.3] text-slate-900 outline-hidden">
            A weekly reset
          </h2>
          <button type="button" aria-label="Close" className="-mr-1.5 -mt-1 inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-slate-500 hover:bg-surface-sunken hover:text-slate-900" onClick={() => onClose(false)}>
            <X className="h-4 w-4" aria-hidden />
          </button>
        </div>
        <p className="m-0 text-sm leading-relaxed text-slate-600">
          <b className="text-slate-900">Why.</b> Once a week: see what you got done, empty your head, and choose what&apos;s next.
        </p>
        <p className="m-0 text-sm leading-relaxed text-slate-600">
          <b className="text-slate-900">When a task stalls.</b> {`If a next action keeps the same wording for ${threshold} days, it asks for a decision. A stall is feedback on the wording, not on you.`}
        </p>
        <p className="m-0 text-sm leading-relaxed text-slate-600">
          <b className="text-slate-900">If it stays undecided.</b> 7 days later it moves to Someday / maybe. You&apos;ll see what moved and can bring it back in one click.
        </p>
        <p className="m-0 text-sm leading-relaxed text-slate-600">
          {`It's the only thing the app moves on its own.${state.grace_until ? ` Tasks you had when you first saw this rule won't move before ${formatReviewDate(state.grace_until)}.` : ""}`}
        </p>
        <div className="flex flex-wrap items-center gap-3 text-sm text-slate-700">
          <label className="flex items-center gap-2">
            Day
            <select className={selectClass} value={day} onChange={(event) => setDay(Number(event.currentTarget.value))}>
              {WEEKDAYS.map((name, index) => (
                <option key={name} value={index + 1}>{name}</option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-2">
            Time
            <select className={selectClass} value={time} onChange={(event) => setTime(event.currentTarget.value)}>
              {times.map((hour) => (
                <option key={hour} value={hour}>{hour}</option>
              ))}
            </select>
          </label>
        </div>
        <div className="flex flex-wrap items-center gap-3 text-sm text-slate-700">
          <span id={`${headingId}-threshold`}>Ask for a decision after</span>
          <div role="radiogroup" aria-labelledby={`${headingId}-threshold`} className="inline-flex gap-1 rounded-lg bg-slate-100 p-[3px]">
            {THRESHOLD_OPTIONS.map((option) => (
              <button
                key={option}
                type="button"
                role="radio"
                aria-checked={threshold === option}
                className={`min-h-11 rounded-md px-3 text-[13px] ${threshold === option ? "bg-white font-semibold text-slate-900 shadow-soft" : "font-medium text-slate-600"}`}
                onClick={() => setThreshold(option)}
              >
                {`${option} days`}
              </button>
            ))}
          </div>
        </div>
        <p className="m-0 text-xs text-slate-500">
          Times are in your local time zone. The web doesn&apos;t send reminders; the sidebar shows when your last review was. If you use the iPhone app, it sends one reminder on your review day.
        </p>
        {!online ? <p role="status" className="m-0 rounded-lg bg-slate-50 px-3 py-2 text-sm text-slate-700">You&apos;re offline. Try again when you&apos;re back online.</p> : null}
        {failure ? (
          <div role="alert" className="flex flex-wrap items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
            <span>Your review settings couldn&apos;t be saved.</span>
            <Ref id={failure.referenceId} />
            <button type="button" disabled={!online || pending} className="min-h-11 rounded-lg px-3 font-semibold hover:bg-amber-100 disabled:opacity-60" onClick={() => void save()}>
              Retry
            </button>
          </div>
        ) : null}
        <div className="flex justify-end">
          <button type="button" disabled={!online || pending} className="min-h-11 rounded-lg bg-sky-700 px-5 text-sm font-semibold text-white hover:bg-sky-800 disabled:opacity-60" onClick={() => void save()}>
            {pending ? "Saving…" : "Continue"}
          </button>
        </div>
      </section>
    </div>
  );
}
