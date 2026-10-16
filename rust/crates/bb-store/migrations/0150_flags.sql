-- 0150_flags: the `flags` schema (owner module: Feature flags, ADR-0019).
-- Parity source: backend/app/repositories/feature_flag.py (`feature_flags`).
-- Global flags; `flag_selected_owners` is the cohort. Forward-only, expand-only.
CREATE SCHEMA IF NOT EXISTS flags;
CREATE TABLE flags.feature_flags (
    flag       text PRIMARY KEY,
    mode       text NOT NULL CHECK (mode IN ('off', 'on', 'selected_users')),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE flags.flag_selected_owners (
    flag     text NOT NULL REFERENCES flags.feature_flags (flag) ON DELETE CASCADE,
    owner_id text NOT NULL,
    PRIMARY KEY (flag, owner_id)
);
CREATE INDEX flag_selected_owners_owner ON flags.flag_selected_owners (owner_id);
