import { useState } from "react";
import { StyleSheet, View } from "react-native";

import type { AgentRunResponse, TaskResponse } from "@/api/types";
import { useAgentRunsFeed } from "@/features/agents/useAgentRunsFeed";
import { AgentRunSection } from "@/features/agents/AgentRunSection";
import { HandoffSheet } from "@/features/agents/HandoffSheet";
import { Button } from "@/components/Button";
import { space } from "@/theme/tokens";

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
  const feed = useAgentRunsFeed(task.id, enabled);
  const [sheetVisible, setSheetVisible] = useState(false);

  if (!enabled) {
    return null;
  }

  const onDispatched = (run: AgentRunResponse) => {
    feed.absorb(run);
  };

  return (
    <View style={styles.section}>
      <AgentRunSection
        runs={feed.runs}
        loading={feed.loading}
        error={feed.error}
        online={feed.online}
        onRunUpdated={feed.absorb}
        onRetry={feed.refresh}
      />
      <Button variant="secondary" onPress={() => setSheetVisible(true)}>
        Hand to agent
      </Button>

      <HandoffSheet
        visible={sheetVisible}
        onClose={() => setSheetVisible(false)}
        task={task}
        projectName={projectName}
        tagNames={tagNames}
        onDispatched={onDispatched}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  section: {
    gap: space.s2,
  },
});
