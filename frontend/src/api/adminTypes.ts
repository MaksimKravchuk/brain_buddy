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
