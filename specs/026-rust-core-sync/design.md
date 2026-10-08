# Design: Rust core and custom sync

**Feature**: `specs/026-rust-core-sync/`
**Spec**: `spec.md`; этот дизайн — черновик к требованиям FR-001–FR-026, не утверждение завершённой clarification/design стадии.
**Screens**: [design/sync-states.html](design/sync-states.html), один автономный статический HTML без внешних ресурсов.
**Human sign-off**: **pending**. Производственная реализация не начата; следующий архитектурный этап требует явного утверждения дизайна по `.specify/agent-commands/speckit-design/SKILL.md`.

## Applicability

Согласованное направление: общий Rust core и собственная синхронизация. iOS и macOS уже используют `BrainBuddyKit`: это замена внутренней реализации с сохранением существующего поведения, а не создание второго независимого task engine. Здесь проектируются только состояния существующей строки синхронизации, Sync settings / popover, существующей карточки решения и AI settings. Новый task workspace, навигация, пятая GTD list, автономные агенты и новый onboarding не входят в дизайн.

Объяснения на русском; весь текст внутри продукта на английском. D- обозначает desktop/macOS, M- — iPhone. Web сохраняет существующие online workflows (FR-024); desktop mock не вводит offline web или новую web sync панель. AI consent применяется и к существующему web flow, без новой страницы.

## Screen inventory

| id | surface | screen | purpose | FR refs |
|---|---|---|---|---|
| M-01 | iPhone, существующая строка и Settings › Sync | Sync status | Работа локально, очередь, диагностика без прерывания capture | FR-001, FR-003, FR-004, FR-005, FR-010, FR-011, FR-012, FR-023, FR-026 |
| D-01 | Mac, существующая строка и popover | Sync status | Та же семантика, полное время последней синхронизации и safe reference ID | FR-001, FR-003, FR-004, FR-005, FR-010, FR-011, FR-012, FR-023, FR-026 |
| M-02 | iPhone, Sync issues detail | Resolve conflict | Сохранить пользовательскую правку; явно выбрать результат | FR-007, FR-008 |
| D-02 | Mac, detail sheet из Sync issues | Resolve conflict | Сравнить конфликтующие версии, подтвердить решение | FR-007, FR-008 |
| M-03 | iPhone, существующие Sync settings / sheets | Recover sync | Resume/reset, upgrade, migration и смена аккаунта без потери pending edits | FR-010, FR-011, FR-012, FR-013, FR-022 |
| D-03 | Mac, существующий popover / sheets | Recover sync | То же; файл миграции и безопасное восстановление | FR-010, FR-011, FR-012, FR-013, FR-022 |
| M-04 | iPhone, существующая review card / AI settings | AI choice, consent and proposal | On-device policy, отдельное cloud согласие, только explicit apply | FR-016, FR-018, FR-019, FR-020, FR-022 |
| D-04 | Mac, существующая review card / AI settings | AI choice, consent and proposal | Та же authority/privacy последовательность; existing web consent эквивалентен | FR-016, FR-018, FR-019, FR-020, FR-022, FR-024 |

Все восемь экранов представлены в HTML. Парные таблицы ниже задают одинаковые состояния для **каждого** указанного ID: 45 shared rows, 90 screen-state combinations, включая явно обоснованные N/A states. Ключ состояния образуется из screen ID и suffix, например `M-02.04`. ID после утверждения не перенумеровывать. HTML показывает ключевые композиции и статические варианты; это не рабочий sync simulator.

## State inventory

### M-01 / D-01 — Sync status (11 states per screen)

Не менять утверждённые тихие строки и timings из `specs/021-mac-sync/design.md`: индикатор после 1 s, минимум 0.5 s; online waiting suffix после 10 s; persistent transport failure после 60 s. Моментальная auth/version ошибка не маскируется этим ожиданием. Sync никогда не блокирует разрешённую локальную команду. Приоритет: неподдерживаемая версия → session ended → issues → persistent failure → offline → waiting → synced. В details доступны все причины.

| suffix / state | trigger | visible result and English copy | FR refs |
|---|---|---|---|
| .01 default | очередь пуста, sync завершён | Quiet row: “Synced just now”; details: “Last synced today at 14:31” | FR-004, FR-023 |
| .02 loading | first upload/pull или долгий sync | “Not synced yet” до первого полного sync; затем прежняя строка + reserved indicator “Syncing”; tasks остаются доступны | FR-001, FR-004, FR-026 |
| .03 empty, first run | нет аккаунта, tasks могут быть пусты или существовать | “On this iPhone · Sign in to sync” / “On this Mac · Sign in to sync”; sign-in не обязателен | FR-001, FR-003 |
| .04 empty, filtered | список отфильтрован до нуля | Статус не меняется; existing list empty state. Sync details не имеют фильтра | FR-001, FR-023 |
| .05 offline / interrupted | сеть отсутствует или relaunch с pending | “Offline · 3 changes waiting”; “Your changes are saved on this device.”; reconnect/resume автоматически | FR-001, FR-010 |
| .06 waiting | подтверждение ещё не получено | “Synced 3 min ago · 3 changes waiting”; retry/replay не увеличивает число локальных команд | FR-005, FR-023 |
| .07 error | persistent timeout/server failure | “Couldn't sync · Retry”; details: причина, “Reference ID: demo-026-sync-01”, Copy reference ID | FR-005, FR-023 |
| .08 partial failure | независимые transaction groups synced; одна не принята | “1 change couldn't sync”; “Other changes synced. This change is saved here.”; Open sync issues | FR-006, FR-007, FR-023 |
| .09 authentication | сервер отказал в авторизации | “Sign in again to sync”; account identity и “Your waiting changes stay with this account.”; локальные правки продолжаются | FR-011 |
| .10 unsupported version | protocol/store version неизвестна | “Update needed to sync”; Open recovery. Не продолжать несовместимый обмен; store read-only только если format невозможно безопасно открыть | FR-012 |
| .11 recovery complete | replay/pull/reset успешно закончены | “Synced just now”; без success modal, без повторного Task/receipt | FR-004, FR-005, FR-010 |

### M-02 / D-02 — Resolve conflict (9 states per screen)

| suffix / state | trigger | visible result and English copy | FR refs |
|---|---|---|---|
| .01 default | concurrent edit одного поля не объединён автоматически | “Choose a title”; варианты “Your saved edit” и “Current account version”; radio choice без default; “Apply choice” disabled до выбора | FR-007 |
| .02 loading | resolution пишется атомарно | “Saving your choice…”; повторная отправка не создаёт второй resolution; Back не стирает конфликт | FR-005, FR-006, FR-007 |
| .03 empty, first run | конфликтов никогда не было | Existing issues view: “No sync issues” | FR-007 |
| .04 empty, filtered | N/A: экран не вводит фильтр | Нет нового empty affordance | FR-007 |
| .05 error | выбранный результат не записался локально | “Your choice wasn't saved. Try again.”; исходные варианты и выбор сохранены | FR-001, FR-007, FR-023 |
| .06 partial failure | другие задачи synced, эта осталась | “Other changes synced. Both versions are saved.”; unrelated tasks доступны | FR-006, FR-007 |
| .07 offline / interrupted | choice сделан offline или приложение закрыто | choice сохраняется durable и показывается как waiting; оба исходника остаются до acknowledged resolution | FR-001, FR-007, FR-010 |
| .08 changed again | версия изменилась после открытия карточки | “This task changed again. Review both versions.”; обновить account side, оставить user's draft; повторное explicit apply | FR-007 |
| .09 deleted elsewhere | серверный delete существующей удаляемой сущности встретил local edit | “This item was deleted on another device. Your edit is saved in this issue.”; Copy saved edit, “Keep item deleted”; **никакого автоматического reopen/create** | FR-007, FR-008 |

Resolution title-примера создаёт обычную title command против показанной текущей версии; другие поля не заменяются старым snapshot. По FR-007/contract v1 допустим консервативный конфликт всей сущности: preview должен показать все различающиеся поля, а не обещать автоматический field merge. Выбор account version явно отбрасывает намерение и требует решения по dependent actions. Вариант ручной переписи текста пока не добавлен: сравнение, Copy saved edit и две явные версии дают минимально достаточную recovery. “Keep item deleted” закрывает issue только после durable записи решения; сохранённый edit доступен в recovery/export согласно retention contract, не исчезает при простом закрытии sheet. Пример удаления относится к существующей удаляемой записи, например comment; новый интерфейс удаления/восстановления Task не вводится. Прежний suffix `.10` зарезервирован и не используется: FR-009 сохраняет текущий порядок/перемещения, manual reorder API и UI в scope отсутствуют.

### M-03 / D-03 — Recover sync (13 states per screen)

| suffix / state | trigger | visible result and English copy | FR refs |
|---|---|---|---|
| .01 default | человек открыл recovery | “Recover sync”; pending count; объяснение: “Rebuild the synced copy. Your waiting changes and saved conflicts will be kept.”; Rebuild synced copy | FR-010 |
| .02 loading | resume/reset идёт | “Rebuilding synced copy…”; count остаётся; не смешивать snapshot с partial transaction; нет обещания числового процента | FR-006, FR-010 |
| .03 empty, first run | нет account sync history | “Not synced yet”; первый sync без reset dialog | FR-003, FR-010 |
| .04 empty, filtered | N/A: нет фильтра | — | FR-010 |
| .05 error | reset/download прерван | “Couldn't rebuild the synced copy. Your waiting changes are saved.”; Try again и safe reference ID | FR-010, FR-023 |
| .06 partial failure | хотя бы одно поле/запись/связь migration не валидируется | “Couldn't import earlier data”; “Your earlier data file is unchanged. The new store hasn't been activated.”; original backup и import report сохранены; частично импортированный store не становится активным | FR-013 |
| .07 offline / interrupted | reset или migration interrupted | “Connect to finish recovery”; локальные pending сохраняются, resume идёт из durable checkpoint | FR-010, FR-013 |
| .08 unsupported protocol | новый server protocol | “Update needed to sync. Your saved tasks and waiting changes stay on this device.”; Update app через platform mechanism | FR-012 |
| .09 unsupported store | файл создан новой версией | “Update needed to open tasks”; Try again, Export saved data when safely possible; никаких записей и фонового sync | FR-012, FR-022 |
| .10 migration uncertain | old outbox ack неизвестен | “Earlier changes need verification”; “Your earlier store and waiting changes are kept while sync checks what reached your account.”; retry без слепого duplicate replay | FR-005, FR-013 |
| .11 account switch | запрос выхода перед сменой account при pending/issues | Existing “Sign out?” warning: актуальный count, account и точное объяснение удаления local copy/unsynced work/issues; Cancel, Export saved data, подтверждённый “Sign out and remove”; sync/resolve можно выбрать вместо выхода, сеть не обязательна для подтверждённого выхода | FR-003, FR-011, FR-022 |
| .12 export / deletion | человек использует existing data controls | Export включает локальный pending/conflict материал; Delete account остаётся existing подтверждённым workflow; локальные копии/AI данные подчинены той же privacy policy | FR-022 |
| .13 complete | reset/migration закончены | возврат к status без нового onboarding; issues остаются отдельно; “Earlier data imported” только при полной verified migration | FR-010, FR-013 |

Смена аккаунта использует существующий warned sign-out: человек может отменить выход и sync/resolve, экспортировать безопасно читаемые local данные или явно подтвердить удаление local copy/unsynced work/issues с точным актуальным count. Доступность сети не является условием такого подтверждённого выхода; pending никогда не передаются другому owner. Export не считается server acknowledgment и сам по себе не снимает предупреждение. Account-less workspace не присваивается другому owner неявно. Reset не является “Start fresh” и не удаляет user intent; destructive sign-out не предлагается как лечение sync. Migration валидирует все поля, IDs, связи, review/local-only данные и outbox в staging: активация только после полной проверки, иначе original store остаётся целым и активным. Если snapshot/state несовместим, read-only recovery означает сохранённые данные доступны только в безопасно декодируемой форме, не выдуманный обещанный export неизвестного binary format.

### M-04 / D-04 — AI choice, consent and proposal (12 states per screen)

| suffix / state | trigger | visible result and English copy | FR refs |
|---|---|---|---|
| .01 default | совместимая local model доступна | “On-device suggestions”; “Task content stays on this device.”; request только по действию человека | FR-018, FR-020 |
| .02 loading | local/cloud request уже authorised | “Preparing suggestions…”; Cancel/Continue without AI; canonical Task не меняется | FR-018, FR-019, FR-020 |
| .03 empty, first run | cloud consent отсутствует | “Use cloud suggestions?”; конкретное configured provider name и точный список полей; Allow cloud suggestions / Continue without AI | FR-019 |
| .04 empty, no proposal | корректный ответ не дал подходящего suggestion | “No suggestion this time”; Continue without AI, ручное решение остаётся доступно | FR-020 |
| .05 error | local unavailable / cloud timeout/cost cap | “Suggestions aren't available. You can continue without AI.”; safe reference ID если cloud; никакого silent cloud fallback | FR-018, FR-019, FR-023 |
| .06 partial input | notes reduced по существующему лимиту | “Part of the notes was not considered”; disclose до apply; не расширять cloud payload | FR-016, FR-019, FR-020 |
| .07 offline / interrupted | сеть отсутствует | local работает при model availability; cloud “Connect to request cloud suggestions”; готовый local draft не стирается | FR-018, FR-019, FR-020 |
| .08 local unsupported | device/language/model policy не подходит | “On-device suggestions aren't available for this task”; existing compatible local download choice если поддержан; cloud только через consent | FR-018, FR-019 |
| .09 consent denied/revoked | decline, revoke, provider/input-version change | “Cloud suggestions are off”; новые запросы запрещены; stale response не подставляется после revocation/account switch | FR-011, FR-019, FR-022 |
| .10 proposal ready | validated suggestion получен | “Review suggestion”; editable field; “Nothing changes until you apply”; Apply suggestion / Keep current wording | FR-020 |
| .11 proposal stale | Task revision изменился | “This task changed. Review it before applying a suggestion.”; сохранить draft, перечитать Task, повторить explicit confirmation | FR-007, FR-020 |
| .12 applied | explicit command committed | карточка показывает новый текст; durable Task command и existing review receipt, без auto-complete Task и без AgentRun badge | FR-016, FR-020, FR-021 |

Cloud example в mock помечен как **illustrative provider: OpenAI**, это не выбор поставщика или включение нового AI flow. При реализации имя должно приходить из текущей provider configuration, и consent хранится per owner/provider/input version. Для существующего review navigator список данных точно из 020-FR-019: title, notes, optional stall reason, project name, up to 20 other open task titles in that project, requested suggestion kind. Copy: “Notes are sent as written, including any names in them.” Иное AI действие обязано показывать свой утверждённый payload, а не переиспользовать этот consent по умолчанию. Данный дизайн не расширяет approved AI model policy или доступность downloadable модели.

## Affordance → requirement map

| screens | affordance | behavior | FR refs |
|---|---|---|---|
| M-01, D-01 | existing status row / Show details | last acknowledged sync, waiting counts, reason; сохранённый локальный результат не выдаётся за server ack | FR-001, FR-004, FR-023 |
| M-01, D-01 | Sign in to sync / Sign in again | existing auth, account-less optional; owner-specific pending | FR-003, FR-011 |
| M-01, D-01 | Retry / Sync now | existing single-flight retry; offline/auth/version disabled с объяснением; running sync не отключает кнопку | FR-005, FR-010 |
| M-01, D-01, M-03, D-03, M-04, D-04 | Copy reference ID | только opaque correlation ID без Task/AI/auth payload; copy failure сообщает error | FR-023 |
| M-01, D-01 | Open sync issues | независимый failed group; successful transactions доступны | FR-006, FR-007 |
| M-02, D-02 | version radio choice + Apply choice | explicit durable resolution против показанной текущей версии; discard dependent actions требует явного решения | FR-007 |
| M-02, D-02 | Copy saved edit / Keep item deleted | edit сохранён; tombstone существующей удаляемой сущности не оживает от replay; нового Task delete UI нет | FR-007, FR-008 |
| M-03, D-03 | Rebuild synced copy / Try again | confirmed non-destructive reset с сохранением pending/conflicts | FR-010 |
| M-03, D-03 | Update app | platform update route, stopped incompatible sync/store writes | FR-012 |
| M-03, D-03 | Open import report / Export saved data | existing recovery/export route, backup и uncertainty видны | FR-013, FR-022 |
| M-03, D-03 | existing Cancel / Export saved data / Sign out and remove | warned sign-out с актуальным count; cancel остаётся в current workspace, confirmed removal не требует сети, pending не переносится другому owner | FR-003, FR-011, FR-022 |
| M-03, D-03, M-04, D-04 | existing Export / Delete account / Revoke consent | полный privacy lifecycle; deletion требует existing confirmation | FR-022, FR-019 |
| M-04, D-04 | on-device choice / supported model download | approved existing availability policy | FR-018 |
| M-04, D-04 | Allow cloud suggestions / Continue without AI | per-owner/provider consent, отказ оставляет ручное review доступным | FR-019 |
| M-04, D-04 | Request suggestions / Cancel | bounded proposal request, no Task command | FR-018, FR-019, FR-020 |
| M-04, D-04 | edit proposal / Apply suggestion / Keep current wording | только explicit Task command; existing review semantics сохраняются | FR-016, FR-020 |

### Requirements with no additional affordance

| FR | reason / observable invariant |
|---|---|
| FR-002 | Общие domain rules и cross-language parity; клиент не показывает выбор engine |
| FR-009 | Существующий порядок, перемещения и completed placement сохраняются; нового manual reorder API/control нет |
| FR-014 | Адаптер старых clients сохраняет существующий API/workflow; отдельная compatibility кнопка не нужна |
| FR-015 | Durable jobs и dedup scheduler; пользователь видит existing result/status, не внутреннюю очередь jobs |
| FR-017 | Calendar dates, instants, stored review timezone и local notification timezone сохраняют действующий контракт; нового date control нет |
| FR-021 | Task и AgentRun разделены; новый run UI не вводится, successful run не завершает Task |
| FR-024 | Web сохраняет текущие workflows и online affordances; новый offline mode не добавлен |
| FR-025 | App/widget multiprocess storage arbitration и atomic reads; lock/engine controls в UI не нужны |
| FR-026 | Local latency/scale и неблокирующий sync; benchmark evidence, не новый performance dashboard |

FR-001/004/005/006/008/009/010/011/012/013 также имеют невидимые durability, convergence, dedup, transaction, tombstone, ordering, reset, isolation и migration инварианты. Показанный статус сам по себе **не** является доказательством этих инвариантов: будущий plan должен назначить contract/storage/replay проверки. FR-016 включает exact formulation clocks, auto-park floors, yield/idempotency, receipts/Undo и feature-flag behaviour из ADR-0027; новых review controls здесь нет. Таблицы выше покрывают все FR в обе стороны; affordances без требования: **none**. Back/Cancel/navigation закрывают только представление, не удаляют durable intent.

## Primary loop impact

Capture → durable atomic Task commands остаётся немедленным локальным действием. Clarify/approve и routing сохраняют существующие shared rules; sync переносит результат, а не повторяет действие. Review/formulation/auto-park сохраняют exact ADR-0027 authority и date semantics. AI выдаёт proposal, которое входит в loop только после explicit apply. Evidence/results, Task completion и AgentRun не объединяются. Conflict/recovery не требуют новой task app layout.

## Mobile viability

- **Target viewport**: 390×851 и узкий 320 px; responsive CSS, wrapping text, без fixed-height content clipping. Runtime проверка overflow **не выполнена**, утверждение “verified” не делается.
- **Tap targets**: CSS устанавливает 44 px min-height для controls и radio labels; native implementation требует 44 pt, включая Copy/Back.
- **One-handed reach**: существующая status row и sheet с full-width stacked actions на mobile; длительная таблица сравнения вертикальная.
- **Dynamic Type / zoom**: длина копии не обрезается; preview values wrap; buttons wrap, не ellipsis. Нужна device проверка large type.
- **Destructive actions**: reset не удаляет pending. “Keep item deleted” оставляет существующую удаляемую запись удалённой и сохраняет правку в recovery. Existing sign-out warning точно называет pending/issues и local copy, которые будут удалены, с Cancel/export route; confirmed removal доступен offline. Export/Delete account используют existing confirmations, не новые скрытые destructive gestures.

## Keyboard and focus

- Tab order: existing opener → details actions; conflict radio group → Apply choice → Copy saved edit → Back; recovery explanation → primary recovery → Cancel; AI disclosure → Allow → Continue without AI.
- На sheet open native focus идёт на heading для VoiceOver, затем первый безопасный control; conflict без заранее выбранной версии. Escape/Back закрывает presentation; focus возвращается к opener. При исчезновении issue — Sync issues heading.
- Error получает одну alert announcement; waiting/time refresh не создаёт повторных announcements. Async status использует polite live region только для actionable transitions.
- “Copy reference ID”, “Copy saved edit”, radio labels и headings имеют текстовые accessible names. Нет icon-only controls и состояния только по цвету.
- HTML — статический review sheet, не имитация focus trap или live backend: links/details/radios работают нативно, product action buttons иллюстративны. Keyboard dialog/retry/clipboard поведение требует отдельной runtime проверки при реализации.

## Design authority and evidence

Sources: accepted ADR-0006/0020/0027; `.claude/skills/brain-buddy-design/SKILL.md`, `README.md`, `colors_and_type.css`; existing `specs/021-mac-sync/design.md`. System font для native surface; slate/sky tokens, sky-700 action text/filled controls согласно existing native deviation, amber warning и double-ring focus. Self-contained CSS без font import, CDN, script или asset dependency. Flat slate-50 background, 4 pt spacing, 8 px buttons, 12 px cards, 20 px panels. Никакого нового branding.

| check | actual evidence |
|---|---|
| design-skill contract unittest | **pass**, 2026-10-08: `python3 -m unittest scripts/test_validate_brain_buddy_design_skill.py`, 6 tests. Проверяет существующий shared design reference, не rendering этих экранов |
| ADR-0006 vocabulary static scan | **pass**, 2026-10-08: case-insensitive `rg` по design.md/design, 0 совпадений с retired vocabulary |
| HTML structure / local links / 44 px CSS static inspection | **pass**, повторно 2026-10-08 после выравнивания с spec/contract: Python HTMLParser, balanced tags, unique ids, 5 local anchors, 56 buttons с explicit type, no scripts/external resources, 44 px CSS, 8 screen IDs, FR-001–FR-026 coverage и 45 shared rows / 90 screen-state combinations. Проверены отсутствие нового manual reorder/delete Task flow и обновлённый warning/migration copy. Runtime geometry/contrast/focus не проверены |
| Screenshots, browser/device rendering, runtime accessibility | **not performed**; static artifacts only |
| Product/CI/deployment acceptance | **not performed**, вне spec-only scope |
| Human approval | **pending**, не разрешение на implementation |

## Open decisions for the human

1. **Concurrent edit resolution**: подтвердить минимальную explicit choice двух сохранённых версий (и copy), без автоматического выбора последней по времени. При конфликте всей сущности preview показывает все различающиеся поля и dependent actions. Для delete/edit существующая удаляемая запись остаётся удалённой; edit сохраняется отдельно; нового Task delete/reorder UI нет.
2. **Account switch warning**: сохранить existing sign-out warning с точным count, Cancel/export/explicit confirmed removal и без переноса pending другому owner. Это не network gate. Reset при этом всегда сохраняет pending/conflicts.
3. **Recovery visibility**: подтвердить quiet status с existing 021 timings и отдельную recovery sheet только для persistent/semantic ошибок; migration uncertainty показывается явно. Migration полностью валидируется перед активацией или завершается ошибкой с original intact; обычная verified migration проходит тихо.

Эти решения — draft recommendations для общей спецификации. Утверждение Rust + custom sync не считается human sign-off этих экранов.
