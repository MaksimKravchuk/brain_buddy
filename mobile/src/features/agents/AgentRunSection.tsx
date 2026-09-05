import { useEffect, useRef, useState } from "react";
import { Pressable, StyleSheet, TextInput, View } from "react-native";

import { isDefinitiveMutationFailure } from "@/api/client";
import {
  useCancelAgentRun,
  useCheckAgentRunDelivery,
  useReplyToAgentRun,
} from "@/api/hooks";
import type { AgentRunResponse } from "@/api/types";
import {
  EXPIRED_CONTENT_NOTICE,
  canCheckDelivery,
  canRetryHandoff,
  dispatchStateDetail,
  artifactPlaceholderCopy,
  cancelOutcomeCopy,
  resultAvailabilityCopy,
  timelineRowLabel,
  lastContactLabel,
  runsNewestFirst,
  sortedEvents,
} from "@/agents/machine";
import { BBText } from "@/components/BBText";
import { Button } from "@/components/Button";
import { ErrorBanner } from "@/components/ErrorBanner";
import { awaitsAnswer, canCancel, canOpenResultLink, canReply } from "@/lifecycle/agentGuards";
import { colors, fonts, radii, space, type as typeScale } from "@/theme/tokens";
import { copyToClipboard } from "@/utils/clipboard";
import { useIntentKey } from "@/utils/ids";

const STALE_NOTICE =
  "Brain Buddy could not reach the server just now, so this is the last report it received and may be out of date.";

interface AgentRunSectionProps {
  runs: AgentRunResponse[];
  loading: boolean;
  error: unknown;
  /** False once a request never reached the server — see `isOfflineError`. */
  online: boolean;
  /** Hand a run a command just returned straight back to the feed. */
  onRunUpdated: (run: AgentRunResponse) => void;
  /** Reopen the review for a hand-off that never left, seeded from its manifest. */
  onRetryHandoff?: (run: AgentRunResponse) => void;
  onRetry?: () => void;
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
    run.question_text,
  ]);
}

/**
 * The iOS view of what an external agent is doing with one task.
 *
 * The server's `primary_state_label` is rendered verbatim — nothing here
 * recomputes it, so iOS and web can never describe the same run differently.
 * Conditions Brain Buddy derived (no recent report, disconnected connection,
 * unconfirmed delivery) are stated separately instead of being folded into that
 * label, and every control is offered only when `agentGuards` allows it.
 */
export function AgentRunSection({
  runs,
  loading,
  error,
  online,
  onRunUpdated,
  onRetryHandoff,
  onRetry,
}: AgentRunSectionProps) {

  // Only an initial failure with nothing to show is an error state. Once a
  // projection has been received, a later failed refresh must not hide it:
  // the honest answer is the last report plus a warning that it may be stale.
  if (error && runs.length === 0) {
    return (
      <View style={styles.section}>
        <BBText variant="label">Agent runs</BBText>
        <ErrorBanner error={error} onRetry={onRetry} />
      </View>
    );
  }
  // A task that was never handed to an agent shows nothing at all: an empty
  // "Agent runs" heading would imply the feature had been used.
  if (runs.length === 0) {
    return null;
  }

  return (
    <View style={styles.section}>
      <BBText variant="label">{runs.length === 1 ? "Agent run" : `Agent runs · ${runs.length}`}</BBText>
      {error ? (
        <View style={styles.staleNotice}>
          <BBText variant="caption" color={colors.warningFg}>
            {STALE_NOTICE}
          </BBText>
          {onRetry ? (
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Check for a newer report"
              onPress={onRetry}
              style={styles.retry}
            >
              <BBText variant="caption" weight="medium" color={colors.infoFg}>
                Try again
              </BBText>
            </Pressable>
          ) : null}
        </View>
      ) : null}
      {loading ? (
        <BBText variant="micro" color={colors.fg6}>
          Checking for a newer report…
        </BBText>
      ) : null}
      {runsNewestFirst(runs).map((run) => (
        <RunCard
            key={run.id}
            run={run}
            online={online}
            onRunUpdated={onRunUpdated}
            onRetryHandoff={onRetryHandoff}
          />
      ))}
    </View>
  );
}

function RunCard({
  run,
  online,
  onRunUpdated,
  onRetryHandoff,
}: {
  run: AgentRunResponse;
  online: boolean;
  onRunUpdated: (run: AgentRunResponse) => void;
  onRetryHandoff?: (run: AgentRunResponse) => void;
}) {
  const reply = useReplyToAgentRun();
  const cancel = useCancelAgentRun();
  const checkDelivery = useCheckAgentRunDelivery();

  // One key per user intent, held across retries: a reply that never got an
  // answer may still have reached the server, and a fresh key would turn that
  // ambiguity into a second command.
  const replyKey = useIntentKey();
  const cancelKey = useIntentKey();
  const checkKey = useIntentKey();
  const replyIntent = useRef<ReplyIntentSnapshot | null>(null);
  const [replyIntentConflict, setReplyIntentConflict] = useState(false);

  const showQuestion = awaitsAnswer(run);
  const displayedQuestionIdentity = questionIdentity(run);
  const [answerDraft, setAnswerDraft] = useState({
    questionIdentity: displayedQuestionIdentity,
    acceptingAnswer: showQuestion,
    message: "",
  });
  if (
    answerDraft.questionIdentity !== displayedQuestionIdentity ||
    answerDraft.acceptingAnswer !== showQuestion
  ) {
    setAnswerDraft({
      questionIdentity: displayedQuestionIdentity,
      acceptingAnswer: showQuestion,
      message: "",
    });
  }
  const answer =
    showQuestion && answerDraft.questionIdentity === displayedQuestionIdentity
      ? answerDraft.message
      : "";
  const setAnswer = (message: string) => {
    setAnswerDraft({
      questionIdentity: displayedQuestionIdentity,
      acceptingAnswer: showQuestion,
      message,
    });
  };
  const replyGuard = canReply(run, run.capabilities, { online });
  const cancelGuard = canCancel(run, run.capabilities, { online });
  const linkGuard = run.result_link ? canOpenResultLink(run) : null;
  // Secondary lines, never the primary label: what the agent said about
  // cancellation, and whether the result fitted, are separate facts from what
  // the run is doing.
  const cancelOutcome = cancelOutcomeCopy(run);
  const tooLarge = resultAvailabilityCopy(run);
  const events = sortedEvents(run);
  const dispatchDetail = run.content_expired ? null : dispatchStateDetail(run);

  useEffect(() => {
    const held = replyIntent.current;
    if (held && (!showQuestion || held.questionIdentity !== displayedQuestionIdentity)) {
      replyKey.settle();
      replyIntent.current = null;
    }
  }, [displayedQuestionIdentity, replyKey, showQuestion]);

  const sendAnswer = () => {
    const trimmed = answer.trim();
    if (!trimmed || !replyGuard.ok) {
      return;
    }
    const held = replyIntent.current;
    if (held && (held.message !== trimmed || held.questionIdentity !== displayedQuestionIdentity)) {
      setReplyIntentConflict(true);
      return;
    }
    setReplyIntentConflict(false);
    const intent =
      held?.message === trimmed && held.questionIdentity === displayedQuestionIdentity
        ? held
        : {
            message: trimmed,
            questionIdentity: displayedQuestionIdentity,
            expectedRevision: run.revision,
            idempotencyKey: replyKey.current(`${displayedQuestionIdentity}:${trimmed}`),
          };
    replyIntent.current = intent;
    reply.mutate(
      {
        runId: run.id,
        payload: {
          message: intent.message,
          expected_revision: intent.expectedRevision,
        },
        idempotencyKey: intent.idempotencyKey,
      },
      {
        onSuccess: (updated) => {
          replyKey.settle();
          replyIntent.current = null;
          setAnswer("");
          onRunUpdated(updated);
        },
        onError: (error) => {
          if (isDefinitiveMutationFailure(error)) {
            replyKey.settle();
            replyIntent.current = null;
          }
        },
      },
    );
  };

  const runCheckAgain = () => {
    if (!online) {
      return;
    }
    checkDelivery.mutate(
      // No identifiers of its own: the correlation ID and the message ID are on
      // the run, so this can only ever repeat the same check. The key is held
      // across retries for the same reason a reply's is. The revision is the
      // run this control was rendered from: the check can end in a send, so it
      // names the state the user was actually looking at (`mobile/AGENTS.md`).
      {
        runId: run.id,
        payload: { current_password: null, expected_revision: run.revision },
        idempotencyKey: checkKey.current(),
      },
      {
        onSuccess: (updated) => {
          checkKey.settle();
          onRunUpdated(updated);
        },
        onError: (error) => {
          if (isDefinitiveMutationFailure(error)) {
            checkKey.settle();
          }
        },
      },
    );
  };

  const requestCancel = () => {
    cancel.mutate(
      { runId: run.id, idempotencyKey: cancelKey.current() },
      {
        onSuccess: (updated) => {
          cancelKey.settle();
          onRunUpdated(updated);
        },
        onError: (error) => {
          if (isDefinitiveMutationFailure(error)) {
            cancelKey.settle();
          }
        },
      },
    );
  };

  return (
    <View style={styles.card}>
      <View style={styles.head}>
        <BBText variant="body" weight="medium" color={colors.fg1}>
          {run.agent_name}
        </BBText>
        <View style={styles.statePill}>
          <BBText variant="micro" weight="medium" color={colors.infoFg}>
            {run.primary_state_label}
          </BBText>
        </View>
      </View>
      <BBText variant="micro" color={colors.fg6}>
        {lastContactLabel(run.last_contact_at)}
      </BBText>

      {run.content_expired ? (
        <BBText variant="caption" color={colors.fg5}>
          {EXPIRED_CONTENT_NOTICE}
        </BBText>
      ) : (
        <>
          {run.progress_text ? (
            <BBText variant="caption" color={colors.fg3}>
              {run.progress_text}
            </BBText>
          ) : null}

          {showQuestion ? (
            <View style={styles.question}>
              <BBText variant="caption" color={colors.warningFg}>
                {run.question_text}
              </BBText>
              {replyGuard.ok ? (
                <>
                  <TextInput
                    accessibilityLabel="Your answer"
                    style={styles.input}
                    value={answer}
                    onChangeText={setAnswer}
                    placeholder="Answer the agent"
                    placeholderTextColor={colors.fg6}
                    editable={!reply.isPending}
                    multiline
                  />
                  <Button
                    variant="secondary"
                    onPress={sendAnswer}
                    disabled={!answer.trim()}
                    loading={reply.isPending}
                  >
                    Send answer
                  </Button>
                </>
              ) : (
                <BBText variant="micro" color={colors.fg5}>
                  {replyGuard.reason}
                </BBText>
              )}
              {reply.isError ? <ErrorBanner error={reply.error} /> : null}
              {replyIntentConflict ? (
                <BBText variant="micro" color={colors.warningFg}>
                  The previous reply outcome is unknown. Restore the exact original answer to retry safely.
                </BBText>
              ) : null}
            </View>
          ) : null}

          {run.blocked_reason ? (
            // M-03-S09. The run needs the user and the agent named why, so the
            // reason is stated verbatim — and stated *without* a control. What
            // blocks an agent here is a credential problem at the agent, which
            // no answer typed into Brain Buddy can solve; a reply field beside
            // this sentence is how a secret gets forwarded to a third party.
            <View style={styles.question}>
              <BBText variant="caption" color={colors.warningFg}>
                {run.blocked_reason}
              </BBText>
            </View>
          ) : null}

          {run.result_text ? (
            <BBText variant="caption" color={colors.fg3}>
              {run.result_text}
            </BBText>
          ) : null}

          {tooLarge ? (
            <BBText variant="caption" weight="medium" color={colors.fg3}>
              {tooLarge}
            </BBText>
          ) : null}

          {run.artifacts_summary.map((artifact, index) => (
            <BBText
              key={`${artifact.name ?? artifact.kind}-${index}`}
              variant="micro"
              color={colors.fg5}
            >
              {artifactPlaceholderCopy(artifact)}
            </BBText>
          ))}

          {run.result_link && linkGuard ? (
            // Inert text beside a 44pt copy control, whatever the scheme
            // (M-03-S10). Nothing is tappable, opened or fetched: a link the
            // product makes tappable is a link the product is vouching for, and
            // Brain Buddy verified nothing about where it leads.
            <View style={styles.field}>
              <BBText variant="caption" color={colors.fg5} selectable style={styles.mono}>
                {run.result_link}
              </BBText>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={`Copy link for ${run.agent_name}`}
                onPress={() => {
                  void copyToClipboard(run.result_link as string);
                }}
                style={styles.rowAction}
              >
                <BBText variant="caption" weight="medium" color={colors.infoFg}>
                  Copy link
                </BBText>
              </Pressable>
              {linkGuard.ok ? null : (
                <BBText variant="micro" color={colors.fg6}>
                  {linkGuard.reason}
                </BBText>
              )}
            </View>
          ) : null}

          {run.failure_reason ? (
            <BBText variant="caption" color={colors.dangerFg}>
              {run.failure_reason}
            </BBText>
          ) : null}
        </>
      )}

      {run.reply_pending ? (
        <BBText variant="micro" color={colors.fg5}>
          Your answer was sent but the agent has not acknowledged it yet.
        </BBText>
      ) : null}
      {cancelOutcome ? (
        <BBText variant="micro" color={colors.fg5}>
          {cancelOutcome}
        </BBText>
      ) : null}
      {run.cancel_requested && !cancelOutcome ? (
        <BBText variant="micro" color={colors.fg5}>
          Cancellation was requested. The agent has not confirmed it, so the work may still be
          running.
        </BBText>
      ) : null}
      {run.agent_task_missing ? (
        <BBText variant="micro" color={colors.fg5}>
          The agent no longer reports this run. Brain Buddy kept everything it had already
          observed and is not claiming the work failed.
        </BBText>
      ) : null}
      {run.stopped_reporting ? (
        <BBText variant="micro" color={colors.fg5}>
          No report since the last contact above. Brain Buddy does not know whether the agent is
          still working.
        </BBText>
      ) : null}
      {run.connection_disconnected ? (
        <BBText variant="micro" color={colors.fg5}>
          This agent was disconnected. Disconnecting did not cancel any work it had already
          accepted.
        </BBText>
      ) : null}
      {dispatchDetail ? (
        <BBText variant="micro" color={colors.fg5}>
          {dispatchDetail}
        </BBText>
      ) : null}
      {canCheckDelivery(run) ? (
        <>
          <BBText variant="micro" color={colors.fg5}>
            Runs the same check again with the same correlation ID and the same message ID. It
            is never a new send.
          </BBText>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Check again"
            accessibilityState={{ disabled: !online }}
            disabled={!online}
            onPress={runCheckAgain}
            style={styles.rowAction}
          >
            <BBText variant="caption" weight="medium" color={colors.infoFg}>
              Check again
            </BBText>
          </Pressable>
          {/* A refused or failed check must not look like a check that found
              nothing: the reason and its correlation reference belong beside
              the control that produced them, exactly as reply and cancel do. */}
          {checkDelivery.isError ? <ErrorBanner error={checkDelivery.error} /> : null}
        </>
      ) : null}
      {canRetryHandoff(run) ? (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Try this hand-off again"
          onPress={() => onRetryHandoff?.(run)}
          style={styles.rowAction}
        >
          <BBText variant="caption" weight="medium" color={colors.infoFg}>
            Try this hand-off again
          </BBText>
        </Pressable>
      ) : null}

      {events.length > 0 ? (
        <View style={styles.timeline}>
          {events.map((event) => (
            <View key={event.id} style={styles.event}>
              <BBText variant="micro" weight="medium" color={colors.fg4}>
                {timelineRowLabel(event)}
              </BBText>
              {event.kind === "task_succession" && event.previous_agent_task_id ? (
                // Both identifiers, because the point of the row is that the
                // one the user saw yesterday is not the one being observed now.
                <BBText variant="micro" color={colors.fg6}>
                  {event.previous_agent_task_id} → {event.new_agent_task_id}
                </BBText>
              ) : null}
              {event.summary && event.kind !== "task_succession" ? (
                <BBText variant="micro" color={colors.fg5}>
                  {event.summary}
                </BBText>
              ) : null}
            </View>
          ))}
        </View>
      ) : null}

      {cancelGuard.ok ? (
        <Button variant="ghost" onPress={requestCancel} loading={cancel.isPending}>
          Request cancellation
        </Button>
      ) : null}
      {cancel.isError ? <ErrorBanner error={cancel.error} /> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  // 44pt: a real decision, tappable like one.
  rowAction: {
    minHeight: 44,
    justifyContent: "center",
  },
  section: {
    gap: space.s2,
  },
  staleNotice: {
    backgroundColor: colors.warningBg,
    borderWidth: 1,
    borderColor: colors.warningBorder,
    borderRadius: radii.sm,
    padding: space.s3,
    gap: space.s1,
  },
  retry: {
    minHeight: 44,
    justifyContent: "center",
  },
  card: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radii.card,
    backgroundColor: colors.surfaceRaised,
    padding: space.s4,
    gap: space.s2,
  },
  head: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: space.s2,
  },
  statePill: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radii.full,
    paddingHorizontal: space.s2,
    paddingVertical: 2,
  },
  question: {
    backgroundColor: colors.warningBg,
    borderWidth: 1,
    borderColor: colors.warningBorder,
    borderRadius: radii.sm,
    padding: space.s3,
    gap: space.s2,
  },
  field: {
    gap: space.s1,
  },
  linkAction: {
    minHeight: 44,
    justifyContent: "center",
  },
  mono: {
    fontFamily: "Menlo",
    fontSize: typeScale.micro,
  },
  input: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radii.sm,
    paddingHorizontal: space.s3,
    paddingVertical: space.s3,
    fontSize: typeScale.body,
    fontFamily: fonts.regular,
    color: colors.fg1,
    backgroundColor: colors.surfaceRaised,
    minHeight: 44,
  },
  timeline: {
    borderTopWidth: 1,
    borderTopColor: colors.border,
    paddingTop: space.s2,
    gap: space.s1,
  },
  event: {
    gap: 1,
  },
});
