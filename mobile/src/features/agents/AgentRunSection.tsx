import { useEffect, useRef, useState } from "react";
import { Linking, Pressable, StyleSheet, TextInput, View } from "react-native";

import { isDefinitiveMutationFailure } from "@/api/client";
import { useCancelAgentRun, useReplyToAgentRun } from "@/api/hooks";
import type { AgentRunResponse } from "@/api/types";
import {
  EXPIRED_CONTENT_NOTICE,
  eventLabel,
  lastContactLabel,
  projectRunsAt,
  runsNewestFirst,
  sortedEvents,
} from "@/agents/machine";
import { BBText } from "@/components/BBText";
import { Button } from "@/components/Button";
import { ErrorBanner } from "@/components/ErrorBanner";
import { awaitsAnswer, canCancel, canOpenResultLink, canReply } from "@/lifecycle/agentGuards";
import { colors, fonts, radii, space, type as typeScale } from "@/theme/tokens";
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
  onRetry,
}: AgentRunSectionProps) {
  // Treat the local retention deadline as authoritative even if no network
  // response arrives at that instant. Only this redacted projection is rendered.
  const effectiveRuns = projectRunsAt(runs);
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
      {runsNewestFirst(effectiveRuns).map((run) => (
        <RunCard key={run.id} run={run} online={online} onRunUpdated={onRunUpdated} />
      ))}
    </View>
  );
}

function RunCard({
  run,
  online,
  onRunUpdated,
}: {
  run: AgentRunResponse;
  online: boolean;
  onRunUpdated: (run: AgentRunResponse) => void;
}) {
  const reply = useReplyToAgentRun();
  const cancel = useCancelAgentRun();

  // One key per user intent, held across retries: a reply that never got an
  // answer may still have reached the server, and a fresh key would turn that
  // ambiguity into a second command.
  const replyKey = useIntentKey();
  const cancelKey = useIntentKey();
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
  const events = sortedEvents(run);

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

          {run.result_text ? (
            <BBText variant="caption" color={colors.fg3}>
              {run.result_text}
            </BBText>
          ) : null}

          {run.result_link && linkGuard ? (
            linkGuard.ok ? (
              <View style={styles.field}>
                <BBText variant="caption" color={colors.fg4} selectable>
                  {run.result_link}
                </BBText>
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel={`Open result for ${run.agent_name}`}
                  onPress={() => {
                    void Linking.openURL(run.result_link as string);
                  }}
                  style={styles.linkAction}
                >
                  <BBText variant="caption" weight="medium" color={colors.infoFg}>
                    Open result
                  </BBText>
                </Pressable>
                <BBText variant="micro" color={colors.fg6}>
                  Opens a site outside Brain Buddy.
                </BBText>
              </View>
            ) : (
              // Only the server decides a link is a safe HTTPS destination
              // (FR-014); anything else stays text and is never opened.
              <View style={styles.field}>
                <BBText variant="caption" color={colors.fg5} selectable style={styles.mono}>
                  {run.result_link}
                </BBText>
                <BBText variant="micro" color={colors.fg6}>
                  {linkGuard.reason}
                </BBText>
              </View>
            )
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
      {run.cancel_requested ? (
        <BBText variant="micro" color={colors.fg5}>
          Cancellation was requested. The agent has not confirmed it, so the work may still be
          running.
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
      {run.dispatch_state === "delivery_unconfirmed" ? (
        <BBText variant="micro" color={colors.fg5}>
          Brain Buddy could not confirm the agent received this hand-off. It was not re-sent.
        </BBText>
      ) : null}

      {events.length > 0 ? (
        <View style={styles.timeline}>
          {events.map((event) => (
            <View key={event.id} style={styles.event}>
              <BBText variant="micro" weight="medium" color={colors.fg4}>
                {eventLabel(event.type)}
              </BBText>
              {event.summary ? (
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
