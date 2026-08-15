# Feature Specification: Live Feature-Flag Management in the Admin Portal

**Feature Branch**: `feat/010-admin-live-feature-flags` · **Created**: 2026-08-14
**Status**: Planning. Not implemented. Revised after campaign 2
(`product-decision-required`, both of its product decisions resolved directly
by the founder rather than through a third campaign) — see
[review-history.md](review-history.md) for the full record, including the
founder-acceptance record that authorizes implementation, and
[analysis.md](analysis.md) for per-requirement traceability.
**Input**: see [intake.md](intake.md) for the founder's ask, verbatim.

A second section on the existing `/admin` screen that lets an already-authorized
operator put each **runtime-manageable** flag into exactly one of three modes
— OFF, ON, SELECTED_USERS — plus a secondary action to clear an override and
restore deploy-default inheritance, and, in SELECTED_USERS mode, add or remove
individual accounts found by the exact-match lookup feature 009 already ships.
The chosen state is written to a single durable document on the existing backend
data volume, overlays the deploy-staged environment baseline per flag, and is
picked up by an already-open browser session within about fifteen seconds
without a sign-out.

Nothing about feature 009's authorization or privacy contract changes: the same
session cookie, the same server-owned operator allow-list, the same
deny-before-touch precedence, and the same `admin_portal` rollout gate. This
feature adds a capability *behind* that boundary; it does not move it. It does
add one narrow, named audit obligation and one narrow, named purge obligation —
see DD-10 and DD-9 — because campaign 1 found the package's claim that neither
was needed was factually wrong, not because the founder's slice grew. Campaign 2
found that a handful of the resulting mechanics still contradicted each other
at their edges (the deploy-default radio state, the clear-override cohort
outcome, audit-record cardinality, the confirmation trigger, and what purge
does to a degraded document); DD-12 and DD-13 below, plus the corrections folded
into DD-1, DD-3, DD-8, DD-9 and DD-10, close those without reopening the frozen
slice. Campaign 2 also found the founder's own "already-open session" requirement
was written web-only when the brief itself is client-generic; the bounded mobile
sublane this adds (FR-009, Lane E) is a correction to match the brief, not new
scope the brief did not ask for.

**Scope is frozen at the founder's slice, as narrowed and corrected by the
campaign-1 and campaign-2 owner decisions below.** The requirements after those
decisions are the whole feature. A reviewer proposal for adjacent hardening — a
reset subsystem, an audit store, a deploy-workflow change, generalized recovery
machinery — is out of scope by construction, not by argument.

## Derived decisions (accepted, do not re-ask)

The founder's brief is the interview and the clarification evidence for this
feature. Campaign 1 found that four points the brief did not spell out had been
guessed inconsistently across spec/design/plan/tasks, and three more points were
asserted as already covered when they were not. Campaign 2 then found several of
campaign 1's own resolutions still contradicted another artifact at their edges,
plus two genuine product decisions campaign 1 had not reached. The owner resolved
all of them directly (not through another review round); every decision below,
including DD-12 and DD-13 added in this revision, is frozen and is not re-opened
by a later campaign.

| # | Question | Decision |
| --- | --- | --- |
| DD-1 | Which flags are runtime-manageable? | **`voice_brain_dump` and `mobile_task_classification` only** — the smallest safe vertical slice: the two member-product flags whose prerequisites (a per-request backend gate this feature can route through the resolver) are already usable. `admin_portal` stays excluded as before (authorization bootstrap for the surface that would be managing it — a self-lockout with no in-app recovery). `delivery_canary` is newly excluded: it is the assertion the authenticated production release smoke uses to prove the deploy-staged internal cohort is wired end-to-end, and campaign 1 found that making it runtime-manageable would let one operator click durably fail and auto-roll-back every subsequent production deploy — a consequence that would require either narrowing this scope (this row) or editing `.github/workflows/`/`scripts/`, which stays frozen. `external_agent_relay` is newly excluded: it already has a per-request backend gate (`external_agent_relay_enabled`/`require_external_agent_relay_enabled` in `backend/app/api/dependencies.py`, wired into eight routes in `backend/app/api/agents.py`) — campaign 2 found campaign 1's rationale wrongly claimed this gate did not exist — but exclusion still holds for a different reason: `container.py`'s `_build_agent_secret_box` makes a **construction-time** decision about whether the relay's secret box exists at all, and no request-time re-evaluation can retroactively satisfy that prerequisite once the process has started. Making the flag runtime-manageable would require rebuilding that startup construction as a live, re-enterable decision, which this feature does not build (FR-008). `delivery_canary` and `external_agent_relay` remain exactly what they are today: environment-only, untouched by this feature, not present in the operator screen, and — for `external_agent_relay` — both of its current call sites (the per-request gate and the construction-time secret-box check) are preserved exactly as they are (FR-002, FR-008). |
| DD-2 | What does an absent vs. a corrupt runtime document mean? | **Split, not conflated.** An **absent** document is healthy: every flag resolves from the environment baseline exactly as today, the operator screen shows no degradation, and the operator's first mutation creates the document rather than being refused (this is what makes User Story 1 and SC-001 possible on a fresh volume). A document that **exists but is unreadable or malformed** is degraded: every flag still falls back to the environment baseline, the operator screen surfaces the degraded state, every mutation is refused rather than overwriting a document the system could not safely read, and the transition from a healthy read to a failed one emits exactly one coarse WARNING log record (correlation id and reason band only, no member data) — not one per subsequent read — so a restrictive override silently ceasing to apply is observable outside the `/admin` screen without any new recovery or reset machinery (FR-004). |
| DD-3 | How is inherited deploy state — especially `internal` — displayed and restored after an override? | **A named inheritance state plus an explicit clear action; the radio group has no selection while inheriting.** The API response for each flag carries three independent fields: `override_mode` (`off` \| `on` \| `selected_users` \| `null`), `source` (`runtime` \| `deploy_default`), and `deploy_default_state` (`off` \| `internal` \| `on`, always present, since the environment baseline always has a value even when a runtime override is active). When `source` is `runtime`, `override_mode` is one of the three non-null values and the operator screen's three-option radio group has exactly that one option checked. When `source` is `deploy_default`, `override_mode` is `null` and **no radio input is checked** — the deploy-default state is shown only in the source note, as its own value, never mapped onto one of the three override radios (a contradiction campaign 2 found: the prior wording required both "always exactly one radio checked" and "never map deploy-default onto a mode," which cannot both hold for an `internal` baseline). A secondary **"Use deploy default"** action clears the flag's runtime entry entirely — deleting it from the document, including any retained SELECTED_USERS cohort (DD-6's retention applies only to a mode change to `off` or `on`, never to this deletion) — and returns the flag to pure environment inheritance, including the `internal`-stage cohort, exactly as if no override, and no retained cohort, had ever existed. This is the one-click reversal the plan always claimed existed; campaign 1 found it had never actually been specified, only implied; campaign 2 found tasks.md had drifted from it by requiring the cohort to survive a clear, which this decision corrects (FR-003, FR-005, FR-010). |
| DD-4 | Does a deploy reset runtime overrides? | **No.** The document lives on the mounted data volume and survives an image swap, exactly like every other stored record. The deploy-staged flag string keeps its role as the **baseline and the rollback floor** for the two flags that are *not* runtime-managed (`delivery_canary`, `external_agent_relay`, and `admin_portal`), and for a managed flag with no runtime entry. No deploy workflow, script or CI file is edited by this feature. |
| DD-5 | What identifies a selected user in the stored document? | **The immutable account ID, and nothing else.** Emails change and are personal data; account IDs are already the key every other stored record uses. The operator-facing list resolves each stored ID to its canonical email for display at read time — a cross-owner account-record read that ADR-0017 §1 already authorizes — so nothing about a member is duplicated into the rollout document (FR-001, FR-007). |
| DD-6 | Does a flag's cohort survive a mode change away from `selected_users`, and can it be edited while inactive? | **Retained, and edit-locked.** A flag's selected-users set is **retained**, not cleared, when its mode changes to OFF or ON, and the operator screen keeps showing its count even while the flag is inactive, so a later switch back to SELECTED_USERS reactivates exactly that cohort rather than an empty one. Add and remove mutations are accepted **only** while the flag's current mode is SELECTED_USERS; the identical request against a flag in OFF or ON mode is refused — a stale tab cannot silently arm a cohort the operator cannot currently see being armed (FR-005, FR-010). |
| DD-7 | Does an unknown account ID refuse every mutation, or only some? | **Split by direction.** Adding requires an exact, currently-resolvable account and is refused otherwise — no partial write, no fuzzy match (unchanged, FR-007). Removing is idempotent by stored account ID: it succeeds and reports success whether or not that ID currently resolves to an account and whether or not it is currently present in the cohort, including removing the same ID twice. Campaign 1 found the prior wording made every unknown-ID mutation refuse, which contradicted the required idempotence of removal (FR-005, FR-007). |
| DD-8 | Does a mutation by this build destroy an entry naming a flag this build does not declare? What about content inside a *known* entry this build does not recognize? | **No — preserved opaquely, and the same tolerance covers every shape of forward-compatible content, not only an unfamiliar flag name.** Anything in the document that is not recognized as this build's known shape for a managed flag — an entry naming a flag the build does not declare, an entry naming a flag this build declares but does not manage (`delivery_canary`, `external_agent_relay`, `admin_portal`), or an unrecognized field inside an otherwise-known managed-flag entry — is ignored for every evaluation and never rendered to the operator, but MUST be carried through every write this build performs value-intact (campaign 2 narrowed "byte-for-byte" to this: preserved under this build's own canonical serialization, not guaranteed identical to a byte sequence a *different* build's serializer produced). Campaign 1 found that "dropped on read" plus a read-modify-write mutation path meant an operator rolled back to this build's image, making one unrelated targeted mutation, would permanently erase a newer build's entry — converting a forward-compatibility tolerance into a version-skew data-loss path no test caught. Campaign 2 found the same tolerance had been specified for undeclared flag *names* only, leaving three sibling cases — an unrecognized field inside a known entry, a declared-but-unmanaged flag's entry, and an actually-invalid mode value in a *recognized* field — undecided; this decision resolves the first two the same way as an undeclared name (preserve, ignore for evaluation) and resolves the third differently: an unrecognized field or entry is forward-compatible content this build merely doesn't understand yet, but a **recognized** field holding a value outside its known vocabulary (a managed flag's `mode` that is not `off`/`on`/`selected_users`) is not forward compatibility — it is the document failing to parse as this build's schema, and is treated as degraded per DD-2, not silently preserved or silently rewritten (FR-001, FR-004, SC-005). One narrow exception to opaque preservation: `AccountService.purge_account`'s cohort scrub (DD-9) MUST remove a purged account's ID from a `selected_users` array even inside an entry this build does not otherwise recognize, because GDPR erasure reaches every parseable copy of the ID, not only the ones this build's schema names — the entry's other content and shape are still preserved unchanged (DD-9, DD-13). |
| DD-9 | Does account purge remove a member's ID from the runtime document? | **Yes, from every parseable cohort, declared or not — see DD-13 for what happens when the document cannot be parsed at all.** `AccountService.purge_account` is documented as erasing every trace of an account, and the repository's own precedent for a non-owner-scoped durable file holding a purged user ID — `InviteRepository.scrub_user`, "GDPR erasure support" — already resolves the equivalent question the same way. Campaign 1 found the ADR-0017 reasoning the prior plan leaned on ("it is a log line, not a stored object") does not transfer to an actual application-side store, so the owner requires the same treatment here: purge scrubs the account ID from every managed flag's cohort, mirroring `scrub_user`'s call from `purge_account`, invoked before any destructive step of that purge (DD-13). Campaign 2 found this scoped to "every **managed** flag's cohort" left a purged ID permanently orphaned inside an *unmanaged or undeclared* flag's entry, since DD-8's opaque preservation carries such an entry through every write untouched and no other sweep is in scope; the scrub now reaches a `selected_users` array inside any parseable entry, not only a managed one, overriding DD-8's byte-preservation for that ID alone (DD-8). This reopens exactly the "account-purge integration" line the founder's slice had excluded, and only that line. The corresponding, narrowly scoped documentation change is now in scope, corrected and widened by a campaign-2 finding: one row in `docs/data-retention.md`'s retention table (mirroring its existing Invites row) and one line in its export-exclusion list, both naming the runtime flag document; the existing **Admin access records** row and section in the same file, amended to also name this feature's flag-mutation and aggregate cohort-resolution records under the identical disposition already decided for 009 (platform log window, excluded from export, not reached by purge); one bullet added to `docs/auth.md`'s three-item operator-authority list naming the new runtime-flag-management authority and pointing at ADR-0018; and — the one item the founder authorizes as a text-only addition mirroring 009's precedent, not the privacy-summary rewrite the founder's slice still excludes — one sentence under `frontend/src/pages/PrivacyPolicyPage.tsx`'s "How long we keep it" section naming the runtime rollout document (it holds only your account id, is scrubbed on account purge, and is excluded from your data export), plus the routine `LAST_UPDATED` bump that edit requires. No other privacy-policy surface changes (FR-007, SC-007). |
| DD-10 | Are operator mutations and the cohort-resolving read actually logged today? | **Not until this feature adds it, and "exactly one" record means exactly one *new* record, not the whole log-line count for an operation.** Campaign 1 found the spec's own Assumption — that existing feature-009 logging already covers this feature's mutations — was factually wrong: 009's `find_account` "Admin lookup" record and its `revoke_sessions` record do not fire for a flag-mode change, a cohort add/remove, or the `GET`'s bulk account-to-email resolution. The owner requires the same content-free shape 009 already uses: one `logger.info` record per operator mutation (set mode, clear override, add account, remove account) carrying operator id, flag name, action, **the target account id when the operation names one** (add: the resolved id; remove: the path-supplied id, logged only when it matches the account-ID pattern, never an email), **and** outcome, plus one aggregate record per cohort-resolving `GET` carrying operator id, flag count and resolved-account count — never an email or display name in either. Campaign 2 found two gaps: first, a successful `add_selected_user` MUST go through 009's `AdminService.find_account` (FR-007), which unconditionally emits its own "Admin lookup" record, so a successful add produces **two** records — this feature's own dedicated mutation record plus 009's pre-existing lookup record — and "exactly one" in FR-006/SC-006 means exactly one of *this feature's own* records, not a claim that `find_account`'s record stops firing; second, the original wording omitted the target account id from add/remove records entirely, which — for `remove_selected_user`, which deliberately performs no lookup (DD-7) — left an add-then-remove sequence unreconstructable from logs, exactly the attributability DD-10 exists to provide. This is still one *new* content-free log line per operation, not the audit store, history API, UI or schema the founder's slice excludes (FR-006, SC-006). |
| DD-11 | Can the 15-second background poll reuse `useAuthStore.hydrate()` unchanged? | **No.** Campaign 1 found that today's `hydrate()` clears the session to anonymous on *any* thrown failure, including a transient network error, which would turn ordinary poll noise into an unwanted sign-out — the opposite of FR-009. The owner requires a distinct session-refresh path for the background poll: a transient (non-401) failure leaves the authenticated session, its user record and its flags untouched and surfaces nothing; a 401 clears the session and stops polling exactly as today. The existing `hydrate()` behavior for **initial/startup** load — any failure, transient or not, resolves to anonymous — is unchanged, because a cold load against an unreachable backend must not hang on "loading" forever (FR-009, SC-004). |
| DD-12 | Which mutations require the lightweight confirmation step, and by what rule? | **An exact operation allowlist, not a computed population-effect rule.** Campaign 1's owner decision 12 (never promoted into this table — a campaign-2 traceability finding this row corrects) required confirmation for setting a flag OFF and for removing the last remaining SELECTED_USERS member. Campaign 2 found the design's own stated *rationale* for that pair — "reduces a currently nonzero effective population to zero" — was falsified by a third action the allowlist omitted: "Use deploy default" can zero a flag's effective population exactly as OFF can (a flag staged ON at runtime, cleared back to a deploy-default baseline that ships OFF, is the feature's own central use case), yet the design showed no confirmation and no deploy-default-state preview for it. Rather than generalize to a computed "does this transition zero the population" rule — which campaign 2 separately found is unenforceable server-side against concurrent edits from two tabs and would need revision tokens this feature excludes — the owner extends the fixed allowlist to exactly three named operations: **setting a flag OFF, removing the last remaining SELECTED_USERS member, and clearing a runtime override ("Use deploy default")**. Every other mutation (ON, SELECTED_USERS, adding a user, removing a non-last member) applies immediately. This is deliberately narrower than "every mutation that could reduce exposure" — a stale-tab race between two operators can still zero a population without either tab's confirm firing, an accepted residual because every mode change is reversible by its own inverse — and the spec and design MUST state the rule as this exact allowlist, not as a population-effect invariant the allowlist does not actually implement (FR-010). |
| DD-13 | What does account purge do when the runtime document is degraded (exists but unreadable or malformed)? | **Halt and retry — GDPR erasure never completes with a purged ID still readable in the store, and the account record is retained, not deleted, until the document is repaired.** FR-004's "every mutation MUST be refused while degraded" and DD-9's "purge scrubs every parseable cohort" collide exactly here: `scrub_user` cannot re-serialize content it could not parse, so it can neither honor DD-8's carve-out (DD-9) nor pretend to have removed an ID from a document it never actually rewrote. The owner requires `scrub_user` to raise rather than silently skip when the document is degraded, so `AccountService.purge_account` aborts **before** `user_repo.delete` — the account, its email and its password hash are retained past the documented 14-day promise for as long as the document stays corrupt, and the 60-second maintenance sweep retries the purge on every pass until an operator repairs the document (deleting or replacing it) and a subsequent purge attempt succeeds. `AccountService.purge_due_accounts` MUST isolate this failure per account (a single corrupt runtime document must not also block every other unrelated account's due purge in the same sweep pass) rather than letting one raised exception abort the whole pass; this is a required correction to the sweep, not an accepted residual, because the alternative — one corrupt file silently stalling every other member's GDPR deletion — is a worse regression than the one this decision closes. The degraded-state WARNING (DD-2) already names that an override has silently stopped applying; it is not extended to separately announce an outstanding erasure obligation, since the retry itself is the recovery signal and no new alerting surface is in scope (FR-004, FR-007, DD-2, DD-8, DD-9). |

## User Scenarios & Testing

The "user" for stories 1–3 is an authorized operator, authenticated exactly as
feature 009 requires. Story 4's user is an ordinary member with a browser tab
already open. See [design.md](design.md) for the screen and its states.

### User Story 1 - Operator sets a flag's mode (Priority: P1)

An operator opens `/admin`, sees each runtime-manageable flag with its current
mode and where that mode came from, and switches one flag between OFF, ON and
SELECTED_USERS, or clears an override to restore the deploy default. The change
is saved server-side and the operator's view is refreshed from the server's own
answer, not from optimistic local state.

**Why this priority**: without it there is no live rollout control at all; every
other story builds on the stored mode.

**Independent Test**: on a data volume with no runtime document yet, set a flag
to ON, read the flag list back, restart the backend process, read it back again
— the document now exists, the mode is still ON, and no other flag moved.

**Acceptance Scenarios**:

1. **Given** a flag with no runtime entry on a data volume that has never held a
   runtime document, **When** the operator sets it to ON, **Then** the document
   is created, the response reports mode ON for that flag, every other flag is
   unchanged, and a later read returns the same state (DD-2).
2. **Given** a flag set to ON at runtime, **When** the backend process is
   restarted, **Then** the flag is still ON.
3. **Given** a flag set to OFF at runtime while the environment baseline says
   `on`, **When** any member's effective flags are computed, **Then** the flag is
   not effective for anyone — the baseline does not leak through.
4. **Given** a flag with a runtime override, **When** the operator uses "Use
   deploy default", **Then** the runtime entry is removed and the flag evaluates
   from the environment baseline, including the `internal`-stage cohort where
   applicable (DD-3).
5. **Given** a save that fails server-side, **When** the operator retries,
   **Then** the operator sees an error state carrying the correlation ID and the
   stored state is unchanged.

---

### User Story 2 - Operator manages a SELECTED_USERS cohort (Priority: P1)

With a flag in SELECTED_USERS mode, the operator adds an account by typing its
exact account ID or canonical email, and removes an account from the list shown
on screen. The list shows how many accounts are selected and enough identity per
row to remove the right one. The cohort is retained if the operator later moves
the flag to OFF or ON, and reappears exactly as it was if the flag returns to
SELECTED_USERS.

**Why this priority**: per-flag cohorts are the capability the shared global
`BRAIN_BUDDY_FEATURE_FLAG_INTERNAL_USERS` list cannot express, and they are what
makes SELECTED_USERS different from ON.

**Independent Test**: add one account to one flag, confirm the count and row
appear, confirm a second flag's cohort is unchanged, remove the account, confirm
the count returns to zero. Then switch the flag to ON and back to
SELECTED_USERS and confirm the (now empty) cohort state is unchanged by the
round trip.

**Acceptance Scenarios**:

1. **Given** a flag in SELECTED_USERS mode, **When** the operator adds an
   existing account by its exact canonical email, **Then** that account appears
   in the flag's list, the count increments, and adding it a second time changes
   nothing and still reports success.
2. **Given** the same flag, **When** the operator submits a prefix, suffix, case
   variant or whitespace variant of a real account ID or email, **Then** nothing
   is added and the operator is told no account was found.
3. **Given** an account in a flag's list, **When** the operator removes it,
   **Then** it disappears from that flag only, and removing it again — or
   removing an account ID that was never in the cohort, or that no longer
   resolves to any account — still reports success (DD-7).
4. **Given** a selected account that has since been deleted, **When** the
   operator opens the list, **Then** the row still renders with its stored ID
   and is still removable, until `AccountService.purge_account` runs and removes
   the ID from the cohort entirely (DD-9).
5. **Given** a flag in SELECTED_USERS mode with a non-empty cohort, **When** the
   operator switches the flag to OFF or ON, **Then** the cohort and its count are
   retained (visible on the row, inert to evaluation) and reappear unchanged if
   the operator switches the flag back to SELECTED_USERS (DD-6).
6. **Given** a flag currently in OFF or ON mode, **When** an add or remove
   request is made against it, **Then** it is refused — cohort mutations require
   the flag to be in SELECTED_USERS mode (DD-6).

---

### User Story 3 - The rollout survives restart and redeploy (Priority: P1)

The operator's changes persist across a process restart and an image swap, and a
rollback to an image built before this feature lands back on exactly the
environment-staged rollout without a crash and without a manual step.

**Why this priority**: a rollout control whose state a redeploy silently
discards is worse than no control.

**Independent Test**: write a runtime document, then evaluate flags with the
runtime store unavailable (the pre-010 code path) and confirm the answer equals
the environment-only answer. Separately, reopen the same data directory through
a fresh application/container instance — not just a fresh repository object —
and confirm the stored state is still in force (DD-2, campaign-1 testability
finding).

**Acceptance Scenarios**:

1. **Given** a runtime document on the data volume, **When** the backend
   restarts as a fresh process/application instance over the same data
   directory, **Then** the stored modes and cohorts are still in force.
2. **Given** a runtime document that names a flag the running build does not
   know, **When** flags are evaluated, **Then** the unknown entry is ignored and
   every known flag still resolves; **When** a targeted mutation is later made to
   a known flag, **Then** the unknown entry is still present in the document,
   byte-for-byte (DD-8).
3. **Given** an absent runtime document, **When** flags are evaluated, **Then**
   every flag resolves from the environment baseline and the state is healthy,
   not degraded (DD-2).
4. **Given** a runtime document that exists but is unreadable or malformed,
   **When** flags are evaluated, **Then** every flag resolves from the
   environment baseline, the degradation is visible to the operator, every
   mutation is refused rather than overwriting the document, and exactly one
   coarse WARNING log record marks the transition into degraded (DD-2).

---

### User Story 4 - A signed-in member picks the change up without signing out (Priority: P2)

A member has a session already open — a browser tab, or the mobile app in the
foreground or backgrounded. An operator changes a flag that affects them. Within
about fifteen seconds — or immediately if the member returns to the tab or
foregrounds the app — the gated capability appears or disappears. The member
never signs out and never reloads or force-quits, and an ordinary network blip
during the background refresh never signs them out either. The requirement is
client-generic — "an already-open session picks up the change" is what the
founder's brief asks for, not "the web tab does" — so it applies to both clients
this feature's flags reach; campaign 2 found the prior revision had specified
only the web half and corrected it here (**Mobile E**, tasks.md).

**Why this priority**: it is the point of "live", but it is strictly downstream
of stories 1–3: without stored state there is nothing to propagate.

**Independent Test**: with fake timers, assert the web client issues a
`/api/auth/me` refetch on the 15-second interval while authenticated, on window
focus and on visibility change, and that the auth store's flags update from the
response. Separately, with fake timers and a faked `AppState`, assert the mobile
client's `SessionProvider` issues the equivalent refetch on the same cadence
while signed in and the app is active, and immediately on foreground.

**Acceptance Scenarios**:

1. **Given** an authenticated web session, **When** fifteen seconds elapse,
   **Then** the client refetches `/api/auth/me` and applies the returned flags.
2. **Given** an authenticated web session in a background tab, **When** the tab
   becomes visible or the window regains focus, **Then** the client refetches
   immediately.
3. **Given** an unauthenticated visitor, **When** any amount of time elapses,
   **Then** no polling request is issued at all.
4. **Given** an authenticated session whose background refetch fails
   transiently, **When** the failure arrives, **Then** the session, its user
   record and its flags are untouched and no error is surfaced; a 401 on that
   same refetch clears the session exactly as today's initial hydration already
   does on any failure, and polling stops (DD-11).
5. **Given** a signed-in mobile session with the app in the foreground, **When**
   fifteen seconds elapse, **Then** `SessionProvider` refetches `/api/auth/me`
   and the resolved `taskClassificationEnabled`/`voiceEnabled` values update; a
   transient refetch failure leaves the session and its flags untouched and
   polling continues; a 401 signs the session out exactly as an in-app 401 does
   today; backgrounding the app (an inactive `AppState`) suspends the poll, and
   returning to the foreground triggers an immediate refetch rather than waiting
   out the remainder of the interval.

### Edge Cases

- The document is absent and the operator performs the very first mutation: the
  document is created holding just that mutation's effect; every other managed
  flag still resolves from the environment baseline (DD-2).
- An existing, previously healthy document becomes unreadable or malformed:
  every flag falls back to the environment baseline, every mutation is refused,
  and exactly one coarse WARNING log record marks the transition (DD-2).
- Two operators (or one operator in two tabs) mutate different flags at the same
  moment: both changes survive; neither document write is partial.
- The backend is killed between the temporary write and the rename: the previous
  document is intact and readable.
- An account in a SELECTED_USERS list is deleted: until `AccountService` purges
  it (end of the 14-day deletion grace), its ID stays in the document, the row
  renders as unresolved, and it remains removable — a stale ID grants nothing,
  because resolution matches the *authenticated* user's ID. Purge itself removes
  the ID from every cohort (DD-9).
- The operator sets a flag to SELECTED_USERS while its cohort is empty: the flag
  is off for everyone, and the screen says so rather than showing an ambiguous
  blank.
- A flag leaves SELECTED_USERS mode with a non-empty cohort: the cohort is
  retained and its count stays visible; it reappears unchanged if the flag
  returns to SELECTED_USERS (DD-6).
- A flag's override is **cleared** ("Use deploy default") with a non-empty
  retained cohort: unlike a mode change to OFF or ON, clearing deletes the
  flag's entire runtime entry, cohort included; the operator screen shows an
  empty, inactive cohort if the flag is later put back into SELECTED_USERS
  (DD-3, DD-6).
- An add or remove request targets a flag that is currently OFF or ON: refused
  — cohort mutations require SELECTED_USERS mode (DD-6).
- A document holds an entry naming a flag this running build does not declare,
  a flag it declares but does not manage, or a managed flag's entry with an
  unrecognized field (for example, a newer build's flag or field, met after a
  rollback to this build's image): ignored for evaluation and never shown to
  the operator, but preserved value-intact through every mutation this build
  performs. A managed flag's entry whose `mode` value is outside `off`/`on`/
  `selected_users` is different — that is malformed content in a field this
  build claims to understand, not forward compatibility, so it is treated as a
  degraded document (DD-2), not silently preserved or silently rewritten (DD-8).
- An account selected on a flag is purged while the runtime document is
  healthy: `scrub_user` removes the ID from every parseable cohort, including
  one inside an unmanaged or undeclared flag's entry, before the purge deletes
  the account record. If the document is instead degraded when the purge runs,
  the purge halts before deleting the account record and retries on the next
  60-second sweep pass until an operator repairs the document; other accounts'
  due purges in the same sweep are not blocked by this one (DD-13).
- An operator turns off the flag gating a capability a member is mid-way
  through: nothing already dispatched is cancelled; the existing per-feature
  rules stand unchanged.
- A malformed mode or an unknown flag name in any mutation: refused with an
  actionable error, no partial write. An unknown account ID: refused when
  adding (no exact match found); idempotently succeeds when removing (DD-7).
- A signed-in mobile session is backgrounded when an operator changes a flag
  that affects it: the poll is suspended while the app is inactive, and
  foregrounding the app triggers an immediate refetch rather than waiting out
  the remainder of the 15-second interval (User Story 4, Mobile E).

## Requirements

### Functional Requirements

- **FR-001**: The system MUST hold runtime rollout state in exactly one
  server-owned JSON document on the existing backend data volume, recording for
  each **runtime-manageable flag** (`voice_brain_dump`, `mobile_task_classification`
  — DD-1) a mode of `off`, `on`, or `selected_users`, and — for `selected_users`
  — a set of immutable account IDs. The document MUST NOT contain email
  addresses, display names, credentials, tokens, session hashes, or any member
  content (DD-5). Content this build does not recognize as its own known
  shape for a managed flag — an entry naming an undeclared flag, an entry
  naming a flag this build declares but does not manage, or an unrecognized
  field inside an otherwise-known managed-flag entry — MUST be preserved
  value-intact under this build's own canonical serialization across every
  write, even though it is ignored for evaluation and never rendered to the
  operator; a managed flag's entry with a `mode` value outside its known
  vocabulary is malformed, not forward-compatible, and is handled as a
  degraded document instead (DD-8). The one exception to this preservation is
  `AccountService.purge_account`'s cohort scrub, which MUST remove a purged
  account's ID from a `selected_users` array even inside such an entry (DD-8,
  DD-9, DD-13).
- **FR-002**: Runtime management MUST be scoped to exactly `voice_brain_dump` and
  `mobile_task_classification`. A mutation naming any other flag — including
  `admin_portal`, `delivery_canary`, `external_agent_relay`, any other
  `PRIVATE_FEATURE_FLAGS` entry, and a name that is not a declared flag at all —
  MUST be refused without writing anything, and the refused flag's effective
  value MUST remain exactly what the environment configuration produces (DD-1).
- **FR-003**: Effective-flag evaluation MUST be per flag and MUST NOT blend the
  two sources. A managed flag with no runtime entry MUST resolve exactly as the
  current environment-only implementation resolves it, including the
  `internal`-stage cohort. A managed flag with a runtime entry MUST resolve from
  that entry alone: `on` is effective for every authenticated user, `off` for
  none, and `selected_users` exactly for the users whose account ID is in that
  flag's set. An operator MAY clear a managed flag's runtime entry entirely
  ("Use deploy default"), which deletes the entry and returns the flag to pure
  environment inheritance, including the `internal`-stage cohort where
  applicable (DD-3).
- **FR-004**: The system MUST treat an **absent** runtime document as healthy:
  every flag resolves from the environment baseline exactly as today, the
  operator screen shows no degradation, and the operator's first mutation MUST
  create the document rather than being refused. The system MUST treat a
  document that **exists but is unreadable or malformed** as degraded: every
  flag still resolves from the environment baseline, the operator screen MUST
  surface the degraded state, every mutation MUST be refused rather than
  overwriting a document the system could not safely read, and the transition
  from a healthy read to a failed one MUST emit exactly one coarse WARNING log
  record (correlation id and reason band only, no member data) rather than one
  per subsequent read. This applies identically to a process whose very first
  read after startup is already degraded: the in-process "was the last read
  healthy" state starts unset, not healthy, so that first degraded read also
  emits the WARNING exactly once, and the WARNING does not repeat again until
  one healthy read resets the transition state (DD-2). Content this build does
  not recognize as its own known shape for a managed flag MUST be ignored
  rather than rejected for evaluation, and MUST be preserved value-intact in the
  document across every mutation this build performs, so an older build cannot
  be broken by a newer name or field and cannot destroy that content either; a
  managed flag's entry whose `mode` value is outside its known vocabulary is
  malformed content in a recognized field, not forward compatibility, and MUST
  make the document degraded rather than being silently preserved or silently
  rewritten (DD-8). `AccountService.purge_account`'s mutation MUST be refused
  by this rule exactly like every other mutation while the document is degraded
  — see DD-13 for the resulting purge disposition, which is a narrow, named
  exception to "every mutation is refused," not a contradiction of it. No
  further recovery, repair or reset machinery is part of this feature.
- **FR-005**: Every mutation MUST be a targeted, idempotent operation: set one
  flag's mode, clear one flag's runtime entry ("Use deploy default"), add one
  account to one flag's `selected_users` cohort, or remove one account from one
  flag's `selected_users` cohort — applied as a read-modify-write serialized
  against concurrent writers and committed by a single atomic replace. Add and
  remove MUST be accepted only while the named flag's current mode is
  `selected_users`; the identical request against a flag in `off` or `on` mode
  MUST be refused (DD-6). A flag's `selected_users` set MUST be retained, not
  cleared, when its mode changes to `off` or `on`, and MUST still be counted and
  shown to the operator while inactive, so a later switch back to
  `selected_users` reactivates exactly the retained cohort (DD-6). Concurrent
  mutations to different flags MUST all survive; a crash at any point MUST leave
  either the prior document or the new one, never a partial one; repeating any
  mutation MUST be a no-op that still reports success. Runtime state MUST
  survive a backend process restart, a machine restart, and a deploy that swaps
  the image, and any in-process cache MUST be invalidated when the document
  changes so a mutation is visible to the very next effective-flag evaluation.
- **FR-006**: All **five** runtime flag routes — the one `GET` read and the four
  mutations (set mode, clear override, add account, remove account) — MUST sit
  behind the existing feature 009 gate — a valid session AND operator allow-list
  membership AND an effective `admin_portal` flag, in that precedence — with an
  unauthenticated caller getting 401, an authenticated non-operator 403, and
  only an authorized operator the feature-absent 404, and with no repository
  read and no write as a side effect of any denial **on any of the five,
  including `GET`, not only the four mutations**. Flags MUST remain exposure
  control and MUST NOT become authorization: no authorization decision may read
  a runtime-managed flag, and the operator allow-list and the `admin_portal`
  gate stay environment-owned, preserving 009-FR-001, 009-FR-002, 009-FR-008 and
  009-FR-013 exactly. Every operator mutation (set mode, clear override, add
  account, remove account) MUST emit exactly one new, dedicated, content-free
  log record — operator id, flag name, action, the target account id when the
  operation names one (add: the resolved id; remove: the path-supplied id,
  logged only when it matches the account-ID pattern, never an email), and
  outcome — **in addition to**, not instead of, feature 009's existing
  `find_account` "Admin lookup" record, which still fires unconditionally for a
  successful add because FR-007 requires add to go through it (DD-10); every
  `GET` read that resolves cohort account IDs to canonical emails MUST emit
  exactly one aggregate record — operator id, flag count and resolved-account
  count — with no email or display name in any of these records, and with no
  new audit store, history API, UI or schema (DD-10).
- **FR-007**: Adding a selected user MUST use the exact-match account lookup
  feature 009 already enforces: exactly one of an immutable account ID or a
  canonical email per request, matched byte-for-byte, with no partial, prefix,
  suffix, case-variant, whitespace-variant or fuzzy match, and no listing,
  enumeration or search endpoint of any kind. An add that does not resolve to
  exactly one existing account MUST be refused and MUST add nobody. Removing a
  selected user MUST be idempotent by stored account ID: it MUST succeed and
  report success whether or not that ID currently resolves to an account and
  whether or not it is currently present in the flag's cohort, including a
  second removal of the same ID (DD-7). Only the resolved account ID is stored.
  A stored ID that no longer resolves to an account MUST still be rendered and
  MUST still be removable, until `AccountService.purge_account` removes it from
  every managed flag's cohort — and from a `selected_users` array inside any
  other parseable entry, declared or not — as part of that purge, mirroring
  `InviteRepository.scrub_user`, invoked before any destructive step of the
  purge, and failing the whole purge closed (before the account record is
  deleted) rather than skipping the scrub when the document is degraded (DD-9,
  DD-13). The documentation this feature edits is exactly what DD-9 names: a
  retention-register row and an export-exclusion entry for the runtime document,
  an amendment to the existing Admin access records row/section for this
  feature's own log records, one bullet in `docs/auth.md`'s operator-authority
  list, and one authorized text-only sentence in the in-app privacy policy's
  "How long we keep it" section naming the runtime document — no broader
  privacy-policy rewrite or user-facing-summary redesign is part of this
  feature.
- **FR-008**: Every existing backend feature-flag check for `voice_brain_dump`
  and `mobile_task_classification` MUST resolve through the runtime resolver —
  named exhaustively so a later reader does not have to re-derive the set:
  `_me_response` (`auth.py`), `voice_brain_dump_enabled` and
  `require_voice_brain_dump_enabled` (`dependencies.py`), `_voice_enabled_for_owner`
  (`container.py`), and the direct `voice_brain_dump_enabled(current_user,
  config)` call inside `command_brain_dump_operation`
  (`backend/app/api/tasks.py`) that gates the brain-dump command route's
  forward actions (`commit`, `retry`, `review_provisional`) — a call site
  campaign 2 found the prior revision had missed entirely, undercounting the
  resolver's reach and its own changed-surface table — plus the member-facing
  effective booleans for those two flags in the `/api/auth/me`,
  `/api/auth/login` and `/api/auth/signup` payloads, so the server stays the
  sole authority for whether either flag is effective. `delivery_canary` and
  `external_agent_relay` MUST remain purely environment-derived and untouched by
  this feature, including the request-time `external_agent_relay` gate and the
  startup-time, construction-only relay secret-box check, which is deliberately
  outside the runtime resolver's scope because it runs once at container
  construction rather than per request and evaluates a flag this feature does
  not manage (DD-1). The `feature_flags` key set MUST remain exactly
  `KNOWN_FEATURE_FLAGS` with `admin_portal` absent, and no other member-facing
  route, response shape, status code, cookie or screen may change — the mobile
  client MUST require no change to keep working against the same payload. A
  runtime override on `voice_brain_dump` MUST NOT move the consent boundary
  ADR-0002/constitution Principle I already draws: a caller newly admitted by a
  `selected_users` cohort still MUST fail visibly when capturing without
  explicit per-recording consent, and a caller under a runtime OFF override MUST
  still reach the owner-authority voice routes (withdraw consent, cancel, delete
  raw audio) that stay reachable regardless of the flag, exactly as they do
  today (campaign-2 regression coverage; no consent-surface behavior changes).
- **FR-009**: While a session is authenticated, the client MUST refetch its
  identity-and-flags endpoint every 15 seconds and immediately on returning to
  the foreground, and MUST apply the returned flags to its local state so a
  gated capability appears or disappears without a logout, login, page reload or
  app restart. This requirement is client-generic — it applies to the web
  frontend and to the mobile app alike, not only to the web tab (a scope gap
  campaign 2 found and corrected here) — and each client realizes it through its
  own idiom: the **web** frontend MUST refetch `GET /api/auth/me` every 15
  seconds and immediately when the window regains focus or the document becomes
  visible, through a session-refresh path distinct from the app's
  initial/startup hydration (a transient, non-401 refresh failure MUST leave the
  authenticated session, its user record and its flags untouched and MUST
  surface no error; a 401 response MUST clear the session exactly as today and
  stop polling; initial/startup hydration behavior — any failure, transient or
  not, resolves to the anonymous state — is unchanged, DD-11); the **mobile**
  app's `SessionProvider` MUST refetch `/auth/me` every 15 seconds while signed
  in and the app's `AppState` is active, and immediately on the app returning to
  the foreground, with the identical transient-tolerant/401-clearing split: a
  transient refresh failure MUST leave the session and its flags untouched and
  the poll MUST continue, while a 401 MUST clear the session and stop the poll
  exactly as an in-app 401 does today. Polling MUST NOT run while unauthenticated
  or, on web, while the document is hidden, or, on mobile, while the app is
  backgrounded, and MUST NOT introduce a WebSocket, an SSE stream, or any other
  new transport on either client.
- **FR-010**: The operator screen MUST display, for each managed flag: its
  current mode among OFF, ON and SELECTED_USERS as a native `fieldset`/`legend`
  grouped radio control **when the flag is under a runtime override** — exactly
  one of the three radio inputs checked, matching the response's non-null
  `override_mode` — and **no radio input checked when the flag is inheriting the
  deploy default** (`override_mode: null`, `source: "deploy_default"`); whether
  that mode is a runtime override or deploy-default inheritance, and in either
  case the deploy-default state (off, internal, or on) shown as its own value —
  never mapped onto one of the three override modes, and never hidden merely
  because a runtime override is currently active, so the operator can always see
  what "Use deploy default" would fall back to before clicking it (DD-3); a
  secondary "Use deploy default" action available whenever a runtime entry
  exists; the selected-user count, shown and retained even while the flag's mode
  is OFF or ON (DD-6); and a list with enough identity per row — including a
  "Remove" action whose accessible name includes the row's account identity — to
  remove the intended account, with focus moved to a defined target after **any**
  mutation succeeds, not only a cohort-row removal: the triggering control (the
  mode radio, the "Use deploy default" action, or the add-user input) for a mode
  change, a clear-override or an add, and the next remaining row's Remove
  action — or, if none remain, the add-user input, or, if the row removed was
  the only visible cohort element, the cohort-count region — for a row removal.
  It MUST express distinct loading, saving, empty-cohort, not-found/unresolvable,
  degraded-store, list-fetch-failure (a transport or server error on the initial
  read, distinct from a successful `degraded: true` response) and
  mutation-error states, each error state carrying the correlation ID when the
  server supplied one and stating named fallback copy when it did not (no
  response was received). It MUST require one lightweight confirmation step
  before applying exactly three mutations — setting a flag to OFF, removing the
  last remaining member of a SELECTED_USERS cohort, and clearing a runtime
  override ("Use deploy default") — stated as this exact operation allowlist,
  not as a claim that it covers every mutation that could reduce a flag's
  effective population to zero (DD-12); every other mutation (ON,
  SELECTED_USERS, adding a user, removing a non-last member) applies immediately
  without confirmation. The confirmation step MUST be dismissible by Escape,
  matching this screen's existing `RevokeConfirmDialog`/`Overlay` convention,
  and MUST receive focus on appearance and return focus to the control that
  opened it on Cancel or Escape. It MUST remain usable at a 390×851 viewport,
  with a stated reflow for the mode control, source note, cohort rows and the
  confirmation step's Confirm/Cancel controls — which MUST stack with a minimum
  44px tappable height at that width, the same treatment given the other new
  controls in this section. After any mutation it MUST re-render from the
  server's authoritative response rather than from optimistic local state.

### Key Entities

- **Runtime flag document**: one server-owned JSON record on the data volume.
  For each runtime-manageable flag name: a mode (`off` | `on` | `selected_users`)
  and, for `selected_users`, a set of account IDs. Holds no member content. May
  also hold, opaquely and unevaluated, content this build does not recognize as
  its own known shape — an entry naming an undeclared flag, an entry naming a
  declared-but-unmanaged flag, or an unrecognized field inside a managed entry
  (DD-8) — except that a purged account's ID is still removed from any
  `selected_users` array reachable inside such an entry (DD-9, DD-13).
- **Managed flag**: one of the two runtime-manageable flags, `voice_brain_dump`
  and `mobile_task_classification` (DD-1) — a subset of `KNOWN_FEATURE_FLAGS`.
  Its effective value for one user comes from the runtime document when an entry
  exists, and from the environment configuration otherwise. `delivery_canary`
  and `external_agent_relay` are `KNOWN_FEATURE_FLAGS` entries that are **not**
  managed flags: their effective value always comes from the environment
  configuration.
- **Selected user**: an account ID present in one managed flag's set, retained
  across mode changes away from `selected_users` (DD-6). Rendered to the
  operator with the canonical email resolved live from the account record; never
  stored alongside the ID. Removed from every managed flag's set when the
  account is purged (DD-9).

## Success Criteria

### Measurable Outcomes

- **SC-001**: An operator can set each of the two managed flags
  (`voice_brain_dump`, `mobile_task_classification`) to OFF, ON and
  SELECTED_USERS, and can clear either flag's override to restore the deploy
  default; every state — including the document created by a first mutation on
  a previously absent store — reads back identically through the API and
  survives a backend process restart; no unmanaged flag (`admin_portal`,
  `delivery_canary`, `external_agent_relay`) and no other managed flag changes
  as a side effect of any mutation.
- **SC-002**: With `voice_brain_dump` in SELECTED_USERS mode and account A
  selected, `GET /api/auth/me` reports that flag `true` for A and `false` for B;
  after A is removed it reports `false` for A on the next response, with no
  session invalidated and no sign-out required; after account A is purged while
  the runtime document is healthy, its ID is absent from the flag's stored
  cohort; and a purge attempted while the document is degraded halts before the
  account record is deleted and succeeds, scrubbing the cohort, on a retried
  purge once the document is repaired (DD-9, DD-13).
- **SC-003**: With no runtime document present, the `feature_flags` payload is
  identical to the payload the current environment-only implementation produces
  for every `BRAIN_BUDDY_FEATURE_FLAGS` state, for an internal-cohort user and a
  non-cohort user alike, for both managed flags and for `delivery_canary`/
  `external_agent_relay` unconditionally; the first mutation performed against
  that absent document creates it, and every other managed flag continues to
  resolve from the environment baseline immediately afterward (DD-2); and
  evaluating with the runtime store unavailable — the code path a pre-010 image
  takes — against a data volume that *does* hold a runtime document yields
  exactly that same environment-only result and raises nothing.
- **SC-004**: An authenticated web session issues a `/api/auth/me` refetch once
  per 15-second interval, once on window focus and once on the document becoming
  visible, issues none while unauthenticated or hidden, opens no WebSocket or SSE
  connection, updates the rendered gated capability from the refetched payload
  without a logout, login or reload, survives a transient background-refresh
  failure without signing the member out or altering the stored user or flags,
  and a 401 on that same background-refresh path clears the session and stops
  polling exactly as today's initial hydration already does on any failure
  (DD-11).
- **SC-005**: Concurrent targeted mutations against different flags all apply;
  the document is never observed partially written; a write interrupted before
  its rename leaves the previous document valid and readable; repeating any
  mutation leaves the document byte-identical while still reporting success; and
  a targeted mutation to a known flag leaves an unrelated entry naming a flag
  this build does not declare present and byte-identical in the document
  afterward (DD-8).
- **SC-006**: Every mutation naming `admin_portal`, `delivery_canary`,
  `external_agent_relay`, any other `PRIVATE_FEATURE_FLAGS` entry, or an
  undeclared flag name is refused and writes nothing; every runtime flag route
  returns 401 for an unauthenticated caller and 403 for an authenticated
  non-operator in **both** `admin_portal` states and 404 to an authorized
  operator when `admin_portal` is not effective, performing no repository read
  on a denial (proved by poisoning the target-facing methods, not only by
  comparing bodies) and leaving the stored document unchanged; and every
  successful operator mutation and every `GET` cohort-resolution read produces
  exactly one content-free log record (DD-10).
- **SC-007**: Adding a selected user by a prefix, suffix, case variant or
  whitespace variant of a real account ID or canonical email adds nobody,
  reports "no account found", and leaves the document unchanged; no endpoint
  added by this feature can enumerate or list accounts; the stored document
  contains no email address, display name, credential, token or session hash
  (proved with distinctive sentinels planted in the display name and the
  request body); a stored ID that resolves to no account still renders and is
  still removable, and removing any account ID — present, absent, or never
  resolvable — always reports success (DD-7); and purging an account removes
  its ID from every managed flag's cohort (DD-9).
- **SC-008**: The operator section renders its loading, saving, empty-cohort,
  not-found/unresolvable, degraded, list-fetch-failure and mutation-error
  states, each error state carrying the correlation ID when available; a
  lightweight confirmation is required before setting a flag OFF or removing the
  last selected member and not before any other mutation; the retained
  selected-user count is visible while a flag's mode is OFF or ON (DD-6); the
  mode control is a native `fieldset`/`legend` radio group and each Remove
  action's accessible name includes the row's identity with focus restored to a
  defined target after removal; the section reflows usably at 390×851; every
  mutation result is rendered from the server's returned state rather than from
  optimistic local state; and with an unreadable document every flag resolves
  from the environment baseline, the section's controls are disabled, every
  mutation is refused, and the document's bytes are unchanged afterward.

## Manual Acceptance Checks

Use **purpose-seeded, non-real accounts** (`@example.com` addresses created for
the check). Any pasted output or screenshot must have account IDs and email
addresses redacted before it enters PR or acceptance evidence — constitution
Principle I forbids real user data there, and both the cohort list and the add
form render an email on screen.

- Sign in as the seeded operator, set `voice_brain_dump` to SELECTED_USERS, add
  the seeded check account, and confirm in a second browser signed in as that
  account that the capability appears without signing out.
- Remove the account again and confirm the capability disappears from the
  already-open second browser within about fifteen seconds.
- Set `voice_brain_dump` back to OFF, confirm the confirmation step appears and
  is required, and confirm the (now empty) cohort count is still visible on the
  row.
- Confirm no admin entry appears anywhere in navigation or the account menu (009
  PD-1 still holds), and that a non-operator member navigating directly to
  `/admin` sees only the generic denied state.

## Out of Scope

A separate feature-flag service or third-party vendor; percentage, gradual or
staged-by-count rollouts; segments, groups, attributes or rule expressions;
scheduled or time-boxed changes; multiple environments; an audit database, an
audit history API, an audit UI, an audit schema, or any retention lifecycle
beyond the existing platform log window; a global user list, user directory,
search, enumeration or pagination; any mobile client change; creating, renaming
or deleting flag names at runtime; runtime management of `PRIVATE_FEATURE_FLAGS`,
`delivery_canary`, or `external_agent_relay` (DD-1); changes to the operator
allow-list mechanism or to any authorization boundary; generalized governance,
roles or delegation; optimistic-concurrency tokens, revision numbers or an
`If-Match` protocol; a schema-migration tool or version-upgrade path for the
runtime document; and any redesign of the deploy or landing workflow.

Also out of scope, and deliberately so — these were proposed by an earlier
planning pass and are excluded from this contract:

- a CLI command, admin button or any other reset subsystem for the runtime
  document, and any generalized recovery, repair or migration machinery for it;
- any cohort sweep beyond the one purge integration point required by DD-9 (no
  scheduled sweep, no bulk reconciliation job);
- a rewrite of the user-facing privacy summary or any other privacy-policy
  surface (a one-row addition to `docs/data-retention.md`'s retention table and
  one line in its export-exclusion list for the runtime flag document are in
  scope — DD-9, FR-007, SC-007);
- any edit to `.github/workflows/`, `scripts/`, or a byte-equivalence assertion
  over deploy artifacts;
- rollback test machinery beyond the two claims in SC-003: an older image ignores
  the new document, and the current image falls back to the environment baseline
  when the document is absent.

## Assumptions

- The production backend runs as a single process on a single Fly machine with
  `min_machines_running = 1` and the `brain_buddy_data` volume mounted at
  `/app/data`, so an advisory file lock plus an atomic replace is sufficient
  serialization. A move to multiple concurrent backend machines would need this
  assumption re-examined; it is not in this feature.
- Operators are the feature 009 allow-list; this feature introduces no new
  identity, credential, role or login path, and inherits the accepted PD-2/PD-5
  risk that the production operator is the seeded smoke identity.
- Every operator mutation and every cohort-resolving read is now recorded
  content-free by the existing application logger, in the same shape feature 009
  already uses (DD-10) — this corrects campaign 1's finding that the prior
  Assumption ("existing 009 rules" already cover it) was factually wrong. This
  feature adds no new record type, schema or store: it is one log line per
  operation.
- No maximum cohort size is enforced. Cohorts are expected to stay small — built
  one exact-match add at a time, with no listing, search or bulk-import path —
  so the per-read email-resolution fan-out and the operator screen stay
  practical without an explicit bound. If cohort sizes grow enough to change
  that, bounding them is a follow-up, not a defect of this slice.
- **Primary loop:** this feature does not change the capture → atomic items →
  clarify/approve → route/CRT → Weekly Review → evidence loop (constitution
  Principle V). It changes *who* is exposed to already-built capabilities, not
  what those capabilities do.
- **Viewport:** the `/admin` screen remains usable at a 390×851 viewport;
  [design.md](design.md) states the reflow treatment for the new section's mode
  control, source note and cohort rows explicitly (FR-010, SC-008) rather than
  only citing the feature-009 precedent. It is still operator tooling and no
  mobile-client evidence is required.
- The 15-second interval is a founder-set default, not a derived requirement. It
  is stated as a single named constant so changing it is one edit.
- Flag changes are **not** retroactive: work already dispatched under a flag keeps
  its existing, per-feature behaviour, and this feature does not revisit those
  rules.
