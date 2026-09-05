import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Bot } from "lucide-react";

import { useAgentKeys } from "../../api/agentHooks";
import { useRelayMutation, useRelayOnline } from "../../api/agentLifecycle";
import type { AgentRunEvent, AgentRunResponse } from "../../api/agentTypes";
import { apiClient } from "../../api/client";
import { Button } from "../../components/ui/Button";
import { getErrorMessage } from "../../utils/error";
import { definitivelyRejected, useIntentKey } from "../../utils/idempotency";
import { AgentHandoffOverlay } from "./AgentHandoffOverlay";
import {
  TASK_SUCCESSION_COPY,
  artifactPlaceholderCopy,
  awaitsAnswer,
  cancelOutcomeCopy,
  canCancelRun,
  canReplyToRun,
  dispatchStateDetail,
  formatTimestamp,
  resultAvailabilityCopy
} from "./agentCopy";

const EXPIRED_NOTICE = "Content expired under retention policy";

function isAgentRunContentExpired(run: AgentRunResponse, now = Date.now()): boolean {
  if (run.content_expired) {
    return true;
  }
  const deadline = Date.parse(run.content_expires_at);
  return Number.isFinite(deadline) && now >= deadline;
}

function useAgentRunContentExpired(run: AgentRunResponse): boolean {
  const serverExpired = run.content_expired;
  const expiresAt = run.content_expires_at;
  const [expired, setExpired] = useState(() => isAgentRunContentExpired(run));
  useEffect(() => {
    const deadline = Date.parse(expiresAt);
    const effective = serverExpired || (Number.isFinite(deadline) && Date.now() >= deadline);
    setExpired((previous) => previous || effective);
    if (effective || !Number.isFinite(deadline)) {
      return;
    }
    let timer = 0;
    const schedule = () => {
      const remaining = deadline - Date.now();
      if (remaining <= 0) {
        setExpired(true);
        return;
      }
      timer = window.setTimeout(schedule, Math.min(remaining, 2_147_483_647));
    };
    schedule();
    return () => window.clearTimeout(timer);
  }, [serverExpired, expiresAt]);
  return expired;
}

/**
 * Timeline wording for one connector report.
 *
 * `completed` reads as the agent's claim, matching the server's own
 * `primary_state_label`, so the timeline can never be more confident than the
 * headline state.
 */
function eventLabel(type: AgentRunEvent["type"]): string {
  switch (type) {
    case "accepted":
      return "Accepted";
    case "running":
      return "Running";
    case "blocked":
      return "Needs you";
    case "completed":
      return "Agent reported complete";
    case "failed":
      return "Failed";
    default:
      return "Cancelled";
  }
}

interface ReplyIntentSnapshot {
  idempotencyKey: string;
  message: string;
  questionIdentity: string;
  expectedRevision: number;
}

function questionIdentity(run: AgentRunResponse): string {
  const blockedEvent = [...run.events].reverse().find((event) => event.type === "blocked");
  return JSON.stringify([
    run.id,
    run.task_id,
    run.connection_id,
    blockedEvent?.id ?? run.run_version,
    run.question_text
  ]);
}

/**
 * One external run attached to a task.
 *
 * Every user-visible claim here comes from the server projection — especially
 * `primary_state_label`, which is rendered verbatim so web and iOS cannot drift
 * into describing the same run differently. Controls follow the connector's
 * disclosed capabilities: an unsupported reply or cancel is stated as
 * unsupported rather than rendered as a button that would fail.
 */
function RunCard({ taskId, run }: { taskId: string; run: AgentRunResponse }): React.JSX.Element {
  const queryClient = useQueryClient();
  const keys = useAgentKeys();
  const online = useRelayOnline();
  const contentExpired = useAgentRunContentExpired(run);
  const [answer, setAnswer] = useState("");
  const [error, setError] = useState<string | null>(null);
  // Re-review of a hand-off that never left. It is the same review, reopened —
  // not a new one — so it is seeded from the run's own frozen manifest.
  const [retrying, setRetrying] = useState(false);

  const invalidate = (updated: AgentRunResponse) => {
    setError(null);
    queryClient.setQueryData(keys.run(updated.id), updated);
    void queryClient.invalidateQueries({ queryKey: keys.runs(taskId) });
  };

  // One key per user intent, held across retries: a reply that timed out may
  // already have reached the server, and re-sending it under a fresh key would
  // turn that ambiguity into a second command.
  const replyKey = useIntentKey(`agent-reply-${run.id}`);
  const cancelKey = useIntentKey(`agent-cancel-${run.id}`);
  const checkKey = useIntentKey(`agent-check-delivery-${run.id}`);
  const replyIntent = useRef<ReplyIntentSnapshot | null>(null);
  const displayedQuestionIdentity = questionIdentity(run);

  const replyMutation = useRelayMutation({
    mutationKey: keys.mutation("reply", run.id),
    mutationFn: (input: ReplyIntentSnapshot) => {
      return apiClient.replyToAgentRun(
        run.id,
        { message: input.message, expected_revision: input.expectedRevision },
        input.idempotencyKey
      );
    },
    onSuccess: (updated) => {
      replyKey.settle();
      replyIntent.current = null;
      setAnswer("");
      invalidate(updated);
    },
    onError: (caught: unknown) => {
      if (definitivelyRejected(caught)) {
        replyKey.settle();
        replyIntent.current = null;
      }
      setError(getErrorMessage(caught));
    }
  });

  const cancelMutation = useRelayMutation({
    mutationKey: keys.mutation("cancel", run.id),
    mutationFn: (input: { idempotencyKey: string }) => {
      return apiClient.cancelAgentRun(run.id, input.idempotencyKey);
    },
    onSuccess: (updated) => {
      cancelKey.settle();
      invalidate(updated);
    },
    onError: (caught: unknown) => {
      if (definitivelyRejected(caught)) {
        cancelKey.settle();
      }
      setError(getErrorMessage(caught));
    }
  });

  const checkMutation = useRelayMutation({
    mutationKey: keys.mutation("check-delivery", run.id),
    // No identifiers of its own: the correlation ID and the message ID are on
    // the run, so this can only ever repeat the same check. The key is held
    // across retries for the same reason a reply's is — an ambiguous check that
    // is retried under a fresh key would stop being the same check. The
    // revision is the run this control was rendered from: the check can end in
    // a send, so it names the state the user was actually looking at.
    mutationFn: (input: { idempotencyKey: string; expectedRevision: number }) =>
      apiClient.checkAgentRunDelivery(
        run.id,
        { current_password: null, expected_revision: input.expectedRevision },
        input.idempotencyKey
      ),
    onSuccess: (updated) => {
      checkKey.settle();
      invalidate(updated);
    },
    onError: (caught: unknown) => {
      if (definitivelyRejected(caught)) {
        checkKey.settle();
      }
      setError(getErrorMessage(caught));
    }
  });

  // The question is only live while the run is blocked, so a finished run never
  // shows an answer box — nor the "replies unsupported" note, which for an old
  // question would only imply an answer was still expected somewhere.
  const showQuestion = !contentExpired && awaitsAnswer(run);
  const canReply = online && !contentExpired && canReplyToRun(run);
  const canCancel = online && !contentExpired && canCancelRun(run);

  const dispatchDetail = contentExpired ? null : dispatchStateDetail(run);
  // Secondary lines, never the primary label: what the agent said about
  // cancellation, and whether the result fitted, are separate facts from what
  // the run is doing.
  const cancelOutcome = cancelOutcomeCopy(run);
  const tooLarge = contentExpired ? null : resultAvailabilityCopy(run);
  // Offered only where BrainBuddy genuinely does not know: a queued exchange
  // has provably not been sent, so there is nothing at the agent to look up.
  const canCheckDelivery =
    !contentExpired &&
    run.dispatch_state === "delivery_unconfirmed" &&
    run.exchange_state !== "queued" &&
    run.reported_state === null &&
    !run.connection_disconnected;
  // A hand-off that never left can be re-offered exactly as it was reviewed —
  // but only while BrainBuddy still holds what was reviewed.
  const frozenManifest =
    !contentExpired && run.dispatch_state === "not_sent" ? run.manifest : null;

  useEffect(() => {
    const held = replyIntent.current;
    if (held && (!showQuestion || held.questionIdentity !== displayedQuestionIdentity)) {
      replyKey.settle();
      replyIntent.current = null;
    }
  }, [displayedQuestionIdentity, replyKey, showQuestion]);

  return (
    <article className="rounded-[12px] border border-ai-border bg-ai-bg px-3 py-2.5">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <Bot className="h-[13px] w-[13px] text-ai-fg" aria-hidden />
        <span className="text-[12.5px] font-medium text-ai-fg">{run.agent_name}</span>
        <span className="rounded-full border border-ai-border bg-white px-2 py-[1px] text-[11px] font-medium text-ai-fg">
          {run.primary_state_label}
        </span>
        <span className="ml-auto text-[11px] text-slate-500">
          Last contact {formatTimestamp(run.last_contact_at)}
        </span>
      </div>

      {contentExpired ? (
        <p className="mt-2 text-[12px] italic text-slate-500">{EXPIRED_NOTICE}</p>
      ) : (
        <>
          {run.progress_text ? (
            <p className="mt-2 whitespace-pre-wrap text-[12.5px] text-slate-700">{run.progress_text}</p>
          ) : null}

          {showQuestion ? (
            <div className="mt-2 rounded-lg border border-needs-you-border bg-needs-you-bg px-2.5 py-2">
              <p className="m-0 whitespace-pre-wrap text-[12.5px] text-needs-you-fg">{run.question_text}</p>
              {canReply ? (
                <form
                  className="mt-2 flex flex-col gap-1.5"
                  onSubmit={(event) => {
                    event.preventDefault();
                    const message = answer.trim();
                    if (message) {
                      const held = replyIntent.current;
                      const intent =
                        held?.message === message && held.questionIdentity === displayedQuestionIdentity
                          ? held
                          : {
                              message,
                              questionIdentity: displayedQuestionIdentity,
                              expectedRevision: run.revision,
                              idempotencyKey: replyKey.current(`${displayedQuestionIdentity}:${message}`)
                            };
                      replyIntent.current = intent;
                      replyMutation.mutate(intent);
                    }
                  }}
                >
                  <label className="flex flex-col gap-1 text-[11px] font-medium text-slate-600">
                    Your answer
                    <textarea
                      aria-label="Your answer"
                      value={answer}
                      onChange={(event) => setAnswer(event.target.value)}
                      rows={2}
                      className="resize-y rounded-md border border-slate-200 bg-white px-2 py-1.5 text-[12.5px] text-slate-900 focus:border-brand-primary focus:outline-none"
                    />
                  </label>
                  <div>
                    <Button type="submit" variant="secondary" size="sm" isLoading={replyMutation.isPending}>
                      Send answer
                    </Button>
                  </div>
                </form>
              ) : run.capabilities.reply ? (
                // The connection or the run is what stopped the reply, and the
                // card already names that condition below — repeating it here
                // as "unsupported" would blame the wrong thing.
                null
              ) : (
                <p className="m-0 mt-1.5 text-[11px] text-slate-600">
                  This agent does not support replies, so the question can only be answered wherever you
                  operate the agent.
                </p>
              )}
            </div>
          ) : null}

          {run.blocked_reason ? (
            // D-03-S10. The run needs the user and the agent named why, so the
            // reason is stated verbatim — and stated *without* a control. What
            // blocks an agent here is a credential problem at the agent, which
            // no answer typed into BrainBuddy can solve; a reply box beside
            // this sentence is how a secret gets forwarded to a third party.
            <p className="mt-2 whitespace-pre-wrap rounded-lg border border-needs-you-border bg-needs-you-bg px-2.5 py-2 text-[12.5px] text-needs-you-fg">
              {run.blocked_reason}
            </p>
          ) : null}

          {run.result_text ? (
            <p className="mt-2 whitespace-pre-wrap text-[12.5px] text-slate-700">{run.result_text}</p>
          ) : null}

          {tooLarge ? (
            <p className="mt-2 text-[12.5px] font-medium text-slate-700">{tooLarge}</p>
          ) : null}

          {run.artifacts_summary.length ? (
            <ul className="mt-1.5 flex flex-col gap-0.5">
              {run.artifacts_summary.map((artifact, index) => (
                <li
                  key={`${artifact.name ?? artifact.kind}-${index}`}
                  className="text-[11.5px] text-slate-500"
                >
                  {artifactPlaceholderCopy(artifact)}
                </li>
              ))}
            </ul>
          ) : null}

          {run.result_link ? (
            // Inert text beside a copy control, whatever the scheme. BrainBuddy
            // never opens or fetches an address an agent reported, and it never
            // makes one clickable — a link the product renders as navigable is
            // a link the product is vouching for (D-03-S11, FR-014).
            <div className="mt-1.5 flex flex-wrap items-baseline gap-2">
              <span className="break-all text-[12px] text-slate-500">{run.result_link}</span>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => {
                  void navigator.clipboard?.writeText(run.result_link ?? "");
                }}
              >
                Copy link
              </Button>
            </div>
          ) : null}

          {run.failure_reason ? (
            <p className="mt-2 whitespace-pre-wrap text-[12.5px] text-rose-700">{run.failure_reason}</p>
          ) : null}
        </>
      )}

      {run.reply_pending ? (
        <p className="mt-1.5 text-[11px] text-slate-500">
          Your answer was sent but the agent has not acknowledged it yet.
        </p>
      ) : null}
      {cancelOutcome ? (
        <p className="mt-1.5 text-[11px] text-slate-500">{cancelOutcome}</p>
      ) : null}
      {run.cancel_requested && !cancelOutcome ? (
        <p className="mt-1.5 text-[11px] text-slate-500">
          Cancellation was requested. The agent has not confirmed it, so the work may still be running.
        </p>
      ) : null}
      {run.agent_task_missing ? (
        <p className="mt-1.5 text-[11px] text-slate-500">
          The agent no longer reports this run. BrainBuddy kept everything it had already observed and
          is not claiming the work failed.
        </p>
      ) : null}
      {run.stopped_reporting ? (
        <p className="mt-1.5 text-[11px] text-slate-500">
          No report since the last contact above. BrainBuddy does not know whether the agent is still
          working.
        </p>
      ) : null}
      {run.connection_disconnected ? (
        <p className="mt-1.5 text-[11px] text-slate-500">
          This agent was disconnected. Disconnecting did not cancel any work it had already accepted.
        </p>
      ) : null}
      {dispatchDetail ? (
        <p className="mt-1.5 text-[11px] text-slate-500">{dispatchDetail}</p>
      ) : null}
      {canCheckDelivery ? (
        <div className="mt-1.5">
          <p className="m-0 text-[11px] text-slate-500">
            Runs the same check again with the same correlation ID and the same message ID. It is
            never a new send.
          </p>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="mt-1"
            disabled={!online}
            isLoading={checkMutation.isPending}
            onClick={() =>
              checkMutation.mutate({
                idempotencyKey: checkKey.current(),
                expectedRevision: run.revision
              })
            }
          >
            Check again
          </Button>
        </div>
      ) : null}
      {frozenManifest ? (
        <div className="mt-1.5">
          <Button type="button" variant="ghost" size="sm" onClick={() => setRetrying(true)}>
            Try this hand-off again
          </Button>
        </div>
      ) : null}

      {run.events.length ? (
        <ol className="mt-2 flex flex-col gap-1 border-t border-ai-border pt-2">
          {run.events.map((event) => (
            <li key={event.id} className="flex flex-wrap items-baseline gap-x-2 text-[11px] text-slate-600">
              <span className="font-medium text-slate-700">
                {event.kind === "task_succession" ? TASK_SUCCESSION_COPY : eventLabel(event.type)}
              </span>
              <span className="text-slate-400">{formatTimestamp(event.received_at)}</span>
              {event.kind === "task_succession" && event.previous_agent_task_id ? (
                // Both identifiers, because the point of the row is that the
                // one the user saw yesterday is not the one being observed now.
                <span className="text-slate-400">
                  {event.previous_agent_task_id} → {event.new_agent_task_id}
                </span>
              ) : null}
              {!contentExpired && event.summary && event.kind !== "task_succession" ? (
                <span className="basis-full text-slate-500">{event.summary}</span>
              ) : null}
            </li>
          ))}
        </ol>
      ) : null}

      {canCancel ? (
        <div className="mt-2">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            isLoading={cancelMutation.isPending}
            onClick={() => cancelMutation.mutate({ idempotencyKey: cancelKey.current() })}
          >
            Request cancellation
          </Button>
        </div>
      ) : null}

      {error ? (
        <p role="alert" className="mt-2 text-[12px] text-rose-700">
          {error}
        </p>
      ) : null}

      {retrying && frozenManifest ? (
        <AgentHandoffOverlay
          taskId={taskId}
          taskTitle={frozenManifest.title}
          // What was frozen is what will be re-sent. The server rebuilds the
          // identical manifest from these three values, so the token — and with
          // it the idempotency key, the run ID and the message ID — is the same
          // one exactly as long as the user changes nothing.
          seed={{
            connectionId: frozenManifest.connection_id,
            includeDetails: frozenManifest.details !== null,
            supportingItems: frozenManifest.supporting_items
          }}
          onClose={() => setRetrying(false)}
          onDispatched={(updated) => {
            setRetrying(false);
            invalidate(updated);
          }}
        />
      ) : null}
    </article>
  );
}

export function AgentRunSection({
  taskId,
  runs,
  isLoading,
  error
}: {
  taskId: string;
  runs: AgentRunResponse[];
  isLoading: boolean;
  error: unknown;
}): React.JSX.Element | null {
  if (error && runs.length === 0) {
    return (
      <div className="flex flex-col gap-2 border-t border-slate-200 px-4 py-3">
        <h3 className="m-0 text-[10px] font-semibold uppercase tracking-[0.06em] text-slate-500">Agent runs</h3>
        <p role="alert" className="m-0 text-[12.5px] text-rose-700">
          {getErrorMessage(error)}
        </p>
      </div>
    );
  }
  // A task that was never handed to an agent shows nothing at all — an empty
  // "Agent runs" heading would imply the feature had been used.
  if (!runs.length) {
    return null;
  }
  return (
    <div className="flex flex-col gap-2 border-t border-slate-200 px-4 py-3">
      <h3 className="m-0 text-[10px] font-semibold uppercase tracking-[0.06em] text-slate-500">
        {runs.length === 1 ? "Agent run" : `Agent runs · ${runs.length}`}
      </h3>
      {isLoading ? <p className="m-0 text-[12px] text-slate-500">Loading runs…</p> : null}
      {error ? (
        <p role="alert" className="m-0 text-[12px] text-amber-700">
          Showing cached agent data because refresh failed: {getErrorMessage(error)}
        </p>
      ) : null}
      <div className="flex flex-col gap-2">
        {runs.map((run) => (
          <RunCard key={run.id} taskId={taskId} run={run} />
        ))}
      </div>
    </div>
  );
}
