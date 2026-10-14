-- 0220_jobs: the `jobs` schema (Tasks owner group, 026 durable jobs). Forward-only, expand-only.
-- data-model.md: "Every owner-scoped table carries `owner_id` and every query filters on it"
-- data-model.md: "Timestamps are `timestamptz` in UTC; identifiers keep their current wire format (prefix + random)"
-- Claim with SELECT ... FOR UPDATE SKIP LOCKED (research R7). `scope` is the owner id, or
-- the system scope for owner-less jobs.
CREATE SCHEMA IF NOT EXISTS jobs;

-- Single monotonic fence source; a lease takes the next value.
CREATE TABLE jobs.fence_counter (
    id    smallint PRIMARY KEY CHECK (id = 1),
    value bigint NOT NULL
);
INSERT INTO jobs.fence_counter (id, value) VALUES (1, 0);

CREATE TABLE jobs.jobs (
    id               text PRIMARY KEY,
    scope            text NOT NULL,
    job_type         text NOT NULL,
    dedup_key        text NOT NULL,
    payload_ref      text,
    run_at           timestamptz NOT NULL,
    status           text NOT NULL,
    attempts         integer NOT NULL DEFAULT 0,
    max_attempts     integer NOT NULL,
    lease_owner      text,
    lease_until      timestamptz,
    fence            bigint NOT NULL DEFAULT 0,
    effect_id        text NOT NULL,
    last_error       text,
    correlation_id   text,
    cancel_requested boolean NOT NULL DEFAULT false,
    created_at       timestamptz NOT NULL,
    updated_at       timestamptz NOT NULL
);
CREATE UNIQUE INDEX idx_jobs_active_dedup
    ON jobs.jobs (scope, dedup_key)
    WHERE status IN ('queued', 'leased', 'reconciliation_required');
CREATE INDEX idx_jobs_due ON jobs.jobs (status, run_at, id);
CREATE INDEX idx_jobs_scope ON jobs.jobs (scope);

-- Jobs that exhausted attempts; content-free (error code only), kept until account purge.
CREATE TABLE jobs.dead_letters (
    job_id         text PRIMARY KEY,
    scope          text NOT NULL,
    job_type       text NOT NULL,
    attempts       integer NOT NULL,
    last_error     text,
    correlation_id text,
    dead_at        timestamptz NOT NULL
);
CREATE INDEX idx_dead_letters_scope ON jobs.dead_letters (scope);

-- Owner generations: once an owner's deletion begins the generation is closed and job
-- writes for that owner are refused (027-FR-017).
CREATE TABLE jobs.owner_generations (
    owner_id   text PRIMARY KEY,
    generation bigint NOT NULL DEFAULT 1,
    closed     boolean NOT NULL DEFAULT false,
    updated_at timestamptz NOT NULL
);
