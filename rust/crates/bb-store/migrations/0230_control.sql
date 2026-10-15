-- 0230_control: the `control` schema owned by the Control module (research R11). Forward-only,
-- expand-only. The append-only ledger entries themselves live in object storage (bucket
-- `control`), outside PostgreSQL, so a point-in-time restore cannot roll them back; only the
-- applied set and the maintenance state live here.
-- data-model.md: "Every owner-scoped table carries `owner_id` and every query filters on it"
-- (these tables are instance-wide and hold no owner data)
-- data-model.md: "Timestamps are `timestamptz` in UTC; identifiers keep their current wire format (prefix + random)"
CREATE SCHEMA IF NOT EXISTS control;

-- Written by bb_store::control::mark_applied(&mut tx, seq) inside the applying module's own
-- transaction, so an entry's effect and its applied row commit together.
CREATE TABLE control.control_applied (
    seq        bigint PRIMARY KEY CHECK (seq > 0),
    applied_at timestamptz NOT NULL DEFAULT now()
);

-- Single-row maintenance state: the server stays closed while the ledger has a gap or a
-- restore reconciliation is pending.
CREATE TABLE control.maintenance (
    id         smallint PRIMARY KEY CHECK (id = 1),
    state      text NOT NULL DEFAULT 'open' CHECK (state IN ('open', 'closed')),
    reason     text,
    floor_seq  bigint NOT NULL DEFAULT 0,   -- control/FLOOR pruning bookkeeping
    updated_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO control.maintenance (id) VALUES (1);
