# Feature 019 release-evidence index

This directory contains **synthetic local pre-candidate evidence** for the Current Reality Tree canvas. It does not claim a deployment, production smoke, rollback drill, or exact committed candidate.

## Current status

| Evidence | Result | Artifact |
| --- | --- | --- |
| Selected-user exposure, keyboard creation, persistence/reload, second-account isolation | PASS in real local Compose | [`runtime/t024-compose-auth-isolation.json`](runtime/t024-compose-auth-isolation.json) |
| 200-card interaction latency | PASS in pinned Chromium 151.0.7922.34: all six operations recorded 20 samples; aggregate p95 and the proportion at or below 200 ms met their declared thresholds. The runtime JSON is the source of truth for exact measurements. | [`runtime/t027-200-card-performance.json`](runtime/t027-200-card-performance.json) |
| Automated accessibility audit | PASS: 0 serious/critical axe violations in the T027 canvas journey | [`runtime/t027-200-card-performance.json`](runtime/t027-200-card-performance.json) |
| Supported-width boundary | PASS at 1024 and 1280 CSS px: no document horizontal overflow or clipped shell at either width | [`runtime/t027-200-card-performance.json`](runtime/t027-200-card-performance.json) |
| Default-OFF/internal-only rollout | PASS locally: selected user received `crt_canvas=true`; unselected second user received content-free 404 and no frontend content requests | [`runtime/t024-compose-auth-isolation.json`](runtime/t024-compose-auth-isolation.json) |
| Rollback procedure | Documented but **NOT_RUN**; no deployment or rollback authorization is claimed | [`rollback/feature-019-crt-rollback.template.json`](rollback/feature-019-crt-rollback.template.json), [`../../../../docs/fly-deployment.md`](../../../../docs/fly-deployment.md) |
| Exact candidate binding | **PENDING PR CI**: checked-in runtime files remain honest local pre-candidate evidence; PR CI attaches fresh T024 and T027 artifacts bound to the explicitly checked-out head SHA | [`runtime/t024-compose-auth-isolation.json`](runtime/t024-compose-auth-isolation.json), [`runtime/t027-200-card-performance.json`](runtime/t027-200-card-performance.json) |
| Exact deployed-SHA screenshots/recording and production smoke | **NOT_RUN**: commit/push/deploy require separate approval | — |

## Approved visual-state references

The bounded visual contract is represented by the checked-in D-series artifacts:

- [`../design/D-01-default-canvas.html`](../design/D-01-default-canvas.html)
- [`../design/D-02-first-run-tree-menu.html`](../design/D-02-first-run-tree-menu.html)
- [`../design/D-03-offline-conflict-confirmation.html`](../design/D-03-offline-conflict-confirmation.html)
- [`../design/D-04-keyboard-inspector.html`](../design/D-04-keyboard-inspector.html)
- [`../design/D-05-system-states.html`](../design/D-05-system-states.html)
- [`../design/D-05-UW-unsupported-width.html`](../design/D-05-UW-unsupported-width.html)
- [`../design/D-06-destructive-confirmation.html`](../design/D-06-destructive-confirmation.html)

Runtime correspondence is exercised by `frontend/tests/e2e/crt.spec.ts`: first-run/tree-menu, keyboard branching, save-failure recovery/conflict, rejected import, normal OFF, degraded flag storage, unsupported width, tree lifecycle, real-Compose auth/persistence/isolation, and the bounded 200-card performance/accessibility journey.

## Evidence integrity

- Runtime files are removed before their owning journey starts and are written only after all assertions pass; a failed rerun cannot leave a prior PASS artifact in place.
- Fixtures and accounts are synthetic. Artifacts contain no real names, email addresses, credentials, local filesystem paths, or production graph content.
- T027 records raw samples and per-operation p95 for selection, drag, Enter, Tab, pan, and zoom. Setup, undo, save stabilization, and fit-all correctness are outside the measured intervals.
- The rollback file is a template with explicit `NOT_RUN` and incomplete-proof fields. It must be replaced by scrubbed exact-candidate observations before any deployment claim.
- Final release evidence still requires a clean committed candidate, exact-SHA reruns, independent exact-SHA review, and authorized deployment/rollback evidence where applicable.
