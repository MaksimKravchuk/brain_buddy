/**
 * The /review route (FR-042): nothing here asks the review API unless
 * `weekly_review` is effective for the signed-in account; the entry or the
 * running review follows once the review state has loaded.
 */
import { useState } from "react";
import { Navigate } from "react-router-dom";

import { describeReviewError } from "../../api/review";
import type { ReviewSession } from "../../api/review";
import { useReviewState, useWeeklyReviewEnabled } from "../../api/reviewHooks";
import { ShellToastProvider } from "../../components/shell/AppShell";
import { ReviewEntry } from "./ReviewEntry";
import { ReviewFrame, ReviewShell } from "./ReviewShell";
import { Ref } from "./steps/stepParts";

function ReviewRoute(): React.JSX.Element {
  const query = useReviewState();
  const [run, setRun] = useState<ReviewSession | null>(null);

  if (query.data === undefined) {
    const referenceId = query.isError ? describeReviewError(query.error).referenceId : undefined;
    return (
      <ReviewFrame title="Weekly review">
        <main className="flex justify-center px-5 py-6 md:px-10">
          <div className="flex w-full max-w-[600px] flex-col gap-3.5">
            {query.isError && !query.isFetching ? (
              <div role="alert" className="flex flex-wrap items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
                <span>We couldn&apos;t load your review. Your progress is safe.</span>
                <Ref id={referenceId} />
                <button type="button" className="min-h-11 rounded-lg px-3 font-semibold hover:bg-amber-100" onClick={() => void query.refetch()}>
                  Retry
                </button>
              </div>
            ) : (
              <p role="status" aria-label="Checking for a review in progress…" aria-busy="true" className="m-0 text-sm text-slate-500">
                Checking for a review in progress…
              </p>
            )}
          </div>
        </main>
      </ReviewFrame>
    );
  }

  return run ? (
    <ReviewShell initial={run} state={query.data} onExit={() => setRun(null)} />
  ) : (
    <ReviewEntry state={query.data} onStart={setRun} />
  );
}

export function ReviewGate(): React.JSX.Element {
  if (!useWeeklyReviewEnabled()) {
    return <Navigate to="/" replace />;
  }
  return (
    <ShellToastProvider>
      <ReviewRoute />
    </ShellToastProvider>
  );
}
