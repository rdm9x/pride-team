@echo off
chcp 65001 >nul
REM Двойной клик в Explorer -> дашборд pride-team запускается, открывается браузер.
REM Закроешь это окно - дашборд остановится.

setlocal
set "REPO=%~dp0"
cd /d "%REPO%"

cls
echo +----------------------------------------------+
echo ^|         pride-team - запуск                  ^|
echo +----------------------------------------------+
echo.

REM 1) Python
where python >nul 2>nul
if errorlevel 1 (
    where py >nul 2>nul
    if errorlevel 1 (
        echo X Python не найден.
        echo.
        echo Установи Python 3.11+ с https://www.python.org/downloads/
        echo Поставь галочку "Add Python to PATH".
        echo После установки запусти этот файл снова.
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
    pause
    exit /b 1
)
echo [OK] Python найден

REM 2) Первый запуск - ставим зависимости
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
powershell -NoProfile -ExecutionPolicy Bypass -File "commands\pride-team-start.ps1"

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
endlocal
