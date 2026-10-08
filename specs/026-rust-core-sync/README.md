# Brain Buddy Rust core and custom synchronization

Specification dated October 8, 2026. The user selected the architectural direction; the concrete protocol and UX are proposals for review. This describes a future implementation, not a completed migration.

[Read in ChatGPT Pages](https://chatgpt.com/space/page_1c47ad1be37c819187af9b4e5707d966) for a mobile-accessible document with diagrams and a collapsible technical protocol.

Rust contains shared task rules and the client runtime for local work. Native interfaces remain in each platform's language. The server accepts commands, synchronizes accepted changes, and runs background jobs. The first stage retains FastAPI with Rust calls through PyO3; a complete server rewrite is unnecessary.

Start with the requirements and technical plan. The protocol is a separate document because lost responses, conflicts, and recovery need precise rules that cannot fit into one diagram.

| Document | Contents |
| --- | --- |
| [spec.md](spec.md) | 5 user stories, 26 requirements, 8 acceptance criteria, and first-stage scope |
| [plan.md](plan.md) | Diagrams, Rust/FFI, native platforms, server, AI, jobs, migration, and verification |
| [contracts/sync-v1.md](contracts/sync-v1.md) | Commands, receipts, dependencies, conflicts, snapshot/delta, retention, restore, and versions |
| [design.md](design.md) | Sync status, conflict, recovery, and AI consent states |
| [design/sync-states.html](design/sync-states.html) | Self-contained mobile and desktop mockups |
| [tasks.md](tasks.md) | Future stages; detailed PR slices must be defined before implementation |
| [adr-draft.md](adr-draft.md) | Narrow amendments needed to existing architecture decisions |
| [research.md](research.md) | Current architecture and code references |
| [verification.md](verification.md) | Document checks and fixes from independent review |

New Android, Windows, and Linux applications become consumers of the same runtime. Sharing, delegation, E2EE, a new recurrence feature, and moving CRT into task sync are outside the first stage. The private account scope supports future development without predefining collaboration semantics that have not yet been agreed.
