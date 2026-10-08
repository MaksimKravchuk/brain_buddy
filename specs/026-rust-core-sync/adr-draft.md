# Proposed ADR: общее Rust-ядро и task sync

Статус: Proposed, 2026-10-08. Номер accepted ADR пока не резервируется. Выбор направления Rust + own sync подтверждён пользователем; конкретный протокол, UX и миграционные границы здесь предлагаются для принятия.

## Решение

Нормативные правила Tasks и native-task Review реализуются в одной чистой Rust-библиотеке. Нативные клиенты используют Rust client runtime с SQLite и устойчивой очередью; backend вызывает domain core через PyO3 и сохраняет действующую Identity authority. Новый task sync передаёт команды, receipts и атомарные изменения. Целевой task store — PostgreSQL, с отдельной управляемой миграцией. Modular monolith сохраняется.

## Какие решения изменяются

ADR-0001 меняется только в выборе реализации Tasks rules и его server persistence. Владение данными, application ports и границы Capture/Organize/Tasks/Thinking/Execution/Identity остаются. ADR-0027 меняется только в технологии хранения и реализации shared rules; его auto-park/yield/review семантика и атомарность task+review остаются обязательными.

Текущая инструкция `ios/AGENTS.md` «No third-party dependencies» должна получить узкое разрешение на audited/pinned Rust bindings и нужный runtime. Только после принятия этого изменения можно менять продуктовую dependency policy; произвольные Apple packages не разрешаются.

Spec 021 last-push-wins для текущего sync заменяется explicit conflict при новом protocol cohort. Legacy clients сохраняют свой задокументированный контракт в compatibility window; их writes не становятся невидимыми для новых клиентов. Новый UX должен быть явно принят, а не представлен как бесшовная внутренняя оптимизация.

ADR-0026 CRT protocol и ADR-0028 Identity authority не отменяются. Их базы, receipts, exports и recovery остаются в их модулях. Переезд Tasks не даёт оснований объединять все системы хранения в одну транзакцию.

## Почему не другие варианты

Серверные правила без общего client runtime не обеспечат одинаковые offline-действия. Managed sync сократил бы часть транспорта, но пользователь выбрал собственный, поэтому мы берём на себя snapshot, ordering, retention, dedup и recovery. Универсальный CRDT не решает авторизацию, подтверждение AI и внешние эффекты; для текущих задач достаточно command protocol и явных конфликтов. Перепись всего backend на Rust увеличит миграционную поверхность без обязательной выгоды для единых правил.

## Цена решения

Команда поддерживает FFI/build matrix и собственный sync protocol. Общие rules тестируются однажды, но платформенные границы, БД, сеть и разные модели AI всё равно требуют своих проверок. Консервативные конфликты иногда требуют лишнего пользовательского выбора. Защита от дублей и восстановление старой uncertainty важнее гладкого happy-path demo.

## Условия принятия

Нужны review конкретного [контракта](contracts/sync-v1.md), UX sign-off [design.md](design.md), подтверждённые limits и точный migration/rollback boundary. Этот draft не выдаёт approval на удаление данных, изменение production schema или автоматический выпуск.
