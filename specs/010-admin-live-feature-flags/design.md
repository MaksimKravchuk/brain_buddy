# Design: Live Feature-Flag Management in the Admin Portal

## Screen and state inventory

**No new route.** The one surface this feature adds is a second section on the
existing `/admin` screen, below the account lookup section feature 009 ships.
Feature 009's PD-1 still holds in full: `/admin` is reached only by typing the
URL, no navigation entry or account-menu item points at it, and no other screen
issues an admin request. The section renders only inside `D-02` (the 009
operator-confirmed state) — an operator who is denied at `D-08`, unverified at
`D-09` or still checking at `D-01` never sees it, so this feature adds no new
denial state and no new way to observe the operator allow-list.

The section covers exactly the two **managed flags** — `voice_brain_dump` and
`mobile_task_classification` (spec.md DD-1). `delivery_canary` and
`external_agent_relay` never appear on this screen: they are not runtime-
manageable, and showing them without controls that work would be more
confusing than not showing them at all.

State IDs are stable and citable by acceptance tests (`F-01` … `F-13`). The
`F-` prefix is deliberate: `D-01` … `D-10` belong to feature 009's states on
the same screen and must stay unambiguous. `F-13` is new in this revision,
closing a campaign-1 gap (state-completeness finding, ux-accessibility-mobile
review).

| ID | State | Trigger | Copy contract |
| --- | --- | --- | --- |
| F-01 | Loading flags | the flag-state read is in flight | "Loading feature flags…" with `role="status"`; no controls rendered yet, so a mode can never be changed against an unknown current state |
| F-02 | Flag list | the read succeeded | one row per managed flag: the flag name, its current mode as a three-option native `fieldset`/`legend` radio group (Off / On / Selected users), a source note reading either "Runtime override" or "Deploy default ({state})" where `{state}` is the environment's own vocabulary — off, internal, or on, never mapped onto one of the three override modes — and, whenever a runtime entry exists, a secondary "Use deploy default" action that clears the flag's entire runtime entry — cohort included, even a non-empty one — and, being one of `F-08a`'s three allowlisted mutations, routes through the confirm step first (010-FR-003, 010-FR-010, DD-3, DD-12) |
| F-03 | Cohort summary | a row has any selected-users state to report | "{n} selected" for that flag, shown **whenever `n` is defined for that flag** — including while the flag's mode is OFF or ON and the cohort is merely retained (010-FR-005, DD-6) — and including zero, so an empty or inactive cohort is never an ambiguous blank |
| F-04 | Cohort list | a row is in `selected_users` mode and has at least one member | one line per selected account: its account ID, its canonical email resolved live from the account record, and a "Remove" action whose accessible name includes that row's identity (e.g. `aria-label="Remove {email or account ID}"`), so a screen-reader user tabbing through a multi-row cohort can tell rows apart (010-FR-010) |
| F-05 | Cohort empty | mode is `selected_users` and the cohort is empty | "No users selected — this flag is off for everyone." Stated as a consequence, not as an empty list, because "selected users, none selected" reads like a loading failure otherwise |
| F-06 | Add user form | mode is `selected_users` | one text input (account ID or canonical email) plus an "Add" submit, per flag row. Reuses the 009 lookup contract; there is no browse, no suggestion list and no result set. Rendered only in `selected_users` mode — add/remove mutations are refused in OFF/ON regardless (010-FR-005, DD-6) |
| F-07 | Add — no match | the exact lookup returned no account | "No account found." — same copy whichever key was submitted, disclosing nothing about which field was checked. Identical wording to 009's `D-04`, deliberately |
| F-08 | Saving | any mutation is in flight | the affected control is disabled and shows its loading affordance; other rows stay usable, because a mutation is scoped to one flag. Reached directly on click for every mutation except the two `F-08a` gates below |
| F-08a | Confirm | the operator clicks one of the exact three allowlisted mutations (010-DD-12) — setting a flag OFF, removing the **last** remaining SELECTED_USERS member, or clearing a runtime override ("Use deploy default") (010-FR-010) | a small inline confirm ("Turn {flag} off for everyone?" / "Remove the last selected user? {flag} will be off for everyone." / "Use the deploy default for {flag}? It currently ships {deploy_default_state} and this clears the runtime override.") with Confirm/Cancel; Confirm proceeds to `F-08`, Cancel returns to `F-02`/`F-04` with nothing sent and focus restored to the control that opened it; Escape does the same. Every other mutation — ON, SELECTED_USERS, adding a user, removing a non-last member — skips straight to `F-08`. This is a fixed operation allowlist, not a computed "does this zero the population" rule: a stale-tab race between two operators can still zero a population without either tab's confirm firing, an accepted residual (DD-12) |
| F-09 | Saved | a mutation succeeded | the row re-renders from the server's returned state, never from optimistic local state (010-FR-010). A brief confirmation is shown with `role="status"`: "Saved." Focus, after a cohort-row removal specifically, moves to a defined target: the next remaining row's Remove action, or — if none remain — the flag's add-user input, or — if the row removed was the only visible cohort element — the flag's cohort-count region |
| F-10 | Mutation failed | any non-404 mutation failure (5xx, network, refused flag name, degraded store) | when the server responded: the existing `Feedback` error banner carrying the correlation ID, retryable by resubmitting. When no response was received at all (a transport failure before any status line) there is no correlation ID to show; the banner instead reads "Could not reach the server. Check your connection and try again." with no correlation-ID fragment rendered. Either way the row reverts to the last server-confirmed state rather than to what the operator clicked |
| F-11 | Store degraded | the read **succeeded** and reported the runtime document is unreadable or malformed (`degraded: true` in a 200 response — 010-FR-004) | a warning region: "Runtime flag state could not be read. Every flag is resolving from the deploy default, and changes are disabled until this is repaired." Every control in the section is disabled — a control that looks live but refuses to write is worse than one that is visibly off. Distinct from `F-13`: this is a confirmed answer, not a failed request |
| F-12 | Unresolvable selected user | a stored account ID no longer resolves to an account | the row renders the ID with "Account not found" in place of the email, and keeps its "Remove" action, so a stale entry is always removable — until the owning account is purged, at which point the row is gone entirely because the ID itself was scrubbed from the cohort (010-FR-007, DD-9) |
| F-13 | Flags list unreachable | the initial `GET /admin/feature-flags` request itself fails — a transient 5xx, a dropped connection, a timeout — **before** any response body exists, as opposed to a successful response reporting `degraded: true` (`F-11`) | a retry-capable error state distinct from both `F-01` and `F-11`: "Couldn't load feature flags." with a "Retry" action and, when a response carried one, the correlation ID; mirrors the `isConfirmedDenial` vs. "could not verify" split feature 009's `AdminPage.tsx` already uses for its own status check, applied to this section's own fetch |

`F-11` deliberately has no "retry" affordance of its own: the degraded state is
a property of the stored document, not of the request, so retrying the read
would just repeat it. `F-13` is the opposite case — a request that never
completed, which a retry can plausibly fix — and is the state campaign 1 found
missing (ux-accessibility-mobile review, state-completeness finding). Neither
state has a "reset all flags" button — a repair or reset subsystem is out of
scope in [spec.md](spec.md), and a one-click destructive control is not
something the founder's slice asked for. While degraded, every flag resolves
from the deploy baseline, which is a safe place to sit (010-FR-004).

## Interaction notes

- **Mode is a three-option control, not two toggles, plus a separate clear
  action.** OFF, ON and SELECTED_USERS are mutually exclusive runtime-override
  states of one flag (010-FR-003), modelled as a native `fieldset`/`legend`
  radio group so the screen can never render a state the server cannot store.
  Deploy-default inheritance is not a fourth radio option: it is the absence of
  a runtime entry, shown by the source note and left by clicking "Use deploy
  default" (F-02), which is a distinct action from selecting a mode.
- **Mutations are targeted, never a whole-form save.** Setting a mode, clearing
  an override, adding one account and removing one account are four separate
  operations (010-FR-005). There is no "Save all" button, so two operators
  editing two different flags never overwrite each other and the screen never
  has to reconcile a stale snapshot.
- **Exactly three named mutations require one lightweight confirmation; the
  rest are immediate (`F-08a`, DD-12).** Setting a flag OFF, removing the last
  remaining SELECTED_USERS member, and clearing a runtime override ("Use
  deploy default") are a fixed operation allowlist, not a computed "does this
  reduce the effective population to zero" rule — campaign 2 found that rule
  unenforceable server-side against concurrent edits from two tabs, and found
  that the population-effect rationale itself required a third action
  ("Use deploy default" can zero a population exactly as OFF can, when the
  deploy default ships OFF) the original two-item list omitted. Every other
  mutation only ever adds capability or moves state the operator can already
  see and immediately undo, so it stays a single click. This is narrower than
  feature 009's confirm-on-revoke, which exists because session revoke is
  irreversible (009-FR-006); a mode change is always reversible by its own
  inverse, so the bar here is a fixed allowlist of three named operations, not
  "is this destructive" or a live population computation.
- **Input classification reuses feature 009's client contract verbatim.** The
  add input sends the value as `email` when it matches the client's email
  pattern and as `account_id` otherwise; it is sent **as typed and never
  trimmed**, because trimming would turn a whitespace variant of a real address
  into the canonical one and manufacture a match the server is required to
  refuse (009-FR-003, 010-FR-007). The same consequences pinned for 009 apply
  here unchanged, including that `admin@localhost` must classify as an email.
- **Emails are display-only and never stored.** Each cohort row's email is
  resolved at read time from the account record (ADR-0017 §1) and is not part
  of the stored document (010-FR-001, DD-5). A member who changes their email
  therefore shows their new one immediately, with nothing to migrate.
- **The retained cohort count stays visible outside SELECTED_USERS mode.**
  Switching a flag to OFF or ON does not clear its cohort (010-FR-005, DD-6);
  `F-03`'s count keeps rendering so the operator is never surprised by who
  becomes affected on a later switch back to SELECTED_USERS. The add/remove
  form (`F-06`) and cohort rows (`F-04`) stay hidden outside SELECTED_USERS mode
  — only the count is shown — because add/remove mutations are refused there.
- **Nothing on this section reveals member data beyond what 009 already
  authorizes.** The only member attributes rendered are the account ID and
  canonical email of an account the operator explicitly selected — the same two
  fields 009's lookup already returns.

### Mobile reflow at 390×851

Feature 009's own screen (one text input, one four-field result panel) never
had to fit this section's density, so citing its precedent alone is not
evidence (campaign-1 ux-accessibility-mobile finding). At 390px:

- each managed flag's row stacks vertically: flag name, then the mode
  `fieldset` (its three radio options wrap to a second line rather than
  overflowing horizontally), then the source note and "Use deploy default"
  action on their own line;
- a cohort row (`F-04`) stacks the account ID above the resolved email, with
  the "Remove" action right-aligned on the email's line and a minimum 44px
  tappable height;
- the add-user input (`F-06`) and its "Add" button stack full-width rather than
  sitting side by side;
- nothing in the section requires horizontal scrolling at this width.

## Propagation behaviour (member-facing, no screen)

`010-FR-009` has no UI of its own on either client: it changes when the
existing auth state is refreshed, not what any screen looks like. The
requirement is client-generic — campaign 2 found the prior revision had
specified only the web half of it against a brief that asks for "an
already-open session," not "the web tab" — so both the web contract and the
mobile contract below are in scope, realized through each client's own idiom
(FR-009, DD-11).

**Web** — its observable contract:

- while `status === "authed"`, `GET /api/auth/me` is refetched on a 15-second
  interval and immediately on `focus` and on `visibilitychange` to visible, via
  a `refreshSession()` operation distinct from the store's initial-load
  `hydrate()` (spec.md DD-11);
- no request is issued while unauthenticated or while the document is hidden,
  so a backgrounded tab costs nothing and a signed-out visitor is untouched;
- the returned `feature_flags` replace the stored ones, so any component
  reading `hasFeatureFlag` re-renders on the next tick;
- a 401 clears the session through the existing path and stops the timer,
  exactly as `hydrate()` already does for the initial load;
- a **transient** failure (anything other than a 401 — a network error, a 5xx,
  a timeout) leaves the session, its user record and its flags untouched and
  surfaces nothing: no error toast, no sign-out, no redirect. This is
  deliberately different from `hydrate()`'s own failure handling, which clears
  to anonymous on *any* failure so a cold load against an unreachable backend
  does not hang on "loading" forever — that startup behavior is unchanged.

**Mobile** — the same contract, through `SessionProvider`'s own idiom rather
than a `visibilitychange` equivalent that does not exist on the platform:

- while signed in **and** the React Native `AppState` is `"active"`,
  `/auth/me` is refetched on the identical 15-second interval, and immediately
  on the app returning to the foreground (an `AppState` transition to
  `"active"`) rather than waiting out the remainder of the interval;
- the poll is suspended, not merely paused mid-tick, while the app is
  backgrounded or inactive, and while signed out;
- the resolved `taskClassificationEnabled`/`voiceEnabled` values update from
  the refetched payload, so a gated capability appears or disappears without a
  logout, login or app restart;
- a transient (non-401) failure leaves the session and its flags untouched and
  the poll continues on its normal cadence; a 401 clears the session and stops
  the poll exactly as an in-app 401 does today.

There is deliberately **no** "your access changed" notice on either client.
The founder's slice asks for the capability to appear or disappear, and a
member who never had the capability has nothing to be told.

## Accessibility

Most of this section's chrome — buttons, the `Feedback` error banner, the
`SectionCard`/`Field` layout — is inherited from the components
`AccountSettingsPage` and feature 009 already use on this same screen. The mode
control is **not**: no radio-group or other multi-option primitive exists
anywhere in `frontend/src/components/ui/` today, and neither
`AccountSettingsPage.tsx` nor feature 009's `AdminPage.tsx` contains one — both
use only `Field`'s single-value text inputs (campaign-1 ux-accessibility-mobile
finding). The mode control and the per-row focus/labelling behavior below are
new work, specified here explicitly rather than claimed as inherited:

- **Mode control markup.** Each flag's mode control is a native
  `<fieldset>` with a `<legend>` reading "{flag name} mode", wrapping three
  `<input type="radio" name="mode-{flag}">` elements labelled Off / On /
  Selected users. Native radio semantics give keyboard operability (arrow-key
  roving within the group, one Tab stop into and out of it) and group naming
  for free, and the current mode is always exactly one checked input — a state
  the screen cannot desynchronize from the server's answer, because `F-09`
  always re-renders it from the response.
- **Remove action naming and focus.** Each cohort row's "Remove" button carries
  `aria-label="Remove {email or account ID}"` so a screen-reader user tabbing
  through several rows can tell which account each one removes, rather than
  hearing "Remove, button" repeated with no distinguishing context. On a
  successful removal, focus moves to the defined target named in `F-09` rather
  than being dropped to the document body.
- **Per-row live regions.** `F-07`, `F-09` and `F-10` announce through
  `role="status"` / `role="alert"` scoped to the row they belong to, so a
  result is attributed to the flag it came from rather than to the page.
- **Confirm step focus.** `F-08a`'s inline confirm receives focus on
  appearance and returns it to the control that opened it (the mode radio, or
  the row's Remove action) on Cancel.
- **Non-color feedback.** `F-05`, `F-07`, `F-09`, `F-10`, `F-11`, `F-12` and
  `F-13` all carry text; none is distinguished by color alone.
