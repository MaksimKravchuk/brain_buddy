import { useState } from "react";
import { StyleSheet, View } from "react-native";

import type { AgentRunResponse, TaskResponse } from "@/api/types";
import { useAgentRunsFeed } from "@/features/agents/useAgentRunsFeed";
import { AgentRunSection } from "@/features/agents/AgentRunSection";
import { HandoffSheet, type AgentHandoffSeed } from "@/features/agents/HandoffSheet";
import { BBText } from "@/components/BBText";
import { Button } from "@/components/Button";
import { compactRunLabel, runsNewestFirst } from "@/agents/machine";
import { colors, space } from "@/theme/tokens";

interface TaskAgentSectionProps {
  task: TaskResponse;
  projectName: string | null;
  tagNames: string[];
  /** The account's `external_agent_relay` flag (fail closed). */
  enabled: boolean;
}

/**
 * Everything a task screen needs for the external-agent relay: the trigger
 * that opens the review-then-confirm hand-off, and the run monitor for that
 * task. A task never handed to an agent shows nothing beyond the trigger, and
 * the whole section is absent when the account's flag is off — existing task
 * behavior is unchanged.
 */
export function TaskAgentSection({
  task,
  projectName,
  tagNames,
  enabled,
}: TaskAgentSectionProps) {
  // Rollout controls creation of new work, not access to work already sent.
  const feed = useAgentRunsFeed(task.id, true);
  const [sheetVisible, setSheetVisible] = useState(false);
  // Non-null exactly when the sheet was reopened for a hand-off that never
  // left. Keyed into the sheet below so a reopened review starts as a fresh
  // component, seeded from the frozen manifest rather than from stale state.
  const [seed, setSeed] = useState<AgentHandoffSeed | null>(null);

  const onDispatched = (run: AgentRunResponse) => {
    feed.absorb(run);
  };

  const retryHandoff = (run: AgentRunResponse) => {
    const frozen = run.manifest;
    if (!frozen) {
      return;
    }
    setSeed({
      connectionId: frozen.connection_id,
      // What was frozen is what will be re-sent: the server rebuilds the
      // identical manifest from these three values.
      includeDetails: frozen.details !== null,
      supportingItems: frozen.supporting_items,
    });
    setSheetVisible(true);
  };

  // Derived rather than read off the response order. The API answers a task's
  // runs newest first, so the last element was the *oldest* one: a failed
  // attempt from last week described as the state of the run working right now.
  const latestRun = runsNewestFirst(feed.runs)[0] ?? null;

  return (
    <View style={styles.section}>
      {latestRun ? (
        // The same compact line the task list shows (M-03-S24), so the two
        // surfaces cannot disagree about the tier or about a control the agent
        // has already withdrawn.
        <BBText variant="micro" color={colors.fg5}>
          {compactRunLabel({
            primary_state_label: latestRun.primary_state_label,
            guarantee_tier: latestRun.guarantee_tier,
            cancel_outcome: latestRun.cancel_outcome,
          })}
        </BBText>
      ) : null}
      <AgentRunSection
        runs={feed.runs}
        loading={feed.loading}
        error={feed.error}
        online={feed.online}
        onRunUpdated={feed.absorb}
        // Only while the rollout allows a hand-off: the review sheet below is
        // mounted only then, and re-sending a hand-off that never left is a
        // fresh content-bearing send rather than acting on work already at the
        // agent (FR-016, 007 FR-019).
        onRetryHandoff={enabled ? retryHandoff : undefined}
        onRetry={feed.refresh}
      />
      {enabled ? (
        <>
          <Button
            variant="secondary"
            onPress={() => {
              setSeed(null);
              setSheetVisible(true);
            }}
          >
            Hand to agent
          </Button>
          <HandoffSheet
            key={seed ? `retry-${seed.connectionId}` : "fresh"}
            visible={sheetVisible}
            onClose={() => setSheetVisible(false)}
            task={task}
            projectName={projectName}
            tagNames={tagNames}
            seed={seed}
            onDispatched={onDispatched}
          />
        </>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  section: {
    gap: space.s2,
  },
});
