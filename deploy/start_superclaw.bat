@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title SuperClaw Service

rem ===========================================================================
rem  Keep this file ASCII-only, and keep it small.
rem
rem  * ASCII-only is not an aesthetic choice. cmd.exe parses a .bat with the
rem    console code page, so UTF-8 Chinese breaks it: a multi-byte character can
rem    end in a lead byte that swallows the trailing newline, gluing the next
rem    line onto this command. The user double-clicking the shortcut then gets
rem    "'xxx' is not recognized as an internal or external command" and nothing
rem    starts. Every Chinese message therefore lives in app\launcher.py, which
rem    writes Unicode to the console safely.
rem  * This file cannot replace itself while it runs, so it is excluded from
rem    auto-updates. All real logic lives in app\launcher.py, which does update.
rem  * SUPERCLAW_SUPERVISOR tells the launcher that a restart loop is above it,
rem    so after applying an update it exits 7 instead of replacing itself. That
rem    keeps this window the owner of the service: the message it prints is
rem    accurate, and closing the window still stops the service.
rem ===========================================================================

set "SUPERCLAW_SUPERVISOR=bat"

if not exist "runtime\python.exe" (
    echo.
    echo   [ERROR] runtime\python.exe is missing.
    echo   The install folder is incomplete - re-extract the package,
    echo   or run the installer again.
    echo.
    pause
    exit /b 1
)

if not exist "app\launcher.py" (
    echo.
    echo   [ERROR] app\launcher.py is missing.
    echo   The app folder is damaged - install the latest package over this one.
    echo.
    pause
    exit /b 1
)

:superclaw_loop

"runtime\python.exe" -u "app\launcher.py"
set RC=%errorlevel%

rem Exit code 7 = an update was applied; come back with a brand new process so
rem the freshly written code is what actually gets imported.
if not "%RC%"=="7" goto superclaw_stopped

echo.
echo   Update applied - restarting with the new version...
echo.
rem ping, not timeout: timeout.exe refuses to run when stdin is redirected
ping -n 2 127.0.0.1 >nul 2>&1
goto superclaw_loop

:superclaw_stopped

if "%RC%"=="3" (
    echo.
    echo   SuperClaw is already running - this copy did nothing.
    echo.
    pause
    exit /b 0
)

if "%RC%"=="4" (
    echo.
    echo   Startup failed. See the messages above.
    echo   Config:   app\config\local.yaml
    echo   Instance: data\instance.json
    echo.
    pause
    exit /b 4
)

echo.
echo   Service stopped (exit code %RC%).
echo   Log: data\logs\launcher.log
echo.
pause
