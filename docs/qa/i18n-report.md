# QA i18n report (E2.5)

> Статический + динамический аудит локализации дашборда после волны E2.1–E2.4.
> Автор: QA-subagent. Дата: 2026-05-22.
> Связанные подзадачи: E2.1 (`docs/i18n-audit.md`), E2.2 (`ru.json`/`en.json`),
> E2.3 (`i18n.js`), E2.4 (`locale-switcher.js`).

## TL;DR — вердикт

**partial-pass.**

* Sync `ru.json` ↔ `en.json` — **OK** (198/198 ключей идентичны, нет пустых,
  нет TODO, нет «оверсайз» EN-строк).
* Smoke рендера — **OK** (`HTTP 200`, статика 200 для всех ассетов, JSON-словари
  парсятся, нет голых `[i18n.missing]` / `undefined` / `null` на странице).
* Hardcoded strings — **FAIL**. Шаблон `kanban.html` и весь `static/app.js`
  фактически **не подключены к i18n-инфраструктуре**: всего 5 `data-i18n` и
  3 `data-i18n-attr` на всю страницу (плюс кнопки локали-свитчера).
  Остальные ≥130 строк остаются hardcoded RU и не переключаются на EN.

Инфраструктура (loader + switcher + JSON-словари) рабочая и проверена.
Но **wire-up шаблона/JS на i18n-loader пока не сделан** — это явный
скоп для отдельной задачи (см. §«Bugs for frontend» в конце).

---

## 1. Synchronization status (ru.json ↔ en.json)

Скрипт: flatten dot-path → set-diff → empty/TODO scan → length-ratio scan.

| метрика | значение |
|---|---|
| Всего ключей RU | **198** |
| Всего ключей EN | **198** |
| `only in RU` | 0 |
| `only in EN` | 0 |
| Пустые значения (`""`) | 0 (в обеих локалях) |
| Маркеры TODO / FIXME / XXX | 0 |
| EN-строк >150% длины RU (с дельтой >8 символов) | 0 |
| EN-строк где RU=="" но EN!="" | 0 |
| Идентичных RU == EN | 7 (намеренно — см. ниже) |

### Идентичные RU == EN (false-positives, не баги)

| key | value |
|---|---|
| `common.ok` | `OK` |
| `nav.brand` | `Praid` |
| `nav.inbox` | `Inbox` |
| `topbar.locale.en_title` | `English` |
| `sidebar.role.qa` | `qa` |
| `sidebar.role.devops` | `devops` |
| `sidebar.role.frontend` | `frontend` |

Это допустимо: бренд, заимствованные/латинские термины и роли,
которые в проекте всегда пишутся латиницей даже в RU-UI.

### Замечание про namespace coverage vs E2.1

E2.1 насчитал 128 уникальных ключей. E2.2 положил 198 ключей в JSON
(больше — потому что E2.2 добавил `onboarding.tour.*` для тура, плюс
`topbar.locale.*` для свитчера, добавленного в E2.4). Это OK,
расхождение объясняется растущим скоупом.

---

## 2. Hardcoded strings findings

### Метод

```bash
grep -nE "[А-Яа-яЁё]+" дашборд/templates/*.html дашборд/static/js/*.js \
                       дашборд/static/app.js дашборд/static/css/*.css
```

Затем ручная классификация: комментарий / `data-i18n` fallback / hardcoded.

### Сводка по файлам

| файл | всего вхождений кириллицы | из них hardcoded UI-строк |
|---|---|---|
| `дашборд/templates/kanban.html` | ~75 | **~58** (см. таблицу ниже) |
| `дашборд/static/app.js` | 140 | **~75** |
| `дашборд/static/js/tour.js` | ~35 | 0 (только fallback-литералы внутри `i18n*Title/Body`-объектов + комменты) |
| `дашборд/static/js/locale-switcher.js` | ~25 | 0 (только комменты) |
| `дашборд/static/js/i18n.js` | 0 | 0 |
| `дашборд/static/css/tour.css` | ~12 | 0 (только комменты) |
| `дашборд/static/style.css` | ~25 | 0 (только комменты + CSS-селекторы вида `.author-тимлид`) |

### 2.1. `kanban.html` — hardcoded UI-тексты без `data-i18n`

Только 8 элементов в шаблоне имеют `data-i18n*` атрибуты (kanban.html:75–77,
134, 135, 148, 164, 175). Всё остальное — hardcoded RU. severity = **P1**
(всё видно сразу при переключении локали на EN).

| location | строка | предложение ключа | severity |
|---|---|---|---|
| `kanban.html:5` | `<title>pride-team · малая команда</title>` | `page.title` (уже в JSON!) — добавить `<title data-i18n="page.title">` либо рендерить на сервере | P1 |
| `kanban.html:23` | `Inbox` | `nav.inbox` (уже в JSON) — `data-i18n` | P1 |
| `kanban.html:28` | `Доска` | `nav.board` | P1 |
| `kanban.html:33` | `Архив` | `nav.archive` | P1 |
| `kanban.html:38` | `Состояние` | `nav.settings` | P1 |
| `kanban.html:45` | `title="Тимлид завершил…"` + текст `тимлид молчит` | `team.silence.title` / `team.silence.label` (есть в JSON) | P1 |
| `kanban.html:46` | `title="Модель которую роутер выберет"` | `team.router.title` | P1 |
| `kanban.html:49` | `title="Использование подписки. Клик — подробности"` + `— сессий` | `usage.badge.title` / `usage.badge.empty` | P1 |
| `kanban.html:53` | `Команда` | `sidebar.team` | P1 |
| `kanban.html:54-60` | `🧭 тимлид`, `🔧 бэкенд`, …, `📝 техписатель` | `sidebar.role.*` (все есть в JSON) | P1 |
| `kanban.html:71` | `+ Новая задача` | `topbar.new_task` | P1 |
| `kanban.html:72` | `placeholder="Поиск по заголовку…"` | `topbar.search_placeholder` (через `data-i18n-attr`) | P1 |
| `kanban.html:79` | `aria-label="Тема"` | `topbar.theme_aria` (через `data-i18n-attr`) | P2 |
| `kanban.html:80-81` | `title="Светлая тема"` / `title="Тёмная тема"` | `topbar.theme_light` / `topbar.theme_dark` | P2 |
| `kanban.html:83` | `⏸ Стоит` | `team.status.stopped` | P1 |
| `kanban.html:84` | `title="Авто-режим: тимлид сам…"` | `topbar.auto_title` | P1 |
| `kanban.html:86` | `🤖 Авто` | `topbar.auto_label` | P1 |
| `kanban.html:88` | `▶ Запустить команду` | `topbar.btn_start` | P1 |
| `kanban.html:89` | `⏹ Остановить` | `topbar.btn_stop` | P1 |
| `kanban.html:96` | `Тебе на стол` | `inbox.title` | P1 |
| `kanban.html:97` | `0 задач требуют тебя` | `inbox.total.zero` (или динамически через JS) | P1 |
| `kanban.html:101` | `Нужно одобрение` | `inbox.group.approvals` | P1 |
| `kanban.html:105` | `Принять работу` | `inbox.group.reviews` | P1 |
| `kanban.html:109` | `Вопросы команды` | `inbox.group.questions` | P1 |
| `kanban.html:118` | `Доска` (h1) | `kanban.title` | P1 |
| `kanban.html:120` | `показывать пустые колонки` | `kanban.show_empty` | P1 |
| `kanban.html:125` | `К работе` + `title="Задачи ещё не взяты в работу"` | `kanban.column.todo` / `kanban.column.todo_title` | P1 |
| `kanban.html:139` | `В работе` + title | `kanban.column.wip` / `kanban.column.wip_title` | P1 |
| `kanban.html:152` | `Нужно одобрение` + title | `kanban.column.needs_approval(_title)` | P1 |
| `kanban.html:156` | `На приёмке` + title | `kanban.column.review(_title)` | P1 |
| `kanban.html:168` | `Готово` + title | `kanban.column.done(_title)` | P1 |
| `kanban.html:184` | `Архив` (h1) | `archive.title` | P1 |
| `kanban.html:185` | `Закрытые задачи старше 7 дней` | `archive.hint` | P1 |
| `kanban.html:193` | `Состояние системы` | `settings.title` | P1 |
| `kanban.html:196` | `Здесь видна сводка…` | `settings.intro` | P1 |
| `kanban.html:198` | `Бекапы БД` | `settings.backups.title` | P1 |
| `kanban.html:199` | `Делаются раз в час…` | `settings.backups.intro` | P1 |
| `kanban.html:200` | `Telegram-алерты` | `settings.tg.title` | P1 |
| `kanban.html:201` | `Состояние неизвестно.` | `settings.tg.status_unknown` | P1 |
| `kanban.html:210` | `Live-вывод тимлида` | `live.title` | P1 |
| `kanban.html:211` | `когда команда работает — здесь поток событий` | `live.hint` | P1 |
| `kanban.html:213` | `aria-label="Режим Live-вывода"` | `live.mode_aria` | P2 |
| `kanban.html:214-215` | `title="Только человекочитаемое…"` / `title="Полный поток stream-json…"` | `live.mode.human_title` / `live.mode.raw_title` | P1 |
| `kanban.html:225` | `Чат с тимлидом` | `chat.title` | P1 |
| `kanban.html:226` | `title="Свернуть чат"` | `chat.collapse_title` | P2 |
| `kanban.html:230` | `placeholder="Спроси тимлида…"` | `chat.placeholder` | P1 |
| `kanban.html:233` | `title="Развернуть чат"` | `chat.expand_title` | P2 |
| `kanban.html:235` | `Чат` (rail-label) | `chat.rail_label` | P1 |
| `kanban.html:250` | `Отмена` (prompt-cancel) | `common.cancel` | P1 |
| `kanban.html:261` | `Подтверди действие` | `modal.confirm.title` | P1 |
| `kanban.html:267` | `Отмена` (confirm-cancel) | `common.cancel` | P1 |
| `kanban.html:278` | `Использование подписки Claude` | `usage.title` | P1 |
| `kanban.html:300` | `Новая задача` | `modal.new.title` | P1 |
| `kanban.html:304` | `Заголовок<input…>` | `modal.new.field.title` | P1 |
| `kanban.html:305` | `Описание<textarea…>` + `placeholder="**TL;DR**: краткая…"` | `modal.new.field.description` / `modal.new.description_placeholder` | P1 |
| `kanban.html:307` | `Приоритет` | `modal.new.field.priority` | P1 |
| `kanban.html:315` | `Назначить` | `modal.new.field.assignee` | P1 |
| `kanban.html:317-323` | options `тимлид`, `бэкенд`, …, `техписатель` | Это **value=**`"тимлид"` — это API-значение, не UI-текст. Отображаемый текст можно локализовать через `modal.assignee.*`. severity = **P3** | P3 |
| `kanban.html:324` | `<option value="">— нет —</option>` | `common.none_dash` | P1 |
| `kanban.html:330` | `Отмена` (modal-new) | `common.cancel` | P1 |
| `kanban.html:331` | `Создать` | `common.create` | P1 |

### 2.2. `app.js` — hardcoded в динамически-генерируемом HTML

| location | строка | предложение ключа | severity |
|---|---|---|---|
| `app.js:113-116` | `"с"`, `"м"`, `"ч"`, `"д"` (shortAge unit suffix) | `kanban.card.age.sec/.min/.hour/.day` (есть в JSON) | P1 |
| `app.js:133` | `title="есть зависимости"` | `kanban.card.has_deps` | P2 |
| `app.js:144` | `${shortAge} назад` | `kanban.card.ago_suffix` | P1 |
| `app.js:168` | `"пусто — перетащи карточку сюда"` | `kanban.col_empty` | P1 |
| `app.js:236` | `alert("Не удалось перенести: " + …)` | `kanban.move_failed` | P1 |
| `app.js:244-247` | `STATUS_LABEL` map (RU labels for todo/wip/…) | `status.*` (есть в JSON) — заменить map на вызов `t('status.'+s)` | P0 (используется в нескольких местах) |
| `app.js:260-261` | `toLocaleString("ru-RU")` | хардкод-локаль; нужно `getLocale()==='en' ? 'en-US' : 'ru-RU'` | P2 |
| `app.js:264` | `toLocaleTimeString("ru-RU")` | то же | P2 |
| `app.js:267` | `пока тихо…` | `task.history.quiet` | P1 |
| `app.js:269` | `"—"` (no assignee) | `task.subtasks.no_assignee` | P3 |
| `app.js:270` | `подзадач нет` | `task.subtasks.none` | P1 |
| `app.js:273` | `пока пусто` | `task.result.none` | P1 |
| `app.js:281-284` | `нет` (deps) | `task.deps.none` | P1 |
| `app.js:289` | `не назначен` | `task.meta.unassigned` | P1 |
| `app.js:292` | `title="Редактировать поля"` + `✎ Редактировать` | `task.meta.edit_title` / `task.meta.edit_btn` | P1 |
| `app.js:295` | `создано {created} · обновлено {updated}` | `task.meta.created_updated` (есть в JSON) | P1 |
| `app.js:299` | `Описание` (h3) | `task.section.description` | P1 |
| `app.js:304` | `Редактирование` (h3) | `task.section.edit` | P1 |
| `app.js:305-306` | `Заголовок` / `Описание` (labels) | `modal.new.field.title` / `…description` | P1 |
| `app.js:308` | `Приоритет` | `modal.new.field.priority` | P1 |
| `app.js:313` | `Исполнитель` | `task.field.assignee` | P1 |
| `app.js:315` | `— нет —` | `common.none_dash` | P1 |
| `app.js:316` | options list `["тимлид","бэкенд",…]` | API-values; UI = `modal.assignee.*` | P3 |
| `app.js:319` | `Статус` | `task.field.status` | P1 |
| `app.js:326-327` | `Отмена` / `Сохранить` | `common.cancel` / `common.save` | P1 |
| `app.js:331` | `Зависимости` (h3) | `task.section.deps` | P1 |
| `app.js:333-334` | `Блокируется:` / `Блокирует:` | `task.deps.blocked_by` / `task.deps.blocking` | P1 |
| `app.js:336` | `placeholder="id блокирующей задачи (например abc123)"` | `task.deps.add_placeholder` | P1 |
| `app.js:337` | `+ Зависимость` | `task.deps.add_btn` | P1 |
| `app.js:341` | `Подзадачи (${n})` | `task.section.subtasks` (с `{n}`) | P1 |
| `app.js:344` | `Результат работы команды` | `task.section.result` | P1 |
| `app.js:347` | `История` (h3) | `task.section.history` | P1 |
| `app.js:351` | `placeholder="комментарий от Дмитрия…"` | `task.comment.placeholder` | P1 |
| `app.js:352` | `Добавить` | `common.add` | P1 |
| `app.js:362-383` | все 11 действий: `Взять в работу`, `Удалить`, `Отправить на приёмку`, … | `task.btn.*` (все есть в JSON!) | P0 |
| `app.js:414` | `alert("Не сохранилось: " …)` | `modal.task.save_failed` | P1 |
| `app.js:437` | `alert("Не получилось: " …)` | `modal.task.dep_failed` | P1 |
| `app.js:458` | `customConfirm("Удалить задачу «" + … + "»?")` | `modal.task.delete_confirm` (с `{title}`) | P1 |
| `app.js:507` | `alert("Ошибка: " …)` | `modal.task.create_failed` | P1 |
| `app.js:538-541` | `Авто-режим включён. За час: …` / `Авто-режим: тимлид…` | `team.auto.enabled` / `team.auto.paused` / `topbar.auto_title` | P1 |
| `app.js:546,551,556` | `🟢 Работает` / `⏳ Авто-пауза` / `⏸ Стоит` | `team.status.running` / `…auto_paused` / `…stopped` | P1 |
| `app.js:593` | `alert("Не удалось запустить: " …)` | `team.start_failed` | P1 |
| `app.js:688-690` | `⚠ Нужно одобрение` / `📋 Принять работу` / `💬 Вопрос команды` (notify titles) | `inbox.notify.approvals/.reviews/.questions` | P1 |
| `app.js:704-705` | `пока ничего не требует тебя` / `${n} задач требуют тебя` | `inbox.total.empty` / `inbox.total.count` | P1 |
| `app.js:707-716` | inbox actions: `✓ Одобрить`, `✗ Отклонить`, `✓ Принять`, `↻ Доработать`, `Ответить`, `Открыть` | `inbox.action.*` | P1 |
| `app.js:727` | `пусто` (inbox-empty-hint) | `inbox.empty_hint` | P1 |
| `app.js:743` | `от {author}` | `inbox.from_prefix` | P1 |
| `app.js:744` | `${shortAge} назад` | `kanban.card.ago_suffix` | P1 |
| `app.js:767-769` | `Ответ на «${title}»` + `placeholder="Что хочешь сказать команде…"` | `inbox.reply.title` / `…placeholder` | P1 |
| `app.js:788-789` | `Причина отказа (опционально)` + `Можно оставить пустым…` | `inbox.reject.title` / `…placeholder` | P1 |
| `app.js:804-805` | `Что доработать?` + `Опиши что не так и что переделать…` | `inbox.rework.title` / `…placeholder` | P1 |
| `app.js:833` | `Архив пуст. Закрытые задачи попадают сюда через 7 дней.` | `archive.empty` | P1 |
| `app.js:849` | `${n} сессий · ${n} турнов` | `usage.models.unit_sessions` / `…unit_turns` | P1 |
| `app.js:850` | `пока пусто` (models list) | `usage.models.empty` | P1 |
| `app.js:854-856` | `Окно` / `Сессии` / `Турны` / `~Стоимость` | `usage.table.*` | P1 |
| `app.js:859-862` | `Последние 5 часов` / `Сегодня (с 00:00)` / `Последние 24 часа` / `За всё время` | `usage.row.*` | P1 |
| `app.js:865` | `Модели` (h3) | `usage.models.title` | P1 |
| `app.js:868-869` | `<code>Сессия</code> — один запуск…` / `Ориентиры: Pro ≈45…` | `usage.note.line1` / `usage.note.line2` (есть в JSON, обе содержат `<code>`-разметку — нужен `innerHTML`, не `textContent`) | P1 |
| `app.js:889` | `Авто-роутер моделей.\nВыбор: …\nЗадач: … (архи …, тривиальных …, прочее …)` | `team.router.tooltip` (с placeholder'ами `{alias}`, `{reason}`, `{total}`, `{arch}`, `{triv}`, `{other}`) | P1 |
| `app.js:906` | `${turns} турн · $${cost}` | `usage.badge.short` (есть в JSON, с `{n}`/`{cost}`) | P1 |
| `app.js:964` | `пока ничего. Напиши тимлиду — увидит при следующем запуске команды.` | `chat.empty` | P1 |
| `app.js:969` | `toLocaleTimeString("ru-RU", {…})` | locale-aware вариант | P2 |
| `app.js:1068` | `alert("Не отправилось: " …)` | `chat.send_failed` | P1 |

### 2.3. Локали в `toLocaleString` — баг доступности

В `app.js:260, 261, 264, 845, 846, 969` дата/число форматируются жёстко
с `"ru-RU"`. При переключении на EN формат остаётся русский (через запятую,
24-часовой). Надо завернуть в helper:

```js
function localeTag() {
  return (window.getLocale && window.getLocale() === 'en') ? 'en-US' : 'ru-RU';
}
```

severity = **P2** (косметика, но видно при EN-локали).

### 2.4. `tour.js` — допустимый паттерн, замечание

Файл содержит RU-fallback'и (`fallbackTitle: 'Привет!…'` и т.п.) — это
**не баг**: они срабатывают только если `window.t()` ещё не загружен.
Однако:

* Fallback всегда **на RU**, даже если `navigator.language === 'en'`.
  Это означает, что при первом запуске на EN-машине пользователь
  увидит RU-текст и сразу после fetch'а локали EN-словарь заменит его.
  Кратко (≤500 мс) — приемлемо. severity = **P3** (не критично).
* В шаблоне popover'а (tour.js:180,182,183) текст `Пропустить/Назад/Далее`
  уже помечен `data-i18n="onboarding.tour.skip/prev/next"` — это OK.

### 2.5. `style.css` — false-positives

Селекторы вида `.chat-message.author-тимлид`, `.author-бэкенд`, … — это
имена классов, привязанные к данным API (`author=="тимлид"`). Это не UI-текст,
менять не надо. severity = **OK**.

---

## 3. Rendering smoke

### Метод

1. `cd дашборд && PRIDE_DASHBOARD_PORT=5050 .venv/bin/python app.py &`
2. `curl -s http://127.0.0.1:5050/ > /tmp/page.html`
3. Анализ страницы + проверка статических ассетов.

### Результат

| проверка | результат |
|---|---|
| `GET /` | **HTTP 200** (16 546 байт) |
| `<html lang="…">` присутствует | **да**, `lang="ru"` |
| `data-i18n="…"` на странице | **5 вхождений** (только `kanban.empty.*`) |
| `data-i18n-attr="…"` на странице | **3 вхождения** (locale switcher) |
| Голые `[i18n.missing]` / `undefined` / `null` в HTML | **0** |
| `GET /static/i18n/ru.json` | HTTP 200, 12 724 байта, валидный JSON |
| `GET /static/i18n/en.json` | HTTP 200, 9 361 байта, валидный JSON |
| `GET /static/js/i18n.js` | HTTP 200 |
| `GET /static/js/locale-switcher.js` | HTTP 200 |
| `GET /static/app.js` | HTTP 200 |
| `Accept-Language: en-US` влияет на `<html lang>` | **нет** (всегда `ru`) — это OK, лангвитч в i18n.js клиентский |

### Логика default-locale (статический разбор `i18n.js`)

```
saved = localStorage.getItem('locale')
nav = (navigator.language || 'ru').slice(0, 2)
lang = saved || nav
final = (lang === 'en') ? 'en' : 'ru'
```

Все локали кроме явного `'en'` сваливаются в `'ru'`. Это норм для текущего
скоупа двух языков, но если в будущем появится третий — потребуется
white-list. Сейчас **не баг**.

### Edge-cases (статически)

* Если `localStorage` недоступен (приватный режим / iframe sandbox) — try/catch
  глотает ошибку и читает `navigator.language`. **OK**.
* Если `/static/i18n/en.json` 404 — fallback на `ru`. **OK**.
* Если ключа нет в словаре — `t()` возвращает сам ключ как строку.
  Это значит, что при опечатке в `data-i18n="foo.bar.baz"` на странице
  появится текст `foo.bar.baz` (вместо переведённого). Не голый `null`,
  но всё-таки заметная регрессия — лучше бы fallback на исходный text
  узла (он уже это делает в `applyToDOM`, см. `i18n.js:73-77`). **OK**.

---

## 4. Checklist по экранам

| экран | static check | smoke | вердикт |
|---|---|---|---|
| Sidebar (nav + footer + team-roles) | RU hardcoded (≥10 строк) | рендерится из шаблона | **fail** — wire-up not done |
| Topbar (search, theme, locale, auto, start/stop) | RU hardcoded (≥10 строк) | рендерится | **fail** |
| Inbox view | RU hardcoded (~7 строк в шаблоне + динамически из `app.js`) | рендерится | **fail** |
| Kanban board (columns + cards + empty-state) | empty-state — переключается; колонки + карточки — hardcoded | рендерится; data-i18n работает для empty-state | **partial-pass** |
| Archive view | RU hardcoded (~3 строки в шаблоне + динамически в `app.js`) | рендерится | **fail** |
| Settings/State view | RU hardcoded (~7 строк в шаблоне + динамически в `app.js`) | рендерится | **fail** |
| Live panel | RU hardcoded (~5 строк) | рендерится | **fail** |
| Chat panel | RU hardcoded (~6 строк) | рендерится | **fail** |
| Modals (prompt/confirm/usage/task/new-task) | RU hardcoded (~15 строк) | рендерятся (скрыты) | **fail** |
| Onboarding tour | rendering: fallback RU + EN после fetch | не проверен в браузере, но статически — ok | **pass** |
| Locale switcher | `data-i18n-attr` для title работает | визуально кнопки RU/EN видны | **pass** |

---

## 5. Bugs for frontend (создать подзадачи)

Тимлид, вот список багов которые имеет смысл оформить отдельными подзадачами
для фронтенда. **Я подзадачи не создаю** (нет MCP-доступа) — это по твоей
части.

### Bug #1 (P0, blocker for E2). Wire `kanban.html` to i18n keys

**TL;DR**: шаблон `kanban.html` использует `data-i18n*` всего на 8 узлах
из ~70. Все остальные ~58 строк RU хардкод. EN-локаль фактически не работает
для всего, кроме kanban-empty-state и тура.

**Шаги воспроизведения**: запустить дашборд, переключить локаль на EN —
поменяется только текст внутри пустых колонок канбана. Всё остальное
останется на RU.

**Ожидание**: все user-facing тексты переключаются.

**Файл**: `дашборд/templates/kanban.html`.

**Скоуп** (см. §2.1 этого отчёта): ~58 пометок `data-i18n`/`data-i18n-attr`
с уже готовыми ключами в `ru.json`/`en.json`. Ключи **уже все есть** —
надо только проставить атрибуты в HTML.

### Bug #2 (P0, blocker for E2). Wire dynamic HTML in `app.js` to `t()`

**TL;DR**: `app.js` генерирует HTML карточек / модалок / списка inbox /
usage-таблицы и т.п. через template literals, в которых hardcoded ~75 RU-строк.
Не вызывает `window.t()` ни разу (`grep -c "window.t(" app.js` == 0).

**Файл**: `дашборд/static/app.js`.

**Скоуп** (см. §2.2): для каждого литерала заменить на `${t('ns.key', {…})}`.
Особенно важны:

* `STATUS_LABEL` map → динамически из `t('status.<key>')`.
* `renderActions()` — 11 кнопок.
* `refreshTeamStatus()` — статусы команды + auto-режим.
* `renderInbox()` / `renderInboxGroup()` — заголовки секций, действия, hint'ы.
* `loadSettings()` — usage-таблица.
* `loadArchive()` — empty-state.
* Все `alert(...)` сообщения об ошибках.
* `customConfirm/Prompt` — заголовки и плейсхолдеры.

Дополнительно: подписаться на `window.addEventListener('localechange', …)`
и при смене локали ререндерить открытую модалку / inbox / settings,
чтобы не приходилось рефрешить страницу.

### Bug #3 (P2). Дата/время не локализуются

**TL;DR**: `toLocaleString("ru-RU")` / `toLocaleTimeString("ru-RU")` в
`app.js:260, 261, 264, 845, 846, 969` хардкодит ru-RU. При EN-локали
формат остаётся русский.

**Файл**: `дашборд/static/app.js`.

**Фикс**: helper `function dtLocale(){ return getLocale()==='en' ? 'en-US' : 'ru-RU' }`
и заменить везде.

### Bug #4 (P3, минор). Tour fallback всегда на RU

**TL;DR**: `tour.js` при недозагруженном `window.t()` показывает RU-fallback
даже на EN-машине (≤500 мс). Не блокер, но при медленной сети заметно.

**Файл**: `дашборд/static/js/tour.js`.

**Фикс (вариант)**: подождать `localechange`/`DOMContentLoaded` перед автозапуском,
ИЛИ детектить `navigator.language` и иметь два набора fallback'ов.
Самый простой — отложить старт тура до `window.applyI18nToDOM()` (одна
дополнительная микрозадержка).

---

## Аппендикс A. Команды воспроизведения

```bash
# 1. Sync audit
cd /Users/dm_pc/Desktop/pride-team-v1.0
python3 - <<'PY'
import json
ru = json.load(open("дашборд/static/i18n/ru.json"))
en = json.load(open("дашборд/static/i18n/en.json"))
def flat(d, p=""):
    out = {}
    for k, v in d.items():
        kk = f"{p}.{k}" if p else k
        if isinstance(v, dict): out.update(flat(v, kk))
        else: out[kk] = v
    return out
rf, ef = flat(ru), flat(en)
print("RU:", len(rf), "EN:", len(ef))
print("only RU:", set(rf) - set(ef))
print("only EN:", set(ef) - set(rf))
PY

# 2. Hardcoded grep
grep -nE "[А-Яа-яЁё]+" дашборд/templates/*.html дашборд/static/js/*.js дашборд/static/app.js дашборд/static/css/*.css

# 3. Smoke
cd дашборд
PRIDE_DASHBOARD_PORT=5050 .venv/bin/python app.py &
sleep 3
curl -s http://127.0.0.1:5050/ > /tmp/page.html
curl -s -o /dev/null -w "ru.json=%{http_code} en.json=" http://127.0.0.1:5050/static/i18n/ru.json
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:5050/static/i18n/en.json
grep -oE 'data-i18n="[^"]+"' /tmp/page.html | wc -l
grep -oE '<html[^>]*' /tmp/page.html
kill %1
```
