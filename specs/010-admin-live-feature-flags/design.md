# Design: Live Feature-Flag Management in the Admin Portal

## Screen and state inventory

**No new route.** The one surface this feature adds is a second section on the existing `/admin` screen, below the account lookup section feature 009 ships. Feature 009's PD-1 still holds in full: `/admin` is reached only by typing the URL, no navigation entry or account-menu item points at it, and no other screen issues an admin request. The section renders only inside `D-02` (the 009 operator-confirmed state) — an operator denied at `D-08`, unverified at `D-09` or still checking at `D-01` never sees it.

The section covers exactly the two **managed flags** — `voice_brain_dump` and `mobile_task_classification` (spec.md DD-1). `delivery_canary` and `external_agent_relay` never appear on this screen: they are not runtime-manageable, and showing them without controls that work would be more confusing than not showing them at all.

State IDs are stable and citable by acceptance tests (`F-01`…`F-13`). The `F-` prefix is deliberate: `D-01`…`D-10` belong to feature 009's states on the same screen and must stay unambiguous. `F-13` closes a state-completeness gap review found (a request that fails outright, distinct from a successful degraded response).

| ID | State | Trigger | Copy contract |
| --- | --- | --- | --- |
| F-01 | Loading flags | the flag-state read is in flight | "Loading feature flags…" with `role="status"`; no controls rendered yet |
| F-02 | Flag list | the read succeeded | one row per managed flag: name, current mode as a three-option native `fieldset`/`legend` radio group (Off / On / Selected users), a source note reading "Runtime override" or "Deploy default ({state})" where `{state}` is off/internal/on — never mapped onto one of the three override modes — and, whenever a runtime entry exists, a "Use deploy default" action that clears the entire entry (cohort included) and, as one of `F-08a`'s three allowlisted mutations, routes through the confirm step first (FR-003, FR-010, DD-3, DD-12) |
| F-03 | Cohort summary | a row has any selected-users state to report | "{n} selected", shown whenever `n` is defined — including while OFF/ON and the cohort is merely retained (FR-005, DD-6) — and including zero, so an inactive cohort is never an ambiguous blank |
| F-04 | Cohort list | a row is `selected_users` with ≥1 member | one line per account: ID, canonical email resolved live, and a "Remove" action whose accessible name includes that row's identity (`aria-label="Remove {email or account ID}"`) (FR-010) |
| F-05 | Cohort empty | mode is `selected_users`, cohort empty | "No users selected — this flag is off for everyone." Stated as a consequence, not an empty list |
| F-06 | Add user form | mode is `selected_users` | one text input (ID or email) plus "Add", per flag row. Reuses the 009 lookup contract — no browse, no suggestions. Rendered only in `selected_users` mode (FR-005, DD-6) |
| F-07 | Add — no match | the exact lookup returned no account | "No account found." — identical wording to 009's `D-04`, regardless of which field was submitted |
| F-08 | Saving | any mutation in flight | the affected control disables and shows loading; other rows stay usable. Reached directly except the two `F-08a` gates |
| F-08a | Confirm | the operator triggers one of the exact three allowlisted mutations (DD-12): setting OFF, removing the **last** SELECTED_USERS member, or "Use deploy default" (FR-010) | inline confirm ("Turn {flag} off for everyone?" / "Remove the last selected user? {flag} will be off for everyone." / "Use the deploy default for {flag}? It currently ships {deploy_default_state} and this clears the runtime override.") with Confirm/Cancel; Confirm proceeds to `F-08`, Cancel/Escape return to `F-02`/`F-04` with nothing sent and focus restored to the opening control. Every other mutation skips straight to `F-08` — a fixed allowlist, not a computed "does this zero the population" rule; a stale-tab race can still zero a population without either tab's confirm firing (accepted residual, DD-12) |
| F-09 | Saved | a mutation succeeded | the row re-renders from the server's returned state, never optimistic local state (FR-010); a brief `role="status"` "Saved." Focus after a cohort-row removal moves to the next remaining row's Remove action, or — if none remain — the add-user input, or — if that was the only visible cohort element — the cohort-count region |
| F-10 | Mutation failed | any non-404 mutation failure (5xx, network, refused name, degraded store) | when the server responded: the existing `Feedback` error banner carrying the correlation ID, retryable. When no response was received at all: "Could not reach the server. Check your connection and try again.", no correlation-ID fragment. The row reverts to the last server-confirmed state |
| F-11 | Store degraded | the read **succeeded** and reported `degraded: true` (FR-004) | a warning region: "Runtime flag state could not be read. Every flag is resolving from the deploy default, and changes are disabled until this is repaired." Every control in the section is disabled. Distinct from `F-13`: a confirmed answer, not a failed request |
| F-12 | Unresolvable selected user | a stored account ID no longer resolves | the row shows the ID with "Account not found" in place of the email, keeps its Remove action, until the owning account is purged and the row is gone entirely (FR-007, DD-9) |
| F-13 | Flags list unreachable | the initial `GET /admin/feature-flags` itself fails (5xx, dropped connection, timeout) before any response body exists — as opposed to a successful `degraded: true` response (`F-11`) | a retry-capable error state distinct from `F-01`/`F-11`: "Couldn't load feature flags." with a "Retry" action and, when available, the correlation ID; mirrors the `isConfirmedDenial` vs. "could not verify" split feature 009's `AdminPage.tsx` already uses |

`F-11` has no retry affordance: degradation is a property of the stored document, not the request. `F-13` is the opposite — a request that never completed, which a retry can plausibly fix. Neither state has a "reset all flags" button — a repair/reset subsystem is out of scope, and a one-click destructive control was not asked for. While degraded, every flag resolves from the deploy baseline, a safe place to sit (FR-004).

## Interaction notes

- **Mode is a three-option control, not two toggles, plus a separate clear action.** OFF/ON/SELECTED_USERS are mutually exclusive runtime-override states (FR-003), modelled as a native `fieldset`/`legend` radio group so the screen can never render a state the server cannot store. Deploy-default inheritance is not a fourth radio option: it is the absence of a runtime entry, shown by the source note and left by clicking "Use deploy default" — a distinct action from selecting a mode.
- **Mutations are targeted, never a whole-form save.** Setting a mode, clearing an override, adding one account and removing one account are four separate operations (FR-005). There is no "Save all," so two operators editing different flags never overwrite each other.
- **Exactly three named mutations require confirmation; the rest are immediate** (`F-08a`, DD-12): setting a flag OFF, removing the last remaining member, and "Use deploy default" — a fixed allowlist, not a computed "reduces exposure to zero" rule (unenforceable server-side against concurrent tabs, and "Use deploy default" can zero a population exactly as OFF can when the deploy default ships OFF). Every other mutation only adds capability or moves state the operator can already see and immediately undo, so it stays a single click — narrower than feature 009's confirm-on-revoke (irreversible, 009-FR-006); a mode change is always reversible by its own inverse.
- **Input classification reuses feature 009's client contract verbatim.** The add input sends the value as `email` when it matches the client's email pattern and as `account_id` otherwise; sent **as typed and never trimmed**, because trimming would manufacture a match the server is required to refuse (009-FR-003, FR-007). `admin@localhost` must classify as an email.
- **Emails are display-only and never stored.** Each cohort row's email is resolved at read time from the account record (ADR-0017 §1), not part of the stored document (FR-001, DD-5). A member who changes their email shows it immediately, nothing to migrate.
- **The retained cohort count stays visible outside SELECTED_USERS mode.** Switching to OFF or ON does not clear the cohort (FR-005, DD-6); `F-03`'s count keeps rendering. The add/remove form (`F-06`) and cohort rows (`F-04`) stay hidden outside SELECTED_USERS mode since add/remove is refused there.
- **Nothing on this section reveals member data beyond what 009 already authorizes.** Only the account ID and canonical email of an account the operator explicitly selected are rendered — the same two fields 009's lookup already returns.

### Mobile reflow at 390×851

Feature 009's own screen never had to fit this section's density, so citing its precedent alone is not evidence. At 390px:

- each managed flag's row stacks vertically: flag name, then the mode `fieldset` (its three radio options wrap to a second line rather than overflowing), then the source note and "Use deploy default" on their own line;
- a cohort row (`F-04`) stacks the account ID above the resolved email, "Remove" right-aligned on the email's line, minimum 44px tappable height;
- the add-user input (`F-06`) and its "Add" button stack full-width;
- `F-08a`'s Confirm/Cancel controls stack with the same 44px-minimum treatment as the section's other controls;
- nothing in the section requires horizontal scrolling at this width.

## Propagation behaviour (member-facing, no screen)

FR-009 has no UI of its own on either client: it changes when existing auth state is refreshed, not what any screen looks like. The requirement is client-generic — "an already-open session," not "the web tab" — so both contracts below are in scope, realized through each client's own idiom (FR-009, DD-11).

**Web:**

- while `status === "authed"`, `GET /api/auth/me` is refetched every 15 seconds and immediately on `focus`/`visibilitychange` to visible, via a `refreshSession()` operation distinct from the store's initial-load `hydrate()`;
- no request while unauthenticated or hidden, so a backgrounded tab costs nothing;
- the returned `feature_flags` replace the stored ones, so any component reading `hasFeatureFlag` re-renders on the next tick;
- a 401 clears the session and stops the timer, exactly as `hydrate()` does for the initial load;
- a **transient** failure (anything but a 401) leaves the session, user record and flags untouched and surfaces nothing — deliberately different from `hydrate()`, which clears to anonymous on *any* failure so a cold load against an unreachable backend does not hang forever; that startup behavior is unchanged.

**Mobile** — the same contract, through `SessionProvider`'s own idiom (no `visibilitychange` equivalent exists on the platform):

- while signed in **and** `AppState` is `"active"`, `/auth/me` is refetched on the same 15-second interval, and immediately on returning to the foreground rather than waiting out the remainder of the interval;
- the poll is suspended, not merely paused mid-tick, while backgrounded, inactive, or signed out;
- the resolved `taskClassificationEnabled`/`voiceEnabled` values update from the refetched payload;
- a transient failure leaves the session and flags untouched and the poll continues; a 401 clears the session and stops the poll exactly as an in-app 401 does today.

There is deliberately **no** "your access changed" notice on either client — the founder's slice asks for the capability to appear or disappear, and a member who never had it has nothing to be told.

## Accessibility

Most of this section's chrome — buttons, the `Feedback` error banner, `SectionCard`/`Field` layout — is inherited from components `AccountSettingsPage` and feature 009 already use on this screen. The mode control is **not**: no radio-group primitive exists anywhere in `frontend/src/components/ui/` today, and neither `AccountSettingsPage.tsx` nor feature 009's `AdminPage.tsx` contains one — both use only `Field`'s single-value text inputs. The mode control and the per-row focus/labelling behavior below are new work, specified explicitly rather than claimed as inherited:

- **Mode control markup.** Each flag's mode control is a native `<fieldset>` with a `<legend>` reading "{flag name} mode", wrapping three `<input type="radio" name="mode-{flag}">` elements labelled Off / On / Selected users. Native radio semantics give keyboard operability (arrow-key roving, one Tab stop) and group naming for free; the current mode is always exactly one checked input, since `F-09` always re-renders it from the response.
- **Remove action naming and focus.** Each cohort row's "Remove" button carries `aria-label="Remove {email or account ID}"` so a screen-reader user tabbing through several rows can tell which account each one removes. On success, focus moves to the defined target named in `F-09`, never dropped to the document body.
- **Per-row live regions.** `F-07`, `F-09` and `F-10` announce through `role="status"`/`role="alert"` scoped to the row they belong to.
- **Confirm step focus.** `F-08a`'s inline confirm receives focus on appearance and returns it to the opening control on Cancel or Escape.
- **Non-color feedback.** `F-05`, `F-07`, `F-09`, `F-10`, `F-11`, `F-12` and `F-13` all carry text; none is distinguished by color alone.
