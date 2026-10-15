-- 0210_sync: the `sync` schema (Tasks owner group, 026 sync). Forward-only, expand-only.
-- data-model.md: "Every owner-scoped table carries `owner_id` and every query filters on it"
-- data-model.md: "Timestamps are `timestamptz` in UTC; identifiers keep their current wire format (prefix + random)"
-- Commit sequences, generations and versions keep their wire format (opaque text), as in sync v1.
CREATE SCHEMA IF NOT EXISTS sync;

CREATE TABLE sync.scopes (
    owner_id          text PRIMARY KEY,
    server_generation text NOT NULL,
    feed_generation   text NOT NULL,
    access_generation text NOT NULL,
    storage_epoch     text NOT NULL,
    admission_open    boolean NOT NULL,
    -- per-scope commit sequence; advanced only inside the committing unit of work
    commit_seq        text NOT NULL
);

CREATE TABLE sync.command_receipts (
    owner_id      text NOT NULL,
    command_id    text NOT NULL,
    writer_origin text NOT NULL,
    fingerprint   text NOT NULL,
    metadata      text NOT NULL,          -- content-free, kept until account purge
    result        text,                   -- full response, dropped after 24 h
    created_at    timestamptz NOT NULL,
    expires_at    timestamptz NOT NULL,
    PRIMARY KEY (owner_id, command_id)
);
CREATE INDEX sync_receipt_expiry ON sync.command_receipts (owner_id, expires_at);

CREATE TABLE sync.legacy_keys (
    owner_id   text NOT NULL,
    key_digest text NOT NULL,
    command_id text NOT NULL,
    PRIMARY KEY (owner_id, key_digest)
);

CREATE TABLE sync.record_versions (
    owner_id       text NOT NULL,
    entity_type    text NOT NULL,
    record_key     text NOT NULL,
    record_version text NOT NULL,
    deleted        boolean NOT NULL,
    PRIMARY KEY (owner_id, entity_type, record_key)
);

CREATE TABLE sync.change_transactions (
    owner_id          text NOT NULL,
    commit_seq        text NOT NULL,
    transaction_id    text NOT NULL,
    source_command_id text NOT NULL,
    committed_at      timestamptz NOT NULL,
    PRIMARY KEY (owner_id, commit_seq),
    UNIQUE (owner_id, transaction_id),
    UNIQUE (owner_id, source_command_id)
);

CREATE TABLE sync.change_records (
    owner_id          text NOT NULL,
    commit_seq        text NOT NULL,
    entity_type       text NOT NULL,
    record_key        text NOT NULL,
    record_version    text NOT NULL,
    edit_revision     text,
    operation         text NOT NULL,
    value             text,
    source_expires_at timestamptz,
    PRIMARY KEY (owner_id, commit_seq, entity_type, record_key),
    FOREIGN KEY (owner_id, commit_seq)
        REFERENCES sync.change_transactions (owner_id, commit_seq) ON DELETE CASCADE
);
CREATE INDEX sync_change_record_history
    ON sync.change_records (owner_id, entity_type, record_key);

CREATE TABLE sync.devices (
    device_id text PRIMARY KEY,
    owner_id  text NOT NULL,
    bound_at  timestamptz NOT NULL
);
CREATE INDEX sync_devices_owner ON sync.devices (owner_id);

CREATE TABLE sync.device_epochs (
    device_id         text NOT NULL,
    device_epoch      text NOT NULL,
    owner_id          text NOT NULL,
    status            text NOT NULL,
    server_generation text NOT NULL,
    registered_at     timestamptz NOT NULL,
    closed_at         timestamptz,
    close_reason      text,
    PRIMARY KEY (device_id, device_epoch)
);
CREATE INDEX sync_device_epochs_owner ON sync.device_epochs (owner_id);

CREATE TABLE sync.transfers (
    owner_id          text NOT NULL,
    transfer_id       text NOT NULL,
    commit_seq        text NOT NULL,
    transaction_id    text NOT NULL,
    source_command_id text NOT NULL,
    feed_generation   text NOT NULL,
    access_generation text NOT NULL,
    page_count        integer NOT NULL,
    record_count      integer NOT NULL,
    total_bytes       bigint NOT NULL,
    sha256            text NOT NULL,
    created_at        timestamptz NOT NULL,
    expires_at        timestamptz NOT NULL,
    PRIMARY KEY (owner_id, transfer_id)
);
CREATE INDEX sync_transfer_commit ON sync.transfers (owner_id, commit_seq);

CREATE TABLE sync.transfer_pages (
    owner_id    text NOT NULL,
    transfer_id text NOT NULL,
    page_index  integer NOT NULL,
    payload     bytea NOT NULL,
    page_sha256 text NOT NULL,
    PRIMARY KEY (owner_id, transfer_id, page_index),
    FOREIGN KEY (owner_id, transfer_id)
        REFERENCES sync.transfers (owner_id, transfer_id) ON DELETE CASCADE
);

CREATE TABLE sync.snapshots (
    owner_id          text NOT NULL,
    snapshot_id       text NOT NULL,
    watermark         text NOT NULL,
    feed_generation   text NOT NULL,
    access_generation text NOT NULL,
    page_count        integer NOT NULL,
    record_count      integer NOT NULL,
    total_bytes       bigint NOT NULL,
    sha256            text NOT NULL,
    created_at        timestamptz NOT NULL,
    expires_at        timestamptz NOT NULL,
    PRIMARY KEY (owner_id, snapshot_id)
);

CREATE TABLE sync.snapshot_pages (
    owner_id    text NOT NULL,
    snapshot_id text NOT NULL,
    page_index  integer NOT NULL,
    payload     bytea NOT NULL,
    page_sha256 text NOT NULL,
    PRIMARY KEY (owner_id, snapshot_id, page_index),
    FOREIGN KEY (owner_id, snapshot_id)
        REFERENCES sync.snapshots (owner_id, snapshot_id) ON DELETE CASCADE
);
