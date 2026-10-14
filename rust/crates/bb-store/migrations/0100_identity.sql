-- 0100_identity: the `identity` schema (owner module: Identity, ADR-0028).
-- Parity source: backend/app/repositories/auth_store.py, cli_auth.py, invite.py.
-- data-model.md: "Every owner-scoped table carries `owner_id` and every query
-- filters on it" (`users.id` is the owner id; the rest carry `owner_id`).
-- data-model.md: "Timestamps are `timestamptz` in UTC; identifiers keep their
-- current wire format (prefix + random)". Forward-only, expand-only; no ledger.
-- Login rate limits stay in process memory: no table.
CREATE SCHEMA IF NOT EXISTS identity;
CREATE TABLE identity.users (
    id                    text PRIMARY KEY,
    email                 text NOT NULL UNIQUE,
    password_hash         text NOT NULL DEFAULT '',  -- Argon2id PHC string
    email_verified_at     timestamptz,
    auth_version          integer NOT NULL DEFAULT 0 CHECK (auth_version >= 0),
    created_at            timestamptz NOT NULL,
    deletion_requested_at timestamptz,
    payload               jsonb NOT NULL
);
CREATE TABLE identity.invites (
    code_hash       text PRIMARY KEY,
    created_at      timestamptz NOT NULL,
    expires_at      timestamptz,
    used_by_user_id text REFERENCES identity.users (id) ON DELETE SET NULL,
    used_at         timestamptz
);
CREATE TABLE identity.auth_identity_bindings (
    id               text PRIMARY KEY,
    owner_id         text NOT NULL REFERENCES identity.users (id) ON DELETE CASCADE,
    provider         text NOT NULL,
    issuer           text NOT NULL,
    namespace        text NOT NULL,
    subject          text NOT NULL,
    state            text NOT NULL DEFAULT 'active',
    generation       integer NOT NULL DEFAULT 1 CHECK (generation >= 1),
    created_at       timestamptz NOT NULL,
    updated_at       timestamptz NOT NULL,
    email            text,
    email_verified   boolean NOT NULL DEFAULT false,
    is_private_email boolean NOT NULL DEFAULT false,
    payload          jsonb NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (provider, issuer, namespace, subject),
    UNIQUE (owner_id, provider),
    UNIQUE (id, owner_id)
);
CREATE TABLE identity.sessions (
    token_hash          text PRIMARY KEY,  -- hash of the opaque cookie token
    owner_id            text NOT NULL REFERENCES identity.users (id) ON DELETE CASCADE,
    created_at          timestamptz NOT NULL,
    expires_at          timestamptz NOT NULL,
    auth_version        integer NOT NULL DEFAULT 0 CHECK (auth_version >= 0),
    auth_method         text NOT NULL DEFAULT 'password',
    confirmed_at        timestamptz,
    provider_binding_id text,
    payload             jsonb NOT NULL,
    UNIQUE (token_hash, owner_id),
    FOREIGN KEY (provider_binding_id, owner_id) REFERENCES identity.auth_identity_bindings (id, owner_id) ON DELETE CASCADE
);
CREATE INDEX sessions_owner ON identity.sessions (owner_id);
CREATE INDEX sessions_expiry ON identity.sessions (expires_at);
CREATE TABLE identity.auth_attempts (
    id               text PRIMARY KEY,
    owner_id         text REFERENCES identity.users (id) ON DELETE CASCADE,
    auth_version     integer NOT NULL DEFAULT 0 CHECK (auth_version >= 0),
    session_hash     text,
    provider         text NOT NULL,
    intent           text NOT NULL,
    action           text,
    channel          text NOT NULL,
    client_challenge text NOT NULL,
    state_hash       text UNIQUE,
    nonce_hash       text,
    binder_hash      text,
    audience         text,
    redirect_label   text,
    status           text NOT NULL DEFAULT 'started',
    created_at       timestamptz NOT NULL,
    expires_at       timestamptz NOT NULL,
    lease_id         text,
    lease_expires_at timestamptz,
    sealed_payload   text,
    key_id           text,
    payload          jsonb NOT NULL DEFAULT '{}'::jsonb,
    FOREIGN KEY (session_hash, owner_id) REFERENCES identity.sessions (token_hash, owner_id) ON DELETE CASCADE
);
CREATE INDEX auth_attempts_owner ON identity.auth_attempts (owner_id);
CREATE INDEX auth_attempts_expiry ON identity.auth_attempts (expires_at);
CREATE TABLE identity.auth_handoffs (
    digest      text PRIMARY KEY,
    attempt_id  text NOT NULL REFERENCES identity.auth_attempts (id) ON DELETE CASCADE,
    expires_at  timestamptz NOT NULL,
    consumed_at timestamptz
);
CREATE INDEX auth_handoffs_expiry ON identity.auth_handoffs (expires_at);
CREATE TABLE identity.auth_challenges (
    id               text PRIMARY KEY,
    owner_id         text REFERENCES identity.users (id) ON DELETE CASCADE,
    auth_version     integer NOT NULL DEFAULT 0 CHECK (auth_version >= 0),
    session_hash     text,
    purpose          text NOT NULL,
    destination      text NOT NULL,
    action           text,
    attempt_id       text REFERENCES identity.auth_attempts (id) ON DELETE CASCADE,
    client_challenge text NOT NULL,
    code_hmac        text,
    key_id           text,
    status           text NOT NULL DEFAULT 'pending',
    eligible         boolean NOT NULL DEFAULT false,
    created_at       timestamptz NOT NULL,
    expires_at       timestamptz NOT NULL,
    resend_at        timestamptz,
    failures         integer NOT NULL DEFAULT 0 CHECK (failures >= 0),
    generation       integer NOT NULL DEFAULT 1 CHECK (generation >= 1),
    payload          jsonb NOT NULL DEFAULT '{}'::jsonb,
    FOREIGN KEY (session_hash, owner_id) REFERENCES identity.sessions (token_hash, owner_id) ON DELETE CASCADE
);
CREATE INDEX auth_challenges_owner ON identity.auth_challenges (owner_id);
CREATE INDEX auth_challenges_expiry ON identity.auth_challenges (expires_at);
CREATE TABLE identity.auth_mail_jobs (
    id             text PRIMARY KEY,
    challenge_id   text NOT NULL REFERENCES identity.auth_challenges (id) ON DELETE CASCADE,
    generation     integer NOT NULL DEFAULT 1 CHECK (generation >= 1),
    status         text NOT NULL DEFAULT 'pending',
    created_at     timestamptz NOT NULL,
    expires_at     timestamptz NOT NULL,
    lease_id       text,
    leased_at      timestamptz,
    sealed_payload text,
    key_id         text,
    payload        jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX auth_mail_jobs_dispatch ON identity.auth_mail_jobs (status, expires_at);
CREATE TABLE identity.auth_proofs (
    digest              text PRIMARY KEY,
    owner_id            text NOT NULL REFERENCES identity.users (id) ON DELETE CASCADE,
    auth_version        integer NOT NULL DEFAULT 0 CHECK (auth_version >= 0),
    session_hash        text,
    client_challenge    text,
    purpose             text NOT NULL,
    action              text,
    provider_binding_id text,
    generation          integer,
    created_at          timestamptz NOT NULL,
    expires_at          timestamptz NOT NULL,
    consumed_at         timestamptz,
    payload             jsonb NOT NULL DEFAULT '{}'::jsonb,
    FOREIGN KEY (session_hash, owner_id) REFERENCES identity.sessions (token_hash, owner_id) ON DELETE CASCADE,
    FOREIGN KEY (provider_binding_id, owner_id) REFERENCES identity.auth_identity_bindings (id, owner_id) ON DELETE CASCADE
);
CREATE INDEX auth_proofs_owner ON identity.auth_proofs (owner_id);
CREATE INDEX auth_proofs_expiry ON identity.auth_proofs (expires_at);
CREATE TABLE identity.auth_budgets (
    scope             text NOT NULL,
    fingerprint       text NOT NULL,
    key_id            text NOT NULL,
    window_started_at timestamptz NOT NULL,
    count             integer NOT NULL DEFAULT 0 CHECK (count >= 0),
    resend_at         timestamptz,
    expires_at        timestamptz NOT NULL,
    PRIMARY KEY (scope, fingerprint, key_id, window_started_at)
);
CREATE INDEX auth_budgets_expiry ON identity.auth_budgets (expires_at);
CREATE TABLE identity.auth_apple_grants (
    id             text PRIMARY KEY,
    owner_id       text NOT NULL REFERENCES identity.users (id) ON DELETE CASCADE,
    binding_id     text NOT NULL,
    issuing_client text NOT NULL,
    generation     integer NOT NULL CHECK (generation >= 1),
    sealed_payload text NOT NULL,
    key_id         text NOT NULL,
    created_at     timestamptz NOT NULL,
    expires_at     timestamptz,
    UNIQUE (binding_id, issuing_client, generation),
    FOREIGN KEY (binding_id, owner_id) REFERENCES identity.auth_identity_bindings (id, owner_id) ON DELETE CASCADE
);
CREATE TABLE identity.auth_apple_cleanup_jobs (
    id               text PRIMARY KEY,
    owner_id         text NOT NULL REFERENCES identity.users (id) ON DELETE CASCADE,
    binding_id       text NOT NULL,
    issuing_client   text NOT NULL,
    generation       integer NOT NULL CHECK (generation >= 1),
    sealed_payload   text,
    key_id           text,
    reason           text NOT NULL,
    status           text NOT NULL DEFAULT 'pending',
    attempts         integer NOT NULL DEFAULT 0 CHECK (attempts >= 0 AND attempts <= 5),
    created_at       timestamptz NOT NULL,
    expires_at       timestamptz NOT NULL,
    next_attempt_at  timestamptz,
    lease_id         text,
    lease_expires_at timestamptz,
    payload          jsonb NOT NULL DEFAULT '{}'::jsonb,
    FOREIGN KEY (binding_id, owner_id) REFERENCES identity.auth_identity_bindings (id, owner_id) ON DELETE CASCADE
);
CREATE INDEX auth_apple_jobs_dispatch
    ON identity.auth_apple_cleanup_jobs (status, next_attempt_at, expires_at);
CREATE TABLE identity.auth_apple_notification_receipts (
    digest              text PRIMARY KEY,
    namespace           text NOT NULL,
    event               text NOT NULL,
    subject_fingerprint text NOT NULL,
    generation          integer,
    event_at            timestamptz NOT NULL,
    created_at          timestamptz NOT NULL,
    expires_at          timestamptz NOT NULL
);
CREATE INDEX auth_apple_receipts_expiry
    ON identity.auth_apple_notification_receipts (expires_at);
-- ADR-0029 CLI device grants (`interval` renamed `poll_interval`, reserved word).
CREATE TABLE identity.cli_device_grants (
    device_hash   text PRIMARY KEY,
    code_hash     text NOT NULL UNIQUE,
    created_at    timestamptz NOT NULL,
    expires_at    timestamptz NOT NULL,
    state         text NOT NULL
        CHECK (state IN ('pending', 'approved', 'denied', 'consumed')),
    poll_interval integer NOT NULL CHECK (poll_interval >= 5),
    next_poll_at  timestamptz NOT NULL,
    owner_id      text REFERENCES identity.users (id) ON DELETE CASCADE,
    source_hash   text,
    auth_version  integer,
    auth_method   text,
    binding_id    text,
    generation    integer,
    FOREIGN KEY (source_hash, owner_id) REFERENCES identity.sessions (token_hash, owner_id) ON DELETE CASCADE,
    FOREIGN KEY (binding_id, owner_id) REFERENCES identity.auth_identity_bindings (id, owner_id) ON DELETE CASCADE
);
CREATE INDEX cli_device_expiry ON identity.cli_device_grants (expires_at);
-- contracts/invite-handoff.md: "stored hashed", "expiry of 10 minutes. Single use."
CREATE TABLE identity.pending_signups (
    token_hash       text PRIMARY KEY,
    provider         text NOT NULL,
    issuer           text NOT NULL,
    namespace        text NOT NULL DEFAULT '',
    subject          text,
    email            text,
    email_verified   boolean NOT NULL DEFAULT false,
    is_private_email boolean NOT NULL DEFAULT false,
    binder_hash      text NOT NULL,  -- binder/session the token was issued to
    created_at       timestamptz NOT NULL,
    expires_at       timestamptz NOT NULL,
    consumed_at      timestamptz,
    CHECK (expires_at <= created_at + interval '10 minutes'),
    CHECK (subject IS NOT NULL OR email IS NOT NULL)
);
CREATE INDEX pending_signups_expiry ON identity.pending_signups (expires_at);
