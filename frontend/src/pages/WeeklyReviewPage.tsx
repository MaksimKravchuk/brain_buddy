import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  Clock,
  Edit3,
  FileText,
  ListChecks,
  RotateCcw,
  Trash2,
  TrendingUp
} from "lucide-react";

import type {
  CaptureItemResponse,
  ReviewOutcomeAction,
  WeeklyReviewDetailResponse
} from "../api/vnext-types";
import {
  useCompleteWeeklyReview,
  useRecordReviewOutcome,
  useStartWeeklyReview
} from "../api/vnext-hooks";
import { Button } from "../components/ui/Button";
import { useUiStore } from "../stores/uiStore";
import { getErrorMessage } from "../utils/error";

const OUTCOME_LABELS: Record<ReviewOutcomeAction, string> = {
  keep: "Keep",
  edit: "Edit",
  delete: "Delete",
  defer: "Defer",
  route: "Route",
  promote_to_crt: "Promote to CRT"
};

const OUTCOME_ICONS: Record<ReviewOutcomeAction, JSX.Element> = {
  keep: <Check className="h-4 w-4" />,
  edit: <Edit3 className="h-4 w-4" />,
  delete: <Trash2 className="h-4 w-4" />,
  defer: <Clock className="h-4 w-4" />,
  route: <TrendingUp className="h-4 w-4" />,
  promote_to_crt: <TrendingUp className="h-4 w-4" />
};

export default function WeeklyReviewPage(): JSX.Element {
  const [review, setReview] = useState<WeeklyReviewDetailResponse | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editText, setEditText] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  const pushToast = useUiStore((state) => state.pushToast);

  const startReview = useStartWeeklyReview();
  const recordOutcome = useRecordReviewOutcome();
  const completeReview = useCompleteWeeklyReview();

  useEffect(() => {
    if (startReview.isIdle) {
      setIsLoading(true);
      startReview.mutate(undefined, {
        onSuccess: (data) => {
          setReview(data);
          setIsLoading(false);
        },
        onError: (error) => {
          pushToast({
            title: "Failed to start review",
            description: getErrorMessage(error),
            variant: "error",
            duration: 6000
          });
          setIsLoading(false);
        }
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const outcomesByCapture = useMemo(() => {
    const map = new Map<string, ReviewOutcomeAction>();
    if (!review) return map;
    for (const o of review.outcomes) {
      map.set(o.atomic_capture_id, o.action);
    }
    return map;
  }, [review]);

  const allDecided = review
    ? review.review.item_ids.every((id) => outcomesByCapture.has(id))
    : false;

  const handleOutcome = (
    capture: CaptureItemResponse,
    action: ReviewOutcomeAction
  ) => {
    if (!review) return;
    if (action === "edit") {
      setEditingId(capture.id);
      setEditText(capture.current_text);
      return;
    }
    recordOutcome.mutate(
      { reviewId: review.review.id, captureId: capture.id, payload: { action } },
      {
        onSuccess: (data) => {
          setReview((prev) => {
            if (!prev) return prev;
            const filtered = prev.outcomes.filter(
              (o) => o.atomic_capture_id !== capture.id
            );
            return {
              ...prev,
              outcomes: [
                ...filtered,
                {
                  id: data.id,
                  atomic_capture_id: data.atomic_capture_id,
                  action: data.action,
                  reason: data.reason ?? null,
                  avoidance_reason: data.avoidance_reason ?? null,
                  decided_at: data.decided_at
                }
              ]
            };
          });
        },
        onError: (error) => {
          pushToast({
            title: "Failed to record outcome",
            description: getErrorMessage(error),
            variant: "error",
            duration: 6000
          });
        }
      }
    );
  };

  const handleEditSubmit = (captureId: string) => {
    if (!review) return;
    recordOutcome.mutate(
      {
        reviewId: review.review.id,
        captureId,
        payload: { action: "edit", new_text: editText }
      },
      {
        onSuccess: (data) => {
          setReview((prev) => {
            if (!prev) return prev;
            const filtered = prev.outcomes.filter(
              (o) => o.atomic_capture_id !== captureId
            );
            const updatedItems = prev.items.map((item) =>
              item.id === captureId
                ? { ...item, current_text: editText, review_state: "approved" as const }
                : item
            );
            return {
              ...prev,
              items: updatedItems,
              outcomes: [
                ...filtered,
                {
                  id: data.id,
                  atomic_capture_id: data.atomic_capture_id,
                  action: data.action,
                  reason: data.reason ?? null,
                  avoidance_reason: data.avoidance_reason ?? null,
                  decided_at: data.decided_at
                }
              ]
            };
          });
          setEditingId(null);
          setEditText("");
        }
      }
    );
  };

  const handleComplete = () => {
    if (!review) return;
    completeReview.mutate(review.review.id, {
      onSuccess: (summary) => {
        pushToast({
          title: "Weekly Review completed",
          description: `${summary.kept + summary.edited} kept, ${summary.deferred} deferred, ${summary.deleted} deleted, ${summary.promoted} promoted`,
          variant: "success",
          duration: 6000
        });
        setReview((prev) =>
          prev
            ? {
                ...prev,
                review: { ...prev.review, status: "completed" }
              }
            : prev
        );
      },
      onError: (error) => {
        pushToast({
          title: "Cannot complete review",
          description: getErrorMessage(error),
          variant: "error",
          duration: 6000
        });
      }
    });
  };

  if (isLoading && !review) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-surface-base">
        <div className="flex items-center gap-3 text-sm text-slate-500">
          <ListChecks className="h-5 w-5 animate-pulse text-brand-primary" />
          <span>Loading Weekly Review...</span>
        </div>
      </div>
    );
  }

  if (!review) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-surface-base">
        <div className="flex max-w-md flex-col items-center gap-4 text-center">
          <AlertTriangle className="h-10 w-10 text-amber-500" />
          <p className="text-sm text-slate-600">
            Could not load the Weekly Review. Try again later.
          </p>
        </div>
      </div>
    );
  }

  const isCompleted = review.review.status === "completed";

  return (
    <div className="min-h-screen bg-surface-base text-slate-900">
      <header className="border-b border-slate-200 bg-surface-raised px-6 py-4">
        <div className="mx-auto max-w-4xl">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-xl font-semibold">Weekly Review</h1>
              <p className="mt-1 text-sm text-slate-500">
                {review.items.length} item(s) to review ·{" "}
                {review.outcomes.length} decided
              </p>
            </div>
            {isCompleted ? (
              <div className="flex items-center gap-2 text-sm text-emerald-600">
                <CheckCircle2 className="h-5 w-5" />
                <span>Completed</span>
              </div>
            ) : (
              <Button
                variant="primary"
                size="md"
                leftIcon={<CheckCircle2 className="h-4 w-4" />}
                onClick={handleComplete}
                isLoading={completeReview.isPending}
                disabled={!allDecided}
              >
                Complete Review
              </Button>
            )}
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-4xl px-6 py-6">
        {!allDecided && !isCompleted && (
          <div className="mb-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
            Each item needs a decision before you can complete the review.
          </div>
        )}

        {review.items.length === 0 ? (
          <div className="flex flex-col items-center gap-4 py-16 text-center">
            <FileText className="h-12 w-12 text-slate-300" />
            <div>
              <p className="text-display font-semibold text-slate-900">
                No items to review
              </p>
              <p className="mt-1 text-sm text-slate-500">
                Capture some thoughts first, then come back for your Weekly Review.
              </p>
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            {review.items.map((item) => {
              const outcome = outcomesByCapture.get(item.id);
              return (
                <ReviewItemCard
                  key={item.id}
                  item={item}
                  outcome={outcome}
                  isEditing={editingId === item.id}
                  editText={editText}
                  onEditTextChange={setEditText}
                  onOutcome={(action) => handleOutcome(item, action)}
                  onSubmitEdit={() => handleEditSubmit(item.id)}
                  onCancelEdit={() => {
                    setEditingId(null);
                    setEditText("");
                  }}
                  disabled={isCompleted || recordOutcome.isPending}
                />
              );
            })}
          </div>
        )}
      </main>
    </div>
  );
}

function ReviewItemCard({
  item,
  outcome,
  isEditing,
  editText,
  onEditTextChange,
  onOutcome,
  onSubmitEdit,
  onCancelEdit,
  disabled
}: {
  item: CaptureItemResponse;
  outcome?: ReviewOutcomeAction;
  isEditing: boolean;
  editText: string;
  onEditTextChange: (text: string) => void;
  onOutcome: (action: ReviewOutcomeAction) => void;
  onSubmitEdit: () => void;
  onCancelEdit: () => void;
  disabled: boolean;
}): JSX.Element {
  const kindColors: Record<string, string> = {
    task: "bg-blue-50 text-blue-700",
    note: "bg-slate-50 text-slate-700",
    question: "bg-purple-50 text-purple-700",
    problem_candidate: "bg-orange-50 text-orange-700"
  };

  return (
    <div
      className={`rounded-xl border bg-surface-raised p-4 shadow-soft transition ${
        outcome ? "border-emerald-200" : "border-slate-200"
      }`}
    >
      <div className="flex items-start gap-3">
        <div className="flex-1">
          {isEditing ? (
            <textarea
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-brand-primary focus:outline-none"
              value={editText}
              onChange={(e) => onEditTextChange(e.target.value)}
              rows={2}
            />
          ) : (
            <p className="text-sm text-slate-900">{item.current_text}</p>
          )}
          <div className="mt-2 flex items-center gap-2">
            <span
              className={`rounded px-2 py-0.5 text-xs font-medium ${kindColors[item.kind] ?? kindColors.note}`}
            >
              {item.kind}
            </span>
            {outcome && (
              <span className="flex items-center gap-1 rounded bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700">
                {OUTCOME_ICONS[outcome]}
                {OUTCOME_LABELS[outcome]}
              </span>
            )}
          </div>
        </div>
      </div>

      {!isEditing && !outcome && !disabled && (
        <div className="mt-3 flex flex-wrap gap-2">
          <Button
            variant="secondary"
            size="sm"
            leftIcon={<Check className="h-3.5 w-3.5" />}
            onClick={() => onOutcome("keep")}
          >
            Keep
          </Button>
          <Button
            variant="secondary"
            size="sm"
            leftIcon={<Edit3 className="h-3.5 w-3.5" />}
            onClick={() => onOutcome("edit")}
          >
            Edit
          </Button>
          <Button
            variant="secondary"
            size="sm"
            leftIcon={<Clock className="h-3.5 w-3.5" />}
            onClick={() => onOutcome("defer")}
          >
            Defer
          </Button>
          <Button
            variant="secondary"
            size="sm"
            leftIcon={<Trash2 className="h-3.5 w-3.5" />}
            onClick={() => onOutcome("delete")}
          >
            Delete
          </Button>
          <Button
            variant="secondary"
            size="sm"
            leftIcon={<TrendingUp className="h-3.5 w-3.5" />}
            onClick={() => onOutcome("promote_to_crt")}
          >
            Promote to CRT
          </Button>
        </div>
      )}

      {isEditing && (
        <div className="mt-3 flex gap-2">
          <Button
            variant="primary"
            size="sm"
            leftIcon={<Check className="h-3.5 w-3.5" />}
            onClick={onSubmitEdit}
            isLoading={false}
          >
            Save
          </Button>
          <Button
            variant="secondary"
            size="sm"
            leftIcon={<RotateCcw className="h-3.5 w-3.5" />}
            onClick={onCancelEdit}
          >
            Cancel
          </Button>
        </div>
      )}
    </div>
  );
}
