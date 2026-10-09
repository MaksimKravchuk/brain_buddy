# Owner decisions for specification 026

Prepared 2026-10-09. This is the concrete approval surface for the completed proposal, not a record of approval. The existing owner decision selects Rust and custom sync; the current request authorizes finishing the specification. Neither statement is a migration, design, or release sign-off.

| Decision | Proposed baseline and review material | Current status |
| --- | --- | --- |
| Product scope and acceptance | First deliver the existing Apple/server path and compatible web/CLI/MCP/voice/Review integrations; PostgreSQL follows the pilot. New platform shells require later specifications. Adopt SC-001–SC-008 with the hardware/workloads and RPO/RTO in [quickstart.md](quickstart.md). | Awaiting owner acceptance |
| Design | [Eight screens](design/sync-states.html) and [90 screen-state combinations](design.md): explicit two-version conflicts; local text retained; quiet existing status timings; reset preserves work; account switching keeps the existing Cancel/export/confirmed-removal choice. No new Task-delete/reorder interface. | Awaiting explicit design sign-off |
| Governance and privacy | [ADR proposal](adr-draft.md): one shared domain authority, narrow audited Rust binding allowance, dedicated command IDs separate from correlation IDs, content-free dedup metadata until purge, source content TTLs preserved, bounded restore/purge controls. Existing ADR-0002/0020/0026/0028 authority remains. | Awaiting acceptance; accepted governance files unchanged |
| Implementation boundaries | Proposed `brainbuddy-pr-slices/v2` map in [tasks.md](tasks.md), including each task, write path, requirement, dependency, budget, check, and outcome. Approval accepts boundaries; it does not claim any slice is built. | Awaiting owner approval |
| High-risk planning review | The mandatory campaign must cover the current artifact digest with all five lenses and the adversarial lens. A named human accepts residual risk only after reading the actual findings and recorded provenance. See [verification.md](verification.md). | No human sign-off recorded |

An owner may accept the proposed scope/design/governance/boundaries together, or name a specific change. Record their actual response with the artifact digest and campaign ID; a merge of the earlier draft PR does not supply missing design or risk acceptance. Amendments to accepted governance are applied only in the authorized governance slice, preserving history and dependent documentation.

The author must finish technical corrections, run structural checks, and present the actual review result before requesting this acceptance. Even after approval, ASK-class schema/persistence/CI changes require their normal exact-SHA review, required CI, and separately recorded landing/cutover authorization. This specification requests no deployment.
