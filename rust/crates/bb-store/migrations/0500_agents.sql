-- 0500 agents: schema owned by the Agents module (specs 007/014).
-- Mirrors agents.sqlite3 (CAP-STORE-008). Forward-only, expand-only.
-- Every owner-scoped table carries `owner_id` and every query filters on it;
-- timestamps are timestamptz (UTC); identifiers keep their wire format
-- (prefix + random). `payload` stays the source of truth for a document; the
-- real columns are projections the schedulers read without parsing JSON.

CREATE SCHEMA IF NOT EXISTS agents;

CREATE TABLE agents.connections (
    owner_id   text        NOT NULL,
    id         text        NOT NULL,
    status     text        NOT NULL,
    created_at timestamptz NOT NULL,
    payload    text       NOT NULL,
    PRIMARY KEY (owner_id, id)
);

-- Sealed connector secrets, split out of the connection payload. Only sealed
-- (encrypted) values are stored; `key_id` is the non-secret id of the sealing
-- key so key retirement can list live key ids per owner.
CREATE TABLE agents.sealed_credentials (
    owner_id      text        NOT NULL,
    connection_id text        NOT NULL,
    kind          text        NOT NULL CHECK (kind IN ('credential', 'inbound_secret')),
    sealed        text        NOT NULL,
    key_id        text        NOT NULL,
    created_at    timestamptz NOT NULL,
    PRIMARY KEY (owner_id, connection_id, kind),
    FOREIGN KEY (owner_id, connection_id)
        REFERENCES agents.connections (owner_id, id) ON DELETE CASCADE
);
CREATE INDEX idx_agent_sealed_key ON agents.sealed_credentials (owner_id, key_id);

-- Runs, including the relay exchange state. `exchange_state` carries
-- none/queued/open/closed/interrupted and `uncertain_after_restore` (set by the
-- restore reconciliation hook, research R11): such an exchange is never resent
-- automatically and surfaces as the existing "needs attention" state.
CREATE TABLE agents.runs (
    owner_id              text        NOT NULL,
    id                    text        NOT NULL,
    connection_id         text        NOT NULL,
    task_id               text        NOT NULL,
    created_at            timestamptz NOT NULL,
    dispatched_at         timestamptz,
    manifest_token        text,
    content_expires_at    timestamptz NOT NULL,
    content_expired       boolean     NOT NULL DEFAULT false,
    agent_task_id         text,
    context_id            text,
    next_observation_at   timestamptz,
    exchange_state        text
        CHECK (exchange_state IN
            ('none', 'queued', 'open', 'closed', 'interrupted',
             'uncertain_after_restore')),
    identifiers_expire_at timestamptz,
    payload               text       NOT NULL,
    PRIMARY KEY (owner_id, id)
);
CREATE INDEX idx_agent_runs_task ON agents.runs (owner_id, task_id, created_at);
CREATE INDEX idx_agent_runs_expiry ON agents.runs (content_expired, content_expires_at);
CREATE INDEX idx_agent_runs_token ON agents.runs (owner_id, manifest_token);
-- Observations: the due-work query runs across owners; index only scheduled rows.
CREATE INDEX idx_agent_runs_observation
    ON agents.runs (next_observation_at) WHERE next_observation_at IS NOT NULL;
CREATE INDEX idx_agent_runs_exchange
    ON agents.runs (exchange_state) WHERE exchange_state = 'uncertain_after_restore';

CREATE TABLE agents.run_events (
    owner_id    text        NOT NULL,
    id          text        NOT NULL,
    run_id      text        NOT NULL,
    run_version integer     NOT NULL,
    received_at timestamptz NOT NULL,
    payload     text       NOT NULL,
    PRIMARY KEY (owner_id, run_id, id)
);
CREATE INDEX idx_agent_events_run ON agents.run_events (owner_id, run_id, run_version);

CREATE TABLE agents.run_commands (
    owner_id   text        NOT NULL,
    id         text        NOT NULL,
    run_id     text        NOT NULL,
    created_at timestamptz NOT NULL,
    payload    text       NOT NULL,
    PRIMARY KEY (owner_id, id)
);
CREATE INDEX idx_agent_commands_run ON agents.run_commands (owner_id, run_id, created_at);

CREATE TABLE agents.audit (
    owner_id   text        NOT NULL,
    id         text        NOT NULL,
    created_at timestamptz NOT NULL,
    payload    text       NOT NULL,
    PRIMARY KEY (owner_id, id)
);
CREATE INDEX idx_agent_audit_created ON agents.audit (created_at);

-- Bounded-cardinality ledger: a real unique key, so two workers racing the same
-- class write exactly one row.
CREATE TABLE agents.audit_buckets (
    owner_id   text        NOT NULL,
    action     text        NOT NULL,
    bucket     text        NOT NULL,
    day        date        NOT NULL,
    created_at timestamptz NOT NULL,
    PRIMARY KEY (owner_id, action, bucket, day)
);
CREATE INDEX idx_agent_audit_buckets_created ON agents.audit_buckets (created_at);

CREATE TABLE agents.idempotency (
    owner_id      text        NOT NULL,
    key_hash      text        NOT NULL,
    command       text        NOT NULL,
    request_hash  text        NOT NULL,
    resource_id   text        NOT NULL,
    command_id    text,
    -- Durable attempt marker written before connector I/O: a retry may resend
    -- a never-attempted command but must reconcile an attempted one.
    delivery_attempted boolean NOT NULL DEFAULT false,
    completed    boolean     NOT NULL DEFAULT true,
    response_body text       NOT NULL,
    created_at    timestamptz NOT NULL,
    PRIMARY KEY (owner_id, key_hash)
);
CREATE INDEX idx_agent_idempotency_created ON agents.idempotency (created_at);
