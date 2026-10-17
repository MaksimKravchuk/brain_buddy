# Feature Specification: Shared Apple Rust bridge cache

**Feature Branch**: `codex/shared-rust-bridge-cache`
**Created**: 2026-10-16
**Status**: Planning
**Input**: Populate a shared Rust bridge cache on main without reducing checks; verify real merge-queue reuse and speed.

## User Scenarios & Testing

### User Story 1 - Reuse unchanged compiler output (Priority: P1)
As the repository owner, I want queued iOS changes to reuse the exact same bridge already built on main.
**Independent Test**: read main-scoped cache metadata, then observe a real merge-group hit and the normal app build and complete package test step.
**Acceptance Scenarios**:
1. Given missing shared output, when trusted main CI prepares it, then both existing Apple variants are built and saved under their existing exact-input keys.
2. Given shared matching output, when a queued PR runs, then its bridge is restored and its app build and full package tests still run.
3. Given different inputs or no readable cache, when CI runs, then it builds the bridge instead of using a nonmatching artifact.

### Edge Cases
Cache eviction, an ordinary miss or failed warming retain the existing cold-build path. Cache-service restore errors retain the existing failure behavior; adding restore-error recovery is outside this correction. Concurrent main pushes cannot cause a wrong-key restore. Toolchain/source/target changes invalidate keys. A canceled warm run cannot certify any product check.

## Requirements
- **FR-001**: Populate both existing Apple Rust bridge variants in main's cache scope from trusted main pushes using the existing input identity.
- **FR-002**: Preserve app/widget builds, full Linux/macOS package tests, platform variants, coverage, required checks, release and queue configuration.
- **FR-003**: Preserve exact-key reuse and normal cold rebuild on cache misses; do not promote PR-created cache contents into main's scope.
- **FR-004**: Record producer and merge-group run links, cache key/ref, timings and actual complete-test evidence without credentials or user content.

## Success Criteria
- **SC-001**: Main-scoped cache entries exist for both existing Apple variants after successful warming.
- **SC-002**: A real merge-group run restores the matching bridge, spends seconds rather than approximately 12 minutes on bridge preparation, and retains passing app build and complete package tests. Report total iOS duration and test count; source changes can change counts legitimately.
- **SC-003**: Existing required CI and workflow safety checks pass on the reviewed SHA; report landing/release outcomes honestly. Cache failure never turns a required check into a pass.

## Clarifications
Owner's current request authorizes the bounded CI change, CI runs, landing through existing protections and live cache verification. Existing main protections are preserved; the ASK landing approval is recorded against the concrete reviewed candidate before enqueue, and any conflict with the normative protection model is surfaced before landing. No user-visible surface or product data changes; no additional product decision is open.
