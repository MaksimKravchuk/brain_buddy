# Hosted audit evidence

These are actual read-only content audits after the canonical CLI campaign failed on proxy CONNECT 403. They do not replace the canonical gate, assert independent providers, or approve implementation. The [manifest](manifest.json) records source/corrected digests, actual hosted model selection and report hashes. All six initial reports review source `a060ddd531753b3ed8bcd339ea8cc8a907ac6d7c`; their original verdicts are preserved byte-for-byte.

| Lens | Original report | Verdict |
| --- | --- | --- |
| Requirements | [Report](requirements-consistency.json) | changes-required |
| Architecture | [Report](architecture-consistency.json) | changes-required |
| Testability | [Report](testability-evidence.json) | pass, one advisory |
| Privacy/security | [Report](privacy-consent-security.json) | changes-required |
| UX/accessibility | [Report](ux-accessibility-mobile.json) | changes-required |
| Adversarial | [Report](adversarial-high-risk.json) | changes-required |

Eight important observations deduplicate to six findings: receipt bindings, SSE ownership, owner-safe errors, Apple AI surface ownership, conflict dependent-action decisions, and AI cancellation/interruption states. [Verification](../../verification.md#hosted-content-audit-and-finding-closure--october-9) records the fixes; the nonexistent Swift filters were also corrected.

## Targeted closure

Four original reviewers reread only their fixes at corrected core digest `5fdcc85f0496ce9dc68716d0cfd2442a065b446bd80143df180859fff354ea99`. These are bounded closure checks, not another full review campaign:

- [Requirements closure](requirements-closure.json): bindings, SSE and Apple AI ownership resolved.
- [Architecture closure](architecture-closure.json): SSE contract and complete server/client dependency path resolved.
- [Privacy closure](privacy-closure.json): foreign/unknown-resource response semantics resolved.
- [UX closure](ux-closure.json): dependent-action choices and AI cancellation/interruption resolved.

All distinct important findings are closed in the text. Planned runtime checks, sizing evidence, rendering and human approvals remain pending. The canonical campaigns remain `escalated` with zero completed CLI reviews; their history and the two-campaign cap are preserved in [verification.md](../../verification.md#requested-formal-review--october-9-attempt-2). No review JSON here is copied into a canonical run or stamped as an admissible oracle. Earlier line references belong to the corresponding recorded digest, not necessarily to the latest document lines.
