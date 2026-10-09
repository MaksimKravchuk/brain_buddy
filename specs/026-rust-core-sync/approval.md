# Owner acceptance of specification 026

**Status: accepted as the specification baseline, 2026-10-09.** MaksimKravchuk explicitly answered “Yes” to approval of the prepared package and residual risks of custom sync, Rust/FFI and migration. The question retained mandatory measurements for complex slices before implementation. The [source record](evidence/026-native-20261009-1/owner-acceptance.json) preserves the exact reply and scope; the [human sign-off](evidence/026-native-20261009-1/human-signoff.json) is bound to the reviewed run and content.

- Approved source commit: `962a7fa8372ac48d9af1edc4e2130f16afb896da`.
- Review run: `026-native-20261009-1`; six of six lenses completed, four distinct technical findings corrected and confirmed closed, all 12 protocol-quality criteria satisfied.
- Approved core artifact digest: `968a327f01a50fb7e14ef84b1d73ab0731efbdd227d75fdeedbad5a394045623`.
- Current planning verdict: **approved**, recorded in the [accepted summary](evidence/026-native-20261009-1/accepted-summary.json).

| Decision | Accepted baseline and review material | Recorded disposition |
| --- | --- | --- |
| Product scope and acceptance | Existing Apple/server path and compatible web/CLI/MCP/voice/Review integrations first; PostgreSQL after the pilot; later platform shells need separate specifications. SC-001–SC-008 use the hardware, workloads and RPO/RTO in [quickstart.md](quickstart.md). | Specification scope and written criteria accepted; product results remain future evidence |
| Design | [Eight screens](design/sync-states.html), [110 combinations](design.md), explicit two-version conflicts, retained local text, quiet status, reset preserving work, and the existing Cancel/export/confirmed-removal account-switch choice. | Design baseline accepted; rendering and native accessibility remain implementation checks |
| Governance and privacy | [Amendment proposal](adr-draft.md): one shared domain authority, narrow audited Rust binding allowance, command IDs separate from correlation IDs, content-free dedup metadata until purge, source TTLs and bounded restore/purge controls. Existing ADR-0002/0020/0026/0028 authorities remain. | Proposal accepted for enactment in PR-01 before conflicting implementation; existing accepted policies are not changed by this record |
| Implementation boundaries | The 60-slice map in [tasks.md](tasks.md), with its paths, dependencies, budgets, checks and outcomes. Rust/FFI PR-03/04/05, runtime/SQLite PR-34 and AI PR-49/59/60 retain the stated measurement prerequisites, including Cargo.lock. | Delivery baseline accepted subject to measured sizing; unmeasured caps are not certified as feasible or unconditionally approved |
| High-risk planning review | Original six-lens reports, targeted closures, provenance and residual risks in [verification.md](verification.md). | Named-human residual-risk acceptance recorded; planning gate approved |

## Frozen inputs and status precedence

The reviewed core documents, HTML and ADR proposal remain byte-for-byte unchanged so the accepted digest and independent evidence still identify the same content. Their earlier “pending”, “proposed” and approval-request labels describe the review snapshot; this acceptance record supersedes those human-decision statuses. The machine-readable slice map remains `proposed` because empirical boundary approval is still conditional. Requirements, technical contracts, numeric budgets, rollout stages and scope are unchanged.

The original review reports, closures, manifests and pre-acceptance summary remain historical evidence. In particular, `corrected-artifacts.json` records the owner packet as it was presented at the approved source commit; its old approval.md hash is not a hash of this subsequent decision record. The new accepted summary supersedes only the missing-human-sign-off escalation, without converting the failed CLI attempts into successful runs or altering reviewer verdicts.

## Conditions carried into implementation

Measure the complex slices before approving their execution boundaries, and revise any boundary that cannot meet its cap. Enact the approved Constitution/ADR/Apple dependency and retention amendments through the governance slice with preserved history. Complete the planned implementation, runtime, design and acceptance evidence at the relevant slice and pilot gates. ASK-class migration, schema, CI, cutover, landing and release actions retain their normal exact-SHA checks and separately required authorization.

This acceptance completes specification planning. No implementation task is marked complete, no runtime measurement is invented, and no migration or release is performed by this record.
