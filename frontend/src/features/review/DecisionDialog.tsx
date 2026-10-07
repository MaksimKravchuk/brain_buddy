/**
 * D-02 — the decision dialog on the web (no navigator yet; that is PR-10).
 *
 * One task, one decision (FR-006): seven decisions in a fixed order with their
 * key numerals, an optional stall reason that recommends without restricting
 * (FR-007), the third-stall offer (FR-005), stale, refusal and failure states
 * with the Ref (FR-011, FR-045), offline disabled (FR-040), an Undo toast
 * after every applied decision (FR-048), and no silently discarded text
 * (FR-052: drafts, the leave warning, the Back and link guard).
 */
import { useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";
import { Archive, CircleHelp, X } from "lucide-react";
import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import { Link, useNavigate } from "react-router-dom";

import { hasFeatureFlag, type AuthUser } from "../../api/auth";
import { apiClient, getApiBaseUrl } from "../../api/client";
import { describeReviewError, isDecisionAlreadyUndone, newIdempotencyKey, reviewApi, withReference } from "../../api/review";
import type { DecisionRequest, DecisionResponse, DecisionType } from "../../api/review";
import {
  applyReviewTask,
  captureReviewScope,
  isCurrentReviewScope,
  refreshAfterReviewWrite,
  useDecideTask,
  useOnlineStatus,
  useReviewClock
} from "../../api/reviewHooks";
import type { TaskFormulationResponse, TaskResponse, TaskState } from "../../api/taskTypes";
import { useShellToast, type ShellNotify } from "../../components/shell/shellToast";
import { useAuthStore } from "../../stores/authStore";
import {
  classifyFromInstants,
  daysInNext,
  formatReviewDate,
  formulationInstants,
  isSubstantiveChange,
  isThirdStall,
  listMarkerFor
} from "./formulation";
import {
  loadReviewDraft,
  removeOtherFormulationDrafts,
  removeReviewDraft,
  saveReviewDraft,
  type DraftForm,
  type ReviewDraftTarget
} from "./reviewFormDrafts";
import { recommendedDecision, STALL_REASONS, type StallReason } from "./stallRecommendation";
import { useLeaveGuard } from "./useLeaveGuard";

export type DecisionOutcome = { kind: "closed" } | { kind: "decided"; task: TaskResponse; leftNext: boolean };

type CardDecision = "complete" | "reformulate" | "first_step" | "waiting" | "someday" | "cancel" | "extend";

const DECISIONS: ReadonlyArray<{ type: CardDecision; label: string; sub?: string }> = [
  { type: "complete", label: "Done" },
  { type: "reformulate", label: "Reformulate", sub: "Say what you'll actually do" },
  { type: "first_step", label: "Find a first step", sub: "Something you could start in 10 minutes" },
  { type: "waiting", label: "Move to Waiting for…" },
  { type: "someday", label: "Release to Someday", sub: "Not now. Bring it back any time" },
  { type: "cancel", label: "Cancel task", sub: "Stays findable under Cancelled" },
  { type: "extend", label: "Keep 7 more days", sub: "Once, with a reason" }
];

/** Decisions taken on the current formulation (http §3): they carry its id. */
const ON_FORMULATION: ReadonlySet<DecisionType> = new Set<DecisionType>(["reformulate", "first_step", "waiting", "someday", "extend"]);

/** What Undo reverts, for its accessible name "Undo: <what> <title>". */
const UNDO_NAMES: Readonly<Record<CardDecision, string>> = {
  complete: "Marked done",
  reformulate: "Reworded",
  first_step: "First step for",
  waiting: "Moved to Waiting for",
  someday: "Released to Someday",
  cancel: "Cancelled",
  extend: "Kept 7 more days"
};

const LIST_NAMES: Readonly<Record<TaskState, string>> = {
  inbox: "Inbox",
  next: "Next actions",
  waiting: "Waiting for",
  someday: "Someday / maybe",
  completed: "Completed",
  cancelled: "Cancelled"
};

const FORMS: Readonly<Record<DraftForm, {
  prompt: string;
  field: string;
  placeholder?: string;
  help?: string;
}>> = {
  reformulate: { prompt: "What will you actually do?", field: "New wording", help: "Name a visible action. A new wording starts a fresh clock." },
  first_step: { prompt: "What's the very first thing you'd do?", field: "First step", placeholder: "Something you could start in 10 minutes" },
  waiting: { prompt: "Who or what are you waiting for?", field: "Waiting for", help: "It moves to Waiting for. The review checks in on it after 7 days." },
  extend: { prompt: "Why does this wording still fit?", field: "Reason, required", placeholder: "One line is enough" }
};

const DAY_MS = 86_400_000;
const COPY = {
  framing: "This wording hasn't moved. That usually means the wording needs work, not you.",
  thirdStall: "This is the third wording in a row that has stalled. Sometimes the task isn't the problem. It may help to set it aside, or to look at what's underneath.",
  extensionUsed: "You've already kept this wording 7 more days once.",
  offline: "You're offline. Decisions need a connection on the web.",
  saveFailed: "Couldn't save your decision. Nothing was changed.",
  notAllowed: "This decision isn't available for this task's current list. Nothing was changed.",
  detailsTooLong: "The notes would be too long with the old title added. Shorten the notes, then try again. Nothing was changed.",
  staleHeading: "Task changed elsewhere",
  staleBody: "Nothing was applied. Here's the current version. Decide again if it still needs it.",
  noLongerAsks: "This task no longer asks for a decision. You can close the card.",
  cosmetic: "Only capitals or punctuation changed, so this is still the same wording and the clock keeps running.",
  discardTitle: "Discard your new wording?",
  discardBody: "It hasn't been saved.",
  draftBack: "Your unsaved text is back.",
  reasonNeeded: "Add a reason to continue"
} as const;

const NOT_ALLOWED: ReadonlySet<string> = new Set(["decision_not_allowed", "extension_already_used", "extension_not_due", "project_archived"]);

const focusableSelector =
  'a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

type Failure = { copy: string; referenceId: string | undefined; retry: boolean };
type Attempt = { type: CardDecision; body: DecisionRequest; key: string; text: string };

function toastMessage(attempt: Attempt, title: string, keptUntil: string): string {
  switch (attempt.type) {
    case "complete":
      return `“${title}” done`;
    case "reformulate":
      return isSubstantiveChange(title, attempt.text)
        ? `New wording saved: “${attempt.text}”`
        : `“${attempt.text}” saved; the clock keeps running`;
    case "first_step":
      return `First step saved: “${attempt.text}”`;
    case "waiting":
      return `“${title}” moved to Waiting for`;
    case "someday":
      return `“${title}” released to Someday`;
    case "cancel":
      return `“${title}” cancelled`;
    case "extend":
      // FR-009: it asks again 7 days after the extension day, which is today.
      return `“${title}” kept until ${keptUntil}`;
  }
}

/** Undo after the dialog is gone: the server answers, and its task wins (formulation-clock §3). */
async function runUndo(notify: ShellNotify, queryClient: QueryClient, response: DecisionResponse, title: string): Promise<void> {
  // The account that pressed Undo: an answer that arrives after it signed out
  // writes nothing and says nothing to whoever is signed in now.
  const scope = captureReviewScope();
  try {
    const undone = await reviewApi.undoDecision(response.decision.id, { expected_task_revision: response.task.revision }, newIdempotencyKey());
    if (!isCurrentReviewScope(scope)) {
      return;
    }
    applyReviewTask(queryClient, undone.task, scope);
    notify(`“${title}” is back as it was`);
  } catch (error) {
    if (!isCurrentReviewScope(scope)) {
      return;
    }
    refreshAfterReviewWrite(queryClient, scope);
    const { kind, referenceId } = describeReviewError(error);
    if (isDecisionAlreadyUndone(error, response.decision.id)) {
      // Already undone (a retry whose first delivery applied, http §3). A 404
      // for the task or anything else falls through to the failure below.
      return;
    }
    if (kind === "undo_unavailable" || kind === "stale") {
      const current = await apiClient.getTask(response.task.id).catch(() => response.task);
      notify(withReference(`Couldn't undo: “${title}” changed on another device. It's in ${LIST_NAMES[current.state]} now.`, referenceId));
      return;
    }
    notify(withReference("Couldn't undo. Nothing was changed.", referenceId));
  }
}

export function DecisionDialog({
  task,
  projectName,
  onClose
}: {
  task: TaskResponse;
  projectName: string | null;
  onClose: (outcome: DecisionOutcome) => void;
}): React.JSX.Element {
  const titleId = useId();
  const hintId = useId();
  const notify = useShellToast();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const decideMutation = useDecideTask();
  const online = useOnlineStatus();
  const now = useReviewClock();
  const user = useAuthStore((state) => state.user);
  const canvasAvailable = hasFeatureFlag(user, "crt_canvas");
  // The dialog is only reachable signed in with the flag on (FR-042).
  // Pinned to the account the dialog was opened for: its text never lands under
  // another account's draft keys, even if the session changes under it.
  const [draftScope] = useState(() => ({ apiOrigin: getApiBaseUrl(), accountId: (user as AuthUser).id }));

  const [current, setCurrent] = useState<TaskResponse | null>(task);
  const [stale, setStale] = useState<{ was: TaskResponse; now: TaskResponse | null } | null>(null);
  const [reason, setReason] = useState<StallReason | null>(null);
  // A draft for this wording reopens its form with the typed text (FR-052).
  const [openingDraft] = useState(() =>
    loadReviewDraft(draftScope, { kind: "task", taskId: task.id, formulationId: (task.formulation as TaskFormulationResponse).id })
  );
  const [view, setView] = useState<DraftForm | null>(openingDraft?.form ?? null);
  const [text, setText] = useState(openingDraft?.text ?? "");
  const [restored, setRestored] = useState(openingDraft !== null);
  const [pending, setPending] = useState<CardDecision | null>(null);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [confirm, setConfirm] = useState<{ then: () => void; rearm: boolean } | null>(null);
  const lastAttempt = useRef<Attempt | null>(null);
  const sectionRef = useRef<HTMLElement>(null);
  const titleRef = useRef<HTMLHeadingElement>(null);
  const fieldRef = useRef<HTMLInputElement>(null);
  const confirmRef = useRef<HTMLDivElement>(null);
  const keepEditingRef = useRef<HTMLButtonElement>(null);
  const focusAfterViewChange = useRef<"field" | CardDecision | null>(null);

  // `current` is null only after a stale answer whose task could not be read
  // again; the forms and decisions are never shown then.
  const currentTitle = current === null ? task.title : current.title;
  const formulation = current?.formulation;
  const formulationId = formulation?.id as string;
  const keepUntil = formatReviewDate(new Date(now.getTime() + 7 * DAY_MS).toISOString());
  const parksOn = formatReviewDate(new Date(now.getTime() + 14 * DAY_MS).toISOString());
  /** Drafts key on the wording the form was opened for (data-model E11). */
  const draftTarget = (): ReviewDraftTarget => ({ kind: "task", taskId: task.id, formulationId });
  const initialText = view === "reformulate" ? currentTitle : "";
  const dirty = view !== null && text !== initialText;
  const formulationClass = classifyFromInstants(now, formulationInstants(formulation));
  const marker = listMarkerFor(formulationClass);
  const asks = marker !== null;
  const extended = Boolean(current?.formulation?.extended_at);
  const decisions = DECISIONS.filter((decision) => decision.type !== "extend" || !extended);
  const recommended = recommendedDecision(reason);
  const busy = pending !== null;
  const disabled = !online || busy;

  // Open: drop drafts of older wordings and put focus on the title.
  useLayoutEffect(() => {
    removeOtherFormulationDrafts(draftScope, task.id, formulationId);
    titleRef.current?.focus();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once per opened dialog: a stale answer later swaps in a newer wording, and focus must not jump back to the title then.
  }, []);

  useEffect(() => {
    const target = focusAfterViewChange.current;
    focusAfterViewChange.current = null;
    if (target === "field") {
      fieldRef.current?.focus();
    } else if (target !== null) {
      sectionRef.current?.querySelector<HTMLButtonElement>(`[data-decision="${target}"]`)?.focus();
    }
  }, [view]);

  useEffect(() => {
    if (confirm) {
      keepEditingRef.current?.focus();
    }
  }, [confirm]);

  const close = () => onClose({ kind: "closed" });

  const persistText = (value: string, form: DraftForm) => {
    // A failure belongs to the text that was sent: once the text changes, its
    // Retry would resend the old text, so the failure goes and Save sends anew.
    if (value !== text) {
      setFailure(null);
    }
    setText(value);
    if (value === (form === "reformulate" ? currentTitle : "")) {
      removeReviewDraft(draftScope, draftTarget());
    } else {
      saveReviewDraft(draftScope, draftTarget(), { form, text: value });
    }
  };

  const discardDraft = () => removeReviewDraft(draftScope, draftTarget());

  /** Every way out of a form goes through here (FR-052): ask first when dirty. */
  const guarded = (then: () => void, rearm = false) => {
    if (dirty) {
      setConfirm({ then, rearm });
      return;
    }
    then();
  };

  const backToCard = () => {
    const from = view;
    discardDraft();
    setView(null);
    setText("");
    setRestored(false);
    setFailure(null);
    focusAfterViewChange.current = from;
  };

  const guard = useLeaveGuard({
    dirty,
    onBack: () => guarded(close, true),
    onNavigate: (href) =>
      guarded(() => {
        guard.release();
        close();
        navigate(href, { replace: true });
      })
  });

  /** "Keep editing" and Escape on the confirmation: after browser Back the guard entry is pushed again. */
  const keepEditing = (rearm: boolean) => {
    if (rearm) guard.rearm();
    setConfirm(null);
    fieldRef.current?.focus();
  };

  const openForm = (form: DraftForm) => {
    setView(form);
    setText(form === "reformulate" ? currentTitle : "");
    setRestored(false);
    setFailure(null);
    focusAfterViewChange.current = "field";
  };

  const send = async (attempt: Attempt) => {
    lastAttempt.current = attempt;
    setPending(attempt.type);
    setFailure(null);
    try {
      const response = await decideMutation.mutateAsync({ taskId: task.id, body: attempt.body, idempotencyKey: attempt.key });
      discardDraft();
      const title = (current as TaskResponse).title;
      notify(toastMessage(attempt, title, keepUntil), {
        action: {
          label: "Undo",
          accessibleLabel: `Undo: ${UNDO_NAMES[attempt.type]} ${title}`,
          onAction: () => void runUndo(notify, queryClient, response, title)
        }
      });
      onClose({ kind: "decided", task: response.task, leftNext: response.task.state !== "next" });
    } catch (error) {
      setPending(null);
      const { kind, referenceId } = describeReviewError(error);
      if (kind === "stale") {
        const was = current as TaskResponse;
        const fresh = await apiClient.getTask(task.id).catch(() => null);
        setStale({ was, now: fresh });
        setCurrent(fresh);
        setView(null);
        setText("");
        return;
      }
      if (kind === "details_too_long") {
        setFailure({ copy: COPY.detailsTooLong, referenceId, retry: false });
      } else if (NOT_ALLOWED.has(kind)) {
        setFailure({ copy: COPY.notAllowed, referenceId, retry: false });
      } else {
        setFailure({ copy: COPY.saveFailed, referenceId, retry: true });
      }
    }
  };

  const decide = (type: CardDecision, value = "") => {
    const live = current as TaskResponse;
    const trimmed = value.trim();
    const body: DecisionRequest = {
      type,
      expected_revision: live.revision,
      ...(ON_FORMULATION.has(type) ? { formulation_id: formulationId as string } : {}),
      ...(reason ? { stall_reason: reason } : {}),
      ...(type === "reformulate" || type === "first_step" ? { title: trimmed } : {}),
      ...(type === "waiting" ? { waiting_for: trimmed } : {}),
      ...(type === "extend" ? { reason: trimmed } : {})
    };
    void send({ type, body, key: newIdempotencyKey(), text: trimmed });
  };

  const choose = (type: CardDecision) => {
    if (type === "complete" || type === "someday" || type === "cancel") {
      decide(type);
    } else {
      openForm(type);
    }
  };

  const trap = (event: ReactKeyboardEvent, container: HTMLElement) => {
    const focusable = Array.from(container.querySelectorAll<HTMLElement>(focusableSelector));
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

  const onKeyDown = (event: ReactKeyboardEvent<HTMLElement>) => {
    if (event.key === "Tab") {
      trap(event, (confirm ? confirmRef.current : sectionRef.current) as HTMLElement);
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      if (confirm) {
        keepEditing(confirm.rearm);
      } else if (view) {
        guarded(backToCard);
      } else {
        close();
      }
      return;
    }
    const target = event.target as HTMLElement;
    const index = Number(event.key) - 1;
    const pick = decisions[index];
    if (confirm || view || !pick || !asks || disabled || event.ctrlKey || event.metaKey || event.altKey || target.matches("input, textarea")) {
      return;
    }
    event.preventDefault();
    choose(pick.type);
  };

  const meta = formulation
    ? [
        `${daysInNext(formulation.started_at, now)} days in Next`,
        projectName ?? "no project",
        ...(formulation.extended_at ? [`kept 7 more days on ${formatReviewDate(formulation.extended_at)}`] : [])
      ].join(" · ")
    : null;
  const formCopy = view ? FORMS[view] : null;
  const trimmedText = text.trim();
  const unchangedWording = view === "reformulate" && trimmedText === currentTitle.trim();
  const cosmetic = view === "reformulate" && trimmedText !== "" && !unchangedWording && !isSubstantiveChange(currentTitle, trimmedText);
  const canSave = online && !busy && trimmedText !== "" && !unchangedWording;
  const saveLabel = view === "reformulate" ? (cosmetic ? "Save anyway" : "Save new wording")
    : view === "first_step" ? "Save first step"
      : view === "waiting" ? "Move to Waiting for"
        : `Keep until ${keepUntil}`;

  return (
    <div className="fixed inset-0 z-[100] flex items-stretch justify-center sm:items-center sm:p-6">
      <div data-testid="decision-dialog-scrim" aria-hidden className="absolute inset-0 bg-slate-50/80 backdrop-blur-xs motion-safe:animate-fade-in" onClick={() => guarded(close)} />
      <section
        ref={sectionRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onKeyDown={onKeyDown}
        className="relative flex h-full w-full flex-col overflow-y-auto bg-white shadow-floating sm:h-auto sm:max-h-[calc(100vh-48px)] sm:w-[560px] sm:rounded-[20px] sm:border sm:border-slate-200"
      >
        <header className="flex items-start gap-3 border-b border-slate-100 px-5 pb-3 pt-4">
          <div className="min-w-0 flex-1">
            {marker ? (
              <p className={`inline-flex h-[22px] items-center gap-1 rounded-full border px-2 text-[11px] font-medium ${marker === "asks" ? "border-indigo-200 bg-indigo-50 text-indigo-700" : "border-amber-200 bg-amber-50 text-amber-800"}`}>
                {marker === "asks" ? <CircleHelp className="h-3 w-3" aria-hidden /> : <Archive className="h-3 w-3" aria-hidden />}
                {marker === "asks" ? "Asks for a decision" : "Moves to Someday tomorrow"}
              </p>
            ) : null}
            <h2 id={titleId} ref={titleRef} tabIndex={-1} className="mt-1 break-words text-[18px] font-semibold leading-[1.3] text-slate-900 outline-hidden">
              {currentTitle}
            </h2>
            {meta ? <p className="mt-0.5 text-xs text-slate-500">{meta}</p> : null}
          </div>
          <button type="button" aria-label="Close" className="-mr-1.5 inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-slate-500 hover:bg-surface-sunken hover:text-slate-900" onClick={() => guarded(close)}>
            <X className="h-4 w-4" aria-hidden />
          </button>
        </header>

        <div className="flex flex-col gap-4 px-5 py-4">
          {!online ? <p role="status" className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700">{COPY.offline}</p> : null}
          {failure ? (
            <div role="alert" className="flex flex-wrap items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
              <span>{failure.copy}</span>
              {failure.referenceId ? <span className="text-xs">Ref {failure.referenceId}</span> : null}
              {failure.retry ? (
                <button
                  type="button"
                  disabled={disabled}
                  className="min-h-11 rounded-lg px-3 font-semibold text-amber-900 hover:bg-amber-100 disabled:opacity-50"
                  onClick={() => void send(lastAttempt.current as Attempt)}
                >
                  Retry
                </button>
              ) : null}
            </div>
          ) : null}
          {stale ? (
            <section aria-labelledby={`${titleId}-stale`} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700">
              <h3 id={`${titleId}-stale`} className="m-0 font-semibold text-slate-900">{COPY.staleHeading}</h3>
              <p className="m-0 mt-1">{COPY.staleBody}</p>
              {stale.now ? (
                <dl className="mt-2 grid grid-cols-[48px_1fr] gap-x-2 text-xs">
                  <dt className="text-slate-500">Was</dt>
                  <dd className="m-0">{stale.was.title}</dd>
                  <dt className="text-slate-500">Now</dt>
                  <dd className="m-0">{stale.now.title}</dd>
                </dl>
              ) : null}
            </section>
          ) : null}

          {view && formCopy ? (
            <form
              className="flex flex-col gap-2"
              onSubmit={(event) => {
                // Implicit submission is blocked while the submit button is
                // disabled, so a submit always carries a savable text.
                event.preventDefault();
                decide(view, text);
              }}
            >
              {restored ? (
                <p className="m-0 flex items-center gap-2 text-xs text-slate-600">
                  {COPY.draftBack}
                  <button
                    type="button"
                    className="min-h-11 rounded-lg px-2 font-medium text-sky-700 hover:bg-sky-50"
                    onClick={() => {
                      persistText(initialText, view);
                      setRestored(false);
                      fieldRef.current?.focus();
                    }}
                  >
                    Clear
                  </button>
                </p>
              ) : null}
              <label className="flex flex-col gap-1 text-sm font-medium text-slate-800">
                {formCopy.prompt}
                <input
                  ref={fieldRef}
                  aria-label={formCopy.field}
                  value={text}
                  maxLength={500}
                  placeholder={formCopy.placeholder}
                  className="min-h-11 rounded-lg border border-slate-300 px-3 text-base font-normal text-slate-900 outline-hidden focus:border-brand-primary sm:text-sm"
                  onChange={(event) => persistText(event.currentTarget.value, view)}
                />
              </label>
              {formCopy.help ? <p className="m-0 text-xs text-slate-600">{formCopy.help}</p> : null}
              {view === "first_step" ? (
                <p className="m-0 text-xs text-slate-600">
                  The old wording stays in this task&apos;s notes as <span className="font-medium text-slate-800">Was: {currentTitle}</span>
                </p>
              ) : null}
              {view === "extend" ? (
                <p className="m-0 text-xs text-slate-600">
                  {`Asks again on ${keepUntil}. If still undecided, it moves to Someday on ${parksOn}. You can do this once for this wording.`}
                </p>
              ) : null}
              {cosmetic ? <p className="m-0 rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-700">{COPY.cosmetic}</p> : null}
              <div className="mt-1 flex flex-wrap items-center gap-2">
                <button type="button" className="min-h-11 rounded-lg px-3 text-sm font-medium text-slate-700 hover:bg-surface-sunken" onClick={() => guarded(backToCard)}>
                  Back
                </button>
                <button
                  type="submit"
                  disabled={!canSave}
                  aria-describedby={view === "extend" && trimmedText === "" ? hintId : undefined}
                  className="ml-auto min-h-11 rounded-lg bg-sky-700 px-4 text-sm font-semibold text-white hover:bg-sky-800 disabled:opacity-50"
                >
                  {busy ? "Saving…" : saveLabel}
                </button>
              </div>
              {view === "extend" && trimmedText === "" ? <p id={hintId} className="m-0 text-right text-xs text-slate-600">{COPY.reasonNeeded}</p> : null}
            </form>
          ) : asks ? (
            <>
              {stale ? null : <p className="m-0 text-sm text-slate-700">{COPY.framing}</p>}
              {isThirdStall(formulationClass, (formulation as TaskFormulationResponse).consecutive_stalled) ? (
                <section aria-label="Third stalled wording" className="rounded-lg border border-sky-200 bg-sky-50 px-3 py-2 text-sm text-slate-700">
                  <p className="m-0">{COPY.thirdStall}</p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {canvasAvailable ? (
                      <Link to="/crt" className="inline-flex min-h-11 items-center rounded-lg border border-slate-200 bg-white px-3 font-medium text-slate-800 hover:border-slate-300">
                        Think it through
                      </Link>
                    ) : null}
                    <button type="button" disabled={disabled} className="min-h-11 rounded-lg border border-slate-200 bg-white px-3 font-medium text-slate-800 hover:border-slate-300 disabled:opacity-50" onClick={() => decide("someday")}>
                      Release to Someday
                    </button>
                  </div>
                </section>
              ) : null}
              <div>
                <p className="m-0 mb-2 text-xs font-semibold text-slate-600">
                  What got in the way? <span className="font-normal text-slate-500">· optional</span>
                </p>
                <div role="group" aria-label="What got in the way, optional" className="flex flex-wrap gap-1.5">
                  {STALL_REASONS.map((option) => (
                    <button
                      key={option.code}
                      type="button"
                      aria-pressed={reason === option.code}
                      disabled={busy}
                      className={`min-h-11 rounded-full border px-3 text-[13px] font-medium ${reason === option.code ? "border-sky-700 bg-sky-50 text-sky-800" : "border-slate-200 bg-white text-slate-700 hover:border-slate-300"}`}
                      onClick={() => setReason(reason === option.code ? null : option.code)}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <p className="m-0 mb-2 text-xs font-semibold text-slate-600">What now?</p>
                <div role="group" aria-label="Decisions" className="flex flex-col gap-1.5">
                  {decisions.map((decision, index) => (
                    <button
                      key={decision.type}
                      type="button"
                      data-decision={decision.type}
                      disabled={disabled}
                      className={`flex min-h-11 w-full items-center gap-2 rounded-lg border px-3 py-2 text-left text-sm ${recommended === decision.type ? "border-sky-600 ring-1 ring-sky-600" : "border-slate-200"} bg-white text-slate-900 hover:border-slate-300 disabled:opacity-60`}
                      onClick={() => choose(decision.type)}
                    >
                      <span className="font-medium">{decision.label}</span>
                      {decision.sub ? <span className="text-xs text-slate-500">{decision.sub}</span> : null}
                      {recommended === decision.type ? <span className="rounded-full bg-sky-100 px-2 py-[1px] text-[11px] font-semibold text-sky-800">Recommended</span> : null}
                      {pending === decision.type ? <span className="text-xs text-slate-600">Saving…</span> : null}
                      <kbd aria-hidden className="ml-auto rounded border border-slate-200 px-1.5 text-[11px] text-slate-500">{index + 1}</kbd>
                    </button>
                  ))}
                </div>
                {extended ? <p className="m-0 mt-2 text-xs text-slate-500">{COPY.extensionUsed}</p> : null}
              </div>
            </>
          ) : (
            <p className="m-0 text-sm text-slate-700">{COPY.noLongerAsks}</p>
          )}
        </div>

        {confirm ? (
          <div className="absolute inset-0 flex items-center justify-center bg-white/80 p-5">
            <div
              ref={confirmRef}
              role="alertdialog"
              aria-modal="true"
              aria-labelledby={`${titleId}-discard`}
              aria-describedby={`${titleId}-discard-body`}
              className="w-full max-w-[360px] rounded-[14px] border border-slate-200 bg-white p-4 shadow-floating"
            >
              <h3 id={`${titleId}-discard`} className="m-0 text-sm font-semibold text-slate-900">{COPY.discardTitle}</h3>
              <p id={`${titleId}-discard-body`} className="m-0 mt-1 text-sm text-slate-600">{COPY.discardBody}</p>
              <div className="mt-3 flex gap-2">
                <button
                  ref={keepEditingRef}
                  type="button"
                  className="min-h-11 flex-1 rounded-lg bg-sky-700 px-3 text-sm font-semibold text-white hover:bg-sky-800"
                  onClick={() => keepEditing(confirm.rearm)}
                >
                  Keep editing
                </button>
                <button
                  type="button"
                  className="min-h-11 flex-1 rounded-lg border border-slate-200 px-3 text-sm font-medium text-slate-700 hover:border-slate-300"
                  onClick={() => {
                    const { then } = confirm;
                    setConfirm(null);
                    discardDraft();
                    setView(null);
                    setText("");
                    then();
                  }}
                >
                  Discard
                </button>
              </div>
            </div>
          </div>
        ) : null}
      </section>
    </div>
  );
}
