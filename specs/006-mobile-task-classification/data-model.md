# Phase 1 data model

Server-side entities are unchanged. The only new structure is device-local.

## Unchanged (server)

| entity | relationship | note |
|---|---|---|
| Task | 0..1 Project, 0..n Tag | carries `revision`, which the server uses to detect a change made elsewhere |
| Project | referenced by 0..n Task | identity assigned by the server |
| Tag | referenced by 0..n Task | identity assigned by the server. ADR-0006: the term is Tag |

## New: PendingClassificationChange (device-local)

| field | type | why it exists |
|---|---|---|
| `taskId` | string | what the change applies to |
| `projectId` | `string \| null \| undefined` | `undefined` means untouched; `null` means deliberately cleared. The distinction is load-bearing — clearing a project is a supported outcome (FR-001) and must not be confused with "no opinion" |
| `tagIds` | `string[] \| undefined` | the whole intended set, not a delta. Coalescing a delta stream is where a queue loses data |
| `observedRevision` | number | the revision the person was looking at. Sent as `expected_revision`; a mismatch is the conflict of FR-008 |
| `queuedAt` | ISO string | shown in the conflict prompt, which must name what changed and when because nothing else does |
| `accountId` | string | FR-011. Part of the storage key, not merely a field |
| `serverUrl` | string | FR-011. Also part of the key |
| `idempotencyKey` | string | FR-017. Stable across retries of an **unchanged payload**; re-minted whenever the payload changes. See invariant 6 — an earlier draft said "never regenerated", which the backend makes unimplementable |
| `sendState` | `'queued' \| 'sending' \| 'conflicted' \| 'expired'` | FR-017, FR-018. `sending` is what makes a second drain trigger a no-op rather than a duplicate send. `expired` retains the payload so a wrong clock is recoverable |
| `originalValue` | `{ projectId, tagIds }` | FR-010. What **the device last displayed** when the first uncoalesced change was made — not necessarily what the server held. See invariant 9 |
| `firstQueuedAt` | ISO string | Immutable. Pairs with `originalValue` and `observedRevision`; sources M-04's "as of" |
| `lastEditedAt` | ISO string | Refreshed on every coalesce. FR-018's 30 days runs from **this**, so a live entry is never destroyed for the age of an edit it no longer contains |
| `firstSentAt` | ISO string \| undefined | Set on the first send attempt. Past 24 h from it the server's replay window has closed, so the entry may no longer be retried blind (invariant 10) |

### Storage key

`bb.pendingClassification.<serverUrl>.<accountId>`

Identity is in the key rather than in a filter. An entry belonging to another
account or server is not hidden from a query — it is in a different key that is
never read while this identity is active. FR-011 and SC-007 become properties of
the structure instead of rules someone has to remember to apply.

**Both halves of the key must be readable with no connection.** `serverUrl`
already is — `mobile/src/config/serverUrl.ts` persists it. `accountId` is not:
its only source today is `/auth/me`. The account id is therefore persisted on
every successful `/auth/me` and read from storage, never from the live session.
Without that, a cold start offline cannot name its own key and FR-009 fails on
the exact path the feature exists for.

### Invariants

1. **At most one _non-`sending`_ entry per `taskId` per key.** FR-010: several
   changes to one task coalesce to the net effect. The exception is load-bearing
   — see invariant 5b. Enforced by the reducer, table-tested.
2. **`observedRevision` is the revision seen when the *first* uncoalesced change
   was made**, not refreshed on coalescing. Refreshing it would silently swallow
   a concurrent edit — exactly what the conflict prompt exists to prevent.
3. **A tag added and then removed before the drain leaves no trace**, because
   `tagIds` is the intended set. If the net set equals the server's, the entry
   is dropped rather than sent as a no-op.
4. **Entries are never migrated across identities.** On a *deliberate* identity
   transition the key's contents are discarded after the FR-011 warning; they
   are not re-keyed. An involuntary session end discards nothing — the key
   simply stops being read until the same identity signs in again (FR-011).
5. **At most one drain in flight per entry.** FR-017. There are two drain
   triggers — app foreground and a successful request — so without this the
   ordinary case is two concurrent sends of one entry. An entry in `sending` is
   skipped by any further drain.
5b. **An edit arriving while an entry is `sending` does not touch that entry.**
   It creates a *successor* entry for the same `taskId`, `queued`, with its own
   fresh key. When the in-flight send settles: on acceptance the successor takes
   its `observedRevision` from the returned task and stays queued; on a failure
   that did not apply, the successor coalesces back into the original.

   Without this the two rules added for FR-010 and FR-017 destroy work between
   them. Invariant 1 forbade a second entry, so an edit during a send had to
   coalesce into the in-flight one — and then `accepted → removed` deletes an
   edit that was never sent, with FR-007 guaranteeing nothing on screen ever
   said it was pending. The 30 s client timeout makes that window wide.

5c. **`sending` is a liveness marker for the running process, never
   authoritative across a restart.** On every cold read of the queue, an entry
   found in `sending` is reset to `queued` before any drain runs. This mirrors
   the lease reconciliation ADR-0002 already specifies for the voice-operation
   queue — the identical problem, already solved once in this codebase.

   Without it, an app kill mid-send (iOS reclaiming the background app, or the
   force-quit `quickstart.md` itself instructs the tester to perform) strands
   the entry: invariant 5 makes every future drain skip it, so it is never sent,
   never conflicts, never errors, and its only terminal outcome is the FR-018
   drop 30 days later. It is safe because of invariant 6 — a re-send of an
   entry the server already applied replays the stored result.

6. **`idempotencyKey` is stable across retries of an unchanged payload, and is
   re-minted whenever the payload changes** — on coalescing, and on a re-send
   after a conflict is resolved in the person's favour.

   The earlier "generated once and never regenerated" was wrong, and wrong in a
   way that produced an entry that could never be sent.
   `_idempotency_record` replays the stored result only when the command *and*
   the request hash both match, and `_request_hash` covers the whole body plus
   `fields_set` (`backend/app/modules/tasks/service.py:1104`, `:1299`). So
   reusing a key with a coalesced payload returns `ConflictError` forever, with
   no retry that can clear it. `mobile/src/utils/ids.ts` already states the
   correct convention for this repo: automatic retries of the same attempt
   reuse the key; a user-initiated retry after a conflict gets a new one.

   Re-minting is safe because what protects a changed payload is
   `expected_revision`, not the key: a stale-revision send lands in the M-04
   conflict that already exists rather than in a dead end.
7. **`originalValue` is captured once and never refreshed**, for the same
   reason as `observedRevision`: it records where the person started, and
   refreshing it would quietly rewrite that to wherever they have got to.
8. **An entry older than 30 days from `lastEditedAt` moves to `expired` at the
   next read**, retaining its payload, and the notice is surfaced rather than
   swallowed (FR-018). Expiry is evaluated on read, not on a timer: a background
   timer in an app that is usually not running mostly does not fire.

   Three guards, because this is the only path in the feature that destroys the
   person's work without asking, and it keys on a clock the person can set:
   - `firstQueuedAt`/`lastEditedAt` are clamped at write time; a timestamp in
     the future is stored as now. Otherwise a clock that was ahead when the
     entry was written makes `now - lastEditedAt` negative and the bound never
     fires — on exactly the entries whose timestamps are least trustworthy.
   - Every response carries a `Date` header. The last server time seen is
     persisted, and the expiry test must pass against it too, so a device clock
     jumped forward cannot delete a queue on its own.
   - `expired` retains the payload until the person dismisses the notice, so a
     clock error is recoverable rather than terminal.

8b. **The sweep runs across every key, not only the active one.** On app start
   and on every identity change, enumerate `AsyncStorage.getAllKeys()` for the
   `bb.pendingClassification.*` and `bb.classificationCache.*` prefixes; apply
   the age rule to all of them, and delete any non-active key outright once a
   different identity has signed in successfully.

   Invariant 4 keeps another identity's entries unreadable, which closes
   disclosure — but unreadable is not deleted. Read-scoped expiry never runs on
   a key nobody reads, so without this sweep account A's queue and A's project
   and Tag names stay on the device forever the moment account B signs in.
   FR-011's "discarded on a different one" and FR-018's bound both become true
   by construction here instead of by a read that may never happen.

9. **`originalValue` is what the device last displayed, and is labelled as
   such.** It is captured once and never refreshed (same reasoning as
   `observedRevision`). It is *not* server history: if the device's copy was
   stale, the value is stale too. M-04 must therefore source it explicitly
   ("your phone last showed Inbox, as of 3 weeks ago") rather than presenting it
   beside the server's current value as though both came from the server. When
   `serverRevision - observedRevision > 1`, M-04 says the task changed more than
   once since the device last saw it — otherwise a sequence of edits the person
   was never party to is rendered as a two-party disagreement.

10. **Past 24 h from `firstSentAt`, an entry may not be retried blind.** The
   server forgets an idempotency key after `IDEMPOTENCY_RETENTION = 24 h`
   (`backend/app/modules/tasks/repository.py:39`) while FR-018 permits 30 days,
   so for most of an entry's life the key is not a dedupe token at all. Beyond
   the window the drain first re-reads the task, then either drops the entry if
   the server already holds the intended value, or re-presents it against the
   current revision with a new key and a refreshed `originalValue`.

   At-most-once is therefore delivered by the key inside 24 h and by
   `expected_revision` outside it. Stating this matters because the plan's
   integration test runs well inside the window and would otherwise be read as
   proving more than it does.

## New: CachedClassificationLists (device-local)

The plan added this store and no artifact modelled it, while three artifacts
asserted the queue was the only new place account content rests. It is not the
smaller of the two: the queue holds ids the device already had, this holds
**names the person wrote**, and project and Tag names routinely carry the most
disclosing content in a GTD system.

| field | type | why it exists |
|---|---|---|
| `projects` | `{ id, name }[]` | the picker must work after a cold start offline (FR-006) |
| `tags` | `{ id, name }[]` | same, for Tags |
| `fetchedAt` | ISO string | drives the same 30-day sweep as the queue, from `fetchedAt` rather than `lastEditedAt` |

Key: `bb.classificationCache.<encoded serverUrl>.<encoded accountId>`, derived
exactly like the queue's.

**Cleared on any deliberate identity transition even when the queue is empty.**
This has to be said separately because M-05 never appears with an empty queue
(design.md) — so a sign-out with nothing pending would otherwise leave one
account's whole project and Tag vocabulary on the device for the next person,
which is the literal thing FR-011 exists to prevent.

### Key derivation, for both stores

```
const esc = (x) => encodeURIComponent(x).replace(/\./g, "%2E");
`bb.<store>.${esc(serverUrl)}.${esc(accountId)}`
```

Components are escaped separately **and the separator is escaped inside each
component**. The second half is not belt-and-braces; without it the key does not
enforce SC-007 at all.

`encodeURIComponent` leaves `.` unescaped, so escaping per component is not
injective under a `.` separator:

```
queueKey("a.b", "c") === queueKey("a", "b.c") === "bb.pendingClassification.a.b.c"
```

`serverUrl` is a URL, so it *always* contains dots — this is reachable, not
theoretical. And because the design deliberately rejects a filter, the key is
the *sole* enforcement of SC-007: a collision here **is** one account reading
another's queue, with no bug anywhere else in the feature.

Escaping `.` to `%2E` leaves exactly two literal `.` boundaries and stays
`decodeURIComponent`-reversible, so `parseClassificationKey()` is a constructive
proof of injectivity rather than an assertion.

An empty component **throws** rather than producing a key. An empty `accountId`
would pool every account into one key, which is precisely the disclosure the
keyed design exists to prevent, so it fails loudly.

**Defence in depth, added despite the key:** every read also verifies each
entry's own `accountId` and `serverUrl` fields against the active identity and
discards a mismatch before display or send. SC-007 should not rest on string
derivation alone.

**Both halves of the identity must be persisted, from every path that
establishes one** — `/auth/me`, `/auth/login` and `/auth/signup`. An earlier
draft said "on every successful `/auth/me`", but `signIn` and `signUp` set the
session directly from their own responses and never call the probe, so a person
who signs in, goes offline and force-quits would have no persisted account id
at the next cold start — and FR-009 fails on the very path this mechanism was
added to fix. Persist the opaque `id` only, never the email.

## State transitions

```
        (person edits)
   ─────────────────────────▶ queued
                                │
              drain attempt ────┴──▶ sending   (a second trigger sees this and skips)
                                       │
          accepted ────────────────────┼──▶ removed, last-synced advances
          rejected on revision ────────┼──▶ conflicted  (M-04)
          rejected otherwise ──────────┼──▶ queued, error surfaced with correlation id
          timeout / connection lost ───┴──▶ queued, same idempotencyKey on the next try

   conflicted ── person keeps theirs ──▶ queued, current revision, key unchanged
   conflicted ── person abandons ──────▶ removed
   conflicted ── app backgrounded ─────▶ stays conflicted; the sheet returns

   edit arrives while sending ─────────▶ successor entry, own key  (inv. 5b)
   cold read finds `sending` ──────────▶ queued  (inv. 5c, ADR-0002 pattern)

   deliberate identity transition ─────▶ warned (M-05), then discarded
   involuntary session end ────────────▶ retained; drains silently on the next
                                          sign-in to the same identity (FR-011)
   30 days after lastEditedAt ─────────▶ expired (payload kept), notice shown;
                                          dismissed ──▶ removed  (FR-018)
   different identity signs in ────────▶ key deleted by the sweep  (inv. 8b)
```

"Offered on the next sign-in" (FR-011) means **made available, not asked
about**: the queue becomes readable again and drains through the ordinary
M-01/M-01b states with no prompt. A prompt would be new chrome for sync
bookkeeping, which is precisely what FR-007 removed.

The involuntary path is deliberately not the deliberate one. `SessionProvider`
today flips to signed-out on any 401 *and* on a plain network failure, so an
offline launch is indistinguishable from a sign-out — which under a
discard-on-sign-out rule would destroy the queue on exactly the path the
feature exists for. FR-019 fixes the detection; FR-011 keeps the work when
nobody chose to end the session. A person who never signs in again is covered
by the 30-day bound rather than by the session rule.

`conflicted` is deliberately a state and not a modal side effect: backgrounding
the app must not resolve it, and with no per-change marker on the task screen
the returning sheet is the only thing that will remind the person it is there.
