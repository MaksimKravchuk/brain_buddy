import { useQueryClient } from "@tanstack/react-query";
import { useLocalSearchParams, useRouter } from "expo-router";
import { Trash2, X } from "lucide-react-native";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  AppState,
  Pressable,
  ScrollView,
  StyleSheet,
  TextInput,
  View,
} from "react-native";

import { useApi } from "@/auth/SessionProvider";
import type { BrainDumpOperationResponse, BrainDumpProposal } from "@/api/types";
import { BBText } from "@/components/BBText";
import { Button } from "@/components/Button";
import { ErrorBanner } from "@/components/ErrorBanner";
import { Screen } from "@/components/Screen";
import {
  applyOperation,
  canCommit,
  isPollable,
  nextPollDelay,
  openConflictCount,
  processingStageLabel,
  visibleProposals,
} from "@/braindump/machine";
import { newIdempotencyKey } from "@/utils/ids";
import { colors, fonts, minHitTarget, radii, space, type as typeScale } from "@/theme/tokens";

export default function BrainDumpOperationScreen() {
  const { operationId } = useLocalSearchParams<{ operationId: string }>();
  const router = useRouter();
  const api = useApi();
  const queryClient = useQueryClient();

  const [operation, setOperation] = useState<BrainDumpOperationResponse | null>(null);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [actionPending, setActionPending] = useState(false);

  const operationRef = useRef<BrainDumpOperationResponse | null>(null);
  const patchQueueRef = useRef<Promise<unknown>>(Promise.resolve());
  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pollDelayRef = useRef<number | null>(null);

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

  // Poll while the server is working; pause in background, refresh on return.
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
        schedule(fresh?.status);
      }, delay);
    };

    (async () => {
      const first = await fetchOnce();
      schedule(first?.status);
    })();

    const subscription = AppState.addEventListener("change", (state) => {
      if (state === "active") {
        if (pollTimerRef.current) {
          clearTimeout(pollTimerRef.current);
        }
        pollDelayRef.current = null;
        fetchOnce().then((fresh) => schedule(fresh?.status));
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
    (proposalId: string, patch: { title?: string; deleted?: boolean; conflict_resolution?: "keep" | "accept" }) => {
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
    async (action: "commit" | "retry" | "review_provisional" | "cancel" | "delete_raw_audio") => {
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
        if (isPollable(next.status)) {
          pollDelayRef.current = null;
          const fresh = await fetchOnce();
          if (fresh && isPollable(fresh.status)) {
            // Re-arm the poll loop for committing.
            pollDelayRef.current = null;
            const tick = async () => {
              const latest = await fetchOnce();
              if (latest && isPollable(latest.status)) {
                const delay = nextPollDelay(pollDelayRef.current);
                pollDelayRef.current = delay;
                pollTimerRef.current = setTimeout(tick, delay);
              }
            };
            const delay = nextPollDelay(pollDelayRef.current);
            pollDelayRef.current = delay;
            pollTimerRef.current = setTimeout(tick, delay);
          }
        }
        if (action === "commit" || action === "cancel") {
          queryClient.invalidateQueries({ queryKey: ["tasks"] });
        }
      } catch (error) {
        setActionError(error);
        await fetchOnce();
      } finally {
        setActionPending(false);
      }
    },
    [api, fetchOnce, queryClient, remember],
  );

  const leave = () => {
    queryClient.invalidateQueries({ queryKey: ["tasks"] });
    router.dismissAll();
  };

  if (!operation) {
    return (
      <Screen padTop padBottom>
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

  return (
    <Screen padTop padBottom>
      <View style={styles.header}>
        <Pressable accessibilityRole="button" onPress={leave} style={styles.headerButton}>
          <BBText variant="body" color={colors.brandPrimary}>
            Close
          </BBText>
        </Pressable>
        <BBText variant="subtitle">Brain dump</BBText>
        <View style={styles.headerButton} />
      </View>

      {isPollable(status) ? (
        <View style={styles.center}>
          <ActivityIndicator color={colors.brandPrimary} size="large" />
          <BBText variant="subtitle">{processingStageLabel(status)}</BBText>
          <BBText variant="caption" color={colors.fg5}>
            You can keep the app open — this usually takes a few seconds.
          </BBText>
        </View>
      ) : status === "awaiting_confirmation" ? (
        <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
          <BBText variant="display">{`Review ${proposals.length} ${proposals.length === 1 ? "task" : "tasks"}`}</BBText>
          <BBText variant="body" color={colors.fg5}>
            Edit before they land in your inbox. Nothing is saved until you confirm.
          </BBText>

          {provisionalOnly ? (
            <View style={styles.warnCard}>
              <BBText variant="body" color={colors.warningFg}>
                Provisional only — the accurate transcript wasn't available, so these come from the
                live preview. Review them carefully.
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
            {proposals.length === 0 ? (
              <View style={styles.card}>
                <BBText variant="body" color={colors.fg5}>
                  No tasks were proposed from this dump.
                </BBText>
              </View>
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
                accessibilityLabel="Delete recording"
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

          <Button onPress={() => runCommand("commit")} disabled={!commitReady} loading={actionPending}>
            {`Confirm ${proposals.length} ${proposals.length === 1 ? "addition" : "additions"}`}
          </Button>
          <Button variant="ghost" onPress={() => runCommand("cancel")} disabled={actionPending}>
            Discard everything
          </Button>
        </ScrollView>
      ) : status === "completed" ? (
        <View style={styles.center}>
          <BBText variant="display" style={styles.centerText}>
            {`Saved ${operation.committed_task_ids.length} to inbox`}
          </BBText>
          <BBText variant="body" color={colors.fg5} style={styles.centerText}>
            Clarify them into next actions when you're ready.
          </BBText>
          <Button onPress={leave}>Done</Button>
        </View>
      ) : status === "cancelled" ? (
        <View style={styles.center}>
          <BBText variant="title">Dump discarded</BBText>
          <BBText variant="body" color={colors.fg5}>
            Nothing was saved and the recording was deleted.
          </BBText>
          <Button onPress={leave}>Done</Button>
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
            <Button variant="ghost" onPress={() => runCommand("cancel")} disabled={actionPending}>
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
  return "The audio was kept — you can retry, review the provisional tasks, or discard.";
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
  const [draft, setDraft] = useState(proposal.title);

  // Adopt reconciled wording unless the user is the author of the change.
  useEffect(() => {
    setDraft(proposal.title);
  }, [proposal.title]);

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
          <X size={18} color={colors.fg5} strokeWidth={2} />
        </Pressable>
      </View>
      <View style={styles.proposalMeta}>
        <BBText variant="micro" color={colors.fg5}>
          {proposal.user_edited
            ? "Edited by you"
            : proposal.status === "reconciled"
              ? "Reconciled"
              : proposal.status === "conflicted"
                ? "Needs a decision"
                : "Provisional"}
        </BBText>
      </View>
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
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: space.s5,
    paddingVertical: space.s3,
  },
  headerButton: {
    minWidth: 64,
    minHeight: minHitTarget,
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
    padding: space.s5,
    gap: space.s4,
  },
  card: {
    backgroundColor: colors.surfaceRaised,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radii.card,
    padding: space.s4,
    gap: space.s2,
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
    gap: space.s2,
  },
  proposalRow: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: space.s2,
  },
  proposalInput: {
    flex: 1,
    fontSize: typeScale.body,
    lineHeight: Math.round(typeScale.body * 1.5),
    fontFamily: fonts.medium,
    color: colors.fg1,
    padding: 0,
  },
  proposalDelete: {
    padding: space.s1,
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
});
