import { useEffect, useRef, useState } from "react";
import {
  Pressable,
  ScrollView,
  StyleSheet,
  TextInput,
  useWindowDimensions,
  View,
} from "react-native";

import { useAgentConnections, useConfirmAgentHandoff, usePreviewAgentHandoff } from "@/api/hooks";
import type {
  AgentConnectionResponse,
  AgentContextItem,
  AgentManifestResponse,
  AgentRunResponse,
  TaskResponse,
} from "@/api/types";
import { buildContextCandidates, manifestRejectionReason } from "@/agents/machine";
import { BBText } from "@/components/BBText";
import { Button } from "@/components/Button";
import { ErrorBanner } from "@/components/ErrorBanner";
import { Sheet } from "@/components/Sheet";
import { canHandOff } from "@/lifecycle/agentGuards";
import { colors, fonts, radii, space, type as typeScale } from "@/theme/tokens";

interface HandoffSheetProps {
  visible: boolean;
  onClose: () => void;
  task: TaskResponse;
  projectName: string | null;
  tagNames: string[];
  onDispatched: (run: AgentRunResponse) => void;
}

interface PreviewMaterial {
  visible: boolean;
  openSession: number;
  task: Pick<TaskResponse, "id" | "revision" | "title" | "details">;
  projectName: string | null;
  tagNames: string[];
  sourceItems: AgentContextItem[];
  connectionId: string | null;
  connection: AgentConnectionResponse | null;
  includeDetails: boolean;
  items: AgentContextItem[];
}

/** Canonical, secret-free projection of every value that can affect review or dispatch safety. */
function previewInputSnapshot(material: PreviewMaterial): string {
  const connection = material.connection;
  return JSON.stringify([
    [material.visible, material.openSession],
    [material.task.id, material.task.revision, material.task.title, material.task.details],
    [material.projectName, material.tagNames, material.sourceItems],
    connection
      ? [
          connection.id,
          connection.name,
          connection.endpoint_url,
          connection.auth_header_name,
          connection.status,
          connection.stale,
          connection.ready_for_handoff,
          [
            connection.capabilities.progress,
            connection.capabilities.reply,
            connection.capabilities.cancel,
          ],
          connection.last_test_error_code,
          connection.last_contact_at,
          connection.last_tested_at,
          connection.stale_after_seconds,
          connection.revision,
        ]
      : material.connectionId
        ? [material.connectionId, "missing"]
        : null,
    [material.connectionId, material.includeDetails, material.items],
  ]);
}

/**
 * Review-then-confirm hand-off. The manifest the server returns is the single
 * source of truth for what leaves Brain Buddy: every value shown below comes
 * from it, and any change to the selection re-previews rather than confirming
 * something the user did not read.
 */
export function HandoffSheet({
  visible,
  onClose,
  task,
  projectName,
  tagNames,
  onDispatched,
}: HandoffSheetProps) {
  const { height } = useWindowDimensions();
  const connections = useAgentConnections(visible);
  const preview = usePreviewAgentHandoff(task.id);
  const confirm = useConfirmAgentHandoff(task.id);

  const initialContextItems = buildContextCandidates(task, { projectName, tagNames });
  const contextSourceSnapshot = JSON.stringify([task.id, projectName, tagNames, initialContextItems]);
  const [connectionId, setConnectionId] = useState<string | null>(null);
  const [includeDetails, setIncludeDetails] = useState(() => Boolean(task.details?.trim()));
  const [contextSelection, setContextSelection] = useState(() => ({
    sourceSnapshot: contextSourceSnapshot,
    items: initialContextItems,
  }));
  const [manifest, setManifest] = useState<AgentManifestResponse | null>(null);
  const [manifestSnapshot, setManifestSnapshot] = useState<string | null>(null);
  const [previewPending, setPreviewPending] = useState(false);
  const [previewError, setPreviewError] = useState<unknown>(null);
  const [password, setPassword] = useState("");
  const [rereviewNotice, setRereviewNotice] = useState<string | null>(null);
  const [previewRequestNonce, setPreviewRequestNonce] = useState(0);
  const previewGeneration = useRef(0);
  const visibility = useRef({ visible, openSession: visible ? 1 : 0 });
  if (visibility.current.visible !== visible) {
    visibility.current = {
      visible,
      openSession: visibility.current.openSession + 1,
    };
  }

  const items = connections.data ?? [];
  const selectedConnection =
    items.find((connection) => connection.id === connectionId) ?? null;
  const selectedConnectionGuard = selectedConnection ? canHandOff(selectedConnection) : null;
  const contextItems =
    contextSelection.sourceSnapshot === contextSourceSnapshot
      ? contextSelection.items
      : initialContextItems;
  const hasDetails = Boolean(task.details?.trim());
  const effectiveIncludeDetails = hasDetails && includeDetails;
  const currentInputSnapshot = previewInputSnapshot({
    visible,
    openSession: visibility.current.openSession,
    task,
    projectName,
    tagNames,
    sourceItems: initialContextItems,
    connectionId,
    connection: selectedConnection,
    includeDetails: effectiveIncludeDetails,
    items: contextItems,
  });
  const currentInputSnapshotRef = useRef(currentInputSnapshot);
  currentInputSnapshotRef.current = currentInputSnapshot;

  useEffect(() => {
    if (contextSelection.sourceSnapshot !== contextSourceSnapshot) {
      setContextSelection({ sourceSnapshot: contextSourceSnapshot, items: initialContextItems });
    }
    if (!hasDetails && includeDetails) {
      setIncludeDetails(false);
    }
  }, [
    contextSourceSnapshot,
    contextSelection.sourceSnapshot,
    hasDetails,
    includeDetails,
    initialContextItems,
  ]);

  useEffect(() => {
    const generation = ++previewGeneration.current;
    const snapshot = currentInputSnapshot;
    setManifest(null);
    setManifestSnapshot(null);
    setPreviewError(null);
    setPreviewPending(false);

    if (
      !visible ||
      !connectionId ||
      !selectedConnection ||
      !selectedConnectionGuard?.ok
    ) {
      return;
    }

    setPreviewPending(true);
    void preview
      .mutateAsync({
        connection_id: connectionId,
        include_details: effectiveIncludeDetails,
        context_items: contextItems,
      })
      .then((fresh) => {
        if (
          generation === previewGeneration.current &&
          currentInputSnapshotRef.current === snapshot
        ) {
          setManifest(fresh);
          setManifestSnapshot(snapshot);
          setPreviewPending(false);
        }
      })
      .catch((caught: unknown) => {
        if (
          generation === previewGeneration.current &&
          currentInputSnapshotRef.current === snapshot
        ) {
          setManifest(null);
          setManifestSnapshot(null);
          setPreviewError(caught);
          setPreviewPending(false);
        }
      });
    // The canonical snapshot, not object identity, owns preview replacement.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentInputSnapshot, previewRequestNonce]);

  useEffect(() => {
    if (visible) {
      preview.reset();
      confirm.reset();
      setPassword("");
      setRereviewNotice(null);
    }
    // Reset only at an open-session boundary; material changes preserve the
    // user's selected agent while forcing a new exact review above.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visibility.current.openSession]);

  const choose = (id: string) => {
    setConnectionId(id);
    setRereviewNotice(null);
  };

  const toggleDetails = () => {
    setIncludeDetails((current) => !current);
  };

  const removeContext = (index: number) => {
    setContextSelection({
      sourceSnapshot: contextSourceSnapshot,
      items: contextItems.filter((_, position) => position !== index),
    });
  };

  const send = () => {
    if (
      !visible ||
      !connectionId ||
      !selectedConnectionGuard?.ok ||
      !manifest ||
      previewPending ||
      manifestSnapshot !== currentInputSnapshot
    ) {
      return;
    }
    confirm.mutate(
      {
        connection_id: connectionId,
        include_details: effectiveIncludeDetails,
        context_items: contextItems,
        manifest_token: manifest.token,
        ...(manifest.reauthentication_required ? { current_password: password } : {}),
      },
      {
        onSuccess: (run) => {
          onDispatched(run);
          onClose();
        },
        onError: (error) => {
          // What would be sent changed, or the reservation lapsed. Review it
          // again — never re-confirm silently behind the user's back.
          if (manifestRejectionReason(error)) {
            setRereviewNotice(
              "What would be sent changed since you reviewed it. The review below has been refreshed — read it again before sending.",
            );
            setManifest(null);
            setManifestSnapshot(null);
            setPreviewRequestNonce((nonce) => nonce + 1);
          }
        },
      },
    );
  };

  const needsPassword = manifest?.reauthentication_required === true;
  const canSend =
    visible &&
    selectedConnectionGuard?.ok === true &&
    Boolean(manifest) &&
    !previewPending &&
    manifestSnapshot === currentInputSnapshot &&
    (!needsPassword || password.length > 0);

  return (
    <Sheet visible={visible} onClose={onClose} title="Hand to agent">
      <ScrollView style={{ maxHeight: height * 0.62 }} keyboardShouldPersistTaps="handled">
        <View style={styles.body}>
          {connections.isError ? <ErrorBanner error={connections.error} /> : null}

          <BBText variant="label">Agent</BBText>
          {items.length === 0 ? (
            <BBText variant="caption" color={colors.fg5}>
              No agents are connected yet. Add one under Settings → Connected agents.
            </BBText>
          ) : null}
          {items.map((connection) => {
            const guard = canHandOff(connection);
            const selected = connection.id === connectionId;
            return (
              <Pressable
                key={connection.id}
                accessibilityRole="button"
                accessibilityState={{ selected, disabled: !guard.ok }}
                disabled={!guard.ok}
                onPress={() => choose(connection.id)}
                style={[
                  styles.option,
                  selected ? styles.optionSelected : null,
                  guard.ok ? null : styles.optionDisabled,
                ]}
              >
                <BBText variant="body" weight="medium" color={colors.fg1}>
                  {connection.name}
                </BBText>
                {guard.ok ? null : (
                  <BBText variant="micro" color={colors.warningFg}>
                    {guard.reason}
                  </BBText>
                )}
              </Pressable>
            );
          })}

          {rereviewNotice ? (
            <View style={styles.notice}>
              <BBText variant="caption" color={colors.warningFg}>
                {rereviewNotice}
              </BBText>
            </View>
          ) : null}

          {previewError ? <ErrorBanner error={previewError} /> : null}
          {confirm.isError && !manifestRejectionReason(confirm.error) ? (
            <ErrorBanner error={confirm.error} />
          ) : null}

          {connectionId && !manifest && previewPending ? (
            <BBText variant="caption" color={colors.fg5}>
              Building the review…
            </BBText>
          ) : null}

          {manifest ? (
            <View style={styles.review}>
              <View style={styles.noticeStrong}>
                <BBText variant="caption" color={colors.warningFg}>
                  {manifest.external_copy_notice}
                </BBText>
              </View>

              <BBText variant="label">Exactly what will be sent</BBText>

              <Field label="Task title" value={manifest.title} />

              {hasDetails ? (
                <View style={styles.field}>
                  <View style={styles.fieldHead}>
                    <BBText variant="label">Task details</BBText>
                    <Pressable
                      accessibilityRole="switch"
                      accessibilityState={{ checked: includeDetails }}
                      accessibilityLabel={
                        includeDetails ? "Exclude task details" : "Include task details"
                      }
                      onPress={toggleDetails}
                      style={styles.toggle}
                    >
                      <BBText variant="caption" weight="medium" color={colors.infoFg}>
                        {includeDetails ? "Exclude" : "Include"}
                      </BBText>
                    </Pressable>
                  </View>
                  <BBText variant="body" color={manifest.details ? colors.fg2 : colors.fg6}>
                    {manifest.details ?? "Not included — details stay in Brain Buddy."}
                  </BBText>
                </View>
              ) : null}

              <View style={styles.field}>
                <BBText variant="label">Context items</BBText>
                {manifest.context_items.length === 0 ? (
                  <BBText variant="caption" color={colors.fg6}>
                    None. Only the fields above will be sent.
                  </BBText>
                ) : null}
                {manifest.context_items.map((item, index) => (
                  <View key={`${item.label}-${index}`} style={styles.contextItem}>
                    <View style={styles.fieldHead}>
                      <BBText variant="caption" weight="medium" color={colors.fg3}>
                        {item.label}
                      </BBText>
                      <Pressable
                        accessibilityRole="button"
                        accessibilityLabel={`Remove ${item.label}`}
                        onPress={() => removeContext(index)}
                        style={styles.toggle}
                      >
                        <BBText variant="caption" weight="medium" color={colors.dangerFg}>
                          Remove
                        </BBText>
                      </Pressable>
                    </View>
                    <BBText variant="caption" color={colors.fg4}>
                      {item.body}
                    </BBText>
                  </View>
                ))}
              </View>

              <Field label="Task ID" value={manifest.task_id} mono />
              <Field label="Run ID" value={manifest.run_id} mono />
              <Field label="Destination endpoint" value={manifest.destination_endpoint} mono />
              <Field
                label="Reporting instructions"
                value={manifest.reporting_instructions}
              />
              <BBText variant="micro" color={colors.fg6}>
                {`Instructions ${manifest.instructions_version} · protocol ${manifest.protocol_version}`}
              </BBText>

              {needsPassword ? (
                <View style={styles.field}>
                  <BBText variant="label">Your Brain Buddy password</BBText>
                  <BBText variant="micro" color={colors.fg5}>
                    Task content is about to leave Brain Buddy for the first time through this
                    agent, so confirm it is you.
                  </BBText>
                  <TextInput
                    style={styles.input}
                    value={password}
                    onChangeText={setPassword}
                    placeholder="Confirm it is you"
                    placeholderTextColor={colors.fg6}
                    autoCapitalize="none"
                    autoCorrect={false}
                    secureTextEntry
                    editable={!confirm.isPending}
                  />
                </View>
              ) : null}
            </View>
          ) : null}
        </View>
      </ScrollView>

      <Button onPress={send} disabled={!canSend} loading={confirm.isPending}>
        {manifest ? `Send to ${manifest.agent_name}` : "Send"}
      </Button>
      <Button variant="ghost" onPress={onClose} disabled={confirm.isPending}>
        Cancel — nothing is sent
      </Button>
    </Sheet>
  );
}

function Field({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <View style={styles.field}>
      <BBText variant="label">{label}</BBText>
      <BBText variant="body" color={colors.fg2} style={mono ? styles.mono : undefined} selectable>
        {value}
      </BBText>
    </View>
  );
}

const styles = StyleSheet.create({
  body: {
    gap: space.s3,
  },
  option: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radii.md,
    paddingHorizontal: space.s3,
    paddingVertical: space.s3,
    minHeight: 44,
    justifyContent: "center",
    gap: 2,
  },
  optionSelected: {
    borderColor: colors.brandPrimary,
    backgroundColor: colors.brandPrimarySoft,
  },
  optionDisabled: {
    opacity: 0.6,
  },
  notice: {
    backgroundColor: colors.warningBg,
    borderWidth: 1,
    borderColor: colors.warningBorder,
    borderRadius: radii.card,
    padding: space.s3,
  },
  noticeStrong: {
    backgroundColor: colors.warningBg,
    borderWidth: 1,
    borderColor: colors.warningBorder,
    borderRadius: radii.card,
    padding: space.s4,
  },
  review: {
    gap: space.s3,
  },
  field: {
    gap: space.s1,
  },
  fieldHead: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: space.s2,
  },
  toggle: {
    minHeight: 44,
    justifyContent: "center",
    paddingHorizontal: space.s2,
  },
  contextItem: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radii.sm,
    padding: space.s3,
    gap: 2,
  },
  mono: {
    fontFamily: "Menlo",
    fontSize: typeScale.caption,
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
});
