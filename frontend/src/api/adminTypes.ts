/** Contracts for the minimum admin portal endpoints (`/api/admin`). */

export type AdminAccountLookupRequest = { account_id: string } | { email: string };

export type AdminAccountResponse = {
  id: string;
  email: string;
  display_name: string | null;
  deletion_requested: boolean;
};

export type AdminRevokeSessionsResponse = {
  revoked_count: number;
};

/** Server-issued operator capability check (`GET /admin/status`); only ever
 * reachable with `is_operator: true` -- a non-operator gets 401/403 instead. */
export type AdminStatusResponse = {
  is_operator: boolean;
};

/** The three runtime-override states one managed flag may hold (010-FR-003). */
export type AdminFeatureFlagMode = "off" | "on" | "selected_users";

/**
 * The deploy-staged baseline's own vocabulary. Deliberately a different type
 * from `AdminFeatureFlagMode`: `internal` is a deploy stage with no override
 * equivalent, and mapping it onto one of the three radios is exactly what
 * DD-3 forbids.
 */
export type AdminFeatureFlagDeployState = "off" | "internal" | "on";

export type AdminFeatureFlagSource = "runtime" | "deploy_default";

/** One cohort row. `email` is resolved live server-side and never stored. */
export type AdminFeatureFlagSelectedUser = {
  account_id: string;
  email: string | null;
};

export type AdminFeatureFlagState = {
  name: string;
  /** Null while the flag inherits the deploy default: no radio is then checked. */
  override_mode: AdminFeatureFlagMode | null;
  source: AdminFeatureFlagSource;
  /** Always present, even under an override, so "Use deploy default" previews. */
  deploy_default_state: AdminFeatureFlagDeployState;
  selected_users: AdminFeatureFlagSelectedUser[];
};

/** `degraded: true` is a *successful* read reporting an unreadable document. */
export type AdminFeatureFlagsResponse = {
  degraded: boolean;
  flags: AdminFeatureFlagState[];
};

export type AdminFeatureFlagUserRequest = { account_id: string } | { email: string };
