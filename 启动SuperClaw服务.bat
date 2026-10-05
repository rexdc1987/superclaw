@echo off
rem ============================================================
rem  SuperClaw service launcher (API on port 8987)
rem
rem  Double-click this file to start the service, then close the
rem  window - the service keeps running on its own.
rem
rem  ASCII-only on purpose: a Chinese console codepage mangles
rem  non-ASCII bytes inside a batch file.
rem ============================================================
setlocal EnableExtensions
chcp 65001 >nul
set "ROOT=E:\Projects\SuperClaw"

if not exist "%ROOT%\run_api.py" (
    echo [ERROR] Project not found at %ROOT%
    pause
    exit /b 1
)
cd /d "%ROOT%"

echo [1/3] Checking whether port 8987 already serves SuperClaw ...
netstat -ano | findstr /C:":8987" | findstr /C:"LISTENING" >nul 2>&1
if not errorlevel 1 (
    echo       Already serving - not starting a second instance.
    echo       Two embedded instances would fight over the same tasks.
    goto verify
)

echo [2/3] Starting the service so it survives this window ...
"%ROOT%\venv\Scripts\python.exe" "%ROOT%\scripts\start_api_detached.py" --port 8987 --timeout 150
if errorlevel 1 (
    echo       Primary launcher did not work - trying the VBScript fallback ...
    "%SystemRoot%\System32\cscript.exe" //nologo "%ROOT%\scripts\start_api_service.vbs"
)

:verify
echo [3/3] Confirming the service answers /health ...
"%ROOT%\venv\Scripts\python.exe" "%ROOT%\scripts\wait_api_ready.py" --port 8987 --timeout 60
if errorlevel 1 (
    echo.
    echo [FAILED] The service did not come up.
    echo          Last lines of logs\api-dev.err.log:
    type "%ROOT%\logs\api-dev.err.log" 2>nul | more
    pause
    exit /b 1
)

echo.
echo You can close this window now - the service keeps running.
echo.
echo While a batch is running: do not stop the service, and do not let
echo this machine sleep for more than 20 minutes, or the watchdog on
echo another machine may mark the tasks as lost.
echo.
pause
