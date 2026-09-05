import { StyleSheet, View } from "react-native";

import type { AgentConnectionResponse } from "@/api/types";
import {
  authSchemeLabel,
  capabilityDisclosure,
  connectionStatusDetail,
  connectionStatusLabel,
  lastContactLabel,
  rateLimitRetryCopy,
} from "@/agents/machine";
import { BBText } from "@/components/BBText";
import { Button } from "@/components/Button";
import {
  canDisconnect,
  canRotateCredential,
  canTestConnection,
  type AgentGuardOptions,
} from "@/lifecycle/agentGuards";
import { colors, radii, space } from "@/theme/tokens";

interface ConnectionCardProps {
  connection: AgentConnectionResponse;
  online?: boolean;
  testing?: boolean;
  onTest: () => void;
  onRotate: () => void;
  onDisconnect: () => void;
}

type Tone = { bg: string; border: string; fg: string };

const NEUTRAL: Tone = { bg: colors.surfaceSunken, border: colors.border, fg: colors.fg4 };
const OK: Tone = { bg: colors.successBg, border: colors.successBorder, fg: colors.successFg };
const WARN: Tone = { bg: colors.warningBg, border: colors.warningBorder, fg: colors.warningFg };
const BAD: Tone = { bg: colors.dangerBg, border: colors.dangerBorder, fg: colors.dangerFg };

function toneFor(connection: AgentConnectionResponse): Tone {
  if (connection.agent_changed || connection.last_test_error_code === "a2a_rate_limited") {
    return WARN;
  }
  switch (connection.status) {
    case "ready":
      return connection.stale ? WARN : OK;
    case "invalid_credentials":
    case "unreachable":
    case "unsupported":
      return BAD;
    default:
      return NEUTRAL;
  }
}

/**
 * One saved connection, told honestly: what the last test found, when the
 * agent was last in contact, and exactly which capabilities it does and does
 * not have. Controls the server would refuse are not offered.
 */
export function ConnectionCard({
  connection,
  online = true,
  testing = false,
  onTest,
  onRotate,
  onDisconnect,
}: ConnectionCardProps) {
  const guardOptions: AgentGuardOptions = { online };
  const tone = toneFor(connection);
  const { supported, unsupported } = capabilityDisclosure(connection.capabilities);
  const testGuard = canTestConnection(connection, guardOptions);
  const rotateGuard = canRotateCredential(connection, guardOptions);
  const disconnectGuard = canDisconnect(connection, guardOptions);
  const card = connection.card;

  return (
    <View style={styles.card}>
      <View style={styles.headRow}>
        <BBText variant="subtitle" color={colors.fg1} style={styles.name} numberOfLines={2}>
          {connection.name}
        </BBText>
        <View style={[styles.pill, { backgroundColor: tone.bg, borderColor: tone.border }]}>
          <BBText variant="micro" weight="medium" color={tone.fg}>
            {connectionStatusLabel(connection)}
          </BBText>
        </View>
      </View>

      <BBText variant="micro" color={colors.fg5} numberOfLines={2}>
        {connection.agent_address}
      </BBText>
      <BBText variant="micro" color={colors.fg6}>
        {`Credential: ${authSchemeLabel(connection)}`}
      </BBText>
      <BBText variant="micro" color={colors.fg5}>
        {lastContactLabel(connection.last_contact_at)}
      </BBText>

      <BBText variant="caption" color={colors.fg4}>
        {connectionStatusDetail(connection)}
      </BBText>

      {connection.last_test_error_code === "a2a_rate_limited" ? (
        <BBText variant="caption" color={colors.warningFg}>
          {rateLimitRetryCopy(connection)}
        </BBText>
      ) : null}

      {connection.agent_changed ? (
        <View style={styles.kv} accessibilityLabel="Interface comparison">
          <BBText variant="micro" color={colors.warningFg}>
            {`Tested interface: ${card?.interface_url ?? "Unknown"}`}
          </BBText>
          <BBText variant="micro" color={colors.warningFg}>
            {`Card now says: ${
              connection.last_test_error_detail &&
              "interface_url" in connection.last_test_error_detail
                ? (connection.last_test_error_detail.interface_url ?? "Unknown")
                : "Unknown"
            }`}
          </BBText>
        </View>
      ) : null}

      {card ? (
        <View style={styles.kv} accessibilityLabel="Discovery result">
          <BBText variant="micro" color={colors.fg5}>{`Name: ${card.name ?? "Not stated"}`}</BBText>
          <BBText variant="micro" color={colors.fg5}>
            {`Version: ${card.version ?? "Not stated"}`}
          </BBText>
          <BBText variant="micro" color={colors.fg5}>
            {`Protocol version: ${card.protocol_version ?? "Not stated"}`}
          </BBText>
          <BBText variant="micro" color={colors.fg5} numberOfLines={2}>
            {`Interface: ${card.interface_url ?? "Not stated"}`}
          </BBText>
          {card.description ? (
            <BBText variant="micro" color={colors.fg5}>
              {card.description}
            </BBText>
          ) : null}
          {card.skills.length > 0 ? (
            <View style={styles.skills} accessibilityLabel="Skills">
              {card.skills.map((skill, index) => (
                <View key={`${skill.id ?? "skill"}-${index}`} style={styles.skill}>
                  <BBText variant="micro" color={colors.fg4}>
                    {skill.name ?? skill.id ?? "Unnamed skill"}
                  </BBText>
                </View>
              ))}
            </View>
          ) : null}
        </View>
      ) : null}

      {connection.tier_disclosure ? (
        <View style={styles.kv} accessibilityLabel="Guarantee">
          <BBText variant="caption" color={colors.fg4}>
            {connection.tier_disclosure}
          </BBText>
          {connection.guarantee_tier === "best_effort" && connection.tier_disclosure_url ? (
            <BBText variant="micro" color={colors.fg5}>
              {`Read the single-start extension specification: ${connection.tier_disclosure_url}`}
            </BBText>
          ) : null}
          {connection.cancellation_disclosure ? (
            <BBText variant="micro" color={colors.fg5}>
              {connection.cancellation_disclosure}
            </BBText>
          ) : null}
        </View>
      ) : null}

      <View style={styles.capabilities}>
        <BBText variant="caption" color={colors.fg4}>
          {supported.length > 0
            ? `Supports ${supported.join(", ")}.`
            : "This agent disclosed no supported capabilities."}
        </BBText>
        {unsupported.length > 0 ? (
          <BBText variant="caption" color={colors.fg4}>
            {`Does not support ${unsupported.join(", ")}. Those controls stay hidden.`}
          </BBText>
        ) : null}
      </View>

      {!connection.ready_for_handoff && connection.status !== "disconnected" ? (
        <BBText variant="caption" color={colors.warningFg}>
          This connection cannot take a hand-off until a connection test succeeds.
        </BBText>
      ) : null}

      <View style={styles.actions}>
        <Button
          variant="secondary"
          style={styles.action}
          disabled={!testGuard.ok}
          loading={testing}
          onPress={onTest}
        >
          Test connection
        </Button>
        <Button
          variant="secondary"
          style={styles.action}
          disabled={!rotateGuard.ok}
          onPress={onRotate}
        >
          Rotate credential
        </Button>
        <Button
          variant="destructive"
          style={styles.action}
          disabled={!disconnectGuard.ok}
          onPress={onDisconnect}
        >
          Disconnect
        </Button>
      </View>

      {!testGuard.ok || !rotateGuard.ok || !disconnectGuard.ok ? (
        <BBText variant="micro" color={colors.fg5}>
          {!testGuard.ok
            ? testGuard.reason
            : !rotateGuard.ok
              ? rotateGuard.reason
              : disconnectGuard.ok
                ? ""
                : disconnectGuard.reason}
        </BBText>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.surfaceRaised,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radii.card,
    padding: space.s4,
    gap: space.s2,
  },
  headRow: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: space.s2,
  },
  name: {
    flex: 1,
  },
  pill: {
    borderRadius: radii.full,
    borderWidth: 1,
    paddingHorizontal: space.s2,
    paddingVertical: 3,
  },
  capabilities: {
    gap: 2,
    marginTop: space.s1,
  },
  kv: {
    gap: 2,
    marginTop: space.s1,
  },
  skills: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: space.s2,
    marginTop: space.s1,
  },
  skill: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radii.full,
    paddingHorizontal: space.s2,
    paddingVertical: 2,
  },
  actions: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: space.s2,
    marginTop: space.s2,
  },
  action: {
    minHeight: 44,
    paddingHorizontal: space.s3,
  },
});
