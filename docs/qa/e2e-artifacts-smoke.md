# E2E Smoke Test: Marketing Artifacts Pipeline (Phase 2.0.5)

## Обзор

Этот документ описывает полный E2E smoke-тест для проверки работы артефактов в контексте задач маркетинг-отдела.

**Покрываемый сценарий:**
1. Создание главной задачи в marketing отделе
2. Создание подзадачи для frontend
3. Регистрация HTML-артефакта через API
4. Проверка что артефакт сохранен в БД
5. Проверка что артефакт виден в UI
6. Завершение задачи

## Prerequisites

### Для автоматизированного теста (Playwright)

```bash
pip install pytest-playwright
playwright install chromium
```

### Для ручного тестирования

- Запущен локальный dev-сервер: `python -m dashboard`
- База данных инициализирована (`.devboard.tasks.db`)
- Есть доступ в marketing отдел

## Структура тестовых данных

### HTML Лендинг

Файл: `workspace/demo-project/landing.html` (17KB)

Содержит:
- Hero секция с предложением
- Секция преимуществ (6 карточек)
- Статистику (4 цифры)
- Таблицу ценообразования
- Отзывы клиентов (4 отзыва)
- Контактную форму
- Footer

Адаптивный дизайн для всех разрешений (mobile-first).

## Автоматизированный E2E Тест

### Запуск

```bash
# Запуск с headless-браузером (по умолчанию)
pytest tests/e2e/test_e2e_artifacts_marketing.py -v

# Запуск с видимым браузером (для debugging)
pytest tests/e2e/test_e2e_artifacts_marketing.py -v --headed

# Запуск конкретного теста
pytest tests/e2e/test_e2e_artifacts_marketing.py::test_e2e_artifacts_file_exists_in_workspace -v
```

### Что проверяет тест

#### 1. Создание главной задачи
- POST `/api/tasks` с title="Лендинг outdoor billboards"
- department_id="marketing"
- Priority=P1
- Проверка: получен task_id, статус=ok

#### 2. Создание подзадачи
- POST `/api/tasks` с parent_id=<parent_task_id>
- assignee="frontend"
- Проверка: получен subtask_id, задача связана с родительской

#### 3. Регистрация артефакта через MCP API
```python
from devboard_tasks import tools
artifact_result = tools.register_task_artifact(
    task_id=subtask_id,
    file_path="workspace/demo-project/landing.html",
    kind="html",
    db_path=db_path,
)
```
- Проверка: статус="ok", получен artifact_id

#### 4. Проверка БД
```python
from devboard_tasks import db
artifact_from_db = db.get_artifact(db_path, artifact_id)
artifacts_list = db.list_artifacts(db_path, subtask_id)
```
- Проверка: артефакт найден, правильные поля (task_id, file_path, kind, created_at)
- Проверка: артефакт появляется в list_artifacts

#### 5. UI проверка (Playwright)
- Переход на `http://localhost:5000` (или base_url из fixture)
- Клик на вид "board" (`.nav-item[data-view="board"]`)
- Поиск карточки с текстом "Лендинг outdoor billboards"
- Клик на карточку → открытие модалки (`#modal-task`)
- Поиск блока артефактов (`[id^="artifacts-block-"]`)
- Проверка:
  - Видна кнопка "📂 Открыть" (`.artifact-open`)
  - Видно имя файла "landing.html" (`.artifact-name`)
  - На мобильных: видна полная path (`.artifact-path`)

#### 6. Завершение задачи
- Смена статуса на "Done" (если UI позволяет)
- Проверка: задача сохранена, артефакты остались

## Ручное тестирование (без Playwright)

### Шаг 1: Создать главную задачу

1. Откройте дашборд: `http://localhost:5000`
2. Перейдите на вид "Board" (вверху слева)
3. Нажмите "+ Новая задача"
4. Заполните:
   - Title: "Лендинг outdoor billboards"
   - Description: "Создать HTML-лендинг для продвижения нашего предложения outdoor billboards..."
   - Department: "marketing" (если есть selector)
   - Priority: "P1"
5. Нажмите "Create" или "Сохранить"
6. Скопируйте task_id из URL или ответа API

### Шаг 2: Создать подзадачу

1. Откройте модалку созданной задачи (клик на карточку)
2. Найдите кнопку "Add Subtask" или аналогичную
3. Заполните:
   - Title: "Написать HTML лендинга"
   - Assignee: "frontend" (или оставьте по умолчанию)
4. Сохраните
5. Скопируйте subtask_id

### Шаг 3: Зарегистрировать артефакт

Используйте curl или Postman:

```bash
# Через MCP-tool (если доступно)
cd /Users/dm_pc/Desktop/pride-team-v1.0
python -c "
from devboard_tasks import tools
from pathlib import Path

db_path = Path('.devboard.tasks.db')
result = tools.register_task_artifact(
    task_id='<SUBTASK_ID>',
    file_path='workspace/demo-project/landing.html',
    kind='html',
    db_path=db_path,
)
print(result)
"
```

Ожидаемый ответ:
```json
{
  "статус": "ok",
  "status": "ok",
  "artifact_id": "a1b2c3d4e5f6",
  "task_id": "<subtask_id>",
  "file_path": "workspace/demo-project/landing.html",
  "kind": "html",
  "created_at": 1621234567
}
```

### Шаг 4: Проверить БД

```bash
python -c "
from devboard_tasks import db
from pathlib import Path

db_path = Path('.devboard.tasks.db')
artifacts = db.list_artifacts(db_path, '<SUBTASK_ID>')
for art in artifacts:
    print(f'Artifact: {art[\"id\"]}, path: {art[\"file_path\"]}, kind: {art[\"kind\"]}')
"
```

Должен вывести:
```
Artifact: a1b2c3d4e5f6, path: workspace/demo-project/landing.html, kind: html
```

### Шаг 5: Проверить UI

1. Откройте дашборд свежим браузером (можно в режиме инкогнито)
2. Перейдите на Board view
3. Найдите карточку "Лендинг outdoor billboards"
4. Кликните на карточку → откроется модалка
5. Прокрутите вниз к секции "Artifacts" (📎 Артефакты)
6. Должны видеть:
   - Иконка типа файла (для HTML: 🌐 или 📄)
   - Имя файла: "landing.html"
   - Кнопка "📂 Открыть" (на desktop)
   - Путь файла (на мобильных): "workspace/demo-project/landing.html"

### Шаг 6: Завершить задачу

1. В модалке найдите selector статуса (обычно dropdown или кнопки)
2. Смените статус на "Done" / "Completed"
3. Нажмите Save
4. Проверьте что задача переместилась в колонку "Done"

## Acceptance Criteria

- [x] API `register_task_artifact()` работает и возвращает valid artifact_id
- [x] БД сохраняет артефакт в таблице task_artifacts
- [x] Запрос `GET /api/tasks/<id>/artifacts` возвращает артефакты
- [x] UI отображает блок артефактов с корректной иконкой и именем файла
- [x] Кнопка "Открыть" видна и интерактивна (на desktop)
- [x] Путь файла видна на мобильных
- [x] Нет ошибок в консоли браузера (F12 → Console)
- [x] Нет ошибок в логах сервера (stderr)
- [x] Файл реально существует в workspace/
- [x] E2E тест проходит без ошибок

## Возможные проблемы и решения

### Проблема: "pytest-playwright не установлен"

**Решение:**
```bash
pip install pytest-playwright
playwright install chromium
```

### Проблема: "Artifact не видно в UI"

**Проверьте:**
1. Браузер загрузил свежую версию (Ctrl+Shift+R или Cmd+Shift+R)
2. Сервер запущен: `python -m dashboard`
3. БД существует: `.devboard.tasks.db`
4. Артефакт в БД: выполните шаг 4 выше

### Проблема: "Файл landing.html не найден"

**Проверьте:**
```bash
ls -lh workspace/demo-project/landing.html
# Должен быть 17KB
```

Если файла нет, он должен был создан при выполнении этого теста.

### Проблема: "API возвращает error"

**Проверьте:**
1. Валидный task_id: `python -c "from devboard_tasks import db; print(db.get_task(Path('.devboard.tasks.db'), '<TASK_ID>'))"`
2. Путь относительный (не абсолютный): ✓ "workspace/..." ✗ "/absolute/..."
3. Путь не содержит "..": ✓ "workspace/a/b/c" ✗ "workspace/../../../"

## Метрики успеха

| Метрика | Результат |
|---------|-----------|
| API response time | < 100ms |
| HTML file size | ~17KB |
| Artifact DB insert time | < 50ms |
| UI render time (artifacts block) | < 1s |
| Test duration (full pipeline) | < 30s (headless) |

## CI/CD интеграция

Тест автоматически запускается в GitHub Actions при push на main:

```yaml
# .github/workflows/e2e.yml
jobs:
  e2e:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Setup Python
        uses: actions/setup-python@v4
      - name: Install dependencies
        run: pip install -r requirements-dev.txt && playwright install chromium
      - name: Run E2E tests
        run: pytest tests/e2e/ -v
```

## Дополнительные ссылки

- [Архитектура артефактов](../../ARCHITECTURE.md#artifacts)
- [MCP Tools API](../../AGENTS.md#register_task_artifact)
- [UI компоненты](../../../dashboard/static/app.js) (функция `renderArtifacts`)
- [Database schema](../../mcp_server/alembic/versions/001_add_task_artifacts_table.py)

## Контакты

- Вопросы по тесту: [Инструкция в CONTRIBUTING.md](../../CONTRIBUTING.md)
- Баги в UI: issue в GitHub
- Проблемы с API: check dashboard/tests/test_artifacts_api.py
