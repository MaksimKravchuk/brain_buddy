# P2 product decision package

**Feature**: `specs/011-rtm-task-parity/` | **Date**: 2026-08-15
**Status**: decisions for the founder. Nothing here is a task until one is made.

Each row carries value, size/risk, dependencies and a recommendation of
`do now | separate feature | do not do`. None of these blocks P0. Evidence for the
"BrainBuddy today" column is in `capability-matrix.md`.

---

## P2-01 — Calendar

**RTM/product capability**: RTM has no calendar of its own but publishes iCalendar feeds
and is commonly paired with one.

**BrainBuddy today**: nothing. Due and start dates exist as data (C-08, and C-09…C-11 after
Slice 2) with no calendar surface.

**Four options, cheapest first**:

| option | value | size / risk | dependencies |
|---|---|---|---|
| none | zero cost; dates remain list-filterable | zero | — |
| internal read-only view | a week/month rendering of existing dated tasks; answers "what does my week look like" without any integration | small; pure client work over the Slice 3 filters | Slice 3 |
| read-only iCalendar export | the user sees BrainBuddy tasks inside the calendar they already use, which is where they actually plan | medium; **but** it forces the timezone question this feature deliberately deferred (FR-004, FR-034) — an `.ics` event has no floating-time escape hatch, and a secret feed URL is a new unauthenticated surface | Slice 2, plus a timezone decision, plus a feed-authentication decision |
| bidirectional integration | full two-way sync with an external calendar | large; ongoing provider maintenance, OAuth, conflict resolution, and a second source of truth for task dates | all of the above plus a sync architecture |

**Recommendation: separate feature — the internal read-only view.** It delivers most of the
"what does my week look like" value at client-only cost, and it does not force the timezone
decision. Read-only iCalendar export is the natural follow-on **after** reminders (P1-09)
settles timezone semantics; doing it before means deciding timezone twice. Bidirectional
integration is `do not do` for the foreseeable roadmap: it makes an external service a
co-owner of task dates, which contradicts the single-owner model this whole feature rests on.

---

## P2-02 — Attachments

**RTM/product capability**: RTM has attachments in its UI and a `hasAttachments` search
term, but exposes no attachment CRUD through MCP.

**BrainBuddy today**: nothing. The nearest thing is the notes/details body and the P1 URL
field (P1-01).

**Value**: real, but narrow — a task with a reference document attached is more useful than
one with a link, for users who work offline.

**Size / risk**: large, and disproportionate to the value. It introduces binary storage,
size and type limits, virus/content handling, per-file authorization, retention and purge
obligations under the existing GDPR export/deletion contract (`docs/data-retention.md`), and
a new egress path. It touches the ASK-class privacy surface directly.

**Dependencies**: the account export and deletion flows must both learn to include and purge
attachments before the first file is accepted, not after.

**Recommendation: do not do.** Ship P1-01's URL field instead. It covers the common case —
"this task is about that document" — at a fraction of the obligation. Revisit only if users
demonstrably ask for offline file access rather than for links.

---

## P2-03 — Contacts, assignment, shared lists, permissions

**RTM/product capability**: contacts, task assignment by email, list sharing as
viewer/editor, and permission inspection.

**BrainBuddy today**: nothing. The product is single-owner end to end — every task, List and
Tag route enforces per-owner filtering, and `waiting_for` is deliberately free text that
creates no Person record (ADR-0006).

**Value**: this is not a feature, it is a different product. It only pays off if BrainBuddy
becomes multi-user.

**Size / risk**: very large. Multi-owner records break the per-owner filtering invariant that
every task route currently relies on and that `FR-031`'s 404-not-403 semantics are built
around. It is ASK-class throughout, and it changes the authorization model rather than
extending it.

**Dependencies**: a product decision that BrainBuddy is multi-user, which no current artifact
makes.

**Recommendation: do not do** at the current product definition. If multi-user is ever
adopted, it is a program with its own constitution amendment, not a feature. The honest
interim answer for delegation is BrainBuddy's own agent handoff, which already exists and
which this feature deliberately keeps separate from task lifecycle (FR-032).

---

## P2-04 — MilkScript-like automation sandbox

**RTM/product capability**: MilkScript runs modern JavaScript server-side against a task
library; scripts can be saved, run, or executed inline.

**BrainBuddy today**: nothing. The nearest analogue is the agent handoff, which is a
different shape: a delegated attempt, not a deterministic script.

**Value**: moderate and speculative. The demonstrated uses — task templates, tag cleanup,
report generation — are each individually cheaper as first-class features than as a scripting
runtime.

**Size / risk**: very large. Arbitrary user code execution server-side is a sandbox-escape,
resource-exhaustion and data-exfiltration surface. It is the single highest-risk item in this
package.

**Dependencies**: a stable, versioned task API contract — which Slices 1–3 are only now
establishing.

**Recommendation: do not do.** Where a concrete MilkScript use case appears, build that use
case. Task templates and bulk tag cleanup are both better served by P1-04 batch operations.

---

## P2-05 — External RTM two-way sync

**RTM/product capability**: RTM's REST API supports incremental sync (`last_sync`), an
`external_id` for stable linkage, push subscriptions, and undo transactions — genuinely good
integration primitives.

**BrainBuddy today**: nothing, and deliberately so. RTM is this feature's **reference model**,
not an integration target (`spec.md` §Non-goals).

**Value**: real for a user with an existing RTM account and an RTM Pro subscription. Zero for
everyone else.

**Size / risk**: large and permanent. Two-way sync means two writers, which means conflict
resolution, a mapping table, dedupe keys, and an ongoing dependency on a third party's API
and their MCP-vs-REST feature asymmetry (the reference map notes `external_id` exists in REST
but is not exposed through MCP, so the MCP path needs a local mapping table the REST path
does not). Every P0 semantic this feature just settled — trash as orthogonal, archive
retaining membership, floating local times, priority `1|2|3|none` — becomes a translation
problem at the boundary.

**Dependencies**: Slices 1–3 complete and stable; a decision on which system wins a conflict.

**Recommendation: separate feature, and only if a user asks.** If it is ever built, start
one-way (BrainBuddy → RTM export, or RTM → BrainBuddy import) rather than two-way. The
capability map's own conclusion supports this: RTM does not model runs, blockers, approval
gates or artifacts, so a two-way sync would be syncing the smaller half of BrainBuddy's model
and would tempt exactly the completion-means-executed conflation FR-032 forbids.

---

## P2-06 — Global settings, defaults, timezone, language

**RTM/product capability**: default list, default due date, date/time formats, and read
access to timezone and language.

**BrainBuddy today**: no task-settings surface. Locale and timezone are handled implicitly —
this feature's floating-local-time decision (FR-004) exists precisely to avoid needing them.

**Value**: mixed, and worth splitting rather than deciding as one row:

- *Default List and default due date*: small, genuinely useful, low risk.
- *Date/time format*: cosmetic; browser and OS locale already answer it.
- *Timezone*: not a preference. It is a correctness prerequisite that P1-09 reminders cannot
  avoid, and pretending it is a setting understates it.
- *Language*: already partly addressed by the multilingual voice work
  (`specs/005-multilingual-voice-brain-dump/`); not a task-module concern.

**Size / risk**: small for defaults, medium for timezone because it changes the meaning of
every stored date.

**Dependencies**: defaults depend on Slice 1; timezone belongs to P1-09.

**Recommendation: split.** *Do now* is wrong for all of it, but **default List and default
due date are a separate small feature** worth doing soon — they remove friction from the
capture path the constitution names as primary. Date/time format and language: *do not do*.
Timezone: **not a settings decision at all** — fold it into P1-09 reminders, where it is a
blocking prerequisite rather than a preference.

---

## Summary

| id | decision | recommendation |
|---|---|---|
| P2-01 | Calendar | separate feature (internal read-only view); iCalendar export after P1-09; bidirectional: do not do |
| P2-02 | Attachments | do not do — ship P1-01 URL instead |
| P2-03 | Contacts / assignment / sharing / permissions | do not do at the current product definition |
| P2-04 | MilkScript-like automation sandbox | do not do — build the specific use cases |
| P2-05 | External RTM two-way sync | separate feature, only on demand, one-way first |
| P2-06 | Settings / defaults / timezone / language | split: defaults → separate small feature; formats and language → do not do; timezone → fold into P1-09 |

Nothing in this package is recommended `do now`. That is the finding, not an omission: every
P2 row is either large enough to deserve its own gate or better served by something already
in the P1 backlog.
