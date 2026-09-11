import { useQueryClient } from "@tanstack/react-query";
import { useLocalSearchParams, useRouter } from "expo-router";
import { Trash2, X } from "lucide-react-native";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  AppState,
  Pressable,
  ScrollView,
  StyleSheet,
  TextInput,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useApi } from "@/auth/SessionProvider";
import type { BrainDumpOperationResponse, BrainDumpProposal } from "@/api/types";
import { BBText } from "@/components/BBText";
import { Button } from "@/components/Button";
import { ErrorBanner } from "@/components/ErrorBanner";
import { Screen } from "@/components/Screen";
import { PaneHead } from "@/components/shell/PaneHead";
import { useToast } from "@/components/ToastHost";
import {
  applyOperation,
  canCommit,
  heardTranscript,
  isPollable,
  nextPollDelay,
  openConflictCount,
  processingStageLabel,
  visibleProposals,
} from "@/braindump/machine";
import { newIdempotencyKey } from "@/utils/ids";
import { useServerDraft } from "@/utils/useServerDraft";
import { colors, fonts, minHitTarget, radii, shadows, space, type as typeScale } from "@/theme/tokens";

interface DiscardPrompt {
  title: string;
  message: string;
  keep: string;
  discard: string;
}

/** Discarding from the failure screen: the recording itself is what is lost. */
const DISCARD_RECORDING: DiscardPrompt = {
  title: "Discard this recording?",
  message: "The audio and transcript are deleted and nothing is saved.",
  keep: "Keep",
  discard: "Discard recording",
};

/** Discarding from the review: the reviewed tasks go with the recording. */
const DISCARD_REVIEW: DiscardPrompt = {
  title: "Discard all tasks?",
  message: "Nothing is saved to Inbox and the recording is deleted.",
  keep: "Keep reviewing",
  discard: "Discard all tasks",
};

/**
 * FR-007: a destructive exit asks first, in the platform dialog. The safe
 * answer is listed first and styled `cancel`, so the platform treats it as
 * the default; only the destructive answer runs `onConfirm`, and dismissing
 * the dialog any other way (Android back, a tap outside) keeps everything as
 * it was.
 */
function confirmDiscard(prompt: DiscardPrompt, onConfirm: () => void): void {
  Alert.alert(
    prompt.title,
    prompt.message,
    [
      { text: prompt.keep, style: "cancel" },
      { text: prompt.discard, style: "destructive", onPress: onConfirm },
    ],
    { cancelable: true },
  );
}

export default function BrainDumpOperationScreen() {
  const { operationId } = useLocalSearchParams<{ operationId: string }>();
  const router = useRouter();
  const api = useApi();
  const queryClient = useQueryClient();
  const insets = useSafeAreaInsets();
  const toast = useToast();

  const [operation, setOperation] = useState<BrainDumpOperationResponse | null>(null);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [actionPending, setActionPending] = useState(false);

  const operationRef = useRef<BrainDumpOperationResponse | null>(null);
  const patchQueueRef = useRef<Promise<unknown>>(Promise.resolve());
  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pollDelayRef = useRef<number | null>(null);
  const closedRef = useRef(false);

  const remember = useCallback((incoming: BrainDumpOperationResponse) => {
    const next = applyOperation(operationRef.current, incoming);
    operationRef.current = next;
    setOperation(next);
    return next;
  }, []);

  const fetchOnce = useCallback(async () => {
    try {
      const fresh = await api.getBrainDump(operationId);
      setLoadError(null);
      return remember(fresh);
    } catch (error) {
      setLoadError(error);
      return null;
    }
  }, [api, operationId, remember]);

  const leave = useCallback(
    (message?: string) => {
      if (closedRef.current) {
        return;
      }
      closedRef.current = true;
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
      router.dismissAll();
      if (message) {
        toast(message);
      }
    },
    [queryClient, router, toast],
  );

  // Poll while the server is working; pause in background, refresh on return.
  // A transient fetch failure must never end the loop: fall back to the last
  // known status (the backoff keeps growing) and only stop once a FETCHED
  // status is settled or interactive.
  useEffect(() => {
    let disposed = false;

    const schedule = (status: string | undefined) => {
      if (disposed || !status || !isPollable(status as never)) {
        pollDelayRef.current = null;
        return;
      }
      const delay = nextPollDelay(pollDelayRef.current);
      pollDelayRef.current = delay;
      pollTimerRef.current = setTimeout(async () => {
        const fresh = await fetchOnce();
        schedule(fresh ? fresh.status : operationRef.current?.status);
      }, delay);
    };

    (async () => {
      const first = await fetchOnce();
      schedule(first ? first.status : operationRef.current?.status);
    })();

    const subscription = AppState.addEventListener("change", (state) => {
      if (state === "active") {
        if (pollTimerRef.current) {
          clearTimeout(pollTimerRef.current);
        }
        pollDelayRef.current = null;
        fetchOnce().then((fresh) => schedule(fresh ? fresh.status : operationRef.current?.status));
      } else if (pollTimerRef.current) {
        clearTimeout(pollTimerRef.current);
      }
    });

    return () => {
      disposed = true;
      subscription.remove();
      if (pollTimerRef.current) {
        clearTimeout(pollTimerRef.current);
      }
    };
  }, [fetchOnce]);

  /**
   * Proposal edits share the operation revision, so they are serialized:
   * each PATCH uses the revision produced by the previous one.
   */
  const enqueueProposalPatch = useCallback(
    (
      proposalId: string,
      patch: { title?: string; deleted?: boolean; conflict_resolution?: "keep" | "accept" },
    ) => {
      patchQueueRef.current = patchQueueRef.current
        .then(async () => {
          const current = operationRef.current;
          if (!current) {
            return;
          }
          const updated = await api.updateBrainDumpProposal(
            current.id,
            proposalId,
            { ...patch, expected_revision: current.revision },
            newIdempotencyKey(),
          );
          remember(updated);
          setActionError(null);
        })
        .catch(async (error) => {
          setActionError(error);
          await fetchOnce();
        });
      return patchQueueRef.current;
    },
    [api, fetchOnce, remember],
  );

  const runCommand = useCallback(
    async (
      action:
        | "commit"
        | "retry"
        | "review_provisional"
        | "reconcile_preview"
        | "cancel"
        | "delete_raw_audio",
    ) => {
      const current = operationRef.current;
      if (!current) {
        return;
      }
      setActionPending(true);
      setActionError(null);
      try {
        await patchQueueRef.current;
        const updated = await api.commandBrainDump(
          current.id,
          action,
          operationRef.current?.revision ?? current.revision,
          newIdempotencyKey(),
        );
        const next = remember(updated);

        if (action === "cancel") {
          leave("Dump discarded — nothing was saved");
          return;
        }
        if (next.status === "completed") {
          leave(`Saved ${next.committed_task_ids.length} to inbox`);
          return;
        }
        if (isPollable(next.status)) {
          const tick = async () => {
            const latest = await fetchOnce();
            if (!latest) {
              // Transient failure: keep polling from the last known status.
              if (isPollable(operationRef.current?.status ?? next.status)) {
                const delay = nextPollDelay(pollDelayRef.current);
                pollDelayRef.current = delay;
                pollTimerRef.current = setTimeout(tick, delay);
              }
              return;
            }
            if (latest.status === "completed") {
              leave(`Saved ${latest.committed_task_ids.length} to inbox`);
              return;
            }
            if (isPollable(latest.status)) {
              const delay = nextPollDelay(pollDelayRef.current);
              pollDelayRef.current = delay;
              pollTimerRef.current = setTimeout(tick, delay);
            }
          };
          pollDelayRef.current = null;
          const delay = nextPollDelay(pollDelayRef.current);
          pollDelayRef.current = delay;
          pollTimerRef.current = setTimeout(tick, delay);
        }
      } catch (error) {
        setActionError(error);
        await fetchOnce();
      } finally {
        setActionPending(false);
      }
    },
    [api, fetchOnce, leave, remember],
  );

  // Every exit that runs `cancel` deletes the audio and the transcript, so
  // each one is confirmed first (FR-007). The failure screen loses a
  // recording; the review loses its reviewed tasks with it, so both review
  // exits share one prompt.
  const discardRecording = () => confirmDiscard(DISCARD_RECORDING, () => runCommand("cancel"));
  const discardReview = () => confirmDiscard(DISCARD_REVIEW, () => runCommand("cancel"));

  if (!operation) {
    return (
      <Screen>
        <View style={styles.center}>
          {loadError ? (
            <ErrorBanner error={loadError} onRetry={() => fetchOnce()} />
          ) : (
            <ActivityIndicator color={colors.brandPrimary} size="large" />
          )}
        </View>
      </Screen>
    );
  }

  const status = operation.status;
  const proposals = visibleProposals(operation);
  const conflicts = openConflictCount(operation);
  const commitReady = canCommit(operation);
  const provisionalOnly = operation.reconciliation_quality === "provisional_only";
  const recoveryActions = operation.available_recovery_actions ?? [];
  // FR-005: a review with no surviving task cannot be saved; it says so and
  // shows what was heard instead of counting tasks it does not have.
  const emptyReview = proposals.length === 0;
  const heard = emptyReview ? heardTranscript(operation.segments) : [];

  const headRow = (
    <View style={[styles.head, { paddingTop: insets.top + space.s3 }]}>
      <View style={styles.headSpacer} />
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Discard recording"
        onPress={discardReview}
        disabled={actionPending}
        style={styles.iconButton}
      >
        <Trash2 size={18} color={colors.fg4} strokeWidth={2} />
      </Pressable>
    </View>
  );

  return (
    <Screen>
      {isPollable(status) ? (
        <View style={styles.center}>
          <ActivityIndicator color={colors.brandPrimary} size="large" />
          <BBText variant="subtitle">{processingStageLabel(status)}</BBText>
          <BBText variant="caption" color={colors.fg5}>
            You can keep the app open — this usually takes a few seconds.
          </BBText>
        </View>
      ) : status === "awaiting_confirmation" ? (
        <>
          {headRow}
          <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
            <PaneHead
              title={
                emptyReview
                  ? "No tasks to review"
                  : `Review ${proposals.length} ${proposals.length === 1 ? "task" : "tasks"}`
              }
              meta={
                emptyReview
                  ? "Nothing actionable came out of this dump"
                  : "Edit before they land in your inbox. Nothing is saved until you confirm."
              }
            />

            {provisionalOnly ? (
              <View style={styles.warnCard}>
                <BBText variant="body" color={colors.warningFg}>
                  Provisional only — the accurate transcript wasn&apos;t available, so these come from
                  the live preview. Review them carefully.
                </BBText>
              </View>
            ) : null}

            {actionError ? <ErrorBanner error={actionError} /> : null}

            <View style={styles.proposalList}>
              {proposals.map((proposal) => (
                <ProposalCard
                  key={proposal.id}
                  proposal={proposal}
                  onTitleCommit={(title) => {
                    if (title.trim() && title.trim() !== proposal.title) {
                      enqueueProposalPatch(proposal.id, { title: title.trim() });
                    }
                  }}
                  onDelete={() => enqueueProposalPatch(proposal.id, { deleted: true })}
                  onResolveConflict={(resolution) =>
                    enqueueProposalPatch(proposal.id, { conflict_resolution: resolution })
                  }
                />
              ))}
              {emptyReview ? (
                <>
                  <View style={styles.card}>
                    <BBText variant="body" color={colors.fg5}>
                      No tasks were proposed from this dump. Discard it to record again.
                    </BBText>
                  </View>
                  <View style={styles.heard}>
                    <BBText variant="label">What was heard</BBText>
                    {heard.length > 0 ? (
                      heard.map((segment) => (
                        <BBText key={segment.id} variant="body">
                          {segment.text}
                        </BBText>
                      ))
                    ) : (
                      <BBText variant="body" color={colors.fg5}>
                        No transcript was captured for this recording.
                      </BBText>
                    )}
                  </View>
                </>
              ) : null}
            </View>

            {operation.raw_audio_present ? (
              <View style={styles.audioRow}>
                <View style={styles.audioText}>
                  <BBText variant="caption" color={colors.fg5}>
                    {operation.raw_audio_expires_at
                      ? `Recording kept until ${new Date(operation.raw_audio_expires_at).toLocaleString()}`
                      : "Recording kept temporarily"}
                  </BBText>
                </View>
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel="Delete retained audio"
                  onPress={() => runCommand("delete_raw_audio")}
                  style={styles.audioDelete}
                >
                  <Trash2 size={16} color={colors.dangerFg} strokeWidth={1.75} />
                  <BBText variant="caption" color={colors.dangerFg}>
                    Delete now
                  </BBText>
                </Pressable>
              </View>
            ) : null}

            {conflicts > 0 ? (
              <BBText variant="caption" color={colors.warningFg}>
                {`Resolve ${conflicts} ${conflicts === 1 ? "conflict" : "conflicts"} before confirming.`}
              </BBText>
            ) : null}
          </ScrollView>

          <View style={[styles.sheet, { paddingBottom: insets.bottom + space.s5 }]}>
            {emptyReview ? null : (
              <Button
                onPress={() => runCommand("commit")}
                disabled={!commitReady}
                loading={actionPending}
                style={styles.sheetButton}
              >
                {`Confirm ${proposals.length} ${proposals.length === 1 ? "addition" : "additions"}`}
              </Button>
            )}
            <Pressable
              accessibilityRole="button"
              onPress={discardReview}
              disabled={actionPending}
              style={styles.ghostAction}
            >
              <BBText variant="caption" weight="medium" color={colors.fg5}>
                Discard all
              </BBText>
            </Pressable>
          </View>
        </>
      ) : status === "completed" ? (
        <View style={styles.center}>
          <BBText variant="display" style={styles.centerText}>
            {`Saved ${operation.committed_task_ids.length} to inbox`}
          </BBText>
          <BBText variant="body" color={colors.fg5} style={styles.centerText}>
            Clarify them into next actions when you&apos;re ready.
          </BBText>
          <Button onPress={() => leave()}>Done</Button>
        </View>
      ) : status === "cancelled" ? (
        <View style={styles.center}>
          <BBText variant="title">Dump discarded</BBText>
          <BBText variant="body" color={colors.fg5}>
            Nothing was saved and the recording was deleted.
          </BBText>
          <Button onPress={() => leave()}>Done</Button>
        </View>
      ) : (
        <View style={styles.center}>
          <View style={styles.errorCard}>
            <BBText variant="title" color={colors.dangerFg}>
              {status === "retryable_error" ? "Processing hit a snag" : "Couldn't finish"}
            </BBText>
            <BBText variant="body" color={colors.fg4}>
              {describeFailure(operation)}
            </BBText>
          </View>
          {actionError ? <ErrorBanner error={actionError} /> : null}
          <View style={styles.recoveryActions}>
            {recoveryActions.includes("retry") ? (
              <Button onPress={() => runCommand("retry")} loading={actionPending}>
                Try again
              </Button>
            ) : null}
            {recoveryActions.includes("review_provisional") ? (
              <Button
                variant="secondary"
                onPress={() => runCommand("review_provisional")}
                disabled={actionPending}
              >
                Review provisional tasks
              </Button>
            ) : null}
            {recoveryActions.includes("reconcile_preview") ? (
              // Offered only when the server still holds a browser-preview
              // transcript — a dump started on the web and resumed here.
              <View style={styles.recoveryOption}>
                <Button
                  variant="secondary"
                  onPress={() => runCommand("reconcile_preview")}
                  disabled={actionPending}
                >
                  Extract tasks from the browser transcript
                </Button>
                <BBText variant="caption" color={colors.fg5} style={styles.recoveryHint}>
                  Sends the browser transcript to the consented task-extraction provider. The result
                  is provisional and is reviewed before anything is saved.
                </BBText>
              </View>
            ) : null}
            <Button variant="ghost" onPress={discardRecording} disabled={actionPending}>
              Discard everything
            </Button>
          </View>
        </View>
      )}
    </Screen>
  );
}

function describeFailure(operation: BrainDumpOperationResponse): string {
  const failed = operation.provider_runs?.find(
    (run) => run.status === "terminal_error" || run.status === "retryable_error",
  );
  if (failed?.error) {
    return failed.error;
  }
  if (failed?.error_code) {
    return failed.error_code;
  }
  // Which recoveries apply is the server's call (`available_recovery_actions`),
  // so this line points at the buttons instead of enumerating them.
  return "The audio was kept — choose one of the options below, or discard everything.";
}

function ProposalCard({
  proposal,
  onTitleCommit,
  onDelete,
  onResolveConflict,
}: {
  proposal: BrainDumpProposal;
  onTitleCommit: (title: string) => void;
  onDelete: () => void;
  onResolveConflict: (resolution: "keep" | "accept") => void;
}) {
  // Adopt reconciled wording unless the user is the author of the change.
  const [draft, setDraft] = useServerDraft(proposal.title);

  const conflicts = proposal.conflicts ?? [];

  return (
    <View style={[styles.card, conflicts.length > 0 ? styles.cardConflicted : null]}>
      <View style={styles.proposalRow}>
        <TextInput
          style={styles.proposalInput}
          value={draft}
          onChangeText={setDraft}
          multiline
          onEndEditing={() => onTitleCommit(draft)}
        />
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Remove proposal"
          onPress={onDelete}
          hitSlop={8}
          style={styles.proposalDelete}
        >
          <X size={16} color={colors.fg6} strokeWidth={2} />
        </Pressable>
      </View>
      {proposal.user_edited || proposal.status === "conflicted" ? (
        <View style={styles.proposalMeta}>
          <BBText variant="micro" color={colors.fg5}>
            {proposal.user_edited ? "Edited by you" : "Needs a decision"}
          </BBText>
        </View>
      ) : null}
      {conflicts.map((conflict, index) => (
        <View key={`${conflict.field}-${index}`} style={styles.conflictBlock}>
          <BBText variant="caption" color={colors.warningFg}>
            {`Suggested ${conflict.field}: ${conflict.suggested_value ?? "—"}`}
          </BBText>
          <View style={styles.conflictButtons}>
            <Button
              variant="secondary"
              style={styles.conflictButton}
              onPress={() => onResolveConflict("keep")}
            >
              Keep mine
            </Button>
            <Button
              variant="secondary"
              style={styles.conflictButton}
              onPress={() => onResolveConflict("accept")}
            >
              Use suggestion
            </Button>
          </View>
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  head: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: space.s4,
    paddingBottom: space.s2,
  },
  headSpacer: {
    flex: 1,
  },
  iconButton: {
    width: minHitTarget,
    height: minHitTarget,
    margin: -space.s2,
    alignItems: "center",
    justifyContent: "center",
  },
  center: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    padding: space.s5,
    gap: space.s4,
  },
  centerText: {
    textAlign: "center",
  },
  scroll: {
    padding: space.s4,
    paddingTop: 18,
    gap: space.s4,
  },
  card: {
    backgroundColor: colors.surfaceRaised,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radii.card,
    padding: 14,
    gap: space.s2,
    ...shadows.soft,
  },
  cardConflicted: {
    borderColor: colors.warningBorder,
    backgroundColor: colors.warningBg,
  },
  warnCard: {
    backgroundColor: colors.warningBg,
    borderWidth: 1,
    borderColor: colors.warningBorder,
    borderRadius: radii.card,
    padding: space.s4,
  },
  errorCard: {
    backgroundColor: colors.dangerBg,
    borderWidth: 1,
    borderColor: colors.dangerBorder,
    borderRadius: radii.card,
    padding: space.s4,
    gap: space.s2,
    alignSelf: "stretch",
  },
  proposalList: {
    gap: 10,
  },
  heard: {
    gap: space.s2,
    paddingHorizontal: space.s1,
  },
  proposalRow: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: space.s2,
  },
  proposalInput: {
    flex: 1,
    fontSize: typeScale.body,
    lineHeight: Math.round(typeScale.body * 1.4),
    fontFamily: fonts.medium,
    color: colors.fg1,
    padding: 0,
  },
  proposalDelete: {
    padding: space.s1,
    marginTop: -2,
    marginRight: -4,
  },
  proposalMeta: {
    flexDirection: "row",
    gap: space.s2,
  },
  conflictBlock: {
    gap: space.s2,
    borderTopWidth: 1,
    borderTopColor: colors.warningBorder,
    paddingTop: space.s2,
  },
  conflictButtons: {
    flexDirection: "row",
    gap: space.s2,
  },
  conflictButton: {
    flex: 1,
    minHeight: 36,
  },
  audioRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: space.s3,
  },
  audioText: {
    flex: 1,
  },
  audioDelete: {
    flexDirection: "row",
    alignItems: "center",
    gap: space.s1,
    minHeight: minHitTarget,
    paddingHorizontal: space.s2,
  },
  recoveryActions: {
    alignSelf: "stretch",
    gap: space.s2,
  },
  recoveryOption: {
    gap: space.s2,
  },
  recoveryHint: {
    textAlign: "center",
    paddingHorizontal: space.s2,
  },
  sheet: {
    alignItems: "center",
    gap: space.s3,
    paddingTop: 14,
    paddingHorizontal: space.s4,
    backgroundColor: "rgba(255,255,255,0.9)",
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  sheetButton: {
    alignSelf: "stretch",
    minHeight: 46,
  },
  ghostAction: {
    minHeight: minHitTarget - 12,
    justifyContent: "center",
  },
});
