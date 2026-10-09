# Current architecture and decision rationale

Audit of local checkout `3b5967f5bc01abae43cb0fc143d8c038cd5c8b0d`, 2026-10-08. No new benchmarks were measured. The owner selected Rust + custom sync after comparing architectures; this table describes the current code rather than the proposed target.

| Fact | Source |
| --- | --- |
| iOS and Mac already share a Swift core/store/sync | `macos/Package.swift:5`, `docs/native-macos-app.md:3` |
| The reducer applies interactive commands and replay, including review | `ios/BrainBuddyKit/Sources/BrainBuddyCore/Reducer.swift:3` |
| StoreDocument JSON contains the base, pending operations, issues, linked account, and local review | `ios/BrainBuddyKit/Sources/BrainBuddyCore/Outbox.swift:137` |
| Storage uses a cross-process lock, flush, atomic rename, and unknown-schema protection | `ios/BrainBuddyKit/Sources/BrainBuddyPersistence/FileDocumentStore.swift:4` |
| Push is sequential and pull is complete; comments/subtasks are hydrated separately | `ios/BrainBuddyKit/Sources/BrainBuddySync/SyncEngine+Push.swift:15`, `SyncEngine+Pull.swift:21` |
| Ordinary native local IDs differ from server IDs | `ios/BrainBuddyKit/Sources/BrainBuddyCore/Identifiers.swift:3` |
| Tasks and native-task review use one SQLite transaction | `backend/app/modules/tasks/repository.py:64`, ADR-0027 §1 |
| Task receipts normally last 24 hours; Capture commit child identities have a durable exception | `backend/app/modules/tasks/repository.py:40`, `:623` |
| Normalization requires NFKC, Python whitespace, and full case folding | `ios/BrainBuddyKit/Sources/BrainBuddyCore/NameNormalizer.swift:3` |
| Project archive preserves membership and historical markers | `backend/app/modules/tasks/service.py:1321`, ADR-0020, spec 021 |
| Review clock bookkeeping does not always increment Task revision; offline decisions have special yield semantics | ADR-0027 §2–3 |
| Identity has its own authority in auth.sqlite3 | ADR-0028 |
| CRT files and the receipt DB have their own reconciliation and 30-day replay | ADR-0026 |
| Current background duties use threads/startup sweeps | `backend/app/main.py:199`, `:268` |
| Rust currently powers the HTTP CLI, not a shared task library | `cli/Cargo.toml:1`, spec 024 non-goals |

Documentation has historical inconsistencies: the earlier iOS archive-clearing description in `docs/native-ios-app.md` must not override newer code, spec 021, and ADR-0020. Parity is checked against actual code, accepted ADRs, and golden traces together.

Useful existing oracles include formulation JSON vectors and review trace replays, project-archive golden traces, reducer/replay/sync race tests in `ios/BrainBuddyKit/Tests/`, and backend task/review tests. New property/fault tests address specific missing protocol and migration guarantees.

UniFFI/Swift/Kotlin, PyO3, C ABI, and GTK4 are proposed integration choices. Bounded build/spike checks are required before locking versions; this specification does not claim that every target toolchain already builds the shared core or that a particular local model supports Russian on every device.
