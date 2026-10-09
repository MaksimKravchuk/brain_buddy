# Owner acceptance of specification 026

**Status: accepted as the specification baseline, 2026-10-09.** MaksimKravchuk explicitly answered “Yes” to approval of the prepared package and residual risks of custom sync, Rust/FFI and migration. The question retained mandatory measurements for complex slices before implementation. The [source record](evidence/026-native-20261009-1/owner-acceptance.json) preserves the exact reply and scope; the [human sign-off](evidence/026-native-20261009-1/human-signoff.json) is bound to the reviewed run and content.

- Approved source commit: `962a7fa8372ac48d9af1edc4e2130f16afb896da`.
- Review run: `026-native-20261009-1`; six of six lenses completed, four distinct technical findings corrected and confirmed closed, all 12 protocol-quality criteria satisfied.
- Approved core artifact digest: `968a327f01a50fb7e14ef84b1d73ab0731efbdd227d75fdeedbad5a394045623`.
- Original planning baseline verdict: **approved**, recorded in the [accepted summary](evidence/026-native-20261009-1/accepted-summary.json).

| Decision | Accepted baseline and review material | Recorded disposition |
| --- | --- | --- |
| Product scope and acceptance | Existing Apple/server path and compatible web/CLI/MCP/voice/Review integrations first; PostgreSQL after the pilot; later platform shells need separate specifications. SC-001–SC-008 use the hardware, workloads and RPO/RTO in [quickstart.md](quickstart.md). | Specification scope and written criteria accepted; product results remain future evidence |
| Design | [Eight screens](design/sync-states.html), [110 combinations](design.md), explicit two-version conflicts, retained local text, quiet status, reset preserving work, and the existing Cancel/export/confirmed-removal account-switch choice. | Design baseline accepted; rendering and native accessibility remain implementation checks |
| Governance and privacy | [Amendment proposal](adr-draft.md): one shared domain authority, narrow audited Rust binding allowance, command IDs separate from correlation IDs, content-free dedup metadata until purge, source TTLs and bounded restore/purge controls. Existing ADR-0002/0020/0026/0028 authorities remain. | Proposal accepted for enactment in PR-01 before conflicting implementation; existing accepted policies are not changed by this record |
| Implementation boundaries | The original 60-slice map at approved source `962a7fa` (subsequently amended below), with its paths, dependencies, budgets, checks and outcomes. Rust/FFI PR-03/04/05, runtime/SQLite PR-34 and AI PR-49/59/60 retain the stated measurement prerequisites, including Cargo.lock. | Delivery baseline accepted subject to measured sizing; unmeasured caps are not certified as feasible or unconditionally approved |
| High-risk planning review | Original six-lens reports, targeted closures, provenance and residual risks in [verification.md](verification.md). | Named-human residual-risk acceptance recorded; planning gate approved |

## Frozen inputs and status precedence

At acceptance commit `7a35fa5`, the reviewed core documents, HTML and ADR proposal were byte-for-byte unchanged from the approved source. Their earlier “pending”, “proposed” and approval-request labels describe that snapshot; this record supersedes its human-decision statuses. The October 9 delivery amendment below changes tasks.md, so the original digest/sign-off is **historical baseline evidence**, not a signature over the amended map. All other core requirements, plan, design, contracts, HTML and ADR proposal remain unchanged. The machine-readable map remains `proposed` because empirical execution-boundary approval is still conditional.

The original review reports, closures, manifests and pre-acceptance summary remain historical evidence. In particular, `corrected-artifacts.json` records the owner packet as it was presented at the approved source commit; its old approval.md hash is not a hash of this subsequent decision record. The new accepted summary supersedes only the missing-human-sign-off escalation, without converting the failed CLI attempts into successful runs or altering reviewer verdicts.

## Owner-requested delivery amendment — October 9

After accepting the technical baseline, the owner explicitly required one task per atomic PR, an explicit dependency graph, maximum safe parallel execution, and no approximately 5,000-line PRs. [tasks.md](tasks.md) now has **64 tasks / 64 PRs** and [the graph](delivery-graph.md) renders all **94 dependency edges**. Four added slices isolate shared domain values, domain registration, route registration and scheduler handoff. Independent rule, job-adapter, endpoint and web work no longer waits on unrelated shared-file edits; genuine semantic and merged-base dependencies remain.

Every implementation PR retains its declared product cap (at most 390 changed lines) and additionally has an **800 total added + deleted line cap**, including tests, docs and lockfiles. Both are mandatory measurements; excess requires re-slicing, with no oversize waiver. This implements the owner's requested delivery constraints and does not certify future code size. PR-61/62/64 join the previously listed complex slices requiring measured feasibility before execution-boundary approval.

The prior six-lens reports and named-human sign-off remain untouched and bind only their recorded baseline digest. The delivery amendment has its own bounded structural/independent review evidence in [verification.md](verification.md); it is not relabeled as another six-lens campaign or a new human sign-off. No product behavior, data/consent contract, migration authority or release permission is changed.

## Conditions carried into implementation

Measure the complex slices before approving their execution boundaries, and revise any boundary that cannot meet its cap. Enact the approved Constitution/ADR/Apple dependency and retention amendments through the governance slice with preserved history. Complete the planned implementation, runtime, design and acceptance evidence at the relevant slice and pilot gates. ASK-class migration, schema, CI, cutover, landing and release actions retain their normal exact-SHA checks and separately required authorization.

The accepted technical baseline and requested delivery refinement complete the written planning package. No implementation task is marked complete, no runtime measurement is invented, and no migration or release is performed by this record.
