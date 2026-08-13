import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Bot, ExternalLink } from "lucide-react";

import { useAgentKeys } from "../../api/agentHooks";
import { useRelayMutation, useRelayOnline } from "../../api/agentLifecycle";
import type { AgentRunEvent, AgentRunResponse } from "../../api/agentTypes";
import { apiClient } from "../../api/client";
import { Button } from "../../components/ui/Button";
import { getErrorMessage } from "../../utils/error";
import { definitivelyRejected, useIntentKey } from "../../utils/idempotency";
import { awaitsAnswer, canCancelRun, canReplyToRun, formatTimestamp } from "./agentCopy";

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

  // The question is only live while the run is blocked, so a finished run never
  // shows an answer box — nor the "replies unsupported" note, which for an old
  // question would only imply an answer was still expected somewhere.
  const showQuestion = !contentExpired && awaitsAnswer(run);
  const canReply = online && !contentExpired && canReplyToRun(run);
  const canCancel = online && !contentExpired && canCancelRun(run);

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

          {run.result_text ? (
            <p className="mt-2 whitespace-pre-wrap text-[12.5px] text-slate-700">{run.result_text}</p>
          ) : null}

          {run.result_link ? (
            run.result_link_interactive ? (
              <p className="mt-1.5 text-[12px]">
                <a
                  href={run.result_link}
                  target="_blank"
                  rel="noopener noreferrer nofollow"
                  className="inline-flex items-center gap-1 font-medium text-brand-primary underline"
                >
                  {run.result_link}
                  <ExternalLink className="h-[11px] w-[11px]" aria-hidden />
                </a>
                <span className="ml-1 text-slate-500">Opens a site outside BrainBuddy.</span>
              </p>
            ) : (
              // Not a safe HTTPS destination, so it stays text and is never
              // fetched or made clickable (FR-014).
              <p className="mt-1.5 break-all text-[12px] text-slate-500">{run.result_link}</p>
            )
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
      {run.cancel_requested ? (
        <p className="mt-1.5 text-[11px] text-slate-500">
          Cancellation was requested. The agent has not confirmed it, so the work may still be running.
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
      {run.dispatch_state === "delivery_unconfirmed" ? (
        <p className="mt-1.5 text-[11px] text-slate-500">
          BrainBuddy could not confirm the agent received this hand-off. It was not re-sent.
        </p>
      ) : null}

      {run.events.length ? (
        <ol className="mt-2 flex flex-col gap-1 border-t border-ai-border pt-2">
          {run.events.map((event) => (
            <li key={event.id} className="flex flex-wrap items-baseline gap-x-2 text-[11px] text-slate-600">
              <span className="font-medium text-slate-700">{eventLabel(event.type)}</span>
              <span className="text-slate-400">{formatTimestamp(event.received_at)}</span>
              {!contentExpired && event.summary ? <span className="basis-full text-slate-500">{event.summary}</span> : null}
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
