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


## Completion decisions, 2026-10-09

Rechecked against merged main `c16daecd13247e35fea280bd9322c8a4b09dabb1`. This pass makes the existing proposal implementable; it does not claim benchmark or toolchain proof.

| Decision | Rationale | Alternative and reason not selected |
| --- | --- | --- |
| Retain accepted public DTOs with enumerated sync projection extensions | Complete offline Review needs captured queues/history links and task clock state omitted by ordinary HTTP responses; see data-model.md | Raw storage snapshots would expose private replay/Undo bookkeeping |
| Stream oversized transaction bodies into staging and apply atomically | Existing bulk/archive/tag operations cannot safely gain a 500-record product limit | Silent chunked application violates accepted atomic effects; an unbounded response cannot guarantee bounded memory |
| Keep per-entity ID wire shapes and explicit alias bindings | Existing Review validation and Smart Add name reuse must remain interoperable | A universal UUID conversion breaks legacy references and can duplicate normalized projects/Tags |
| SSE hint plus active 60-second polling | Foreground convergence has a concrete transport and a loss-tolerant fallback | APNs would add delivery/signing work without proving background scheduling promises |
| Fix reference devices and deterministic workload in quickstart | Makes SC-003/004 falsifiable before code; no performance is claimed | Choosing a fast machine after implementation could hide a regression |
| Seven-day maximum protected restore horizon; remove affected backups before purge completes | Restores cannot resurrect deleted owners or extend source TTLs | Indefinite owner-linked control metadata would contradict the accepted purge policy |
| First-stage Apple/server, separate later platform specifications | Reuses current native surfaces and proves portability boundaries without inventing new application UX | Simultaneous five-client delivery would add unaccepted product scope |

Binding/library versions remain engineering choices of the explicit build-proof slice, pinned before consumers depend on them. The portable FFI behavior, supported existing target matrix and failure semantics are frozen now; inability to build them rejects that slice instead of silently changing the contract.
