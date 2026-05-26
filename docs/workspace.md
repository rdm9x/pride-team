# Workspace Infrastructure

## Описание

`workspace/` — это директория для хранения артефактов задач (файлы, логи, результаты обработки) в режиме работы тимлида и других ролей.

**Структура:**
```
workspace/
├── .gitkeep
├── dev/
│   ├── .gitkeep
│   └── <task-id>/
│       ├── output/
│       ├── logs/
│       └── artifacts/
└── marketing/
    ├── .gitkeep
    └── <task-id>/
        ├── output/
        ├── logs/
        └── artifacts/
```

Все файлы в `workspace/` добавлены в `.gitignore` (исключение: `.gitkeep` внутри поддиректорий), поэтому локальные артефакты НЕ коммитятся в git.

---

## Использование: `register_task_artifact()`

Функция `register_task_artifact()` предназначена для сохранения файла артефакта в workspace с автоматической регистрацией метаданных в БД.

### Сигнатура

```python
def register_task_artifact(
    task_id: str,
    artifact_path: str,
    artifact_type: str = "output",
    metadata: dict = None
) -> dict:
    """
    Сохранить артефакт задачи в workspace и зарегистрировать в БД.
    
    Args:
        task_id: UUID задачи (12 символов, hex).
        artifact_path: Путь файла (относительный к workspace/<project>/<task-id>/).
        artifact_type: Категория артефакта ('output', 'log', 'debug', 'report').
        metadata: Опциональный словарь метаданных (версия, статус, размер, и т.п.).
    
    Returns:
        {
            'status': 'ok' | 'error',
            'artifact_id': str,
            'workspace_path': str,  # Полный путь в workspace
            'size_bytes': int,
            'timestamp': ISO8601,
            'reason': str  # При ошибке
        }
    """
```

### Примеры

#### 1. Dev-проект: сохранение логов теста

```python
# Роль: QA, тестирование задачи
from pride_team.workspace import register_task_artifact

task_id = "a1b2c3d4e5f6"
project = "dev"

# Запустить тесты и вывести логи в файл
with open("test_run.log", "w") as f:
    f.write("Test suite execution...\n")
    f.write("✓ auth_test passed\n")
    f.write("✗ payment_test failed\n")

# Зарегистрировать артефакт
result = register_task_artifact(
    task_id=task_id,
    artifact_path="logs/test_run.log",
    artifact_type="log",
    metadata={
        "test_suite": "unit_tests",
        "passed": 1,
        "failed": 1,
        "duration_sec": 12.5
    }
)

# Результат:
# {
#     'status': 'ok',
#     'artifact_id': 'artifact_xyz789',
#     'workspace_path': '/workspace/dev/a1b2c3d4e5f6/logs/test_run.log',
#     'size_bytes': 156,
#     'timestamp': '2026-05-25T17:45:32Z'
# }
```

#### 2. Marketing-проект: сохранение отчёта по обработке заказа

```python
# Роль: системный агент (скилл pride-order-processor)
import json
from pride_team.workspace import register_task_artifact

task_id = "m1n2o3p4q5r6"
project = "marketing"

# Результат обработки заказа от клиента
order_report = {
    "client": "Customer A",
    "items_processed": 45,
    "errors": 2,
    "warnings": 8,
    "status": "completed_with_warnings"
}

# Сохранить JSON-отчёт
output_file = "order_report.json"
with open(output_file, "w") as f:
    json.dump(order_report, f, indent=2)

# Зарегистрировать
result = register_task_artifact(
    task_id=task_id,
    artifact_path="output/order_report.json",
    artifact_type="output",
    metadata={
        "client": "Customer A",
        "processing_time_sec": 23.4,
        "version": "1.0"
    }
)

print(f"Сохранено: {result['workspace_path']}")
```

#### 3. Debug-артефакт для диагностики

```python
# Роль: backend при решении сложной задачи
import traceback
from pride_team.workspace import register_task_artifact

task_id = "d3e4f5g6h7i8"
project = "dev"

try:
    # Попытка обработки с возможной ошибкой
    result = complex_algorithm()
except Exception as e:
    # Сохранить stacktrace и состояние системы
    debug_output = f"""
Error occurred: {str(e)}

Traceback:
{traceback.format_exc()}

System state:
- Memory: 512 MB
- CPU: 45%
- Disk: 1.2 TB
"""
    
    with open("error_debug.txt", "w") as f:
        f.write(debug_output)
    
    result = register_task_artifact(
        task_id=task_id,
        artifact_path="debug/error_debug.txt",
        artifact_type="debug",
        metadata={
            "error_type": type(e).__name__,
            "severity": "high",
            "timestamp": "2026-05-25T18:00:00Z"
        }
    )
```

---

## Структура Workspace по ролям

### Dev-проект (`workspace/dev/<task-id>/`)

**Типичные артефакты:**
- `logs/` — логи тестов, development-сервера, CI/CD пайплайна
- `output/` — результаты сборки, скомпилированный код, JSON-отчёты
- `debug/` — stacktraces, state dumps, профилирование
- `coverage/` — отчёты о покрытии тестами

**Процесс:**
1. Backend/QA запускает task и генерирует артефакты
2. Вызывает `register_task_artifact()` с типом 'log' или 'output'
3. Файл сохраняется в `workspace/dev/<task-id>/logs/...`
4. БД регистрирует метаданные (размер, время, версия)

### Marketing-проект (`workspace/marketing/<task-id>/`)

**Типичные артефакты:**
- `output/` — обработанные заказы (JSON, XLSX), отчёты
- `logs/` — логи обработки клиентских таблиц
- `artifacts/` — дизайн-макеты, готовые к печати файлы

**Процесс:**
1. Скилл `pride-order-processor` загружает Excel от клиента
2. Обрабатывает и сохраняет результат (JSON/XLSX)
3. Регистрирует артефакт с метаданными (клиент, кол-во позиций, ошибки)
4. Тимлид может просмотреть отчёт через API

---

## API: Получение артефактов

```python
def get_task_artifacts(task_id: str) -> list:
    """Получить список всех артефактов для задачи."""
    # Возвращает:
    # [
    #     {
    #         'artifact_id': 'abc123',
    #         'type': 'log',
    #         'path': 'logs/test_run.log',
    #         'size_bytes': 156,
    #         'timestamp': '2026-05-25T17:45:32Z',
    #         'metadata': {...}
    #     },
    #     ...
    # ]

def download_artifact(artifact_id: str) -> bytes:
    """Загрузить содержимое артефакта."""
    # Возвращает содержимое файла
```

---

## Правила

1. **Не коммитить workspace-файлы** — они в `.gitignore`
2. **Использовать `register_task_artifact()` всегда** при сохранении результатов
3. **Очищать старые артефакты** (>30 дней) через админскрипт
4. **Метаданные обязательны** для отчётов и важных файлов
5. **.gitkeep в каждой директории** — гарантирует наличие папок в repo

---

## Развёртывание

```bash
# Инициализация workspace на новом окружении
mkdir -p workspace/{dev,marketing}
touch workspace/.gitkeep workspace/dev/.gitkeep workspace/marketing/.gitkeep
git add workspace/.gitkeep workspace/dev/.gitkeep workspace/marketing/.gitkeep

# .gitignore уже содержит правило на workspace/**/*
git add .gitignore
git commit -m "chore: add workspace infrastructure"
```

После коммита `.gitkeep`-файлы вернут структуру, остальные файлы в `workspace/` не будут отслеживаться git.
