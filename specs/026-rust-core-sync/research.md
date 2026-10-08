# Исходная архитектура и основания решения

Аудит локального checkout `3b5967f5bc01abae43cb0fc143d8c038cd5c8b0d`, 2026-10-08. Новых benchmark измерений нет. Выбор Rust + own sync сделан владельцем после сравнения архитектур; таблица ниже описывает текущий код, а не proposed target.

| Факт | Источник |
| --- | --- |
| iOS и Mac уже используют общий Swift core/store/sync | `macos/Package.swift:5`, `docs/native-macos-app.md:3` |
| Reducer применяет interactive команды и replay, включая review | `ios/BrainBuddyKit/Sources/BrainBuddyCore/Reducer.swift:3` |
| StoreDocument JSON содержит base, pending, issues, linked account и local review | `ios/BrainBuddyKit/Sources/BrainBuddyCore/Outbox.swift:137` |
| Хранилище имеет cross-process lock, flush, atomic rename и защиту неизвестной schema | `ios/BrainBuddyKit/Sources/BrainBuddyPersistence/FileDocumentStore.swift:4` |
| Push последовательный, pull полный; comments/subtasks гидратируются отдельно | `ios/BrainBuddyKit/Sources/BrainBuddySync/SyncEngine+Push.swift:15`, `SyncEngine+Pull.swift:21` |
| Native ordinary local IDs отличаются от server IDs | `ios/BrainBuddyKit/Sources/BrainBuddyCore/Identifiers.swift:3` |
| Tasks и native-task review используют одну SQLite transaction | `backend/app/modules/tasks/repository.py:64`, ADR-0027 §1 |
| Task receipts обычно 24 часа; Capture commit child identities имеют durable исключение | `backend/app/modules/tasks/repository.py:40`, `:623` |
| Normalization требует NFKC, Python whitespace и полного case folding | `ios/BrainBuddyKit/Sources/BrainBuddyCore/NameNormalizer.swift:3` |
| Архив проекта сохраняет membership и исторические markers | `backend/app/modules/tasks/service.py:1321`, ADR-0020, spec 021 |
| Review clock bookkeeping не всегда увеличивает Task revision; offline decision имеет special yield | ADR-0027 §2–3 |
| Identity — отдельная authority в auth.sqlite3 | ADR-0028 |
| CRT files + receipt DB имеют собственный reconciliation и 30-day replay | ADR-0026 |
| Текущие background обязанности исполняются threads/startup sweeps | `backend/app/main.py:199`, `:268` |
| Rust сейчас используется HTTP CLI, не общей task library | `cli/Cargo.toml:1`, spec 024 non-goals |

У документации есть исторические расхождения: прежнее описание iOS archive clearing в `docs/native-ios-app.md` не должно переопределять более новый код, spec 021 и ADR-0020. Для parity проверяются фактический код, accepted ADR и golden traces вместе.

Полезные существующие oracles: formulation JSON vectors и review trace replays, project-archive golden traces, reducer/replay/sync race tests в `ios/BrainBuddyKit/Tests/`, backend task/review tests. Новые property/fault tests добавляются для конкретных отсутствующих гарантий protocol и migration.

UniFFI/Swift/Kotlin, PyO3, C ABI и GTK4 — предложенные integration choices. До выбора lockfile версии нужны bounded build/spike проверки; эта спецификация не утверждает, что все target toolchains уже собирают общее ядро или что конкретная локальная модель подходит русскому языку на всех устройствах.
