# Design: Web task-title autocomplete

**Feature**: `012-task-title-autocomplete`
**Status**: Implementation-ready interaction contract

## Surface

The only changed surface is the existing new-Task composer in `TaskListPage`. The title `<input>` remains the single editable title field. A compact listbox is anchored immediately below it; no ghost text, modal, second editor, or mobile layout is introduced.

## States

- **A-01 — Flag OFF**: Existing composer is byte-for-byte behaviorally unchanged. No provider discovery, consent control, request, menu, metric, or autocomplete status is emitted.
- **A-02 — Provider unavailable**: Flag ON but provider discovery returns unavailable. The title input and ordinary submit remain enabled; a compact `AI suggestions unavailable` status is visible. No task text leaves the server.
- **A-03 — Consent not granted**: Flag ON and provider available. An unchecked, session-local consent checkbox names the provider and says the current draft, selected Project name, and prior Task titles will be sent. No autocomplete request is made.
- **A-04 — Below threshold**: Consent is current but the trimmed draft has fewer than three whitespace-delimited words without Project context, or is blank in Project context. No request or menu appears.
- **A-05 — Debouncing**: The draft is eligible and the UI waits 350 ms after the latest draft/Project change. Ordinary typing and submit remain responsive.
- **A-06 — Loading**: One request is active. No old menu remains visible. A compact non-blocking loading status is exposed to assistive technology.
- **A-07 — Three candidates**: Exactly three distinct full-title candidates render in one labelled listbox below the input. The first is active initially. No Smart Add listbox is present.
- **A-08 — Accepted draft**: Mouse or Enter replaces the whole input value with the chosen full title, keeps focus in the input, dismisses the menu, and emits only a content-free best-effort acceptance event. No Task is submitted or created. A later ordinary Enter/click follows existing submit behavior.
- **A-09 — Dismissed**: Escape closes the listbox and preserves the draft. The same unchanged draft does not reopen until draft or Project context changes.
- **A-10 — Safe unavailable**: Timeout, 429, provider error, invalid provider output, or offline failure dismisses candidates and shows a compact actionable status with correlation ID when supplied. The draft and ordinary submit remain enabled.
- **A-11 — Smart Add owns keyboard**: A caret-local completed or active `#`/`@` Smart Add token suppresses/cancels autocomplete. Only Smart Add's menu receives Arrow/Enter/Escape.
- **A-12 — Autocomplete owns keyboard**: When no Smart Add token/menu is active and autocomplete is open, autocomplete alone receives Arrow/Enter/Escape. Candidate validation rejects completed Smart Add syntax so acceptance cannot silently add Project/Tag side effects.

## Keyboard and accessibility

- ArrowDown/ArrowUp wraps through exactly three options.
- Enter with autocomplete open accepts the active candidate and calls `preventDefault`; it never submits the form. A subsequent Enter after the menu closes is the existing ordinary submit.
- Escape dismisses without changing text. Tab follows normal focus order and does not accept.
- Mouse selection has the same draft-only effect as Enter.
- The input exposes `aria-expanded`, `aria-controls`, and `aria-activedescendant`; the menu is a labelled `listbox`, each candidate is an `option`, and status text uses a non-disruptive live region.

## Responsive behavior

The listbox width follows the existing input container, wraps title text to at most two lines per candidate, and must not introduce horizontal scrolling at the existing 390×851 and 1280×780 acceptance viewports. No mobile application code changes; “web” includes the responsive browser shell only.
