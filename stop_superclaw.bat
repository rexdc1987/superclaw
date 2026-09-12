@echo off
setlocal
REM ============================================================
REM  Stop SuperClaw (API + Web UI)
REM ============================================================
echo Stopping SuperClaw ...

for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8987 ^| findstr LISTENING') do (
    echo   killing API pid %%a
    taskkill /F /PID %%a >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :3000 ^| findstr LISTENING') do (
    echo   killing Web pid %%a
    taskkill /F /PID %%a >nul 2>&1
)
taskkill /FI "WINDOWTITLE eq SuperClaw-API*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq SuperClaw-Web*" /F >nul 2>&1

echo Done.
timeout /t 2 >nul
endlocal
