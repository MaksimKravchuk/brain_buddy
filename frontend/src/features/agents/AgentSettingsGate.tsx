import { hasFeatureFlag } from "../../api/auth";
import { useAuthStore } from "../../stores/authStore";
import { AgentSettingsPage } from "./AgentSettingsPage";

/**
 * Rollout gate for the external-agent relay.
 *
 * An OFF rollout blocks new work and connection mutations, but FR-019 preserves
 * owner-scoped reads and credential-destroying disconnect for existing connections.
 * A missing flag remains OFF (see `hasFeatureFlag`).
 */
export function AgentSettingsGate(): React.JSX.Element {
  const user = useAuthStore((state) => state.user);
  return <AgentSettingsPage rolloutEnabled={hasFeatureFlag(user, "external_agent_relay")} />;
}
