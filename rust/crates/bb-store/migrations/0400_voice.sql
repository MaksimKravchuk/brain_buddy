-- 0400 voice: schema owned by the Capture / voice workflow module (ADR-0002).
-- Mirrors voice_operations.sqlite3 (CAP-STORE-006). Forward-only, expand-only.
-- Every owner-scoped table carries `owner_id` and every query filters on it;
-- timestamps are timestamptz (UTC); identifiers keep their wire format
-- (prefix + random). Audio bytes live in the object store (bucket `voice`,
-- key <owner_id>/<operation_id>/<chunk_seq>, research R11); this schema holds
-- metadata and keys only.

CREATE SCHEMA IF NOT EXISTS voice;

CREATE TABLE voice.operations (
    owner_id   text        NOT NULL,
    id         text        NOT NULL,
    status     text        NOT NULL,
    updated_at timestamptz NOT NULL,
    payload    jsonb       NOT NULL,
    PRIMARY KEY (owner_id, id)
);
CREATE INDEX idx_voice_operations_owner_status
    ON voice.operations (owner_id, status, updated_at, id);

-- Per-operation workflow stages (upload, transcribe, extract, reconcile...).
CREATE TABLE voice.operation_stages (
    owner_id     text        NOT NULL,
    operation_id text        NOT NULL,
    stage        text        NOT NULL,
    status       text        NOT NULL,
    attempts     integer     NOT NULL DEFAULT 0,
    error_code   text,
    started_at   timestamptz,
    finished_at  timestamptz,
    updated_at   timestamptz NOT NULL,
    PRIMARY KEY (owner_id, operation_id, stage),
    FOREIGN KEY (owner_id, operation_id)
        REFERENCES voice.operations (owner_id, id) ON DELETE CASCADE
);
CREATE INDEX idx_voice_stages_status
    ON voice.operation_stages (status, updated_at);

-- Stored-audio object keys. `deleting` is the delete marker of the research R11
-- protocol: mark rows deleting -> delete every object (idempotent, retried) ->
-- delete rows. The purge job resumes from `deleting` rows. `unavailable` marks
-- a row whose object is gone (AUDIO_UNAVAILABLE after a restore).
CREATE TABLE voice.audio_objects (
    owner_id     text        NOT NULL,
    operation_id text        NOT NULL,
    chunk_seq    integer     NOT NULL CHECK (chunk_seq >= 0),
    object_key   text        NOT NULL,
    sha256       text        NOT NULL,
    size_bytes   bigint      NOT NULL CHECK (size_bytes >= 0),
    state        text        NOT NULL DEFAULT 'stored'
                 CHECK (state IN ('stored', 'deleting', 'unavailable')),
    created_at   timestamptz NOT NULL,
    updated_at   timestamptz NOT NULL,
    PRIMARY KEY (owner_id, operation_id, chunk_seq),
    UNIQUE (object_key)
);
-- The orphan sweep and the purge resume read by state and age.
CREATE INDEX idx_voice_audio_state ON voice.audio_objects (state, updated_at);
CREATE INDEX idx_voice_audio_owner ON voice.audio_objects (owner_id, state);

-- Provisional items proposed from a transcript before the owner confirms them.
CREATE TABLE voice.provisional_items (
    owner_id     text        NOT NULL,
    operation_id text        NOT NULL,
    id           text        NOT NULL,
    status       text        NOT NULL DEFAULT 'provisional'
                 CHECK (status IN ('provisional', 'user_edited', 'confirmed', 'discarded')),
    payload      jsonb       NOT NULL,
    created_at   timestamptz NOT NULL,
    updated_at   timestamptz NOT NULL,
    PRIMARY KEY (owner_id, operation_id, id),
    FOREIGN KEY (owner_id, operation_id)
        REFERENCES voice.operations (owner_id, id) ON DELETE CASCADE
);

CREATE TABLE voice.idempotency_records (
    owner_id      text        NOT NULL,
    key_hash      text        NOT NULL,
    key           text        NOT NULL,
    command       text        NOT NULL,
    request_hash  text        NOT NULL,
    resource_id   text        NOT NULL,
    response_body jsonb       NOT NULL,
    created_at    timestamptz NOT NULL,
    PRIMARY KEY (owner_id, key_hash)
);
CREATE INDEX idx_voice_idempotency_owner_created
    ON voice.idempotency_records (owner_id, created_at);
