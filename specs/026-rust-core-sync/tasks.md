# Tasks: общее Rust-ядро и собственная синхронизация

Статус: draft последовательности, не разрешение исполнять продуктовые изменения. Пользователь запросил спецификацию. До реализации подробные PR-срезы должны получить отдельную согласованную карту `brainbuddy-pr-slices/v2`; ниже этапы, а не заявления, что весь этап поместится в один PR. У каждого будущего среза будут реальные пути, бюджет ≤ 400 product lines / 12 files и собственная проверка.

## Phase 1 — Зафиксировать контракт

- [ ] T001 Уточнить и принять `specs/026-rust-core-sync/design.md`, `adr-draft.md` и proposed defaults контракта; записать реальные решения, не присваивать human sign-off автоматически.
- [ ] T002 Провести mandatory planning review по ADR-0011 с актуальными `spec.md`, `design.md`, `plan.md`, `contracts/sync-v1.md`; исправить подтверждённые дефекты и получить допустимый verdict.
- [ ] T003 Выпустить schema/OpenAPI, mapping всех текущих writers/команд и PR-slice map в `specs/026-rust-core-sync/contracts/` и этом файле; проверить полноту FR-001…FR-026 и провести analyze. До frozen contracts coding не начинается.

## Phase 2 — US1 и US4, один core на Apple и сервере

- [ ] T004 Сверить существующие normalization, formulation и archive golden vectors в `ios/BrainBuddyKit/Tests/` и `backend/tests/`; зафиксировать parity oracle, целевые устройства и нагрузку для SC-001/003.
- [ ] T005 Пройти вертикальный Rust/Swift/Python срез в будущих `rust/crates/bb-domain/`, `rust/bindings/swift/`, `rust/bindings/python/`, сохранив один writer; проверить FFI lifecycle/error/packaging и требования `ios/AGENTS.md`.
- [ ] T006 По группам правил перенести reducer, Smart Add, normalization, queries и Review из `BrainBuddyCore` и `backend/app/modules/tasks/` в core; удалить заменённую domain authority после parity, не оставляя второй live implementation.

## Phase 3 — US1, US2 и US3, надёжный sync

- [ ] T007 Добавить устойчивые receipt/feed transactions и compatibility adapter в `backend/app/modules/tasks/` вместе с недостающими тестами crash/dedup/ordering; включить все writers через `backend/app/container.py` и application ports.
- [ ] T008 Реализовать snapshot/delta/capabilities и version/epoch handling в будущем `backend/app/modules/tasks/sync/`; доказать commit-order, expiry, account isolation и current auth recheck.
- [ ] T009 Реализовать SQLite/outbox/replay runtime в `rust/crates/bb-client/` и JSON import через `BrainBuddyPersistence`; проверить multiprocess, full disk, old uncertain outbox, accountless и linked identity mapping.
- [ ] T010 Подключить runtime через `BrainBuddyWorkspace` и существующие iOS/macOS sync surfaces; реализовать согласованные M-/D- состояния из `design.md` и проверить conflict/reset/sign-out на устройствах.
- [ ] T011 Провести fault/convergence/compatibility suite и pilot rollout существующих Apple-клиентов с current backend, до отдельной server DB миграции; сохранить exact-SHA и recovery evidence.

## Phase 4 — US4 и US5, серверные обязанности и AI adapters

- [ ] T012 По inventory `backend/app/main.py` перенести существующие задания в durable job adapter с leases/fencing; отключать старого scheduler владельца только после проверки equivalence и safe retry.
- [ ] T013 Подключить общую AI policy/proposal validation к существующим `backend/app/workflows/voice_brain_dump/` и нативным adapters; проверить consent denial, cancellation и недопустимые предложения, не меняя ADR-0002.
- [ ] T014 Подготовить отдельный stopped-writer перенос Tasks aggregate/receipts/feed/jobs на PostgreSQL; добавить миграцию в `backend/app/modules/tasks/`, обновить backup/export/purge/recovery adapters; получить требуемый допуск этой миграции.

## Phase 5 — Новые платформы

- [ ] T015 Зафиксировать отдельные platform slices и реализовать Android consumer `rust/bindings/kotlin/` плюс нативный shell с US1–US3; переиспользовать shared rules, проверить реальное устройство и offline recovery.
- [ ] T016 После Android portability gate согласовать и выполнить Windows C ABI consumer и Linux GTK shell; их новые product paths и packaging фиксируются в platform slice до coding.

## Зависимости и приёмка

T001–T003 → T004–T006 → T007–T011. T012/T013 могут готовиться после frozen command contract, но не обходят изменения domain authority; T014 выполняется отдельным migration rollout. T015/T016 используют уже принятый protocol/runtime. Внутри этапов параллельная работа допустима только по disjoint approved slices.

Критерии — US1–US5 и SC-001…SC-008 из `spec.md`; конкретные проверки указаны в plan §8 и contract §10. Product acceptance, traceability и report создаются по фактической реализации. Текущая spec-only проверка не закрывает ни один checkbox реализации.
