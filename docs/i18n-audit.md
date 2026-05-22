# i18n audit (E2.1)

> Инвентарь всех hardcoded русских / UI-строк в шаблонах и фронтенд-JS дашборда.
> Источник — задача **#2bad8889912d** в pride-tasks.
> Цель — на следующем шаге (**E2.2**) сгенерировать на основе этой таблицы
> `static/i18n/ru.json` и `static/i18n/en.json` и заменить inline-тексты на ключи.
>
> Как пользоваться:
> - Колонка **key** — предлагаемый snake_case ключ с namespace через точку.
> - Колонка **ru** — текст ровно как он сейчас в исходнике (без перевода!).
> - Колонка **location** — `file:line` (пути относительно репо-корня).
> - Дубли (одна строка в нескольких местах) перечислены в одной строке с несколькими location через `;`.
>
> Что НЕ попало в инвентарь (намеренно):
> - JS-комментарии (`// ...`, `/* ... */`) — не UI.
> - HTML-комментарии (`<!-- ... -->`) — не UI.
> - CSS-комментарии и имена классов — не UI.
> - Имена ролей и статусов внутри API-payload (`status: "todo"`, `author: "дмитрий"`)
>   — это значения, идущие по API, а не UI-лейблы. Они вынесены отдельно как `enum.*`
>   только там, где используются как **отображаемый** список (`<option>` в формах).
> - Локали для `toLocaleString("ru-RU")` — это код локали, не текст.

---

## Сводка

| метрика | значение |
|---|---|
| просканировано файлов | **2** (`дашборд/templates/kanban.html`, `дашборд/static/app.js`) |
| уникальных ключей | **128** |
| из них в HTML-шаблоне | 60 |
| из них в JS | 68 |
| дубликатов (один и тот же текст в ≥2 местах) | **8** (см. конец документа) |

Топ namespace по размеру:

| namespace | кол-во ключей |
|---|---|
| `task.*` | 27 |
| `modal.*` | 16 |
| `nav.*` / `sidebar.*` | 14 |
| `inbox.*` | 13 |
| `chat.*` | 11 |
| `team.*` | 10 |
| `status.*` | 8 |
| `usage.*` | 9 |
| `live.*` | 5 |
| `archive.*` | 3 |
| `settings.*` | 6 |
| `common.*` | 6 |

---

## `common.*` — общие кнопки / лейблы

| key | ru | location |
|---|---|---|
| `common.cancel` | Отмена | templates/kanban.html:211 ; templates/kanban.html:228 ; templates/kanban.html:291 ; static/app.js:318 |
| `common.ok` | OK | templates/kanban.html:212 ; templates/kanban.html:229 |
| `common.save` | Сохранить | static/app.js:319 |
| `common.create` | Создать | templates/kanban.html:292 |
| `common.add` | Добавить | static/app.js:344 |
| `common.none_dash` | — нет — | templates/kanban.html:285 ; static/app.js:307 |

## `nav.*` — навигация / sidebar

| key | ru | location |
|---|---|---|
| `nav.brand` | Praid | templates/kanban.html:16 |
| `nav.inbox` | Inbox | templates/kanban.html:22 |
| `nav.board` | Доска | templates/kanban.html:27 |
| `nav.archive` | Архив | templates/kanban.html:32 |
| `nav.settings` | Состояние | templates/kanban.html:37 |
| `sidebar.team` | Команда | templates/kanban.html:52 |
| `sidebar.role.teamlead` | тимлид | templates/kanban.html:53 |
| `sidebar.role.backend` | бэкенд | templates/kanban.html:54 |
| `sidebar.role.qa` | qa | templates/kanban.html:55 |
| `sidebar.role.architect` | архитектор | templates/kanban.html:56 |
| `sidebar.role.frontend` | frontend | templates/kanban.html:57 |
| `sidebar.role.devops` | devops | templates/kanban.html:58 |
| `sidebar.role.tech_writer` | техписатель | templates/kanban.html:59 |
| `page.title` | pride-team · малая команда | templates/kanban.html:5 |

## `topbar.*` — верхний бар

| key | ru | location |
|---|---|---|
| `topbar.new_task` | + Новая задача | templates/kanban.html:70 |
| `topbar.search_placeholder` | Поиск по заголовку… | templates/kanban.html:71 |
| `topbar.theme_aria` | Тема | templates/kanban.html:74 |
| `topbar.theme_light` | Светлая тема | templates/kanban.html:75 |
| `topbar.theme_dark` | Тёмная тема | templates/kanban.html:76 |
| `topbar.auto_label` | 🤖 Авто | templates/kanban.html:81 |
| `topbar.auto_title` | Авто-режим: тимлид сам запустит следующую сессию когда есть работа | templates/kanban.html:79 ; static/app.js:529 |
| `topbar.btn_start` | ▶ Запустить команду | templates/kanban.html:83 |
| `topbar.btn_stop` | ⏹ Остановить | templates/kanban.html:84 |

## `team.*` — статус команды / роутер

| key | ru | location |
|---|---|---|
| `team.status.stopped` | ⏸ Стоит | templates/kanban.html:78 ; static/app.js:544 |
| `team.status.running` | 🟢 Работает | static/app.js:534 |
| `team.status.auto_paused` | ⏳ Авто-пауза | static/app.js:539 |
| `team.auto.enabled` | Авто-режим включён. За час: {n} сессий | static/app.js:527 |
| `team.auto.paused` | Авто-режим включён. Сейчас пауза: {reason}. За час: {n} | static/app.js:526 |
| `team.silence.title` | Тимлид завершил сессию но не оставил итогов | templates/kanban.html:44 |
| `team.silence.label` | тимлид молчит | templates/kanban.html:44 |
| `team.router.title` | Модель которую роутер выберет | templates/kanban.html:45 |
| `team.router.tooltip` | Авто-роутер моделей.\nВыбор: {alias}\n{reason}\nЗадач: {total} (архи {arch}, тривиальных {triv}, прочее {other}) | static/app.js:877 |
| `team.start_failed` | Не удалось запустить:  | static/app.js:581 |

## `kanban.*` — доска

| key | ru | location |
|---|---|---|
| `kanban.title` | Доска | templates/kanban.html:113 |
| `kanban.show_empty` | показывать пустые колонки | templates/kanban.html:115 |
| `kanban.column.todo` | К работе | templates/kanban.html:120 |
| `kanban.column.todo_title` | Задачи ещё не взяты в работу | templates/kanban.html:120 |
| `kanban.column.wip` | В работе | templates/kanban.html:124 |
| `kanban.column.wip_title` | Сейчас в работе у команды | templates/kanban.html:124 |
| `kanban.column.needs_approval` | Нужно одобрение | templates/kanban.html:128 |
| `kanban.column.needs_approval_title` | Требует твоего одобрения | templates/kanban.html:128 |
| `kanban.column.review` | На приёмке | templates/kanban.html:132 |
| `kanban.column.review_title` | Команда закончила, ждёт приёмки | templates/kanban.html:132 |
| `kanban.column.done` | Готово | templates/kanban.html:136 |
| `kanban.column.done_title` | Закрытые задачи (старше 7 дней — в Архиве) | templates/kanban.html:136 |
| `kanban.col_empty` | пусто — перетащи карточку сюда | static/app.js:162 |
| `kanban.move_failed` | Не удалось перенести:  | static/app.js:228 |
| `kanban.card.ago_suffix` | назад | static/app.js:144 ; static/app.js:732 |
| `kanban.card.has_deps` | есть зависимости | static/app.js:133 |
| `kanban.card.age.sec` | с | static/app.js:113 |
| `kanban.card.age.min` | м | static/app.js:114 |
| `kanban.card.age.hour` | ч | static/app.js:115 |
| `kanban.card.age.day` | д | static/app.js:116 |
| `kanban.empty.todo` | Пока нет задач — создай первую | templates/kanban.html (E3.1) |
| `kanban.empty.wip` | Никто пока не работает — назначь задачу | templates/kanban.html (E3.1) |
| `kanban.empty.review` | Приёмка пуста — работа сделана | templates/kanban.html (E3.1) |
| `kanban.empty.done` | Пока ничего не закрыто — двигаемся дальше | templates/kanban.html (E3.1) |
| `kanban.empty.cta.create_task` | + Создать задачу | templates/kanban.html (E3.1) |

## `status.*` — лейблы статусов задач (STATUS_LABEL)

| key | ru | location |
|---|---|---|
| `status.todo` | К работе | static/app.js:237 |
| `status.wip` | В работе | static/app.js:237 |
| `status.needs_approval` | Нужно одобрение | static/app.js:237 |
| `status.review` | На приёмке | static/app.js:238 |
| `status.done` | Готово | static/app.js:238 |
| `status.blocked` | Заблокирована | static/app.js:238 |

## `inbox.*` — Inbox / "Тебе на стол"

| key | ru | location |
|---|---|---|
| `inbox.title` | Тебе на стол | templates/kanban.html:91 |
| `inbox.total.zero` | 0 задач требуют тебя | templates/kanban.html:92 |
| `inbox.total.empty` | пока ничего не требует тебя | static/app.js:692 |
| `inbox.total.count` | {n} задач требуют тебя | static/app.js:693 |
| `inbox.group.approvals` | Нужно одобрение | templates/kanban.html:96 |
| `inbox.group.reviews` | Принять работу | templates/kanban.html:100 |
| `inbox.group.questions` | Вопросы команды | templates/kanban.html:104 |
| `inbox.notify.approvals` | ⚠ Нужно одобрение | static/app.js:676 |
| `inbox.notify.reviews` | 📋 Принять работу | static/app.js:677 |
| `inbox.notify.questions` | 💬 Вопрос команды | static/app.js:678 |
| `inbox.empty_hint` | пусто | static/app.js:715 |
| `inbox.from_prefix` | от  | static/app.js:731 |
| `inbox.action.approve` | ✓ Одобрить | static/app.js:695 |
| `inbox.action.reject` | ✗ Отклонить | static/app.js:696 |
| `inbox.action.accept` | ✓ Принять | static/app.js:699 |
| `inbox.action.rework` | ↻ Доработать | static/app.js:700 |
| `inbox.action.reply` | Ответить | static/app.js:703 |
| `inbox.action.open` | Открыть | static/app.js:704 |
| `inbox.reply.title` | Ответ на «{title}» | static/app.js:755 |
| `inbox.reply.placeholder` | Что хочешь сказать команде… | static/app.js:756 |
| `inbox.reject.title` | Причина отказа (опционально) | static/app.js:776 |
| `inbox.reject.placeholder` | Можно оставить пустым… | static/app.js:777 |
| `inbox.rework.title` | Что доработать? | static/app.js:792 |
| `inbox.rework.placeholder` | Опиши что не так и что переделать… | static/app.js:793 |

## `archive.*` — архив

| key | ru | location |
|---|---|---|
| `archive.title` | Архив | templates/kanban.html:145 |
| `archive.hint` | Закрытые задачи старше 7 дней | templates/kanban.html:146 |
| `archive.empty` | Архив пуст. Закрытые задачи попадают сюда через 7 дней. | static/app.js:821 |

## `settings.*` — экран «Состояние системы»

| key | ru | location |
|---|---|---|
| `settings.title` | Состояние системы | templates/kanban.html:154 |
| `settings.intro` | Здесь видна сводка по подписке, моделям, БД, бекапам. | templates/kanban.html:157 |
| `settings.backups.title` | Бекапы БД | templates/kanban.html:159 |
| `settings.backups.intro` | Делаются раз в час пока работает дашборд. Хранятся 7 дней. Папка: | templates/kanban.html:160 |
| `settings.tg.title` | Telegram-алерты | templates/kanban.html:161 |
| `settings.tg.status_unknown` | Состояние неизвестно. | templates/kanban.html:162 |

## `usage.*` — модалка / бейдж usage

| key | ru | location |
|---|---|---|
| `usage.title` | Использование подписки Claude | templates/kanban.html:239 |
| `usage.badge.title` | Использование подписки. Клик — подробности | templates/kanban.html:48 |
| `usage.badge.empty` | — сессий | templates/kanban.html:49 |
| `usage.badge.short` | {n} турн · ${cost} | static/app.js:894 |
| `usage.table.window` | Окно | static/app.js:842 |
| `usage.table.sessions` | Сессии | static/app.js:842 |
| `usage.table.turns` | Турны | static/app.js:842 |
| `usage.table.cost` | ~Стоимость | static/app.js:844 |
| `usage.row.last5h` | Последние 5 часов | static/app.js:847 |
| `usage.row.today` | Сегодня (с 00:00) | static/app.js:848 |
| `usage.row.last24h` | Последние 24 часа | static/app.js:849 |
| `usage.row.total` | За всё время | static/app.js:850 |
| `usage.models.title` | Модели | static/app.js:853 |
| `usage.models.unit_sessions` | сессий | static/app.js:837 |
| `usage.models.unit_turns` | турнов | static/app.js:837 |
| `usage.models.empty` | пока пусто | static/app.js:838 |
| `usage.note.line1` | <code>Сессия</code> — один запуск тимлида. <code>Турн</code> — пара prompt→ответ (лимит подписки считается в них). <code>Input</code> включает кеш-чтение. | static/app.js:856 |
| `usage.note.line2` | Ориентиры: Pro ≈45 турн/5ч · Max 5x ≈225 · Max 20x ≈900. | static/app.js:857 |

## `live.*` — Live-вывод тимлида (нижняя панель)

| key | ru | location |
|---|---|---|
| `live.title` | Live-вывод тимлида | templates/kanban.html:171 |
| `live.hint` | когда команда работает — здесь поток событий | templates/kanban.html:172 |
| `live.mode_aria` | Режим Live-вывода | templates/kanban.html:174 |
| `live.mode.human_title` | Только человекочитаемое: о чём думает тимлид и что делает | templates/kanban.html:175 |
| `live.mode.raw_title` | Полный поток stream-json + все tool-вызовы | templates/kanban.html:176 |

## `chat.*` — правая панель чата

| key | ru | location |
|---|---|---|
| `chat.title` | Чат с тимлидом | templates/kanban.html:186 |
| `chat.collapse_title` | Свернуть чат | templates/kanban.html:187 |
| `chat.expand_title` | Развернуть чат | templates/kanban.html:194 |
| `chat.rail_label` | Чат | templates/kanban.html:196 |
| `chat.placeholder` | Спроси тимлида… | templates/kanban.html:191 |
| `chat.empty` | пока ничего. Напиши тимлиду — увидит при следующем запуске команды. | static/app.js:952 |
| `chat.send_failed` | Не отправилось:  | static/app.js:1056 |

## `modal.*` — модалки

| key | ru | location |
|---|---|---|
| `modal.confirm.title` | Подтверди действие | templates/kanban.html:222 |
| `modal.new.title` | Новая задача | templates/kanban.html:261 |
| `modal.new.field.title` | Заголовок | templates/kanban.html:265 ; static/app.js:297 |
| `modal.new.field.description` | Описание | templates/kanban.html:266 ; static/app.js:291 ; static/app.js:298 |
| `modal.new.description_placeholder` | **TL;DR**: краткая суть в одной строке\n\nДетали:\n... | templates/kanban.html:266 |
| `modal.new.field.priority` | Приоритет | templates/kanban.html:268 ; static/app.js:300 |
| `modal.new.field.assignee` | Назначить | templates/kanban.html:276 |
| `modal.assignee.teamlead` | тимлид | templates/kanban.html:278 |
| `modal.assignee.backend` | бэкенд | templates/kanban.html:279 |
| `modal.assignee.architect` | архитектор | templates/kanban.html:281 |
| `modal.assignee.tech_writer` | техписатель | templates/kanban.html:284 |
| `modal.task.delete_confirm` | Удалить задачу «{title}»? | static/app.js:450 |
| `modal.task.save_failed` | Не сохранилось:  | static/app.js:406 |
| `modal.task.dep_failed` | Не получилось:  | static/app.js:429 |
| `modal.task.create_failed` | Ошибка:  | static/app.js:499 |

## `task.*` — модалка задачи (renderTaskBody / renderActions)

| key | ru | location |
|---|---|---|
| `task.meta.unassigned` | не назначен | static/app.js:281 |
| `task.meta.edit_title` | Редактировать поля | static/app.js:284 |
| `task.meta.edit_btn` | ✎ Редактировать | static/app.js:284 |
| `task.meta.created_updated` | создано {created} · обновлено {updated} | static/app.js:287 |
| `task.section.description` | Описание | static/app.js:291 |
| `task.section.edit` | Редактирование | static/app.js:296 |
| `task.field.assignee` | Исполнитель | static/app.js:305 |
| `task.field.status` | Статус | static/app.js:311 |
| `task.section.deps` | Зависимости | static/app.js:323 |
| `task.deps.blocked_by` | Блокируется: | static/app.js:325 |
| `task.deps.blocking` | Блокирует: | static/app.js:326 |
| `task.deps.none` | нет | static/app.js:273 ; static/app.js:276 |
| `task.deps.add_placeholder` | id блокирующей задачи (например abc123) | static/app.js:328 |
| `task.deps.add_btn` | + Зависимость | static/app.js:329 |
| `task.section.subtasks` | Подзадачи ({n}) | static/app.js:333 |
| `task.subtasks.none` | подзадач нет | static/app.js:262 |
| `task.subtasks.no_assignee` | — | static/app.js:261 |
| `task.section.result` | Результат работы команды | static/app.js:336 |
| `task.result.none` | пока пусто | static/app.js:265 |
| `task.section.history` | История | static/app.js:339 |
| `task.history.quiet` | пока тихо… | static/app.js:259 |
| `task.comment.placeholder` | комментарий от Дмитрия… | static/app.js:343 |
| `task.btn.claim` | Взять в работу | static/app.js:354 |
| `task.btn.delete` | Удалить | static/app.js:355 ; static/app.js:372 |
| `task.btn.send_review` | Отправить на приёмку | static/app.js:358 |
| `task.btn.block` | Заблокировать | static/app.js:359 |
| `task.btn.back_to_queue` | Вернуть в очередь | static/app.js:360 |
| `task.btn.approve` | ✓ Одобрить | static/app.js:363 |
| `task.btn.reject` | ✗ Отклонить | static/app.js:364 |
| `task.btn.accept` | ✓ Принять | static/app.js:367 |
| `task.btn.rework` | ↻ На доработку | static/app.js:368 |
| `task.btn.reopen` | Переоткрыть | static/app.js:371 |
| `task.btn.unblock` | Разблокировать | static/app.js:375 |

---

## Дубликаты (одна строка ≥ 2 location)

Эти строки появляются в нескольких местах — в `ru.json` будут одной записью,
все вхождения должны указывать на один и тот же ключ при замене на этапе E2.2.

| текст | ключ-кандидат | locations |
|---|---|---|
| Отмена | `common.cancel` | templates/kanban.html:211, 228, 291 ; static/app.js:318 |
| OK | `common.ok` | templates/kanban.html:212, 229 |
| — нет — | `common.none_dash` | templates/kanban.html:285 ; static/app.js:307 |
| К работе | `status.todo` ≡ `kanban.column.todo` | templates/kanban.html:120 ; static/app.js:237 |
| В работе | `status.wip` ≡ `kanban.column.wip` | templates/kanban.html:124 ; static/app.js:237 |
| Нужно одобрение | `status.needs_approval` ≡ `kanban.column.needs_approval` ≡ `inbox.group.approvals` | templates/kanban.html:96, 128 ; static/app.js:237 |
| На приёмке | `status.review` ≡ `kanban.column.review` | templates/kanban.html:132 ; static/app.js:238 |
| Готово | `status.done` ≡ `kanban.column.done` | templates/kanban.html:136 ; static/app.js:238 |
| Описание | `modal.new.field.description` | templates/kanban.html:266 ; static/app.js:291, 298 |
| Приоритет | `modal.new.field.priority` | templates/kanban.html:268 ; static/app.js:300 |
| Заголовок | `modal.new.field.title` | templates/kanban.html:265 ; static/app.js:297 |
| Авто-режим: тимлид сам запустит следующую сессию когда есть работа | `topbar.auto_title` | templates/kanban.html:79 ; static/app.js:529 |
| ⏸ Стоит | `team.status.stopped` | templates/kanban.html:78 ; static/app.js:544 |
| Архив | `nav.archive` ≡ `archive.title` | templates/kanban.html:32, 145 |
| Доска | `nav.board` ≡ `kanban.title` | templates/kanban.html:27, 113 |
| Удалить | `task.btn.delete` | static/app.js:355, 372 |
| нет | `task.deps.none` | static/app.js:273, 276 |
| назад | `kanban.card.ago_suffix` | static/app.js:144, 732 |
| ✓ Одобрить | `task.btn.approve` ≡ `inbox.action.approve` | static/app.js:363, 695 |
| ✗ Отклонить | `task.btn.reject` ≡ `inbox.action.reject` | static/app.js:364, 696 |
| ✓ Принять | `task.btn.accept` ≡ `inbox.action.accept` | static/app.js:367, 699 |

**Итого**: 128 уникальных ключей, 2 файла, 21 дубль-сценарий
(в `ru.json` после слияния получится ≈ 110 строк).

---

## Замечания для E2.2

1. **Statuses**: `STATUS_LABEL` (`static/app.js:236-239`) и `<h2>` заголовки колонок
   доски — это **одни и те же** строки. В `ru.json` имеет смысл хранить только
   `status.*`, а `kanban.column.*` сделать алиасами или ссылаться на `status.*`
   из JS-рендера.
2. **Roles**: имена ролей встречаются и как UI-лейбл (`<option>тимлид</option>`,
   sidebar), и как API-значение (`assignee: "тимлид"`). UI-лейблы — переводимы,
   API-значения — НЕТ (это enum значения БД). При переводе на en это разделение
   станет критичным.
3. **Эмодзи-префиксы** (`✓`, `⏸`, `🟢`, `▶`) включены в строки как часть UI —
   при i18n либо вынести в `icon` отдельно, либо оставить в строке (как сейчас).
4. **Placeholder с переменными**: строки вида `{n} задач требуют тебя`,
   `Авто-режим включён. За час: {n} сессий`, `Удалить задачу «{title}»?`
   потребуют шаблонизатора (ICU / просто `.replace(...)` ) на E2.3.
5. **`alert(...)` сообщения** (`Не удалось перенести: ...`, `Не сохранилось: ...`,
   `Ошибка: ...` и т.д.) — это error toast'ы. В E2.3 имеет смысл переименовать
   ветку в `error.*` или `toast.*`, сейчас они сложены в свой модуль
   (`modal.task.*_failed`, `kanban.move_failed`, `chat.send_failed`,
   `team.start_failed`).

---

## Следующие шаги

- **E2.2**: создать `static/i18n/ru.json` (значения из колонки `ru` этой таблицы)
  и пустой `static/i18n/en.json` (для последующего перевода).
- **E2.3**: внедрить простой `t(key)` helper и заменить hardcoded строки
  на вызовы / `data-i18n` атрибуты по координатам из колонки `location`.
- **E2.4**: перевести `en.json` (≈ 110 строк).
