# ADR-0019: SQLite becomes the sole runtime feature-flag store; `admin_portal` is deleted

Date: 2026-08-15
Status: Accepted
Decision owner: Founder (Maksim)
Related: ADR-0001, ADR-0002, ADR-0008, ADR-0012, ADR-0017, ADR-0018
Supersedes: nothing. Narrows ADR-0018 going forward, exactly as ADR-0018 itself narrowed ADR-0017 rather than editing it — ADR-0012 forbids amending an accepted record retroactively, so ADR-0018's text stays as written and is read together with this one.

## Context

Feature 010 (`specs/010-admin-live-feature-flags/`) shipped a JSON-overlay
design under ADR-0018: a document on the data volume overlaid the
deploy-staged environment baseline per managed flag, with an absent document
treated as healthy (fall back to the baseline) and a corrupt one treated as
degraded, plus an explicit "use deploy default" action to clear an override.
Before that design was implemented, the founder issued a direct, bounded
correction to it (this record and the matching correction to spec.md's DD
table, `specs/010-admin-live-feature-flags/spec.md`). The correction is
narrower than a new feature: it changes the storage architecture and one
authorization detail of an already-accepted, not-yet-implemented package, not
its user-facing shape (still OFF/ON/SELECTED_USERS, still the same `/admin`
section, still the same 15-second propagation contract).

## Decision

### 1. SQLite is the only source of truth for three runtime flags

`voice_brain_dump`, `mobile_task_classification`, and now `external_agent_relay`
are runtime-manageable, each with an explicit row (mode plus, for
`selected_users`, an account-id set) in one `feature_flags` table inside the
backend's existing SQLite persistence on the data volume — the same volume and
the same repository/transaction pattern `TaskRepository` already uses in this
codebase, not a new database abstraction. There is no environment overlay and
no "deploy default" left to inherit or clear once migration has run: every
managed flag's SQLite row is the entire answer.

`delivery_canary` is untouched: it stays a separate, environment/deploy-owned
release-smoke input, exactly as ADR-0018 §2 already decided, never
runtime-manageable, never migrated into this store.

### 2. `external_agent_relay` becomes runtime-manageable; capability stays separate

ADR-0018 §2 excluded `external_agent_relay` because `container.py`'s
`_build_agent_secret_box` makes a **construction-time** decision about the
relay's secret box that no request-time re-evaluation could retroactively
satisfy. That reasoning is preserved, not overturned: the secret-box
construction step is untouched, still decided once at boot. What changes is
that *rollout* (is this flag ON/OFF/SELECTED_USERS for this user) is no longer
conflated with *capability* (was a real secret box actually wired). They are
now two independent axes evaluated by AND: a runtime ON can never expose the
relay without a constructed capability, and a configured capability never
overrides a SQLite rollout answer that excludes the caller. Both must be
favorable, and either being unfavorable fails closed.

### 3. Migration is one-time, transactional, restart-idempotent, and never a standing fallback

A migration routine, guarded by a ledger row committed in the same transaction
as the seeded flag rows (mirroring `TaskRepository._migrate_legacy_json_once`),
runs once per fresh database: per flag, the pre-correction JSON overlay's
entry wins when it is present, well-formed, and for a flag that overlay ever
wrote (`voice_brain_dump`/`mobile_task_classification` only — it never wrote
`external_agent_relay`); otherwise the deploy-staged environment baseline
supplies it, resolving an `internal` stage to `selected_users` by looking up
each configured internal-user email's current immutable account id and
**skipping**, never substituting, an email that does not currently resolve —
migration can only narrow a cohort relative to the old behavior, never widen
it. A failure before the migration transaction commits leaves neither a ledger
row nor partial flag rows, and never deletes, renames or mutates the legacy
JSON file or the environment configuration, so a retried process start
migrates cleanly. After a successful migration, the environment and the legacy
JSON are never consulted again by normal reads or writes — only by the
one-time migration code itself, which is where `BRAIN_BUDDY_FEATURE_FLAGS` and
`BRAIN_BUDDY_FEATURE_FLAG_INTERNAL_USERS` retire to for these three flags.

### 4. Absence is impossible after migration; anything else is degraded, fail-closed

ADR-0018 §4 split an absent document (healthy) from a corrupt one (degraded).
That split no longer applies: migration guarantees all three rows exist, so
absence in normal operation is itself a storage failure, not a starting state.
The store is either **readable with three well-formed rows** (healthy) or
**degraded** — unreadable, a missing row, or a row whose `mode` is outside its
vocabulary — in which every flag resolves to ineffective, every mutation is
refused, and the store is never silently reconstructed from any other source.
The transition into degraded still emits exactly one coarse WARNING per
transition, as before.

### 5. `admin_portal` is deleted; the Admin Portal is always available to an authorized operator

ADR-0018 §2 excluded `admin_portal` from the managed set because "one click
could lock the only operator out with no in-app recovery." The founder
correction resolves that risk structurally instead of by exclusion:
`admin_portal` is deleted as a feature flag everywhere — `KNOWN_FEATURE_FLAGS`,
`PRIVATE_FEATURE_FLAGS` (now empty and removed), every gate
(`require_admin_portal_enabled` is deleted; every admin route depends on
feature 009's `require_operator` directly), every test, every doc reference,
and the deploy-staged `BRAIN_BUDDY_FEATURE_FLAGS` string. `/admin` is always
reachable by an authenticated operator on the server-owned allow-list — the
same session cookie, the same deny-before-touch precedence, the same
content-free denial audit feature 009 already established. No navigation
changes: 009 PD-1 still holds, `/admin` is reached only by typing the URL.

### 6. Everything ADR-0018 did not narrow stays as it was

Per-flag targeted mutations, cohort retention across OFF/ON, exact-match add
with idempotent remove, the content-free audit obligation (now three mutation
kinds instead of four — no more clear-override), the purge-scrub obligation
and its fail-closed halt-and-retry when degraded, and the 15-second client
propagation contract are all unchanged in substance. `docs/data-retention.md`
and `docs/auth.md` are updated to say "store" instead of "document" and to
point at this record where they pointed at ADR-0018; no new retention or audit
concept is introduced.

## Consequences

- ADR-0018's JSON-overlay design is superseded by this record for
  implementation purposes; ADR-0018 itself is left as written, a historical
  record of the design that preceded this correction, per ADR-0012.
- ADR-0017's "no admin data store" carve-out (narrowed once already by
  ADR-0018 §1) is unchanged in kind: one rollout-configuration store holding
  flag modes and account IDs, now three flags instead of two, still no member
  content.
- `docs/data-retention.md`, `docs/auth.md` and
  `frontend/src/pages/PrivacyPolicyPage.tsx` need the narrow, DD-9-named edits
  restated for "store" instead of "document" and for three flags instead of
  two; no new privacy surface.
- The deploy-staged `BRAIN_BUDDY_FEATURE_FLAGS` string retires its three
  managed-flag entries (staging them is inert after migration) and its
  `admin_portal` entry (deleted); `delivery_canary` keeps its entry unchanged.
  `.github/workflows/deploy-fly-production.yml` and
  `scripts/validate_trunk_delivery.py` need the corresponding narrow edits —
  named in tasks.md Lane G — with no other deploy mechanism change.
- Rollback is still ordered and has no dead end: an operator clicks the
  inverse (still effective within about fifteen seconds); an image rollback
  restores an older image whose own contemporaneous deploy-staged string is
  what its own rollback step restages, unaffected by this record; a code
  revert leaves the SQLite database on the volume as an unread file, exactly
  as the JSON document would have been.
- Changes to this boundary stay ASK class under ADR-0008 and never land
  automatically.
- Anything beyond this record and ADR-0018's untouched sections — percentage
  or scheduled rollouts, segments or rule expressions, an audit history
  platform, runtime management of a flag not named here, a second concurrent
  writer, or a redesign of the relay/provider secret-box construction — still
  requires its own ADR. Citing this record is not sufficient.
