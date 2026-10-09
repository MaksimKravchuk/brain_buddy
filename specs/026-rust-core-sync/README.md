# Brain Buddy Rust core and custom synchronization

Specification accepted October 9, 2026. The owner approved the prepared scope, design, governance proposal and residual risks after six-lens review and correction closure. The [acceptance record](approval.md) preserves that decision and the [approved review status](evidence/026-native-20261009-1/accepted-summary.json) for its original digest. The owner subsequently requested the 64-PR delivery amendment: separate tasks, an explicit graph, concurrent ready workers and an 800-line full-diff cap. Earlier pending labels in unchanged baseline documents are historical. Complex slice sizing remains mandatory before implementation. This describes an accepted specification for future implementation, not a completed migration.

The [historical ChatGPT Pages copy](https://chatgpt.com/space/page_1c47ad1be37c819187af9b4e5707d966) reflects the earlier proposal and has not been updated by this repository-only completion. These versioned files are authoritative.

Rust contains shared task rules and the client runtime for local work. Native interfaces remain in each platform's language. The server accepts commands, synchronizes accepted changes, and runs background jobs. The first stage retains FastAPI with Rust calls through PyO3; a complete server rewrite is unnecessary.

Start with the requirements and technical plan. The protocol is a separate document because lost responses, conflicts, and recovery need precise rules that cannot fit into one diagram.

| Document | Contents |
| --- | --- |
| [spec.md](spec.md) | 5 user stories, 26 requirements, 8 acceptance criteria, and first-stage scope |
| [plan.md](plan.md) | Diagrams, Rust/FFI, native platforms, server, AI, jobs, migration, and verification |
| [contracts/sync-v1.md](contracts/sync-v1.md) | Commands, receipts, dependencies, conflicts, snapshot/delta, retention, restore, and versions |
| [design.md](design.md) | Sync status, conflict, recovery, and AI consent states |
| [design/sync-states.html](design/sync-states.html) | Self-contained mobile and desktop mockups |
| [tasks.md](tasks.md) | 64 atomic PRs: tasks, requirements, paths, product/full-diff budgets, dependencies and evidence |
| [delivery-graph.md](delivery-graph.md) | All 64 PRs and 94 dependency edges; start ready independent work immediately |
| [adr-draft.md](adr-draft.md) | Narrow amendments needed to existing architecture decisions |
| [research.md](research.md) | Current architecture and code references |
| [data-model.md](data-model.md) | Domain projections, durable state, identity, transitions and retention |
| [contracts/command-catalog.md](contracts/command-catalog.md) | Supported commands, legacy adapters and every writer |
| [contracts/runtime-ffi.md](contracts/runtime-ffi.md) | Pure core, Swift/Python boundaries, lifecycle, errors and AI port |
| [quickstart.md](quickstart.md) | Reused checks, acceptance scenarios, measurement and cutover drill |
| [approval.md](approval.md) | Concrete owner decisions and true approval status |
| [verification.md](verification.md) | Document checks, formal review and cross-artifact analysis |

New Android, Windows, and Linux applications become consumers of the same runtime. Sharing, delegation, E2EE, a new recurrence feature, and moving CRT into task sync are outside the first stage. The private account scope supports future development without predefining collaboration semantics that have not yet been agreed.
