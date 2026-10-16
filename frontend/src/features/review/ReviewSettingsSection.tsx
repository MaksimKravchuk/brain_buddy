/**
 * D-04 — the "Weekly review" section of the account settings page (web).
 *
 * This slice carries the threshold only (FR-039): "Ask for a decision after"
 * 7, 14, 21 or 28 days, saved on change with the floor note, a failed save
 * keeping the old value with its Ref and Retry (FR-045), offline disabled.
 * Day, time, "Last review" and the cloud-consent switch come with later
 * slices. `ThresholdControl` is shared with the D-05 explainer.
 */
import { useEffect, useId, useRef, useState } from "react";

import { describeReviewError, newIdempotencyKey, THRESHOLD_OPTIONS, type ThresholdDays } from "../../api/review";
import { beginReviewContinuation, useOnlineStatus, useReviewState, useUpdateReviewSettings, useWeeklyReviewEnabled } from "../../api/reviewHooks";
import { SectionCard } from "../../components/ui/SettingsSection";
import { formatReviewDate } from "./formulation";

export function ThresholdControl({
  value,
  onChange,
  disabled
}: {
  value: ThresholdDays;
  onChange: (value: ThresholdDays) => void;
  disabled: boolean;
}): React.JSX.Element {
  const labelId = useId();
  const name = useId();
  return (
    <div className="flex flex-col gap-2 text-co-meta sm:flex-row sm:items-center sm:gap-4">
      <span id={labelId} className="text-ink-muted">Ask for a decision after</span>
      <div role="radiogroup" aria-labelledby={labelId} className="inline-flex flex-wrap gap-1.5">
        {THRESHOLD_OPTIONS.map((days) => (
          <label key={days} className="inline-flex min-h-11 cursor-pointer items-center">
            <input
              type="radio"
              name={name}
              value={days}
              checked={value === days}
              disabled={disabled}
              className="peer sr-only"
              onChange={() => onChange(days)}
            />
            <span className="rounded-control bg-quiet px-3 py-1.5 text-co-meta text-ink peer-checked:bg-ink peer-checked:font-semibold peer-checked:text-ground peer-focus-visible:shadow-ring-focus peer-disabled:opacity-60">
              {days} days
            </span>
          </label>
        ))}
      </div>
    </div>
  );
}

const COPY = {
  description: "Tasks move to Someday 7 days after they start asking.",
  offline: "You're offline. Changes can't be saved. Retry when you're back online.",
  loadFailed: "We couldn't load your review settings."
} as const;

export function ReviewSettingsSection(): React.JSX.Element | null {
  const enabled = useWeeklyReviewEnabled();
  const stateQuery = useReviewState();
  const update = useUpdateReviewSettings();
  const online = useOnlineStatus();
  const [note, setNote] = useState<string | null>(null);
  const [failure, setFailure] = useState<{ referenceId: string | undefined } | null>(null);
  const attempt = useRef<{ threshold: ThresholdDays; revision: number; key: string } | null>(null);
  const [slow, setSlow] = useState(false);
  const loading = stateQuery.isPending;

  // Loading placeholders appear only after 300 ms, and are static (design).
  useEffect(() => {
    if (!loading) {
      return;
    }
    const id = window.setTimeout(() => setSlow(true), 300);
    return () => window.clearTimeout(id);
  }, [loading]);

  if (!enabled) {
    return null;
  }

  const save = (threshold: ThresholdDays, revision: number) => {
    const previous = attempt.current;
    // The same change against the same revision reuses its key (a safe replay).
    const key = previous?.threshold === threshold && previous.revision === revision ? previous.key : newIdempotencyKey();
    attempt.current = { threshold, revision, key };
    setNote(null);
    setFailure(null);
    const run = beginReviewContinuation();
    update.mutate(
      { body: { threshold_days: threshold, expected_revision: revision }, idempotencyKey: key },
      {
        onSuccess: (saved) => {
          if (!run.stillCurrent()) return;
          attempt.current = null;
          setNote(
            `Saved. Markers in Next update now. Because of this change, nothing moves to Someday before ${formatReviewDate(saved.owner_park_floor_at as string)}.`
          );
        },
        onError: (error) => {
          if (!run.stillCurrent()) return;
          setFailure({ referenceId: describeReviewError(error).referenceId });
          void stateQuery.refetch();
        }
      }
    );
  };

  let body: React.JSX.Element;
  if (stateQuery.isError) {
    const loadReference = describeReviewError(stateQuery.error).referenceId;
    body = (
      <div role="alert" className="flex flex-wrap items-center gap-2 rounded-card bg-quiet px-3 py-2 text-co-meta text-warning">
        <span>{COPY.loadFailed}</span>
        {loadReference ? <span className="text-co-meta">Ref {loadReference}</span> : null}
        <button type="button" className="min-h-11 rounded-control px-3 font-semibold text-ink hover:bg-quiet-pressed" onClick={() => void stateQuery.refetch()}>
          Retry
        </button>
      </div>
    );
  } else if (stateQuery.data) {
    const settings = stateQuery.data.settings;
    const shown = update.isPending ? update.variables.body.threshold_days as ThresholdDays : settings.threshold_days;
    body = (
      <div className="flex flex-col gap-3">
        <ThresholdControl value={shown} disabled={!online || update.isPending} onChange={(days) => save(days, settings.revision)} />
        {!online ? <p role="status" className="m-0 text-co-meta text-ink-muted">{COPY.offline}</p> : null}
        {note ? <p role="status" className="m-0 text-co-meta text-ink">{note}</p> : null}
        {failure ? (
          <div role="alert" className="flex flex-wrap items-center gap-2 rounded-card bg-quiet px-3 py-2 text-co-meta text-warning">
            <span>{`Your new threshold couldn't be saved. It's still ${settings.threshold_days} days.`}</span>
            {failure.referenceId ? <span className="text-co-meta">Ref {failure.referenceId}</span> : null}
            <button
              type="button"
              className="min-h-11 rounded-control px-3 font-semibold text-ink hover:bg-quiet-pressed"
              onClick={() => save((attempt.current as { threshold: ThresholdDays }).threshold, settings.revision)}
            >
              Retry
            </button>
          </div>
        ) : null}
      </div>
    );
  } else {
    body = slow ? <div data-testid="review-settings-placeholder" aria-hidden className="h-11 w-2/3 rounded-card bg-quiet" /> : <div />;
  }

  return (
    <SectionCard title="Weekly review" description={COPY.description}>
      {body}
    </SectionCard>
  );
}
