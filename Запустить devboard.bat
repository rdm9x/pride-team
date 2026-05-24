@echo off
chcp 65001 >nul
REM Двойной клик в Explorer -> дашборд devboard запускается, открывается браузер.
REM Закроешь это окно - дашборд остановится.
REM Запуск с флагом --diag: "Запустить devboard.bat" --diag
REM   -> печатает диагностику (Python, OS, encoding, path) и НЕ запускает дашборд.

setlocal
set "REPO=%~dp0"
cd /d "%REPO%"

REM ---- ExecutionPolicy: разовый Bypass для этого процесса (не меняет системную политику) ----
powershell -NoProfile -Command "Get-ExecutionPolicy -Scope Process" >nul 2>&1 || (
    powershell -NoProfile -Command "Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force" >nul 2>&1
)

cls
echo +----------------------------------------------+
echo ^|         devboard - запуск                  ^|
echo +----------------------------------------------+
echo.

REM ---- Диагностический режим (--diag) ----
if /i "%~1"=="--diag" goto diag_mode

REM 1) Python
where python >nul 2>nul
if errorlevel 1 (
    where py >nul 2>nul
    if errorlevel 1 (
        echo X Python не найден.
        echo.
        echo   Установи Python 3.11 или новее:
        echo     https://www.python.org/downloads/
        echo.
        echo   ВАЖНО при установке:
        echo     [*] Поставь галочку "Add Python 3.xx to PATH"
        echo         (она на первом экране установщика, внизу)
        echo     [*] Или выбери "Customize installation" -^> убедись что pip включён
        echo.
        echo   После установки ЗАКРОЙ и СНОВА ОТКРОЙ это окно, затем запусти файл ещё раз.
        echo.
        pause
        exit /b 1
    )
    set "PY=py"
) else (
    set "PY=python"
)

%PY% -c "import sys; assert sys.version_info >= (3, 11), sys.version" 2>nul
if errorlevel 1 (
    echo X Нужен Python 3.11 или новее. У тебя:
    %PY% --version
    echo.
    echo   Обнови Python: https://www.python.org/downloads/
    echo   При установке поставь галочку "Add Python to PATH".
    pause
    exit /b 1
)
echo [OK] Python найден

REM 2) Первый запуск — ставим зависимости
if not exist "mcp_server\.venv\Scripts\python.exe" goto needs_setup
if not exist "dashboard\.venv\Scripts\python.exe" goto needs_setup
goto run

:needs_setup
echo.
echo [*] Первый запуск - устанавливаю зависимости. Займёт 1-2 минуты...
echo.
%PY% setup.py
if errorlevel 1 (
    echo.
    echo X Установка упала. Прокрути выше - найди причину.
    pause
    exit /b 1
)

:run
if not defined PRIDE_DASHBOARD_PORT set "PRIDE_DASHBOARD_PORT=4999"
echo.
echo [*] Запускаю дашборд на порту %PRIDE_DASHBOARD_PORT%...
powershell -NoProfile -ExecutionPolicy Bypass -File "commands\devboard-start.ps1"

REM 3) Ждём готовности (до 20 секунд)
echo|set /p="  ждём готовности"
for /l %%i in (1,1,40) do (
    powershell -NoProfile -Command "try { (Invoke-WebRequest -Uri http://127.0.0.1:%PRIDE_DASHBOARD_PORT%/healthz -UseBasicParsing -TimeoutSec 1).StatusCode } catch { 0 }" 2>nul | findstr "200" >nul && goto healthy
    echo|set /p="."
    timeout /t 1 /nobreak >nul
)
:healthy
echo  OK

REM 4) Открываем браузер
start "" http://127.0.0.1:%PRIDE_DASHBOARD_PORT%

echo.
echo --------------------------------------------------
echo [OK] Дашборд: http://127.0.0.1:%PRIDE_DASHBOARD_PORT%
echo.
echo   * Не закрывай это окно - иначе дашборд остановится.
echo   * Чтобы остановить - закрой это окно.
echo   * Логи: data\dashboard.log
echo --------------------------------------------------
echo.

REM Держим окно живым пока pid жив
:waitloop
if not exist "data\dashboard.pid" goto done
set /p PID=<"data\dashboard.pid"
tasklist /FI "PID eq %PID%" 2>nul | find "%PID%" >nul
if errorlevel 1 goto done
timeout /t 2 /nobreak >nul
goto waitloop

:done
echo (дашборд завершился)
pause
goto end

REM ================================================================
REM  DIAGNOSTIC MODE  ("Запустить devboard.bat" --diag)
REM  Печатает Python version, OS, PATH, encoding. Дашборд НЕ стартует.
REM ================================================================
:diag_mode
echo [DIAG] Diagnostic mode — дашборд НЕ запускается.
echo.

REM Python version
where python >nul 2>nul
if not errorlevel 1 (
    set "PY=python"
) else (
    where py >nul 2>nul
    if not errorlevel 1 (
        set "PY=py"
    ) else (
        echo [DIAG] Python: НЕ НАЙДЕН
        goto diag_os
    )
)
echo [DIAG] Python binary : %PY%
%PY% --version
%PY% -c "import sys; print('[DIAG] Python path   :', sys.executable)"
%PY% -c "import sys; print('[DIAG] Version tuple :', sys.version_info[:3])"

:diag_os
echo.
echo [DIAG] OS / Platform
%PY% -c "import platform; print('[DIAG] OS            :', platform.system(), platform.release(), platform.version())"
%PY% -c "import platform; print('[DIAG] Machine       :', platform.machine())"

echo.
echo [DIAG] Encoding
%PY% -c "import sys, locale; print('[DIAG] stdout enc    :', sys.stdout.encoding); print('[DIAG] locale        :', locale.getpreferredencoding(False))"
echo [DIAG] PYTHONIOENCODING=%PYTHONIOENCODING%
echo [DIAG] PYTHONUTF8=%PYTHONUTF8%

echo.
echo [DIAG] Paths
echo [DIAG] REPO dir      : %REPO%
%PY% -c "import sys; [print('[DIAG] sys.path      :', p) for p in sys.path[:5]]"

echo.
echo [DIAG] Files
if exist "mcp_server\.venv\Scripts\python.exe" (
    echo [DIAG] mcp_server venv: OK
) else (
    echo [DIAG] mcp_server venv: НЕ НАЙДЕН (setup.py ещё не запускался?)
)
if exist "dashboard\.venv\Scripts\python.exe" (
    echo [DIAG] dashboard venv : OK
) else (
    echo [DIAG] dashboard venv : НЕ НАЙДЕН
)
if exist "data\tasks.db" (
    echo [DIAG] tasks.db       : OK
) else (
    echo [DIAG] tasks.db       : нет (будет создана при первом запуске)
)

echo.
echo [DIAG] PowerShell ExecutionPolicy
powershell -NoProfile -Command "Write-Host '[DIAG] EP (Process)  :' (Get-ExecutionPolicy -Scope Process); Write-Host '[DIAG] EP (User)     :' (Get-ExecutionPolicy -Scope CurrentUser)"

echo.
echo --------------------------------------------------
echo  Скопируй вывод выше и пришли его в поддержку.
echo --------------------------------------------------
echo.
pause
goto end

:end
endlocal
