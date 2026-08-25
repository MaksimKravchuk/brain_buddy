# Research: Web task-title autocomplete

## Repository findings

1. `frontend/src/features/tasks/TaskListPage.tsx` owns the one new-Task title input and already integrates Smart Add through `parseSmartAdd`, `SmartAddSuggestions`, and one form submission path.
2. Smart Add's accepted contract (`specs/003-smart-add-classification/` and ADR-0007) keeps parsing local, gives its open listbox first ownership of Arrow/Enter/Escape, and performs no durable action until submit. Autocomplete must compose with this rather than add a second simultaneous menu.
3. `TaskRepository.list_for_owner(owner_id=...)` already returns owner-scoped Task documents from the existing Tasks SQLite store. Prior titles need no new entity, table, sidecar, or memory service.
4. `/api/auth/me` already projects server-owned effective flags. `FeatureFlagService` and `FeatureFlagOverrideRepository` make SQLite authoritative for runtime-managed flags and fail closed when the store is degraded.
5. ADR-0019 freezes a three-flag managed set and requires another ADR for a new runtime-managed flag. ADR-0021 therefore records the bounded fourth flag and its default-OFF initialization.
6. Existing validation-provider code is validation-shaped and the Voice reconciler is operation-shaped; neither contract safely represents title completion. Reuse `httpx`, configuration conventions, dependency injection, error envelopes, and correlation middleware, but introduce a narrow Tasks-owned completion port rather than coercing unrelated provider results.
7. The backend already has a small in-memory sliding-window limiter. A dedicated owner-keyed limiter can reuse it without a new dependency or durable rate store.
8. Existing API client calls accept `AbortSignal`, enabling browser cancellation. Cancellation is best-effort after an upstream provider request has started; the server timeout and no-retry rule bound residual cost.

## Decisions

- Endpoint required: provider discovery is necessary so consent can name the actual configured provider; completion generation is server-side so owner isolation, flag enforcement, context bounding, provider credentials, and logging policy cannot be bypassed.
- Candidate shape: three complete replacement titles, not suffixes. Each must extend the normalized draft and pass strict server validation.
- History bound: at most 50 distinct owner titles, Project matches first then `updated_at` descending. This bounds prompt size while using only the frozen context categories.
- Interaction timing: 350 ms debounce, one current request, abort on any eligibility/context/menu-owner change, monotonic stale-response rejection.
- Provider: one configured OpenAI adapter using the fixed official OpenAI API origin in v0, default disabled; deterministic fake only in tests. No arbitrary endpoint or provider selection UI.
- No result cache or suggestion history. Current component state is ephemeral and cleared on flag/consent/context changes or unmount.
- Instrumentation: content-free request outcome/latency/token counts and a best-effort accept event containing only completion request ID and rank. No title, Project name, prior title, prompt, response, content hash, or provider body is logged.

## Alternatives rejected

- Client-side AI call: would expose provider credentials and bypass owner-scoped context assembly.
- Reusing Smart Add suggestions: they complete classification tokens, not Task intent.
- Inline ghost text: explicitly outside the frozen UX and creates caret/keyboard ambiguity.
- Durable suggestion memory/vector store: unnecessary for v0 and prohibited by scope.
- Local title-only fallback after remote failure: would hide provider/consent failure and make experiment results incomparable. Safe unavailable preserves ordinary capture instead.
