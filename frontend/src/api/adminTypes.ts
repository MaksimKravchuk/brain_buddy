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
