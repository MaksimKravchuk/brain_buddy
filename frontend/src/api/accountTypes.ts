/** Contracts for the self-serve account management endpoints (`/api/account`). */

export type AccountResponse = {
  id: string;
  email: string;
  display_name: string | null;
  created_at: string;
  /** Set while an account deletion is pending; null otherwise. */
  deletion_requested_at: string | null;
  /** When the pending deletion becomes irreversible; null when none is pending. */
  purge_at: string | null;
};

export type ProfileUpdatePayload = {
  display_name: string;
};

export type EmailChangePayload = {
  new_email: string;
  current_password: string;
};

export type PasswordChangePayload = {
  current_password: string;
  new_password: string;
};

export type AccountDeletePayload = {
  current_password: string;
};

export type AccountDeleteResponse = {
  deletion_requested_at: string;
  purge_at: string;
};
