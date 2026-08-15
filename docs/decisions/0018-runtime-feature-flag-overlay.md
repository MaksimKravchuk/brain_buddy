# ADR-0018: A runtime feature-flag overlay for two managed flags

Date: 2026-08-14
Status: Accepted
Decision owner: BrainBuddy
Related: ADR-0001, ADR-0002, ADR-0008, ADR-0012, ADR-0017
Supersedes: nothing. Narrows ADR-0017's "no admin data store" going forward.

## Context

Rollout flags are staged in `BRAIN_BUDDY_FEATURE_FLAGS` and reach production
only through a deploy. Feature 010 (`specs/010-admin-live-feature-flags/`) asks
an already-authorized operator to move a flag between OFF, ON and a
per-flag list of selected accounts *without* a deploy, and to have an
already-open member session pick the change up within about fifteen seconds.

That needs somewhere durable to put the chosen state. ADR-0017 ends with "no
new role model, no delegation, no impersonation, **no admin data store**" and
"anything beyond point 1 … requires its own ADR". Adding a durable,
operator-written document is beyond point 1, so proceeding without a record
would silently contradict an accepted decision — the exact failure ADR-0017 was
written to prevent. This record states the narrowing and dates it. ADR-0012
forbids amending an accepted record retroactively, so ADR-0017's text stays as
written.

## Decision

### 1. One document, holding rollout configuration and account IDs only

Runtime rollout state lives in exactly one server-owned JSON document on the
existing data volume, `{BRAIN_BUDDY_DATA_DIR}/feature-flags/runtime.json`
(`/app/data/feature-flags/runtime.json` in production). Per managed flag it
records a mode of `off`, `on` or `selected_users`, and — for `selected_users` —
a set of immutable account IDs.

It holds no email address, display name, credential, token, session hash or
member content. Emails shown on the operator screen are resolved live from the
account record at read time, which is the cross-owner account-record read
ADR-0017 §1 already authorizes; nothing about a member is duplicated into this
document. This is rollout *configuration* that happens to name accounts, not an
admin store of member data, and the distinction is the whole of the narrowing:
ADR-0017 §2 is unchanged, and no member content becomes operator-reachable.

### 2. Two managed flags, and why the other two are excluded

Only `voice_brain_dump` and `mobile_task_classification` are runtime-manageable.
The other `KNOWN_FEATURE_FLAGS` entries and the one `PRIVATE_FEATURE_FLAGS`
entry are not, each for its own stated reason:

- **`admin_portal`** — it is the authorization bootstrap for the surface that
  would be managing it. One click could lock the only operator out with no
  in-app recovery.
- **`delivery_canary`** — it is the assertion the authenticated production
  release smoke reads out of `/api/auth/me` to prove the deploy-staged internal
  cohort is wired end to end. Making it runtime-manageable would let one
  operator click durably fail and auto-roll-back every subsequent production
  deploy.
- **`external_agent_relay`** — it already has a per-request backend gate, so
  that is *not* the reason. The reason is that `container.py`'s
  `_build_agent_secret_box` makes a **construction-time** decision about whether
  the relay's secret box exists at all. No request-time re-evaluation can
  retroactively satisfy a prerequisite a completed startup step already decided,
  so managing this flag at runtime would mean rebuilding that construction step
  as a live, re-enterable one. That is a different feature.

A mutation naming any other flag is refused without writing anything, and the
refused flag's effective value stays exactly what the environment produces.

### 3. Per-flag precedence, never a merge — plus an explicit clear

Effective-flag evaluation is per flag and never blends the two sources. A
managed flag with no runtime entry resolves exactly as the environment-only
implementation resolves it, including the `internal`-stage cohort. A managed
flag *with* an entry resolves from that entry alone: `on` for every
authenticated user, `off` for none, `selected_users` exactly for the account IDs
in that flag's set.

Deploy-default inheritance is the **absence** of an entry, not a fourth mode.
An operator restores it with a distinct "use deploy default" action that deletes
the flag's entire entry, cohort included. Setting a mode that happens to match
the deploy default is still an override; only deleting the entry restores actual
inheritance.

The deploy-staged string keeps its job for every flag: it is the baseline a
fresh volume starts from, the floor an image rollback lands on, and — for
`delivery_canary` and `external_agent_relay` — the only source of truth. A
build that predates this record has no code that reads the document, so the
document is inert to it. No deploy workflow, script or CI file changes.

### 4. Absence is healthy; corruption is degraded

An **absent** document is the ordinary starting state of a fresh volume: every
flag resolves from the baseline and the operator's first mutation creates the
file. A document that **exists but cannot be parsed** is degraded: every flag
still resolves from the baseline, every mutation is refused rather than
overwriting bytes nobody could read, and the transition into that state emits
exactly one coarse `WARNING` (correlation id, reason band, count of overrides
that stopped applying — no member data).

Content this build does not recognize as its own known shape — an entry naming
an undeclared flag, an entry naming a declared-but-unmanaged flag, or an
unrecognized field inside a managed entry — is ignored for evaluation and
carried through every write value-intact, so a rollback to an older image cannot
destroy a newer one's state. A *recognized* field holding a value outside its
vocabulary is not forward compatibility; it is the document failing to parse,
and is degraded.

There is no reset command, repair button or recovery subsystem. Both fallbacks
land on a state the system already reaches by itself.

### 5. Flags stay exposure control, and the boundary does not move

No authorization decision reads a runtime-managed flag. The operator allow-list
and the `admin_portal` gate stay deployment configuration, exactly as ADR-0017
§3 requires, and every runtime-flag route sits behind feature 009's existing
gate — a valid session AND allow-list membership AND an effective
`admin_portal`, in that precedence, denying before it touches anything.

A runtime override also does not move the ADR-0002 consent boundary: a caller
newly admitted by a cohort still fails visibly when capturing without explicit
per-recording consent, and a caller under a runtime OFF override still reaches
the owner-authority voice routes (withdraw consent, cancel, delete raw audio).

### 6. Audit obligation: one content-free record per operation

Feature 009's `find_account` and `revoke_sessions` records do not fire for a
flag mutation, so this feature adds its own, in the same content-free shape:

- one `logger.info` per operator mutation (set mode, clear override, add
  account, remove account) carrying operator id, flag name, action, the target
  account id when the operation names one, and outcome;
- one aggregate record per cohort-resolving read carrying operator id, flag
  count and resolved-account count.

Never an email or display name in either. A successful add produces **two**
records — this feature's own, plus 009's pre-existing "Admin lookup", which
still fires because the add goes through `find_account` for its exact-match
semantics. That is one *new* record per operation, not a claim that 009's
record stops firing.

This narrows ADR-0017's per-account-operation audit clause in one direction
only: rendering a cohort resolves N account records but writes **one** aggregate
count record, never one attributed lookup per member per page load. Attributing
N lookups the operator never performed would dilute the 009 audit signal rather
than sharpen it.

No new audit store, schema, history API or UI. The disposition is the one
already decided for 009: platform log window, excluded from a member's data
export, not reached by account purge (`docs/data-retention.md`).

### 7. Purge obligation: erasure reaches every parseable cohort

`AccountService.purge_account` is documented as erasing every trace of an
account, and `InviteRepository.scrub_user` is the repository's own precedent for
a non-owner-scoped durable file holding a purged user ID. So purge scrubs the
account ID from every `selected_users` array the document can parse — including
one inside an entry this build does not otherwise recognize, which §4 would
otherwise carry through every write untouched. That single field for that single
ID is the one exception to opaque preservation.

When the document is **degraded**, the scrub cannot honor that obligation
against content it never parsed, so it raises rather than silently completing or
silently skipping, and `purge_account` aborts **before** deleting the account
record. Erasure is therefore always complete-or-pending, never silently partial;
the cost, recorded deliberately, is that the account, its email and its password
hash are retained past the documented 14-day promise for as long as the document
stays corrupt, and the maintenance sweep retries every pass until an operator
repairs it. The sweep isolates that failure per account, so one corrupt file
cannot stall every other member's deletion.

### 8. Serialization assumes one process on one machine

Writes are a targeted read-modify-write under an `fcntl.flock` advisory lock,
committed by a temporary file and an atomic replace. That is correct for the
production topology this record assumes: a single backend process on a single
Fly machine with `min_machines_running = 1` and the `brain_buddy_data` volume
mounted at `/app/data`.

Fly volumes are single-attach and per-machine, so scaling out does **not**
produce two writers racing over one file — it produces divergence: each machine
gets its own document, and an operator's change lands only on whichever machine
served the write. Anyone raising `min_machines_running` must revisit this
section first; it is not solved here, because solving it means shared or
replicated storage this feature deliberately excludes.

## Consequences

- ADR-0017's "no admin data store" now reads with one carve-out: a single
  rollout-configuration document holding flag modes and account IDs. Member
  content stays owner-scoped and unreachable, and ADR-0017 §2 is untouched.
- Operator authority grows by one capability — changing who is exposed to two
  already-built features. It does not grow by any capability over member data.
  `docs/auth.md` names the new authority in its operator-authority list.
- `docs/data-retention.md` registers the document, excludes it from a member's
  data export, and names this feature's log records under the disposition
  already decided for 009.
- The in-app privacy policy gains one sentence naming the document: it holds
  only your account id, is scrubbed on account purge, and is excluded from your
  data export.
- Rollback is ordered and has no dead end: an operator clicks the inverse (the
  intended path, effective within about fifteen seconds); an image rollback is a
  no-op for flag resolution; a code revert leaves the document as an unread file.
- Changes to this boundary are ASK class under ADR-0008 and never land
  automatically.
- Anything beyond this record — percentage or scheduled rollouts, segments or
  rule expressions, an audit history platform, runtime management of a flag not
  named in §2, or a second concurrent writer — requires its own ADR. Citing this
  record is not sufficient.
