-- 0300_crt: the `crt` schema (spec 027, PR-19, ASK-class).
--
-- Replaces the JSON tree files (`<tree_id>/tree.json`, `versions/`, `validation/`,
-- `index.json`, CAP-STORE-012), `crt_commands.sqlite3` (CAP-STORE-009) and the
-- validation provider registry `config.json` (CAP-STORE-013).
--
-- data-model.md rules, quoted:
--   "Every owner-scoped table carries `owner_id` and every query filters on it"
--   "Timestamps are `timestamptz` in UTC; identifiers keep their current wire
--    format (prefix + random)"
-- Forward-only and expand-only: nothing here drops or rewrites an existing object.
-- No cross-schema foreign keys: owner_id references identity by value only, and
-- account purge reaches this schema through the purge port (data-model.md).

CREATE SCHEMA IF NOT EXISTS crt;

-- One row per tree aggregate; also serves as the tree index (index.json).
CREATE TABLE crt.trees (
    id              text PRIMARY KEY,
    owner_id        text NOT NULL,
    revision        integer NOT NULL DEFAULT 1 CHECK (revision >= 1),
    schema_version  integer NOT NULL DEFAULT 1 CHECK (schema_version >= 1),
    last_command_id text CHECK (last_command_id ~ '^[0-9a-f]{64}$'),
    title           text NOT NULL,
    description     text,
    metadata        text,
    created_at      timestamptz NOT NULL,
    updated_at      timestamptz NOT NULL
);
-- Owner listing ordered by recency (the index listing).
CREATE INDEX idx_crt_trees_owner_updated ON crt.trees (owner_id, updated_at DESC);

CREATE TABLE crt.nodes (
    tree_id    text NOT NULL REFERENCES crt.trees (id) ON DELETE CASCADE,
    id         text NOT NULL,
    owner_id   text NOT NULL,
    label      text NOT NULL,
    payload    text NOT NULL,  -- position, metadata, visual, validation, extra
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    PRIMARY KEY (tree_id, id)
);
CREATE INDEX idx_crt_nodes_owner ON crt.nodes (owner_id, tree_id);

CREATE TABLE crt.relations (
    tree_id        text NOT NULL REFERENCES crt.trees (id) ON DELETE CASCADE,
    id             text NOT NULL,
    owner_id       text NOT NULL,
    source_id      text NOT NULL,
    target_id      text NOT NULL,
    question_label text NOT NULL DEFAULT 'WHY?',
    notes          text,
    author         text,
    created_at     timestamptz NOT NULL,
    updated_at     timestamptz NOT NULL,
    PRIMARY KEY (tree_id, id),
    FOREIGN KEY (tree_id, source_id) REFERENCES crt.nodes (tree_id, id)
        ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (tree_id, target_id) REFERENCES crt.nodes (tree_id, id)
        ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED
);
CREATE INDEX idx_crt_relations_owner ON crt.relations (owner_id, tree_id);

-- Version snapshots (`versions/<slug>.json`); ids such as "v::..." stay verbatim.
CREATE TABLE crt.versions (
    tree_id        text NOT NULL REFERENCES crt.trees (id) ON DELETE CASCADE,
    id             text NOT NULL,
    owner_id       text NOT NULL,
    label          text NOT NULL,
    captured_at    timestamptz NOT NULL,
    author         text,
    notes          text,
    diff           text NOT NULL,
    conflicts      text NOT NULL DEFAULT '[]',
    tree_snapshot  text NOT NULL,
    PRIMARY KEY (tree_id, id)
);
CREATE INDEX idx_crt_versions_owner ON crt.versions (owner_id, tree_id, captured_at);

-- Validation history (`validation/<node_id>.json`): ordered, append-only entries.
CREATE TABLE crt.validation_history (
    tree_id      text NOT NULL REFERENCES crt.trees (id) ON DELETE CASCADE,
    node_id      text NOT NULL,
    seq          bigint GENERATED ALWAYS AS IDENTITY,
    owner_id     text NOT NULL,
    confidence   integer NOT NULL CHECK (confidence BETWEEN 0 AND 100),
    summary      text NOT NULL,
    provider     text NOT NULL,
    prompt_hash  text NOT NULL,
    checked_at   timestamptz NOT NULL,
    raw_response text,
    PRIMARY KEY (tree_id, node_id, seq)
);
CREATE INDEX idx_crt_validation_owner ON crt.validation_history (owner_id, tree_id);

-- Validation provider registry (`config.json`, CAP-STORE-013). Deployment-wide,
-- not owner-scoped: it holds only provider ids, model names and `api_key_ref`
-- indirection (never a key value).
CREATE TABLE crt.validation_providers (
    provider_id text PRIMARY KEY,
    api_key_ref text,
    model       text,
    extra       text NOT NULL DEFAULT '{}',  -- ProviderConfig allows extras
    updated_at  timestamptz NOT NULL DEFAULT now()
);
-- At most one row; default_provider is NULL when none is chosen.
CREATE TABLE crt.validation_provider_default (
    singleton        boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    default_provider text REFERENCES crt.validation_providers (provider_id)
        ON DELETE SET NULL
);

-- Idempotency receipts (ADR-0026, `crt_command_receipts`). The response body is
-- kept exactly 30 days (expires_at = created_at + 30 days), then the sweep sets
-- state = 'expired', clears response_json and stamps redacted_at, leaving a
-- content-free tombstone until account purge.
CREATE TABLE crt.command_receipts (
    owner_id                text NOT NULL,
    key_digest              text NOT NULL,
    command                 text NOT NULL,
    normalized_route        text NOT NULL,
    request_hash            text NOT NULL,
    state                   text NOT NULL CHECK (state IN ('pending', 'committed', 'expired')),
    resource_id             text NOT NULL,
    base_revision           integer,
    target_revision         integer,
    response_status         integer,
    response_json           text,
    created_at              timestamptz NOT NULL,
    committed_at            timestamptz,
    expires_at              timestamptz NOT NULL,
    pending_target_snapshot text,
    redacted_at             timestamptz,  -- tombstone marker (body gone)
    PRIMARY KEY (owner_id, key_digest),
    CONSTRAINT crt_receipt_tombstone_empty
        CHECK (state <> 'expired' OR (response_json IS NULL AND pending_target_snapshot IS NULL))
);
CREATE INDEX idx_crt_command_expiry ON crt.command_receipts (expires_at)
    WHERE state <> 'expired';
CREATE INDEX idx_crt_command_pending ON crt.command_receipts (created_at)
    WHERE state = 'pending';
CREATE INDEX idx_crt_command_resource ON crt.command_receipts (owner_id, resource_id)
    WHERE state = 'pending';

-- Per-owner CRT exposure (the owner-level flag decision CrtExposureService reads).
CREATE TABLE crt.exposure (
    owner_id   text PRIMARY KEY,
    enabled    boolean NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);
