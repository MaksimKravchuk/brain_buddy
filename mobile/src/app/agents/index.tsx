import { useState } from "react";
import { ActivityIndicator, ScrollView, StyleSheet, View } from "react-native";

import { useAgentConnections, useTestAgentConnection } from "@/api/hooks";
import type {
  AgentConnectionCreatedResponse,
  AgentConnectionResponse,
  AgentConnectionSigningSecretResponse,
} from "@/api/types";
import { isOfflineError } from "@/agents/machine";
import { useSession } from "@/auth/SessionProvider";
import { BBText } from "@/components/BBText";
import { Button } from "@/components/Button";
import { EmptyState } from "@/components/EmptyState";
import { ErrorBanner } from "@/components/ErrorBanner";
import { Screen } from "@/components/Screen";
import { TopBar } from "@/components/shell/TopBar";
import { AddConnectionSheet } from "@/features/agents/AddConnectionSheet";
import { ConnectionCard } from "@/features/agents/ConnectionCard";
import { DisconnectSheet } from "@/features/agents/DisconnectSheet";
import { RotateCredentialSheet } from "@/features/agents/RotateCredentialSheet";
import { ReplaceSigningSecretSheet } from "@/features/agents/ReplaceSigningSecretSheet";
import { SigningSecretSheet } from "@/features/agents/SigningSecretSheet";
import { colors, radii, space } from "@/theme/tokens";

export default function ConnectedAgentsScreen() {
  const { agentRelayEnabled } = useSession();
  const connections = useAgentConnections(agentRelayEnabled);
  const test = useTestAgentConnection();

  const [addVisible, setAddVisible] = useState(false);
  const [createdSecret, setCreatedSecret] = useState<AgentConnectionCreatedResponse | null>(null);
  const [rotating, setRotating] = useState<AgentConnectionResponse | null>(null);
  const [replacingSigningSecret, setReplacingSigningSecret] =
    useState<AgentConnectionResponse | null>(null);
  const [replacementSecret, setReplacementSecret] =
    useState<AgentConnectionSigningSecretResponse | null>(null);
  const [disconnecting, setDisconnecting] = useState<AgentConnectionResponse | null>(null);
  const [testingId, setTestingId] = useState<string | null>(null);

  // "Offline" here means a request never reached the server, so anything on
  // screen is a cache that may already be wrong.
  const online = !(connections.isError && isOfflineError(connections.error));

  if (!agentRelayEnabled) {
    return (
      <Screen padBottom>
        <TopBar leading="back" title="Connected agents" />
        <ScrollView contentContainerStyle={styles.scroll}>
          <EmptyState
            headline="Not enabled"
            hint="External agents are not enabled for this account. Nothing is connected and no task content can leave Brain Buddy this way."
          />
        </ScrollView>
      </Screen>
    );
  }

  const items = connections.data ?? [];

  return (
    <Screen padBottom>
      <TopBar leading="back" title="Connected agents" />
      <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
        <BBText variant="caption" color={colors.fg5}>
          You own each agent listed here — its hosting, tools, credentials, cost, and output. Brain
          Buddy relays one task at a time and reports only what the agent says.
        </BBText>

        {!online ? (
          <View style={styles.staleCard}>
            <BBText variant="caption" color={colors.warningFg}>
              Brain Buddy could not reach the server. This list is a cached copy and may be out of
              date.
            </BBText>
          </View>
        ) : null}

        {connections.isError && online ? (
          <ErrorBanner error={connections.error} onRetry={() => connections.refetch()} />
        ) : null}
        {test.isError ? <ErrorBanner error={test.error} /> : null}

        {connections.isLoading ? (
          <View style={styles.center}>
            <ActivityIndicator color={colors.brandPrimary} />
          </View>
        ) : null}

        {!connections.isLoading && items.length === 0 ? (
          <EmptyState
            headline="No agents yet"
            hint="Connect an agent you run, then hand it a single task from that task's screen."
          />
        ) : null}

        {items.map((connection) => (
          <ConnectionCard
            key={connection.id}
            connection={connection}
            online={online}
            testing={test.isPending && testingId === connection.id}
            onTest={() => {
              setTestingId(connection.id);
              test.mutate(connection.id, { onSettled: () => setTestingId(null) });
            }}
            onRotate={() => setRotating(connection)}
            onReplaceSigningSecret={() => setReplacingSigningSecret(connection)}
            onDisconnect={() => setDisconnecting(connection)}
          />
        ))}

        <Button onPress={() => setAddVisible(true)}>Add an agent</Button>
      </ScrollView>

      <AddConnectionSheet
        visible={addVisible}
        onClose={() => setAddVisible(false)}
        onCreated={(connection) => {
          setAddVisible(false);
          setCreatedSecret(connection);
        }}
      />

      <SigningSecretSheet connection={createdSecret} onDismiss={() => setCreatedSecret(null)} />

      <RotateCredentialSheet
        connection={rotating}
        onClose={() => setRotating(null)}
        onRotated={() => setRotating(null)}
      />

      <ReplaceSigningSecretSheet
        connection={replacingSigningSecret}
        onClose={() => setReplacingSigningSecret(null)}
        onReplaced={(connection) => {
          setReplacingSigningSecret(null);
          setReplacementSecret(connection);
        }}
      />

      <SigningSecretSheet
        connection={replacementSecret}
        onDismiss={() => setReplacementSecret(null)}
      />

      <DisconnectSheet
        connection={disconnecting}
        onClose={() => setDisconnecting(null)}
        onDisconnected={() => setDisconnecting(null)}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  scroll: {
    padding: space.s4,
    paddingTop: space.s5,
    gap: space.s3,
    paddingBottom: space.s8,
  },
  center: {
    alignItems: "center",
    paddingVertical: space.s8,
  },
  staleCard: {
    backgroundColor: colors.warningBg,
    borderWidth: 1,
    borderColor: colors.warningBorder,
    borderRadius: radii.card,
    padding: space.s4,
  },
});
