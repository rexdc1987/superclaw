@echo off
rem ============================================================
rem  Stop the SuperClaw service listening on port 8987.
rem  ASCII-only on purpose: a Chinese console codepage mangles
rem  non-ASCII bytes inside a batch file.
rem ============================================================
setlocal EnableExtensions
chcp 65001 >nul

set "SVC_PID="
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /C:":8987" ^| findstr /C:"LISTENING"') do set "SVC_PID=%%P"

if not defined SVC_PID (
    echo Nothing is listening on port 8987. Nothing to stop.
    pause
    exit /b 0
)

echo Found the SuperClaw service on port 8987, PID=%SVC_PID%.
echo.
echo WARNING: stopping it aborts every task this machine is running now.
echo          Their rows stay "running" until something reclaims them.
set "ANSWER="
set /p "ANSWER=Type Y to stop it, anything else to cancel: "
if /i not "%ANSWER%"=="Y" (
    echo Cancelled. Nothing was stopped.
    pause
    exit /b 0
)

taskkill /PID %SVC_PID% /T /F
echo.
echo Stopped.
pause
