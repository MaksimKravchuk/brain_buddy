# Предлагаемый контракт sync v1

Статус: Draft. Это новый протокол только Tasks aggregate и native-task Review. «v1» означает первую версию нового протокола, не текущего REST API. Ни CRT, ни Identity, ни сырое аудио не помещаются в task change feed. Имена будущих endpoint ниже — проектируемые, не существующие маршруты.

## 1. Основные гарантии

Устройство немедленно сохраняет допустимое локальное намерение. Сервер определяет окончательно принятый порядок и проверяет действующие права. Доставка команд и изменений допускает повтор. Однократность внутренней мутации обеспечивают устойчивый command receipt и одна серверная транзакция, а не обещание сети доставить пакет ровно один раз.

Клиент хранит `confirmed_base`, `outbox`, `sync_issues`, `drafts` и производную `visible_state`. Последняя равна повторному применению допустимых pending-команд к подтверждённой базе. Отклонённая команда перестаёт выглядеть как подтверждённое состояние, но её payload и локальный текст сохраняются в issue. Неотправленный редактор не заменяется пришедшей серверной версией.

## 2. Идентичность и версии

`owner_id` остаётся существующим immutable account ID. `scope_id` — серверный идентификатор приватного task scope этого owner. Его наличие не создаёт sharing. Любой scope в запросе проверяется против действующей сессии; actor сервер выводит из Identity, тело запроса его не назначает.

Новые сущности и команды получают случайные UUID на клиенте до первой записи. Старые ID не перенумеровываются. UUID не используется как время или порядок. `device_id` зарегистрирован на аккаунт; `device_epoch` создаётся для поколения установки/очереди и закрывается при принудительном reset. Это дополнительный барьер, не credential.

У сущности есть два разных счётчика: `edit_revision` — принятой доменной конкурентности, и `record_version` — любого сериализованного изменения записи. Clock bookkeeping из ADR-0027 может увеличивать `record_version`, не меняя `edit_revision`. Они не взаимозаменяемы. Каждый accepted write также получает `commit_seq` внутри scope. Все счётчики передаются JSON-строками, чтобы не зависеть от ограничения JavaScript 2^53.

## 3. Локальная команда и зависимости

Пример wire envelope:

```json
{
  "protocol_version": 1,
  "command_id": "01900000-0000-4000-8000-000000000001",
  "scope_id": "scope-example",
  "device_id": "device-example",
  "device_epoch": "epoch-example",
  "local_sequence": "42",
  "type": "task.update",
  "command_version": 1,
  "entity_id": "task-existing-id",
  "preconditions": [
    {"entity_type": "task", "entity_id": "task-existing-id", "edit_revision": "17"}
  ],
  "depends_on": [],
  "issued_at": "2026-10-08T10:00:00Z",
  "payload": {"title": "Подготовить расчёт"}
}
```

`issued_at` сохраняет исходное время намерения и нужен существующим временным правилам, но не даёт прав, не определяет порядок commit и не является общим правилом победы в конфликте. Ограничения доверия ко времени auto-park сохраняются из ADR-0027.

В одной SQLite transaction runtime читает актуальное локальное состояние, проверяет команду через core, присваивает local sequence, добавляет envelope и обновляет проекцию. Ошибка диска откатывает всё. Повтор жеста после неизвестного результата локального API тоже сверяет command ID, а не создаёт второй ID автоматически.

Envelope неизменен после устойчивой постановки. Если следующая offline-команда зависит от создания/редактирования, её `depends_on` содержит предыдущий command ID. Вместо выдуманного будущего server revision допускается предусловие `after_command: {command_id, entity_type, entity_id}`: сервер подставляет **edit_revision из receipt той команды**, затем сравнивает с текущей. Если между ними вмешалась другая команда, получается конфликт. Все остальные затронутые сущности имеют собственные предусловия; не только главный task ID.

Runtime отправляет по одной команде на scope, сохраняя порядок зависимостей. Отклонение блокирует её descendants; независимые commands продолжаются. `local_sequence` — уникальный порядок локальной очереди, сервер не требует непрерывной числовой последовательности: отменённые и заблокированные записи не должны навечно остановить scope.

Неотправленные изменения не компактизируются в MVP. После подтверждённого отказа или явного разрешения конфликта создаётся новая команда с новым ID и `supersedes_command_id`; descendants тоже явно перепланируются с новыми ID. На исход с uncertainty это правило не распространяется.

## 4. Серверная транзакция

Для небольшого приватного scope достаточно сериализации его writes. Все пути записи берут один owner/scope lock, включая REST-адаптер, MCP, auto-park и задания. В PostgreSQL это row lock scope, удерживаемый до commit; в переходном SQLite — transaction/writer policy одного экземпляра. Порядок нескольких блокировок фиксирован; произвольная работа с сетью под lock запрещена.

1. Проверить сессию, ownership, account generation, активность device epoch, версию протокола, размер и форму запроса.
2. Найти receipt по `(scope_id, command_id)`. Существующий ID с тем же нормализованным содержимым возвращает известный исход. С иным содержимым возвращает `IDEMPOTENCY_KEY_REUSED`, ничего не исполняя. Права проверяются заново перед выдачей любых данных receipt.
3. Проверить зависимости, edit revisions и доменные ограничения общей Rust-функцией на текущих данных. Зависимость без terminal receipt даёт retryable `DEPENDENCY_PENDING`; rejected dependency — terminal `DEPENDENCY_REJECTED`.
4. Для accepted command атомарно записать domain changes, новые версии, receipt, change transaction и необходимые внутренние job/effect records. Для terminal rejection записать receipt отказа без доменной мутации.
5. Commit, затем ответ. Уведомление устройств — после commit, может теряться и дублироваться.

Fingerprint вычисляется на сервере по RFC 8785 canonical JSON всего envelope без транспортных observability headers. Дубли ключей JSON и нецелые числовые значения там, где ожидается строковый счётчик, отклоняются до исполнения. Одинаковый command ID нельзя повторить другим endpoint с изменённой семантикой. Fingerprint хранится как служебное защищённое значение и никогда не логируется.

Обычная DB sequence не задаёт cursor: transaction A может получить номер раньше B и commit позже. Scope counter увеличивается **под тем же lock и в той же transaction**, поэтому выдаваемый commit order не имеет такого разрыва. Это намеренный предел write throughput одного scope; при доказанной нагрузке механизм можно заменить на commit-ordered log, сохранив контракт.

## 5. Receipt и неизвестный исход

```json
{
  "command_id": "01900000-0000-4000-8000-000000000001",
  "outcome": "accepted",
  "server_generation": "generation-example",
  "commit_seq": "908",
  "result_versions": [
    {"entity_type": "task", "entity_id": "task-existing-id", "edit_revision": "18", "record_version": "24"}
  ],
  "correlation_id": "opaque-support-reference"
}
```

Terminal outcomes: `accepted`, `rejected`. Accepted включает допустимый доменный no-op с результатом, но без лишнего эффекта. Rejected содержит код, безопасные детали и доступную актуальную версию. `pending` у чтения результата означает незавершённую обработку; `not_found` означает отсутствие **на момент lookup**, а не доказательство, что ранее отправленный запрос никогда не commit-ится.

Timeout, разрыв соединения и 5xx оставляют `sending/unknown`. Клиент повторяет тот же envelope или читает receipt. Перед повтором применяет exponential backoff с jitter; 429 учитывает Retry-After. 401 приостанавливает до reauth; 403/закрытый epoch требуют отдельного восстановления. Эти transport/policy отказы не уничтожают outbox.

Receipt нельзя просто удалить через 24 часа. Предлагается 30 дней хранить полный ответ, затем минимальную запись `(scope, command ID, fingerprint, outcome/code, commit_seq, result_versions)` до purge аккаунта. После redaction ответ сообщает `result_redacted` и требует прочитать текущее состояние, но никогда не повторяет мутацию. Удаление сущности досрочно убирает её текст из всех retained receipt payloads. Fingerprint/IDs остаются только в закрытом служебном хранилище и удаляются при purge; в безопасный export пользовательского содержимого они не выдаются.

После закрытия device epoch неизвестные commands не принимаются как новые. Пользовательская сверка завершается до создания нового epoch/новых намерений. Новая установка сама по себе не стирает историю дедупликации. Восстановленный backup не получает возможность переиграть старые эффекты.

## 6. Delta feed и снимок

Проектируемый API:

| Метод и путь | Назначение |
| --- | --- |
| `POST /api/sync/v1/devices` | Регистрация device epoch для текущего owner |
| `POST /api/sync/v1/commands` | Одна команда; terminal receipt либо retryable error |
| `GET /api/sync/v1/commands/{id}` | Owner-scoped lookup результата |
| `POST /api/sync/v1/snapshots` | Создать стабильный snapshot и watermark |
| `GET /api/sync/v1/snapshots/{id}?page=...` | Следующая страница неизменного снимка |
| `GET /api/sync/v1/changes?cursor=...&limit=...` | Полные change transactions после cursor |
| `GET /api/sync/v1/capabilities` | Protocol/schema/command versions, limits и reset policy |

Cursor — opaque token, связанный со scope, access generation и feed generation. `has_more` и `next_cursor` обязательны. Ответ содержит transaction ID, commit sequence, source command ID и типизированные upsert/tombstone after-images с record versions. Внутри transaction — все записи изменения: task, project/tag membership, children, review clocks/settings/receipts. Secrets и raw media исключены.

Страница не разрезает logical transaction. Предлагаемые начальные limits: request ≤ 256 KiB, ≤ 500 изменённых записей в одном доменном command, page target ≤ 1 MiB и ≤ 100 transactions; одна целая transaction может увеличить страницу до hard limit 4 MiB. Oversize command отклоняется до записи; batch/archive/import с большим объёмом требует отдельного согласованного chunk/operation контракта, не тихого разделения атомарной команды. Эти limits должны быть сверены с существующими максимальными размерами до cutover.

Snapshot строится из одного согласованного DB snapshot вместе с watermark H и материализуется в owner-scoped временный объект. Все страницы относятся к одной версии; TTL 30 минут, continuation token не заменяет авторизацию. Клиент пишет страницы в staging DB, сверяет полноту и checksum, затем атомарно активирует confirmed base и cursor H, сохраняя outbox/issue/draft. До активации приложение читает старую базу. Checksum используется для целостности, не для поиска похожих задач, и не логируется.

После snapshot клиент читает delta строго после H. Снимок, истёкший до завершения, запускается заново, без удаления pending. Предлагаемое хранение delta — 90 дней. Cursor вне окна, смена feed generation или восстановление server backup дают `RESET_REQUIRED`. Клиент не считает пустой ответ восстановлением.

Tombstones содержат ID, тип и final record version. Полные after-images в feed доступны только текущему owner. При удалении сущности предыдущие retained payloads с её удаляемым содержимым редактируются/удаляются согласно deletion policy, snapshot с этим содержимым инвалидируется; tombstone и minimal dedup остаются. Account purge удаляет feed, snapshots, receipts и jobs соответствующего scope. Cursor никогда не переносится на новый аккаунт.

## 7. Применение изменений на устройстве

В одной локальной transaction runtime применяет **всю** change transaction к confirmed base, сопоставляет source command IDs с outbox, сохраняет receipt, затем replay оставшихся допустимых намерений и сохраняет cursor. Confirmed base меняется только последовательными feed transactions или полной активацией согласованного snapshot. ACK не записывает after-images в confirmed base: иначе поздний ACK через пропущенную transaction может разорвать согласованность нескольких записей, даже с record-version guard. Cursor не прыгает к commit_seq ACK через неизвестные промежуточные записи.

ACK переводит команду в `accepted_awaiting_feed`: повтор отправки больше не нужен, но её устойчивое намерение и optimistic projection сохраняются. Оно удаляется из pending только в transaction, которая доказала включение результата в confirmed base: применён feed с source command ID, либо snapshot той же server generation с watermark ≥ receipt.commit_seq. No-op/rejected receipt, не имеющий domain changes, можно завершить непосредственно по receipt; принятую команду нельзя превратить в локальный конфликт только потому, что feed ещё не догнал ACK. Snapshot recovery отдельно сверяет **все** неизвестные command IDs через receipt lookup. ACK новее watermark snapshot остаётся ожидающим до последующего delta; отсутствие команды в delta само по себе не доказывает её исход.

Каждый запрос захватывает `(workspace_generation, session_generation, local_sync_generation, server_generation)`. Все ACK, receipt, feed и snapshot responses содержат server generation. При reset/restore runtime **до** подготовки нового снимка увеличивает local sync generation и отменяет старые requests; поздние ответы с прежним набором поколений игнорируются, даже если account/session те же. Pending сохраняются и сверяются с текущей server generation. Результат из старого поколения не может убрать намерение или доказать его наличие после restore. Обычный restart клиента сам по себе не меняет server generation. Уже полученный ответ старого аккаунта не доставляется в новый workspace. Отзыв доступа останавливает sync и закрывает отображение account cache согласно существующей sign-out/security policy; unsent work не загружается новому owner. Физически отозвать данные с устройства, которое никогда больше не выйдет в сеть, сервер не может.

APNs, WebSocket/SSE и network callbacks только будят pull. Активный клиент делает fallback pull не реже 60 с, при foreground и network return. Мобильная ОС не обязана будить приложение точно по времени. «Synced» означает пустую очередь без issues и применённый текущий полученный watermark; подпись last synced показывает время последнего успешного прохода, а не гарантию вечной свежести.

## 8. Конфликты

| Случай | Обязательное поведение v1 |
| --- | --- |
| Изменилась ожидаемая edit revision | Terminal `REVISION_CONFLICT`; сохранить локальное намерение и показать актуальную доступную запись |
| Изменены разные поля одного task | В v1 допустим явный конфликт; автоматическое field merge — отдельное улучшение с проверкой всех инвариантов |
| Повтор того же command ID | Receipt replay независимо от того, насколько состояние уже продвинулось |
| Другой ID с «уже завершить» | No-op только если accepted доменное правило доказывает тот же результат; не маскировать intervening reopen/cancel |
| Delete против Edit | `ENTITY_DELETED`, без upsert; копирование в новую сущность только явно |
| Project archive против membership edit | Применить ADR-0020 под lock, при нарушении предусловия — issue |
| Auto-park против своевременного review decision | Специализированный reducer ADR-0027; generic stale rejection не отменяет право на yield |
| Tag membership | Явные add/remove операции над отношением; не перезапись всей коллекции чужим старым снимком |
| Зависимая команда после отказа | `blocked_dependency`; никакого слепого replay поверх другого смысла |

«Оставить мою версию» создаёт команду против **показанной** пользователю актуальной версии. Если её снова изменили, требуется новое разрешение, а не force overwrite. «Использовать серверную» явно отбрасывает локальное намерение и спрашивает о dependent actions. Bulk «всегда последняя запись побеждает» в первой версии отсутствует. Существующий Mac last-push-wins изменяется только при отдельном принятии нового conflict UX и ADR.

## 9. Совместимость

Protocol, command schema, доменные правила, локальная DB schema и server storage epoch версионируются отдельно. Сервер принимает текущую и предыдущую опубликованную major command версию минимум 180 дней с момента замены; capabilities возвращает точные поддерживаемые версии и deadline. Старше — `UPGRADE_REQUIRED`, данные/очередь сохраняются. Правило не позволяет старому клиенту потерять неизвестные поля при full-object PUT.

REST-адаптер переводит legacy запросы в общий command handler и feed в той же transaction, сохраняя прежние preconditions и response shapes. Это не даёт старому клиенту новый conflict UI: legacy writes остаются сериализованными событиями, а новый клиент может конфликтовать с ними. Гарантия новых explicit conflicts относится к новым клиентам; её нельзя обещать для старых last-writer клиентов. Окно совместимости заканчивается управляемым minimum-version gate перед изменением несовместимых инвариантов.

Фича включается по scope capabilities, не только локальным UI flag. После активации нового хранения flag OFF останавливает rollout и новые подключения, но не возвращает старый writer к новой DB. У каждого storage epoch есть старейший совместимый образ. Восстановление сервера меняет server/feed generation, закрывает опасные epochs и сверяет внешние эффекты; rollback DB отдельно от receipts/effects запрещён.

Restore выполняется при закрытом доступе. До разрешения чтений и writes необходимо повторно применить **все** последующие purge/deletion и credential/session revocation решения из durable control ledger, который не откатывается вместе с task backup. Иначе старый backup мог бы воскресить удалённые данные или ранее отозванный доступ. При восстановлении Identity сомнительные сессии отзываются и требуется свежая аутентификация; одного закрытия device epochs недостаточно. Если completeness ledger нельзя доказать, сервис остаётся закрытым до сверки. Control ledger сам содержит только минимальные IDs/generations и имеет собственную защищённую backup/retention policy.

Backup/WAL policy должна задавать проверенный RPO/RTO до production cutover. Потерю подтверждённых commits при disaster restore нельзя объявлять «успешной синхронизацией»: восстановление до более старой точки требует явного incident/reconciliation, закрытых epochs и сверки сохранившихся клиентских намерений/receipts. Из уже утраченного receipt невозможно получить exactly-once задним числом; новый ID не является восстановлением доказательства.

## 10. Обязательные сценарии проверки

Проверить crash до/после каждой transaction boundary; duplicate и reordered delivery; ACK после более нового delta; ACK до пропущенного промежуточного multi-record delta; ACK за watermark snapshot; две offline-команды после create; вмешательство другого устройства между зависимостями; independent queue progress после rejection; snapshot pagination при конкурентных writes; delete/redaction во время snapshot; 90-дневный offline; receipt после 30 дней; purge/revocation после даты восстановленного backup; поздний pre-restore ACK при той же сессии; stale session response; неподдерживаемый command; lock/commit race; app/widget concurrent writes; auto-park yield и bookkeeping без edit revision. Инвариант: `visible = confirmed + replay(допустимые pending)` и terminal receipt никогда не разрешает повторный внутренний эффект.
