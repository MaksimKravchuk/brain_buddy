# BrainBuddy vNext CloudDesign build contract

Date: 2026-07-13

Status: Accepted implementation contract; unresolved gates defer only their named slices

Scope: CloudDesign v2, the implementation baseline at this record's date, ADR-0001, and
ADR-0002. ADR-0006 contains the later current-state audit and narrower native-GTD
lifecycle/query decisions.

## 1. Purpose and authority

This document turns the supplied CloudDesign v2 mockups into an implementation backlog
and traceability contract. It does not make the mockup executable by treating every label
as an accepted domain decision. The precedence order is:

1. accepted ADRs and their normative acceptance scenarios;
2. this contract within its accepted scope and explicit per-slice gates;
3. CloudDesign interaction intent;
4. demo text and placeholder behavior in the mockup.

ADR-0001 is `Accepted`; ADR-0002 remains `Proposed` and is the most specific voice-operation
contract. Where CloudDesign conflicts with either, this document names the conflict rather
than silently choosing the mockup. Unresolved decisions in Section 11 defer only the slices
named there; they do not reopen D-01 or the native backend boundary.

The original authorization conflict is resolved. ADR-0001 now accepts BrainBuddy-owned
Tasks, Projects, and Contexts as the canonical first-tranche GTD store. Section 6 is the
build-level elaboration of that accepted boundary: native task state belongs to Tasks,
while execution runs/results and optional adapters remain separate and deferred.

This contract preserves the current CRT. A task or project is not a tree or node. The
project `Think` affordance may open or create a linked CRT through the existing Thinking
port, but no task API, repository, or UI may duplicate `TreeDocument`, `NodeDocument`,
`RelationDocument`, or the live cause-to-effect relation semantics.

## 2. Evidence baseline

The repository inventory and gap classifications in this section are a historical
2026-07-13 baseline. Use
`docs/decisions/0006-native-gtd-lifecycle-and-capability-baseline.md` for the current
implementation matrix and for accepted Tag terminology, lifecycle recovery, Waiting,
date, Priority, search, sort, and pagination semantics.

### 2.1 Design archive

Analyzed archive:

- `/home/max/.hermes/cache/documents/doc_2a9c9ca2a1d5_BrainBuddy v2.zip`
- SHA-256: `ad1dc51db84b40e479aa7a00c28a73e775530deb66ad7d32e5a116c118a1c907`
- extracted source: `/home/max/Code/brain_buddy/.hermes/design-imports/cloud-design-v2`

The source files, not the six hand-annotated PNG uploads, are the exhaustive interaction
evidence. The PNGs emphasize the desktop GTD navigation and alternative placements of
the mobile recording controls; they do not add states absent from the JSX.

Primary design evidence:

- desktop interactive shell and demo state: `app/bb-app.jsx`
- eight static desktop frames: `app/bb-screens.jsx`
- shared task row/detail behavior: `app/bb-shell.jsx`
- mobile interactive state machine: `app/bbm-app.jsx`
- nine static mobile frames: `app/bbm-screens.jsx`
- mobile task/navigation components: `app/bbm-parts.jsx`

CloudDesign is a prototype, not production code. `prompt()` task creation, local React
arrays, toast messages saying “not built,” and labels such as “send to inbox” are evidence
of intended affordances, not accepted persistence or safety semantics.

### 2.2 Current repository

The live product has:

- invite-gated session authentication and owner resolution;
- a single protected route rendering `TreeWorkspace` (`frontend/src/App.tsx`);
- React Query, Zustand, typed API clients, toasts, and reusable controls;
- authenticated `/api/trees` CRUD plus node, relation, version, validation, import/export,
  and AI-feedback routes (`backend/app/api/routes.py`);
- file-backed owner-scoped tree/auth repositories wired through
  `backend/app/container.py`;
- the canonical CRT documents in `backend/app/schemas/domain.py`;
- backend ownership/API tests and frontend component/store tests.

It has no task, project, context, capture, operation, review, route, or native task API or
repository. No CloudDesign screen is wired into the live router.

### 2.3 Existing vNext contracts

- ADR-0001 defines the modular monolith, immutable capture provenance, mutable
  `CaptureItem`, Weekly Review, routing, CRT promotion, result linkage, owner scoping,
  revisions, and idempotency.
- ADR-0002 defines one persisted `AsyncOperation` substrate for brain dump and voice-led
  Weekly Review, ordered patches/events, offline chunk upload, reconnect, retry, cancel,
  explicit confirmation, partial commit, and bounded undo.
- `specs/002-async-voice-workflows/acceptance-tests.md` is normative for voice operation
  implementation.

## 3. Exact CloudDesign screen and state inventory

### 3.1 Shared information architecture

Both form factors expose:

- GTD lists: **Inbox**, **Next actions**, **Waiting for**, **Someday / maybe**;
- **Weekly review**, with a `due Sun` indicator;
- projects with a color marker and project task view;
- contexts such as `@calls`, `@errands`, `@deep-work`, and `@laptop`;
- task completion checkboxes;
- task metadata for due date, context, project, waiting age, AI state, and CRT-thinking
  state;
- task detail containing subtasks, run log/agent area, and comments;
- voice Brain Dump entry.

The demo task visual states are:

| State shown | Visible example | Required projection, not necessarily Task-owned |
|---|---|---|
| plain/open | `Buy stamps` | open task |
| completed | checkbox/strikethrough after toggle | terminal task completion plus reopen policy |
| due | `before Fri` | task due value |
| waiting | `sent Tue` | waiting metadata |
| AI offered | `AI can draft` | optional execution capability |
| AI working | `Drafter · ready in ~5 min` | active Execution run projection |
| AI needs user | `Needs you — choose a venue`, `Choose one` | blocked run plus requested action |
| AI review | `Ready for review` | completed run/result awaiting user review |
| thinking | `Thinking · 12 steps` | linked CRT projection, never embedded graph state |

### 3.2 Desktop static frames

`app/bb-screens.jsx` lays out exactly eight desktop frames:

| ID | Frame | Visible content and states | Affordances |
|---|---|---|---|
| D-01 | Next actions | six tasks; running, due, needs-you, thinking, AI-offer, and plain states | complete task; open row; AI/action chips; group by project; sort; add next action; sidebar navigation; search; Brain dump; account |
| D-02 | Inbox | four raw items and processing guidance | complete/open item; sort; add task; shared navigation |
| D-03 | Task details | first next action expanded inline | toggle task; toggle/add subtask; inspect run log and timestamps; add comment; collapse row |
| D-04 | Group by project | Onboarding revamp, Team offsite, Pricing, and No project sections | turn grouping off; task interactions; sort |
| D-05 | Project | project title/meta, project tasks, `Think` | open/complete task; launch linked thinking; add project task |
| D-06 | Context | `@deep-work`, three tasks across lists | open/complete task; retain project/list identity |
| D-07 | Weekly review | explicit placeholder and guidance | navigation only; workflow is not designed in CloudDesign |
| D-08 | Brain dump | modal over Next actions | close modal only; desktop recording is explicitly “Placeholder — not designed yet” |

The desktop interactive prototype also makes all four list views, all demo project views,
and all four context views reachable. It maintains completion counts, supports a local
`prompt()` add action, expands one task row at a time, and toggles project grouping. Search,
sort, account, new project, task-detail chips, project add, and `Think` only emit
not-built placeholders. Density and project-column switches belong to the design tool's
Tweaks panel and are **not product affordances**.

The shared expanded-detail component has two additional data-dependent variants: a run
log can contain an artifact link or a requested action, and a task with no run log shows
`Hand to agent` and `Edit prompt & hand off`. The interactive prototype routes those
controls to not-built toasts; they belong to the deferred Execution affordance, not the
first-tranche task domain.

### 3.3 Mobile static frames

`app/bbm-screens.jsx` lays out exactly nine mobile frames:

| ID | Frame | Visible content and states | Affordances |
|---|---|---|---|
| M-01 | Next actions | six task cards with the same metadata/state language as desktop | open drawer; start Brain Dump; open task; complete task |
| M-02 | Drawer | all four GTD lists, Weekly Review, projects, and contexts | select destination and close drawer/scrim |
| M-03 | Inbox | four raw items and processing guidance | add/open/complete item; start Brain Dump |
| M-04 | Task details | title, completion, AI/context/project chips, subtasks, run log, comments | back; complete; toggle/add subtask; invoke run action/artifact; add comment |
| M-05 | Brain dump recording | transcript tail, waveform, extracted cards, forming card, candidate count | stop recording; static label currently says `Stop & send … to inbox` |
| M-06 | Brain dump review | removable extracted task cards with optional date chips | remove; add date; close/discard; discard all; send to inbox |
| M-07 | Project | project tasks and `Think` | back; open/complete task; launch thinking; add project task |
| M-08 | Context | tasks across lists | back; open/complete task |
| M-09 | Weekly review | placeholder and due guidance | drawer/Brain Dump only; review workflow is not designed |

The mobile interactive prototype adds navigation history, functional local completion,
local task add, drawer dismissal, a recording-to-review transition, per-review-item
removal, discard, and local insertion into Inbox. It does not implement editing review
text or adding a date despite the labels. It has no operation persistence, reconnect,
offline, error, retry, cancel-during-processing, reconciliation, commit progress, or
partial-result state.

### 3.4 Brain Dump visual variants in uploaded annotations

The six PNG uploads show the same mobile recording concept at several vertical layouts:
mic/status and transcript either above the candidate list or in the bottom sheet, with
`Headed to inbox · 5`, three stable cards, a dashed “forming” card, waveform, and a
`Stop & send 5 to inbox` button. One wider image also shows a review mockup titled
`Review 9 tasks` with date/context/project chips. These are layout explorations. The
repeated red hand annotations highlight placement; they do not define additional domain
states.

## 4. Affordance traceability and gap classification

Legend:

- **Reuse**: live capability can be retained behind the new shell.
- **T1**: first-tranche must-build after decision gates.
- **T2**: next tranche required for full CloudDesign behavior.
- **Deferred**: intentionally not in the first product tranche.
- **Non-goal**: demo/design-tool behavior that must not become product behavior.

### 4.1 Global shell and navigation

| Affordance | CloudDesign source | Current code/API | ADR contract | Classification |
|---|---|---|---|---|
| authenticated shell/account | `bb-app.jsx:238-247`; `bbm-app.jsx:115-121` | `frontend/src/App.tsx:26-40`; auth store and `/api/auth/*` | ADR-0001 Identity and authorization sections | **Reuse/T1 integration** |
| four GTD lists and counts | `bb-app.jsx:252-269`; `bbm-app.jsx:227-247` | no task list API or component; live protected route renders only `TreeWorkspace` | ADR-0001 Tasks ownership and list contract | **T1** |
| projects navigation/color | `bb-app.jsx:271-283`; `bbm-app.jsx:248-259` | `TreeMenu` selects CRT trees, which are not projects; no Project API | ADR-0001 Tasks owns Project; Thinking owns CRT | **T1** |
| contexts navigation/filter | `bb-app.jsx:286-295`; `bbm-app.jsx:260-268` | no Context model, API, or component | ADR-0001 Tasks owns Context | **T1** |
| Weekly Review entry/due | `bb-app.jsx:266-268`; `bbm-app.jsx:243-246` | none | ADR-0001 WeeklyReview; ADR-0002 Weekly Review specialization | **T2**; placeholder may ship in T1 only if clearly unavailable |
| search tasks and trees | `bb-app.jsx:240-243` | no cross-domain search; current API client is tree-specific | no search contract | **Deferred**; separate task and tree search before federation |
| account menu | `bb-app.jsx:244-247` | only sign-out at `TreeWorkspace.tsx:174-189` | ADR-0001 Identity | **T1 minimal sign-out; Deferred menu** |
| responsive desktop sidebar/mobile drawer | `bb-app.jsx:250-301`; `bbm-app.jsx:207-271` | no task shell; only `TreeWorkspace` at `/` | transport/domain neutral | **T1** |
| design Tweaks panel | `bb-app.jsx:333-340` | none | none | **Non-goal** |

### 4.2 Lists, tasks, projects, and contexts

| Affordance | CloudDesign source | Current code/API | Required ADR/domain contract | Classification |
|---|---|---|---|---|
| list/query/count open tasks | `bb-app.jsx:108-112,175-231`; `bbm-app.jsx:181-203` | no Task schema/route/repository in `backend/app/schemas/domain.py`, `api/routes.py`, or `container.py` | ADR-0001 owner-scoped Task query projection | **T1** |
| add task/next action | `bb-app.jsx:114-118,227-230`; `bbm-app.jsx:99-103,199-202` | mock uses `prompt()` and local arrays; live product has no endpoint | idempotent Task create command | **T1** |
| open/collapse task detail | `bb-shell.jsx:193-227`; mobile `bbm-app.jsx:127-150,191-196` | no task route/component; current inspectors are CRT node/relation only | Task detail query and responsive route/panel | **T1** |
| complete/reopen task | `bb-shell.jsx:197-203`; `bbm-app.jsx:132-136,292-298` | prototype toggles local state; no live Task transition | audited Task command, revision check, completed timestamp, explicit reopen destination | **T1** |
| edit title/details/list/project/contexts/due/waiting | metadata rendered by `bb-shell.jsx:204-225` and `bbm-parts.jsx:61-78`; prototype does not persist edits | absent | Task patch/move commands and invariants in Section 6 | **T1** for fields required to make lists truthful |
| sort | `bb-app.jsx:196`; static `bb-screens.jsx:152,164` | not-built toast; no query sort | stable default `order_key`; named sort modes need a later contract | **Deferred** beyond manual/list default order |
| group by project | `bb-app.jsx:72-87,191-224`; static `bb-screens.jsx:184-211` | local projection over complete demo array | fetch every page for the selected state before client grouping, with explicit loading/error; no incomplete group may be presented as complete | **T1 desktop**; no new persistence concept |
| create/edit/archive project | `bb-app.jsx:271-283` (`New project` is placeholder) | no Project model/API; CRT tree create is not reusable as project create | Project commands and owner-scoped repository | **T1 create/read**, edit/archive **T2** |
| project view and add project task | `bb-app.jsx:130-154`; `bbm-app.jsx:156-169` | no Project/Task view; add emits placeholder | Project query plus Task create with `project_id` | **T1** |
| context view/filter | `bb-app.jsx:156-173,286-293`; `bbm-app.jsx:171-179,260-266` | no Context model/API | context query parameter and same-owner Context records | **T1** |
| task subtasks | `bb-shell.jsx:76-101`; mobile detail uses same component at `bbm-app.jsx:148` | demo-local state only | TaskSubtask records/commands | **T2** |
| task comments | `bb-shell.jsx:147-171`; mobile detail uses same component at `bbm-app.jsx:148` | demo-local state only | TaskComment append/query; owner actor only in MVP | **T2** |
| due date / review `Add date` | `bb-shell.jsx:206`; `bbm-app.jsx:139,351`; static review `bbm-screens.jsx:185-193` | display/label only | date-only Task field and proposal patch; D-04 | **T1 date display/edit**, reminders **Deferred** |
| waiting age/person | demo data `bb-app.jsx:48-54`; render `bb-shell.jsx:222` | display only | waiting metadata and validated state transition; D-05 | **T1** |
| AI run log/status/artifact/requested action | `bb-shell.jsx:104-145,205-221`; demo states `bb-app.jsx:29-55` | static data/not-built callbacks; current AI endpoint only validates CRT nodes | ADR-0001 Execution-owned run/result projection; autonomous execution is deferred | **Deferred**; no fake active AI states |
| `Think` from project | `bb-app.jsx:141`; `bbm-app.jsx:162` | placeholder; existing tree APIs are reusable only behind Thinking port | ADR-0001 ProblemCandidate and confirmed CRT promotion; preserve current tree model | **T2** |
| `Thinking · N steps` | render `bb-shell.jsx:211`; demo data `bb-app.jsx:44` | static demo value | linked existing-tree summary; count remains blocked by D-06 | **T2** |

### 4.3 Brain Dump and Weekly Review

| Affordance/state | CloudDesign source | Current code/API | ADR-0002 mapping | Classification |
|---|---|---|---|---|
| microphone start | `bb-app.jsx:245,304-319`; `bbm-app.jsx:105,119,273-277` | desktop placeholder/mobile local state only; no operation API | create `voice_brain_dump` operation after permission/consent | **T1 operation slice** |
| waveform/local recording feedback | `bbm-app.jsx:315-334` | fixed animated bars; no media capture | client-local `<100 ms` feedback | **T1** |
| stable transcript | `bbm-app.jsx:325-327` | fixed string | ordered `TranscriptSegment` projection | **T1** |
| growing candidate list/forming item | `bbm-app.jsx:319-323`; static `bbm-screens.jsx:157-172` | fixed strings | provisional ordered patches with source lineage | **T1** |
| numbered provisional cards | absent from CloudDesign source | absent | stable candidate identity/order; founder-approved language required by this task | **T1; replace mockup card language** |
| stop | `bbm-app.jsx:331` | local `stopDump` immediately loads fixed review data | seal upload, drain fast stage, reconcile; no canonical write | **T1** |
| cancel | absent | absent | idempotent `cancelling -> cancelled` | **T1** |
| processing/reconciliation | absent | absent | operation progress/state projection | **T1** |
| post-stop review | `bbm-app.jsx:339-363`; static `bbm-screens.jsx:177-203` | local fixed task array | frozen reconciled proposal batch | **T1** |
| edit/remove/reorder candidate | remove at `bbm-app.jsx:354`; labels imply edit/date but do not implement them | only remove mutates local review array | user patches; edits lock fields; freeze invalidation | edit/remove **T1**, reorder **T2** |
| add date in review | `bbm-app.jsx:351`; `bbm-screens.jsx:190` | label only | proposal field patch; exact date semantics | **T2** |
| explicit confirmation | `bbm-app.jsx:360` | appends fixed items directly to local Inbox | `confirm` idempotent batch commit | **T1**, relabel as confirm/add |
| close/discard/reopen/resume | close/discard at `bbm-app.jsx:342,361`; no resume UI | close currently discards; no persisted operation | UI close never cancels; discard is explicit cancel; refetch projection on reopen | **T1** |
| offline/chunk retry | absent | absent | numbered chunks, manifest, missing-chunk resume | **T1 safety requirement** |
| retryable/terminal errors | absent | absent | operation error states and checkpoint retry | **T1** |
| commit progress/partial result | absent | absent | action DAG and per-action results | **T1** |
| bounded undo | absent | absent | ADR-0002 explicit inverse command | **T2 UI**, backend contract must not preclude it |
| retention/raw-audio deletion/consent withdrawal | absent | absent | ADR-0002 provenance, consent, and privacy section | **T1 policy visibility and controls** |
| voice Weekly Review | Weekly Review placeholders at `bb-app.jsx:122-127`; `bbm-app.jsx:151-155` | absent | same operation substrate, review snapshot | **T2** |

## 5. First-tranche product contract

With D-01 resolved by accepted ADR-0001, the first tranche is the smallest honest version
of the CloudDesign product loop:

1. signed-in users land in a responsive task shell, with existing CRT reachable as a
   separate Thinking destination;
2. users can create, inspect, edit, classify, complete, and reopen native tasks across
   Inbox, Next, Waiting, Someday, projects, and contexts;
3. users can make a Brain Dump, see numbered **provisional** captures and stable transcript
   while speaking, stop or cancel, survive reconnect/retry, review reconciled proposals,
   and explicitly confirm selected additions;
4. only confirmed actions create canonical source provenance and native tasks;
5. no screen claims AI execution, Weekly Review completion, routing, or CRT promotion until
   the corresponding domain workflow is real.

First-tranche exclusions:

- autonomous agent assignment, run log, “AI can draft,” “Needs you,” and artifacts;
- federated search, arbitrary sort modes, reminders, recurrence, calendar sync, and
  external task editing;
- comments, collaboration, sharing, teams, and delegated ownership;
- full Weekly Review and voice-led Weekly Review;
- automatic task routing or CRT promotion;
- service extraction, broker, deployment changes, or new Fly resources.

The visual shell may reserve unavailable destinations only when they are visibly disabled
or labeled preview—not populated with fabricated activity.

## 6. Accepted native GTD domain model

### 6.1 Accepted ownership decision

ADR-0001 adopts native tasks with these boundaries:

- add a **Tasks** bounded module owning native GTD records and transitions;
- keep Organize ownership of `CaptureItem`, clarification, source-preserving edits, and
  confirmation decisions;
- let the application workflow create a Task through `TaskPort` only after confirmation;
- add `native_task` as an allowed confirmed destination; reserve but defer
  `external_task_tracker` rather than aliasing or synchronizing it;
- define task completion in Tasks while capture completion remains Organize-owned;
- keep Review outcomes referencing task IDs without copying task state;
- keep Execution runs and EvidenceResults outside Task;
- keep CRT graph ownership in Thinking.

Do not place native tasks in `TreeDocument`, do not turn projects into trees, and do not
make `CaptureItem` itself the mutable task. One capture may later create multiple tasks or
one task may combine multiple captures; separate IDs avoid locking those concepts into a
false one-to-one relationship.

### 6.2 Canonical records

All records use opaque IDs, `owner_id`, UTC timestamps, `schema_version`, and integer
`revision`. All writes are owner-scoped, revision-checked, idempotent commands.

```text
Task:
  id, owner_id
  title
  details?
  state: inbox | next | waiting | someday | completed | cancelled
  project_id?
  context_ids[]
  due_date?                 # local calendar date; no reminder implication
  waiting_for?
  waiting_since?
  order_key                 # stable order within state
  source_capture_ids[]      # provenance references, not embedded source text
  created_at, updated_at, completed_at?, cancelled_at?
  schema_version, revision

Project:
  id, owner_id
  name
  color?                    # validated presentation token/value
  state: active | completed | archived
  linked_tree_ids[]         # references existing CRT only
  created_at, updated_at, schema_version, revision

Context:
  id, owner_id
  name                      # canonical form includes or renders `@`
  state: active | archived
  created_at, updated_at, schema_version, revision

TaskSubtask:
  id, owner_id, task_id
  title, order_key
  state: open | completed | cancelled
  created_at, updated_at, completed_at?, schema_version, revision

TaskComment:
  id, owner_id, task_id, actor_id
  body
  created_at, edited_at?, schema_version, revision
```

Invariants:

- `completed` and `cancelled` are terminal until an explicit `reopen` command.
- Reopen requires a destination open state; it never guesses the previous state.
- `waiting` requires `waiting_for` or an explicit `waiting_since`; leaving `waiting`
  preserves history in an audit decision but clears the active projection fields.
- `project_id` and every context ID must resolve to active, same-owner records.
- project completion/archive never silently completes or deletes its tasks.
- task deletion is a separate privacy/soft-delete concern; checkbox completion is not
  deletion.
- comments are append-only in T2 except an owner edit that preserves audit history.
- source capture text is never copied into an audit log or event payload.
- AI/run/thinking chips are composed read projections:
  `Task + ExecutionSummary + linked CRT summary`; those states are not Task enums.

### 6.3 Task API

All endpoints are under `/api`, use the current session cookie and error envelope, return
`X-Correlation-ID`, and are owner-scoped. Mutations require `Idempotency-Key`; updates and
transitions require `expected_revision` and return `409` on stale state.

```text
GET    /tasks?state=&project_id=&context_id=&unassigned_project=&include_completed=&cursor=&limit=
POST   /tasks
GET    /tasks/{task_id}
PATCH  /tasks/{task_id}                       # title/details/metadata/order only
POST   /tasks/{task_id}/transitions           # move, complete, reopen, cancel

GET    /projects
POST   /projects
GET    /projects/{project_id}
PATCH  /projects/{project_id}
POST   /projects/{project_id}/transitions      # complete/archive/reopen

GET    /contexts
POST   /contexts
PATCH  /contexts/{context_id}
POST   /contexts/{context_id}/archive

GET    /tasks/{task_id}/subtasks
POST   /tasks/{task_id}/subtasks
PATCH  /tasks/{task_id}/subtasks/{subtask_id}
POST   /tasks/{task_id}/subtasks/{subtask_id}/transitions

GET    /tasks/{task_id}/comments
POST   /tasks/{task_id}/comments
PATCH  /tasks/{task_id}/comments/{comment_id}
```

Representative commands:

```text
POST /tasks
{
  "title": "Call the dentist to reschedule",
  "state": "next",
  "project_id": null,
  "context_ids": ["ctx_calls"],
  "due_date": "2026-07-17",
  "source_capture_ids": []
}

POST /tasks/{id}/transitions
{
  "action": "move",
  "to_state": "waiting",
  "waiting_for": "venue",
  "expected_revision": 3
}

POST /tasks/{id}/transitions
{
  "action": "complete",
  "expected_revision": 4
}
```

`GET /tasks` follows ADR-0001's normative list contract. It returns a flat `TaskPage` with
`items`, `next_cursor`, `has_more`, and open `counts_by_state`; default/max limits are
50/200. Filters are owner-scoped, project/context counts ignore only the state filter, and
the stable order is `order_key`, `created_at`, then `id`. The opaque cursor binds that sort
tuple and normalized filters. For T1 group-by-project, the client must fetch every page for
the selected state before it renders groups and must show aggregate loading/error while
doing so. It may not present a partially fetched group as complete. If task volume makes
full retrieval unacceptable, replace that implementation with a server `group_by=project`
projection that exposes per-group counts and cursors before release; silently incomplete
client grouping is never conformant.

The operation confirmation API remains ADR-0002's `/operations/{id}/confirm`. The client
must not create tasks one by one after confirmation. The server workflow commits
Capture source, CaptureItem, and Task records with deterministic child idempotency keys
and returns per-action results.

### 6.4 Capture-to-task mapping

A confirmed “add to Inbox” proposal performs:

1. create immutable `AtomicCaptureSource` with transcript-segment lineage;
2. create the Organize-owned `CaptureItem`;
3. record approval and destination `native_task`;
4. create a Task in `inbox` with a new ID and `source_capture_ids=[capture_id]`;
5. persist the route/link result and mark the capture `completed` only after the Task write
   is known to have succeeded;
6. return both IDs in the operation action result.

A retry reuses deterministic child keys and yields one source, one item, and one task. A
partial failure remains visible and retryable; it does not invent an atomic filesystem
transaction.

## 7. Brain Dump UX mapped to ADR-0002

### 7.1 Required correction to CloudDesign language

> Superseded on 2026-09-05 (ADR-0002 amendment): the recording surface no longer
> shows a candidate list at all. Browser-preview text is rendered as a transcript
> readout, and tasks appear only on the review surface once the reconciler has
> turned the accurate transcript into next actions. The mapping below documents
> the earlier mockup language and is kept as design history.

During recording, no item is “headed to inbox,” nothing has been sent, and the total may
change during reconciliation. Replace the mockup's authority language:

| Mockup | Contract language |
|---|---|
| `Headed to inbox · 5` | `Provisional · 5` or `5 provisional items` |
| unnamed cards | stable numbered cards `#1`, `#2`, … |
| forming dashed text | `Wording still changing` |
| stable candidate | `Provisional` until reconciliation/confirmation |
| `Stop & send 5 to inbox` | `Stop` (seals recording; does not commit) |
| `Nothing is saved until you stop` | `Nothing is added to your tasks until you confirm` |
| `Send 5 to inbox` | `Confirm 5 additions` after a frozen batch exists |

Numbers are presentation order, not durable IDs. Reorder/merge/split keeps opaque lineage
and recomputes visible numbering.

### 7.2 User-visible state mapping

| Operation state | Required mobile/desktop UX |
|---|---|
| `idle` | Brain dump button/mic; permission and processing-consent entry |
| `recording` | waveform, duration, network state, stable transcript, numbered provisional cards, `Stop`, `Cancel`; upload/fast-stage subprogress may overlap |
| offline while recording | `Offline — recording locally`, local-limit warning, continue/stop choice, no fake server progress |
| `uploading` / `fast_processing` | stage text, missing/uploaded chunk status when useful, cancel; never a made-up percentage |
| `reconciling` | preserve visible provisional cards and user edits; show `Reviewing wording and duplicates…`; allow leave/resume/cancel |
| `awaiting_confirmation` | reconciled batch, before/after/source/confidence warnings, edit/remove/select, retry reconciliation, confirm |
| `committing` | per-action progress, prevent duplicate confirm, allow cancel under ADR-0002's bounded semantics |
| `completed` | actual added/failed counts, links to created tasks, bounded undo where supported |
| `retryable_error` | failed stage, preserved checkpoint/work, `Retry`, `Cancel`, and transcript-only/manual fallback where allowed |
| `terminal_error` | plain failure explanation, salvage/delete options, zero claimed canonical writes |
| `cancelling/cancelled` | explicit cleanup state/result; closing the UI is never treated as cancel |

Every operation view also exposes current processing-consent status and working-artifact
retention in a privacy/details surface. After successful reconciliation it shows when raw
audio is scheduled for deletion and offers `Delete raw audio now`. Withdrawing external
processing consent while active stops future upload/provider calls, transitions to an
explicit salvage/cancellation choice, and schedules uncommitted media/transcripts for
deletion; it must not masquerade as an ordinary provider failure.

Desktop must not retain CloudDesign's placeholder modal once Brain Dump ships. It should
use the same operation projection and commands as mobile, adapted to a dialog or dedicated
route. Correctness cannot differ by layout.

### 7.3 Reconnect, event, and confirmation rules

- Persist `operation_id` client-side immediately after creation.
- Reopen by `GET /operations/{id}` and subscribe with `after_sequence`; poll when SSE is
  unavailable.
- Ignore duplicate event sequences, buffer bounded gaps, and refetch projection on an
  unrecoverable gap.
- Continue local chunk capture offline within the configured limit and upload only missing
  chunks on reconnect.
- Send `withdraw_external_consent` and `delete_raw_audio` through ADR-0002's idempotent
  `POST /operations/{id}/commands`; the operation projection reports cleanup status.
- User edits are `user` patches and lock changed fields against model overwrite.
- Reconciliation may merge/split/reword but must preserve source lineage and surface
  conflicts.
- Freeze a batch before enabling confirmation. Any later edit supersedes that batch.
- Confirmation is one idempotent command with deterministic child keys. Timeouts and
  repeats cannot create duplicate tasks.
- Cancel and close are separate. Close leaves the operation resumable.

## 8. Executable vertical slices and dependencies

Each slice must produce a user-visible path plus API/repository tests; no “frontend-only
complete” slice may populate fake domain state.

### Slice 0 — decide and scaffold boundaries

Dependencies: D-03 for product landing/deep-link behavior. Native backend work is not
blocked by an external-tracker decision because that adapter is deferred.

Deliverable:

- consume accepted ADR-0001 native-Tasks ownership and API contracts;
- package/import architecture test for Identity, Capture, Organize, Tasks, Review,
  Thinking, Execution, and operation workflow ownership;
- reserve `/` for task shell and move existing CRT workspace to a stable `/trees` route
  without changing CRT schemas or services;
- define typed API schemas before UI implementation.

### Slice 1 — manual Inbox-to-completion loop

Dependencies: Slice 0.

Backend:

- Task, Project, Context repositories/services and `/tasks`, `/projects`, `/contexts` APIs;
- create, query, edit, move, complete, reopen;
- owner isolation, revision conflict, idempotency, stable counts/order.

Frontend:

- responsive shell, desktop sidebar/mobile drawer;
- Inbox/Next/Waiting/Someday lists, add/edit/detail, completion;
- project and context create/select/filter;
- real empty/loading/error/retry states;
- explicit link to preserved CRT workspace.

Exit evidence: a signed-in user creates an Inbox task, moves it to Next, assigns project
and context, completes and reopens it on both responsive layouts; refresh preserves state.

### Slice 2 — persisted operation shell with deterministic fakes

Dependencies: Slice 1 and ADR-0002 schemas.

Deliverable:

- create/get/events/chunk/seal/commands/batch/confirm operation endpoints;
- persisted operation/event/patch projections and deterministic fake stages;
- microphone permission/consent, local chunk capture, waveform, stop/cancel;
- reconnect/polling fallback, retryable error, terminal error, and cleanup projections;
- visible consent/retention state, consent withdrawal, and an immediate
  post-reconciliation raw-audio deletion command;
- no canonical capture/task write before confirm.

Exit evidence: acceptance scenarios OP, UP, EV, CO-01, and core privacy tests pass using
fakes; browser refresh during recording/reconciliation/confirmation restores projection.

### Slice 3 — provisional transcript and two-stage reconciliation

Dependencies: Slice 2 and calibrated provider adapters.

Deliverable:

- stable transcript segments, numbered provisional patches, field locks;
- fast-stage failure fallback and reconciler retry/manual review;
- merge/split/remove/edit with lineage;
- latency telemetry and versioned evaluation report for configured thresholds.

Exit evidence: PA/TR scenarios and latency gates in
`specs/002-async-voice-workflows/acceptance-tests.md` pass with deterministic model fakes;
no live provider is used in CI.

### Slice 4 — confirmed Brain Dump to native Inbox

Dependencies: Slices 1–3.

Deliverable:

- frozen review batch and explicit selection/confirmation;
- atomic-source, CaptureItem, decision/link, and Task writes through ports;
- deterministic per-action idempotency, partial-result/retry UI;
- completed operation links to created tasks; bounded undo for new unrouted captures/tasks.

Exit evidence: repeated/time-out confirmation produces one task per confirmed action;
source-to-task provenance is inspectable; cross-owner and stale-revision tests pass.

### Slice 5 — detail depth and thinking link

Dependencies: Slice 1; Slice 4 for source links.

Deliverable:

- subtasks and comments;
- project `Think` through `ProblemCandidate` and user-confirmed CRT promotion;
- linked existing tree summary only—no duplicate graph model;
- truthful execution/result chips only when Execution records exist.

### Slice 6 — smart Weekly Review

Dependencies: Slice 4 plus ADR-0001 Review implementation.

Deliverable:

- resumable Weekly Review with bounded snapshot and full outcome coverage;
- same `AsyncOperation` substrate for voice-led review;
- confirm-before-write, retries, partial outcomes, and completion summary;
- no second voice state machine.

## 9. Migration boundaries

### 9.1 Frontend

- Keep login/signup and `ProtectedRoute` unchanged unless a separate auth task requires it.
- Introduce an authenticated application shell route. The task workspace becomes the
  product landing route only after Slice 1 is functional.
- Move/wrap `TreeWorkspace` behind `/trees` (and `/trees/:treeId` when deep links are
  introduced). Preserve React Flow canvas behavior, tree stores, inspectors, versions,
  import/export, and AI validation.
- Reuse generic Button, Spinner, Toast, API client/error handling, React Query, and auth
  store patterns. Do not copy prototype JSX or global-window design-system code into the
  TypeScript product.
- Use server state in React Query. Keep only ephemeral UI and offline audio/operation resume
  metadata client-side; task arrays are never Zustand/local-only canonical state.

### 9.2 Backend and persistence

- Add new packages under `backend/app/modules/` and operation workflows under
  `backend/app/workflows/` as ADR-0001 suggests.
- Existing flat tree services remain the canonical CRT implementation and are exposed via
  a Thinking adapter; do not migrate them as part of task/capture slices.
- New records get owner-specific directories and atomic writes. A candidate layout is:

```text
tasks/{owner_id}/{task_id}.json
projects/{owner_id}/{project_id}.json
contexts/{owner_id}/{context_id}.json
operations/{owner_id}/{operation_id}.json
task-comments/{owner_id}/{task_id}.jsonl
```

- Derived indexes/counts are rebuildable. Per-owner/per-operation writes must serialize.
- Existing tree/auth files require no data migration for Slice 1.
- Move workflow data to SQLite at ADR-0001's concurrency/recovery trigger; do not treat that
  as service extraction.

### 9.3 Contract compatibility

- Existing `/api/trees*` and `/api/auth*` routes remain backward compatible.
- New APIs use the current error envelope, correlation middleware, cookie auth, and
  wrong-owner `404` behavior.
- Operation clients invoke operation endpoints, not Capture/Task endpoints directly.
- Internal events remain redacted and contain IDs/enums, not task, transcript, comment, or
  evidence text.

## 10. Required test evidence

### 10.1 Domain and repository

- every Task/Project/Context allowed and forbidden transition;
- same-key/same-body idempotency and key/body conflict;
- stale revisions return `409` without mutation;
- cross-owner reads/references/commands return `404`;
- stable ordering and counts across complete/reopen/move;
- inactive/wrong-owner project/context assignment is rejected;
- project archive does not mutate member tasks;
- source-to-task links survive Capture working-artifact cleanup;
- import architecture test forbids cross-module repository imports;
- existing CRT tree/node/relation tests remain unchanged and green.

### 10.2 API

- authenticated list/create/detail/update/transition round trips;
- invalid query combinations and pagination boundaries;
- correlation ID response behavior;
- deterministic operation confirm yields exactly one task/source/item per action after
  duplicate request and timeout-after-accept;
- no canonical task exists before confirmation;
- wrong-owner operation, task, project, context, and source references leak nothing;
- consent withdrawal stops later uploads/provider calls and schedules uncommitted working
  artifacts for deletion;
- immediate raw-audio deletion after reconciliation removes media while transcript/source
  provenance remains valid and the projection reports the updated retention state.

### 10.3 Frontend

- desktop sidebar and mobile drawer reach every supported list/project/context;
- loading, empty, error, retry, offline, reconnect, and stale-conflict states;
- checkbox completion and reopen use server results and survive refresh;
- group-by-project does not hide unprojected tasks;
- recording card numbers/order remain stable under duplicate/out-of-order events;
- user edits survive fast/reconciler patches;
- Stop does not commit, Close does not cancel, Cancel commits nothing, Confirm is
  double-click safe;
- the privacy/details surface shows consent and retention, supports consent withdrawal,
  and exposes immediate raw-audio deletion after successful reconciliation;
- responsive accessibility: keyboard navigation, labeled controls, focus return for
  dialog/drawer, status announcements, reduced-motion waveform fallback.

### 10.4 Voice release gate

All applicable scenarios in `specs/002-async-voice-workflows/acceptance-tests.md` are
normative. A provider-backed release additionally requires the versioned labelled
confidence evaluation and p50/p95 telemetry described there. Live model calls are never a
CI dependency.

## 11. Decision register

| ID | Decision needed | Options and impact | Owner/gate |
|---|---|---|---|
| D-01 | Is BrainBuddy now the canonical native GTD task store? | **Resolved A:** accepted ADR-0001 makes Tasks/Projects/Contexts product-owned canonical records. External projections cannot own completion or list state. | Resolved 2026-07-13; unblocks Slice 0/1 |
| D-02 | What is the first-tranche external tracker posture after native Tasks? | **Resolved: defer.** No external route, import, export, dual write, or synchronization in T1. Existing integrations are later adapter/migration concerns and never the native UI source of truth. | Resolved 2026-07-13; no backend blocker |
| D-03 | Product landing and CRT navigation | Task shell at `/` with CRT at `/trees` is proposed. Confirm deep-link/back-navigation expectations. | Product; blocks shell routing |
| D-04 | Date semantics | **Resolved:** first tranche is an ISO local calendar date only; no time-of-day, timezone, or reminder promise. | Resolved in ADR-0001 |
| D-05 | Waiting semantics | **Resolved:** free-text `waiting_for` or explicit `waiting_since` is sufficient; no person/task reference model in T1. | Resolved in ADR-0001 |
| D-06 | Meaning of `Thinking · N steps` | Node count, unresolved questions, or operation steps. Proposed: do not ship the number until defined; show `Linked thinking tree`. | Product/CRT; before Slice 5 |
| D-07 | Project-to-CRT cardinality | Proposed project may link multiple existing trees; `Think` asks link existing vs create new. One automatic tree per project would conflate domains. | Product/CRT; before Slice 5 |
| D-08 | Comment scope | Owner-only notes vs future collaborators. Proposed T2 owner-authored notes; do not design mentions/permissions now. | Product; before comments |
| D-09 | Brain Dump selection default | Proposed safe new additions may be preselected after reconciliation, but confirmation remains explicit; low-confidence/conflicted items are not preselected. | Product/safety; before Slice 4 |
| D-10 | Desktop Brain Dump layout | Modal, side sheet, or dedicated route. All must use the same persisted operation; choose via responsive usability testing, not domain divergence. | Design; does not block backend Slice 2 |
| D-11 | Weekly Review scheduling | `due Sun` is mock data. Define cadence, timezone, and due calculation before showing a badge. | Product; before Slice 6 |
| D-12 | Native task hard-delete/retention | Define privacy deletion and source-provenance consequences. Soft completion/cancel is not erasure. | Product/privacy; before deletion API |

## 12. Definition of contract completion

An implementation may claim CloudDesign vNext conformance only when:

- accepted ADR-0001 remains authoritative for native GTD ownership, provenance, list
  semantics, execution separation, and CRT preservation;
- every first-tranche affordance in Section 4 is backed by a real owner-scoped API or is
  visibly unavailable;
- Brain Dump uses the corrected provisional/confirmation language and all ADR-0002 safety,
  reconnect, retry, cancellation, privacy, and idempotency semantics;
- confirmed additions have inspectable transcript-segment -> AtomicCaptureSource ->
  CaptureItem -> Task provenance;
- current CRT schemas, services, relation direction, and tests remain canonical;
- the required automated evidence in Section 10 is green.

Until then, CloudDesign remains design evidence—not proof of implemented behavior.
