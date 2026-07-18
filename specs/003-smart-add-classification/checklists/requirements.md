# Smart Add specification quality checklist

**Purpose**: Verify the feature is implementation-ready before the backend/frontend card
starts.
**Created**: 2026-07-18
**Feature**: `specs/003-smart-add-classification/spec.md`

## Requirement completeness

- [x] User value and desktop/web scope are explicit.
- [x] `#` Tag and `@` Project terminology is unambiguous.
- [x] Existing-name suggestions and unknown-name creation are specified.
- [x] Many-Tag and zero/one-Project invariants are specified.
- [x] Repeated Project replacement and superseded-name non-creation are specified.
- [x] Clean-title behavior is deterministic.
- [x] Plain-title, title-edit, contextual-create, dropdown, and Voice compatibility are
  specified.
- [x] Chip/navigation presentation rules are specified.

## Grammar and interaction quality

- [x] Left/right boundaries, unquoted names, quoted names, and escaping are defined.
- [x] Partial, bare, invalid, and unclosed tokens have defined behavior.
- [x] Delimiters, punctuation, casing, Unicode normalization, whitespace, wrappers, and empty
  title are covered.
- [x] Duplicate Tag and repeated Project semantics are deterministic.
- [x] Caret-local query, ranking, result cap, create option, keyboard, mouse, and ARIA behavior
  are defined.
- [x] Selecting a suggestion has no durable side effect.

## Contract and architecture quality

- [x] Existing literal `POST /tasks` and PATCH contracts remain unchanged.
- [x] Compound Smart Add request/response and strict reference XOR are defined.
- [x] Owner, active-state, normalization, idempotency, transaction, rollback, and error
  semantics are defined.
- [x] Contextual Project/Tag IDs compose with inline name refs.
- [x] Affected backend/frontend files and cache behavior are identified.
- [x] ADR-0001/ADR-0006 ownership and CRT separation are preserved.
- [x] No service extraction, storage migration, remote search, AI, or mobile redesign is
  introduced.

## Acceptance and delivery quality

- [x] Independently testable user stories and measurable success criteria are present.
- [x] Parser, component, API/service, browser, literal-title, and Voice regression evidence is
  planned.
- [x] Exact verification commands and PR/release gates are documented.
- [x] The implementation task sequence is tests-before-code and grouped by shippable
  checkpoints.
- [x] No unresolved clarification marker or placeholder remains.

## Result

PASS — ready for implementation through the dependent Hermes Kanban card.
