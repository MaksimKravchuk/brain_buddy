-- 0200_tasks: the `tasks` schema (027 data-model.md, PR-17).
-- Source of truth: backend/app/modules/tasks/repository.py and review_repository.py.
--
-- data-model.md: "Every owner-scoped table carries `owner_id` and every query filters on it"
-- data-model.md: "Timestamps are `timestamptz` in UTC; identifiers keep their current wire format (prefix + random)"
--
-- Forward-only and expand-only. Owned by bb_store::tasks (the Tasks owner group:
-- tasks, review, navigator). The sync and jobs schemas arrive in 0210 and 0220.
-- No foreign key reaches into `identity`: owner_id is an opaque text id and the
-- account purge port deletes across schemas. `migration_ledger` (legacy JSON
-- import) is not ported: production starts empty (FR-019).
--
-- Length limits mirror the 026 command catalog, counted in Unicode scalar
-- values (char_length): task title 500, details/comment 20,000, name 500,
-- project outcome 1,000. They are enforced in bb-domain; the CHECKs below are
-- the column bounds that back them. Fields not promoted to columns stay in the
-- jsonb `payload`, exactly as the document models do today.

CREATE SCHEMA IF NOT EXISTS tasks;

CREATE TABLE tasks.projects (
    owner_id        text  NOT NULL,
    id              text  NOT NULL,
    normalized_name text  NOT NULL,
    state           text  NOT NULL,
    payload         jsonb NOT NULL,
    PRIMARY KEY (owner_id, id),
    CONSTRAINT projects_name_len
        CHECK (char_length(payload->>'name') BETWEEN 1 AND 500),
    CONSTRAINT projects_normalized_name_len
        CHECK (char_length(normalized_name) <= 500),
    CONSTRAINT projects_outcome_len
        CHECK (char_length(payload->>'desired_outcome') <= 1000)
);

CREATE TABLE tasks.tags (
    owner_id        text  NOT NULL,
    id              text  NOT NULL,
    normalized_name text  NOT NULL,
    state           text  NOT NULL,
    payload         jsonb NOT NULL,
    PRIMARY KEY (owner_id, id),
    CONSTRAINT tags_name_len
        CHECK (char_length(payload->>'name') BETWEEN 1 AND 500),
    CONSTRAINT tags_normalized_name_len
        CHECK (char_length(normalized_name) <= 500)
);

CREATE TABLE tasks.tasks (
    owner_id   text        NOT NULL,
    id         text        NOT NULL,
    state      text        NOT NULL,
    project_id text,
    order_key  integer     NOT NULL CHECK (order_key >= 0),
    created_at timestamptz NOT NULL,
    payload    jsonb       NOT NULL,
    PRIMARY KEY (owner_id, id),
    FOREIGN KEY (owner_id, project_id)
        REFERENCES tasks.projects (owner_id, id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT tasks_title_len
        CHECK (char_length(payload->>'title') BETWEEN 1 AND 500),
    CONSTRAINT tasks_details_len
        CHECK (char_length(payload->>'details') <= 20000),
    CONSTRAINT tasks_waiting_for_len
        CHECK (char_length(payload->>'waiting_for') <= 500)
);

CREATE TABLE tasks.task_tags (
    owner_id text NOT NULL,
    task_id  text NOT NULL,
    tag_id   text NOT NULL,
    PRIMARY KEY (owner_id, task_id, tag_id),
    FOREIGN KEY (owner_id, task_id)
        REFERENCES tasks.tasks (owner_id, id) ON DELETE CASCADE,
    FOREIGN KEY (owner_id, tag_id)
        REFERENCES tasks.tags (owner_id, id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE TABLE tasks.subtasks (
    owner_id text  NOT NULL,
    task_id  text  NOT NULL,
    id       text  NOT NULL,
    payload  jsonb NOT NULL,
    PRIMARY KEY (owner_id, task_id, id),
    FOREIGN KEY (owner_id, task_id)
        REFERENCES tasks.tasks (owner_id, id) ON DELETE CASCADE,
    CONSTRAINT subtasks_title_len
        CHECK (char_length(payload->>'title') BETWEEN 1 AND 500)
);

CREATE TABLE tasks.comments (
    owner_id text  NOT NULL,
    task_id  text  NOT NULL,
    id       text  NOT NULL,
    payload  jsonb NOT NULL,
    PRIMARY KEY (owner_id, task_id, id),
    FOREIGN KEY (owner_id, task_id)
        REFERENCES tasks.tasks (owner_id, id) ON DELETE CASCADE,
    CONSTRAINT comments_body_len
        CHECK (char_length(payload->>'body') BETWEEN 1 AND 20000)
);

-- Full response kept as the exact stored text so replay is byte-identical;
-- redaction after 24 h is a retention job (data-model.md retention rules).
CREATE TABLE tasks.idempotency_records (
    owner_id      text        NOT NULL,
    key_hash      text        NOT NULL,
    key           text        NOT NULL,
    command       text        NOT NULL,
    request_hash  text        NOT NULL,
    resource_id   text        NOT NULL,
    response_body text        NOT NULL,
    created_at    timestamptz NOT NULL,
    PRIMARY KEY (owner_id, key_hash)
);

CREATE TABLE tasks.review_settings (
    owner_id text    PRIMARY KEY,
    revision integer NOT NULL,
    payload  jsonb   NOT NULL
);

CREATE TABLE tasks.review_sessions (
    owner_id   text        NOT NULL,
    id         text        NOT NULL,
    status     text        NOT NULL,
    started_at timestamptz NOT NULL,
    payload    jsonb       NOT NULL,
    PRIMARY KEY (owner_id, id)
);

CREATE TABLE tasks.review_decisions (
    owner_id   text        NOT NULL,
    id         text        NOT NULL,
    task_id    text        NOT NULL,
    session_id text,
    decided_at timestamptz NOT NULL,
    payload    jsonb       NOT NULL,
    PRIMARY KEY (owner_id, id)
);

CREATE TABLE tasks.review_receipts (
    owner_id text  NOT NULL,
    task_id  text  NOT NULL,
    kind     text  NOT NULL,
    payload  jsonb NOT NULL,
    PRIMARY KEY (owner_id, task_id, kind)
);

CREATE TABLE tasks.review_park_acks (
    owner_id       text  NOT NULL,
    task_id        text  NOT NULL,
    formulation_id text  NOT NULL,
    payload        jsonb NOT NULL,
    PRIMARY KEY (owner_id, task_id, formulation_id)
);

CREATE TABLE tasks.review_bulk_releases (
    owner_id   text        NOT NULL,
    id         text        NOT NULL,
    created_at timestamptz NOT NULL,
    payload    jsonb       NOT NULL,
    PRIMARY KEY (owner_id, id)
);

CREATE TABLE tasks.navigator_consents (
    owner_id text  NOT NULL,
    provider text  NOT NULL,
    payload  jsonb NOT NULL,
    PRIMARY KEY (owner_id, provider)
);

CREATE TABLE tasks.navigator_usage (
    owner_id text  NOT NULL,
    day      date  NOT NULL,
    payload  jsonb NOT NULL,
    PRIMARY KEY (owner_id, day)
);

CREATE INDEX idx_tasks_owner_state
    ON tasks.tasks (owner_id, state, order_key, created_at, id);
CREATE INDEX idx_task_tags_owner_tag
    ON tasks.task_tags (owner_id, tag_id, task_id);
CREATE INDEX idx_idempotency_owner_created
    ON tasks.idempotency_records (owner_id, created_at);
CREATE INDEX idx_review_sessions_owner_status
    ON tasks.review_sessions (owner_id, status, started_at);
CREATE INDEX idx_review_decisions_owner_task
    ON tasks.review_decisions (owner_id, task_id);
CREATE INDEX idx_review_decisions_owner_session
    ON tasks.review_decisions (owner_id, session_id);
