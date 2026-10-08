# Проверка спецификации

Дата: 2026-10-08. Проверяется комплект документов, не реализация Rust или нового sync. Product code, данные, credentials, CI configuration и production не изменялись.

## Результаты

| Проверка | Результат |
| --- | --- |
| Baseline `python3 scripts/check_spec_kit_specs.py` перед изменениями | PASS |
| Резервирование feature number | 026 свободен среди всех доступных локальных git refs; создана отдельная ветка/worktree |
| `make check-specs` | PASS: 247 unit tests в существующих validator suites, 246 прошли и 1 штатно skipped; artifact/manifests/integrity и существующие requirement coverage checks прошли |
| Shared design reference tests | PASS, 6 tests; не является runtime-проверкой новых экранов |
| Design vocabulary и HTML structure | PASS после удаления лишнего reorder и согласования sign-out/import; 8 screen IDs, 90 enumerated states, no external resources |
| Внутренние Markdown links и FR/SC IDs | Проверены в финальном комплекте |
| `git diff --check` | PASS |
| Browser rendering | Попытка Chromium/Playwright не удалась: sandbox запретил `setsockopt` при запуске crashpad. Геометрия на iPhone, screenshot и runtime accessibility не объявлены проверенными |
| Backend/native/new-sync product tests | N/A для spec-only результата; критерии будущей реализации записаны в plan и contract |

`make verify-all`, exact-SHA product CI, release/production smoke не запускались: эта работа не реализует и не выпускает описанный продукт. Формальный Spec Kit planning review, human design sign-off, ADR acceptance и PR-slice approval ещё не выполнены и не подменены зелёным validator.

## Независимая проверка

Read-only аудит текущего кода выполнен отдельным агентом. Учтены: уже общий Mac/iPhone kit; JSON store и cross-process lock; local/server ID mapping; 24-hour legacy task receipts; Review clocks без revision bump; archive semantics; отдельные Identity/CRT authorities.

Отдельный adversarial review протокола нашёл три существенных дефекта. Все исправлены; targeted reread подтвердил устранение:

1. ACK мог менять confirmed base через пропущенную multi-record transaction. Теперь базу изменяют только последовательный feed или согласованный snapshot; ACK оставляет `accepted_awaiting_feed` до доказанного включения.
2. Поздний ответ до restore мог примениться после reset под той же сессией. Каждый ответ теперь ограничен workspace/session/local-sync/server generations.
3. Старый backup мог вернуть удалённые данные или отозванную сессию. Restore закрыт до применения последующих purge/revocation решений из отдельного control ledger; недоказанная сверка не открывает доступ.

Это содержательный review текста, не официальный пятиаспектный approval и не доказательство корректности ещё не написанного кода.

## Доставка для чтения

Основная читательская версия: [спецификация в ChatGPT Pages](https://chatgpt.com/space/page_1c47ad1be37c819187af9b4e5707d966). Page создана приватной, без Space/parent; широкое sharing не включалось. Сохранённый текст прочитан обратно, проверены native headings, требования и схемы. Предпросмотр самой Page на iPhone недоступен; HTML mock отдельно также не имеет успешной runtime-проверки.
