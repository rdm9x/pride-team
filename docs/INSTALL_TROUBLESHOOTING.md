# INSTALL TROUBLESHOOTING

Типичные ошибки при установке и запуске devboard на каждой ОС.

---

## Windows

### 1. `bash: /bin/bash^M: bad interpreter`

**Причина**: Git на Windows конвертировал `.sh`-файлы в CRLF (line endings `\r\n`).
Bash не понимает CRLF и видит `^M` в имени интерпретатора.

**Решение**:
```bash
git config --global core.autocrlf input
git rm -r --cached commands/
git checkout commands/
```
Или, если `.gitattributes` уже есть в репо:
```bash
git add --renormalize .
```

**Профилактика**: В репо должен быть `.gitattributes` с `*.sh text eol=lf`.

---

### 2. `python` не найден / `'python' is not recognized`

**Причина**: Python не добавлен в PATH при установке.

**Решение**:
1. Откройте установщик Python (`python-3.xx-amd64.exe`) через «Apps → Изменить».
2. Нажмите «Modify» → убедитесь что галочка «Add Python to PATH» включена.
3. Или выполните `py -3.11 setup.py` вместо `python setup.py` — `py.exe` (launcher) работает без PATH.

---

### 3. `uv` не находится после `pip install --user uv`

**Причина**: `%APPDATA%\Python\Scripts` не в PATH.

**Решение**:
```cmd
setx PATH "%PATH%;%APPDATA%\Python\Python311\Scripts"
```
Закройте и снова откройте терминал, затем повторите `python setup.py`.

---

### 4. PowerShell: `cannot be loaded because running scripts is disabled`

**Причина**: `ExecutionPolicy = Restricted` — дефолт на корпоративных Windows.

**Решение** (только для текущего сеанса):
```powershell
powershell -ExecutionPolicy Bypass -File commands\devboard-start.ps1
```
Или используйте `Запустить devboard.bat` — он сам выставляет Bypass на уровне процесса.

---

### 5. Кириллица в логах / кракозябры вместо русского текста

**Причина**: Кодировка терминала Windows — cp1251 или cp866, не UTF-8.

**Решение**:
```powershell
# Выставить перед запуском:
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
chcp 65001
```
Все `devboard-*.ps1` скрипты уже выставляют эти флаги автоматически.

---

### 6. `FileNotFoundError: [Errno 2] No such file or directory: 'claude'`

**Причина**: Claude CLI (`claude`) не в PATH.

**Решение**: Установите Claude CLI для Windows:
```powershell
winget install Anthropic.Claude
```
Или скачайте бинарь с https://claude.ai/download и добавьте в PATH.

---

### 7. Порт 4999 занят

**Симптом**: `OSError: [Errno 10048] Only one usage of each socket address is permitted`.

**Решение**:
```cmd
netstat -ano | findstr :4999
taskkill /PID <найденный_PID> /F
```
Или запустите на другом порту:
```powershell
$env:PRIDE_DASHBOARD_PORT = "5555"
powershell -ExecutionPolicy Bypass -File commands\devboard-start.ps1
```

---

### 8. `No module named 'fcntl'`

**Причина**: Какой-то файл проекта напрямую импортирует `fcntl` без Windows-ветки.

**Нормальная ситуация**: `mcp_server/pride_tasks/db.py` правильно использует
`if sys.platform == "win32": import msvcrt` / `else: import fcntl`.

Если ошибка всё же появляется — создайте issue с полным traceback.

---

## macOS

### 1. Порт 5000 занят (AirPlay Receiver)

**Симптом**: `OSError: [Errno 48] Address already in use` на порту 5000.

**Причина**: macOS Monterey+ резервирует порт 5000 под AirPlay Receiver.

**Решение**: devboard уже использует порт **4999** по умолчанию. Если вы изменили порт вручную — не используйте 5000.

Отключить AirPlay Receiver: «Настройки» → «Пункт назначения AirPlay» → выключить.

---

### 2. `uv: command not found`

**Причина**: `uv` установлен в `~/.local/bin`, которого нет в PATH (`.zshrc` не настроен).

**Решение**:
```bash
# Добавьте в ~/.zshrc или ~/.bashrc:
export PATH="$HOME/.local/bin:$PATH"
source ~/.zshrc
```

---

### 3. `python: command not found` (есть только `python3`)

**Причина**: На macOS нет алиаса `python` → `python3` по умолчанию.

**Решение**:
```bash
python3 setup.py
```
Или создайте алиас:
```bash
echo "alias python=python3" >> ~/.zshrc
source ~/.zshrc
```

---

### 4. `SyntaxError: ...` или `ModuleNotFoundError` в тестах

**Причина**: Запущен системный Python (2.x или 3.9), а не Python 3.11+.

**Проверка**:
```bash
python3 --version   # нужно >= 3.11
```
**Решение**:
```bash
brew install python@3.11
python3.11 setup.py
```

---

### 5. `nohup: /usr/bin/nohup: не найдено` (WSL / урезанные окружения)

Это macOS/Linux-специфика. На чистом macOS `nohup` всегда есть в `/usr/bin/nohup`.
Если запускаете через WSL — используйте `.ps1`-скрипты вместо `.sh`.

---

## Linux

### 1. `uv: command not found`

**Решение**:
```bash
pip install --user uv
export PATH="$HOME/.local/bin:$PATH"
```
Или установите через официальный инсталлер:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

---

### 2. `xdg-open: command not found` (headless / server)

**Причина**: Кнопка «Открыть папку» в Settings вызывает `xdg-open` — он не работает без GUI.

**Решение**: Не использовать кнопку «Открыть папку» в headless-окружении. Папка с данными: `data/` в корне репо.

---

### 3. Нет прав запускать `.sh` скрипты

**Симптом**: `Permission denied: commands/devboard-start.sh`

**Решение**:
```bash
chmod +x commands/*.sh
```

---

### 4. `ModuleNotFoundError: No module named '_sqlite3'`

**Причина**: Python собран без SQLite (редко, но бывает в минимальных образах).

**Решение**:
```bash
sudo apt-get install python3-dev libsqlite3-dev
# Пересобрать Python или установить через pyenv
```

---

## Универсальные проблемы

### Диагностика одной командой

**Windows**:
```cmd
"Запустить devboard.bat" --diag
```
Выведет: версию Python, кодировки, пути, наличие venv, ExecutionPolicy.

**macOS/Linux**:
```bash
python3 -c "import sys, platform; print(sys.version, platform.system())"
ls mcp_server/.venv/bin/python dashboard/.venv/bin/python
cat data/dashboard.log | tail -20
```

---

### Сброс установки

Если что-то пошло не так с зависимостями — удалите venv и повторите:
```bash
rm -rf mcp_server/.venv dashboard/.venv
python setup.py     # или python3 setup.py на macOS/Linux
```

---

### .mcp.json содержит устаревшие пути

**Симптом**: MCP-сервер не запускается, Claude не видит tools.

**Причина**: `.mcp.json` генерируется с абсолютными путями под конкретную машину.
При переносе репо в другую папку пути устаревают.

**Решение**:
```bash
python setup.py    # перегенерирует .mcp.json с актуальными путями
```

---

### Путь к репо содержит пробелы или кириллицу (Windows)

**Симптом**: Различные `FileNotFoundError` или `SyntaxError` в неожиданных местах.

**Причина**: Часть инструментов (старые версии pip, некоторые shell-скрипты) плохо обрабатывают пробелы и Unicode в путях.

**Решение**: Переместите папку `pride-team-v1.0` в путь без пробелов и кириллицы, например `C:\devboard\`. Это рекомендованная практика для Windows-разработки.

> **Примечание по кириллице**: Часть файлов проекта (`roles/бэкенд.md`, `roles/архитектор.md` и др.) содержит кириллические имена — это намеренно и корректно обрабатывается через `encoding="utf-8"` во всех read/write операциях. Проблема только в **пути к директории проекта** на некоторых Windows-конфигурациях.

---

*Последнее обновление: S13.3 cross-platform audit (2026-05-24)*
