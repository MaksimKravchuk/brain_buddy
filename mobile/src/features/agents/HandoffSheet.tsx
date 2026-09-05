import { useEffect, useRef, useState } from "react";
import {
  Linking,
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

/**
 * The reviewed payload of a hand-off that never left, replayed exactly.
 *
 * Seeding the review from a run's frozen manifest is what makes **Try this
 * hand-off again** a *retry*: the server rebuilds the same manifest and returns
 * the same token, so the same run ID and message ID are reused precisely when
 * the user changed nothing.
 */
export interface AgentHandoffSeed {
  connectionId: string;
  includeDetails: boolean;
  supportingItems: AgentContextItem[];
}

interface HandoffSheetProps {
  visible: boolean;
  onClose: () => void;
  task: TaskResponse;
  projectName: string | null;
  tagNames: string[];
  onDispatched: (run: AgentRunResponse) => void;
  seed?: AgentHandoffSeed | null;
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
          connection.agent_address,
          connection.auth_scheme,
          connection.auth_header_name,
          connection.status,
          connection.stale,
          connection.ready_for_handoff,
          [connection.capabilities.streaming, connection.capabilities.push_notifications],
          [connection.controls_offered.reply, connection.controls_offered.cancel],
          connection.guarantee_tier,
          connection.agent_changed,
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
export function HandoffSheet({ visible, onClose, ...contentProps }: HandoffSheetProps) {
  // Seeded from a run's frozen manifest when the review is *re*opened. That is
  // what makes **Try this hand-off again** a retry rather than a second
  // hand-off: the server rebuilds the same manifest, returns the same token,
  // and the token is the idempotency key.
  const [connectionId, setConnectionId] = useState<string | null>(
    contentProps.seed?.connectionId ?? null,
  );
  const [confirmPending, setConfirmPending] = useState(false);
  return (
    <Sheet visible={visible} onClose={onClose} title="Hand to agent" dismissible={!confirmPending}>
      {visible ? (
        <HandoffSheetContent
          visible
          onClose={onClose}
          connectionId={connectionId}
          onConnectionIdChange={setConnectionId}
          onConfirmPendingChange={setConfirmPending}
          {...contentProps}
        />
      ) : null}
    </Sheet>
  );
}

interface HandoffSheetContentProps extends HandoffSheetProps {
  connectionId: string | null;
  onConnectionIdChange: (connectionId: string) => void;
  onConfirmPendingChange: (pending: boolean) => void;
}

function HandoffSheetContent({
  visible,
  onClose,
  task,
  projectName,
  tagNames,
  onDispatched,
  seed,
  connectionId,
  onConnectionIdChange,
  onConfirmPendingChange,
}: HandoffSheetContentProps) {
  const { height } = useWindowDimensions();
  const connections = useAgentConnections(visible);
  const preview = usePreviewAgentHandoff(task.id);
  const confirm = useConfirmAgentHandoff(task.id);

  const initialContextItems = buildContextCandidates(task, { projectName, tagNames });
  const contextSourceSnapshot = JSON.stringify([task.id, projectName, tagNames, initialContextItems]);
  const [includeDetails, setIncludeDetails] = useState(() =>
    seed ? seed.includeDetails : Boolean(task.details?.trim()),
  );
  const [contextSelection, setContextSelection] = useState(() => ({
    sourceSnapshot: contextSourceSnapshot,
    items: seed?.supportingItems ?? initialContextItems,
  }));
  const [receivedManifest, setManifest] = useState<AgentManifestResponse | null>(null);
  const [manifestSnapshot, setManifestSnapshot] = useState<string | null>(null);
  const [previewPending, setPreviewPending] = useState(false);
  const [previewError, setPreviewError] = useState<unknown>(null);
  const [password, setPassword] = useState("");
  // Asked once per connection, and again whenever its verified scope resets.
  // Held here rather than derived: the user's tap is the thing being recorded,
  // and a value read back off the manifest would tick itself.
  const [acknowledged, setAcknowledged] = useState(false);
  const [rereviewNotice, setRereviewNotice] = useState<string | null>(null);
  const [previewRequestNonce, setPreviewRequestNonce] = useState(0);
  const previewGeneration = useRef(0);

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
    openSession: 1,
    task,
    projectName,
    tagNames,
    sourceItems: initialContextItems,
    connectionId,
    connection: selectedConnection,
    includeDetails: effectiveIncludeDetails,
    items: contextItems,
  });
  const manifest = manifestSnapshot === currentInputSnapshot ? receivedManifest : null;

  useEffect(() => {
    const generation = ++previewGeneration.current;
    const snapshot = currentInputSnapshot;

    if (
      !visible ||
      !connectionId ||
      !selectedConnection ||
      !selectedConnectionGuard?.ok
    ) {
      return;
    }

    const request = preview.mutateAsync({
      connection_id: connectionId,
      include_details: effectiveIncludeDetails,
      supporting_items: contextItems,
    });
    void Promise.resolve().then(() => {
      if (generation !== previewGeneration.current) return;
      setManifest(null);
      setManifestSnapshot(null);
      setPreviewError(null);
      setPreviewPending(true);
    });
    void request
      .then((fresh) => {
        if (generation === previewGeneration.current) {
          setManifest(fresh);
          setManifestSnapshot(snapshot);
          setPreviewPending(false);
        }
      })
      .catch((caught: unknown) => {
        if (generation === previewGeneration.current) {
          setManifest(null);
          setManifestSnapshot(null);
          setPreviewError(caught);
          setPreviewPending(false);
        }
      });
    // The canonical snapshot, not object identity, owns preview replacement.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentInputSnapshot, previewRequestNonce]);


  const choose = (id: string) => {
    onConnectionIdChange(id);
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

  const send = async () => {
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
    onConfirmPendingChange(true);
    try {
      const run = await confirm.mutateAsync({
        payload: {
          connection_id: connectionId,
          include_details: effectiveIncludeDetails,
          supporting_items: contextItems,
          manifest_token: manifest.token,
          // Part of the request identity, so a replayed confirmation carries
          // exactly what the user agreed to (AC-026).
          acknowledge_duplicate_risk: manifest.acknowledgement_required
            ? acknowledged
            : false,
          ...(manifest.reauthentication_required ? { current_password: password } : {}),
        },
        idempotencyKey: `agent-handoff-${manifest.token}`,
      });
      onDispatched(run);
      onClose();
    } catch (error) {
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
    } finally {
      onConfirmPendingChange(false);
    }
  };

  const needsPassword = manifest?.reauthentication_required === true;
  const canSend =
    visible &&
    selectedConnectionGuard?.ok === true &&
    Boolean(manifest) &&
    !previewPending &&
    manifestSnapshot === currentInputSnapshot &&
    (!needsPassword || password.length > 0) &&
    // The acknowledgement gates the send *here* as well as at the server: the
    // user has to be able to see that ticking the row is what unlocks the
    // action they are about to take (AC-026, M-02-S12/S13).
    (manifest?.acknowledgement_required !== true || acknowledged);

  return (
    <>
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
                <BBText variant="label">Supporting items</BBText>
                {manifest.supporting_items.length === 0 ? (
                  <BBText variant="caption" color={colors.fg6}>
                    None. Only the fields above will be sent.
                  </BBText>
                ) : null}
                {manifest.supporting_items.map((item, index) => (
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
              <Field label="Correlation ID" value={manifest.correlation_id} mono />
              {/* Card-sourced, so inert: shown precisely so the owner can see
                  where their content would go, which is also why it is never a
                  `Linking` target (AC-031). */}
              <Field label="Destination" value={manifest.destination_interface} mono />
              {manifest.push_callback?.registered ? (
                <View style={styles.field}>
                  <BBText variant="label">Push callback</BBText>
                  <BBText variant="body" color={colors.fg2} style={styles.mono} selectable>
                    {manifest.push_callback.url_preview}
                  </BBText>
                  <BBText variant="caption" color={colors.fg5}>
                    {manifest.push_callback.disclosure}
                  </BBText>
                </View>
              ) : null}

              <View style={styles.field}>
                <BBText variant="label">Guarantee</BBText>
                <BBText variant="body" color={colors.fg2}>
                  {manifest.tier_disclosure}
                </BBText>
                {manifest.guarantee_tier === "best_effort" ? (
                  <Pressable
                    accessibilityRole="link"
                    accessibilityLabel="Read the single-start extension specification"
                    onPress={() => {
                      void Linking.openURL(manifest.tier_disclosure_url);
                    }}
                  >
                    <BBText variant="caption" weight="medium" color={colors.infoFg}>
                      Read the single-start extension specification
                    </BBText>
                  </Pressable>
                ) : null}
                {manifest.acknowledgement_required ? (
                  <>
                    <Pressable
                      accessibilityRole="checkbox"
                      accessibilityLabel="I understand that a duplicate task is possible with this agent"
                      accessibilityState={{ checked: acknowledged }}
                      onPress={() => setAcknowledged((current) => !current)}
                      style={styles.acknowledgeRow}
                    >
                      <BBText variant="body" color={colors.fg2}>
                        {acknowledged ? "☑" : "☐"} I understand that a duplicate task is
                        possible with this agent
                      </BBText>
                    </Pressable>
                    {acknowledged ? (
                      <BBText variant="caption" color={colors.fg5}>
                        Acknowledged. Brain Buddy will not ask again for this agent.
                      </BBText>
                    ) : null}
                  </>
                ) : manifest.guarantee_tier === "best_effort" ? (
                  <BBText variant="caption" color={colors.fg5}>
                    You acknowledged the duplicate risk for this agent on your first hand-off,
                    so there is no acknowledgement step here.
                  </BBText>
                ) : null}
              </View>

              <BBText variant="caption" color={colors.fg5}>
                {manifest.cancellation_disclosure}
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

      <Button onPress={() => void send()} disabled={!canSend} loading={confirm.isPending}>
        {manifest ? `Send to ${manifest.agent_name}` : "Send"}
      </Button>
      <Button variant="ghost" onPress={onClose} disabled={confirm.isPending}>
        Cancel — nothing is sent
      </Button>
    </>
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
  // 44pt, because it is a real decision and has to be tappable like one.
  acknowledgeRow: {
    minHeight: 44,
    justifyContent: "center",
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
