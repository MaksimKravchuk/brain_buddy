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

/**
 * The three runtime states one managed flag may hold (010-FR-003). Always
 * present, never null: ADR-0019 (DD-3, DD-15) retired the inherited
 * deploy-default state, so a flag's stored mode is the entire answer.
 */
export type AdminFeatureFlagMode = "off" | "on" | "selected_users";

/** One cohort row. `email` is resolved live server-side and never stored. */
export type AdminFeatureFlagSelectedUser = {
  account_id: string;
  email: string | null;
};

export type AdminFeatureFlagState = {
  name: string;
  mode: AdminFeatureFlagMode;
  selected_users: AdminFeatureFlagSelectedUser[];
};

/** `degraded: true` is a *successful* read reporting an unreadable document. */
export type AdminFeatureFlagsResponse = {
  degraded: boolean;
  flags: AdminFeatureFlagState[];
};

export type AdminFeatureFlagUserRequest = { account_id: string } | { email: string };
