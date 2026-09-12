@echo off
setlocal enabledelayedexpansion
REM ============================================================
REM  SuperClaw one-click launcher (API + Web UI)
REM  Double-click this file to start the whole system.
REM  Auto-detects Node.js and MuMu paths - portable across machines.
REM ============================================================
set "ROOT=%~dp0"
cd /d "%ROOT%"

echo ============================================================
echo   SuperClaw launcher
echo   Root: %ROOT%
echo ============================================================

REM ---------- 1. Locate Node.js ----------
REM Preference: WorkBuddy bundled node (version dir name changes over time,
REM so pick the newest by reverse name sort). Fallback: whatever is on PATH.
set "NODE_DIR="
for /f "delims=" %%D in ('dir /b /ad /o-n "%USERPROFILE%\.workbuddy\binaries\node\versions" 2^>nul') do (
  if not defined NODE_DIR set "NODE_DIR=%USERPROFILE%\.workbuddy\binaries\node\versions\%%D"
)
if defined NODE_DIR (
  set "PATH=%NODE_DIR%;%PATH%"
  echo [env] Node dir : !NODE_DIR!
) else (
  echo [env] Node dir : using system PATH
)
where npm.cmd >nul 2>&1
if errorlevel 1 (
  echo.
  echo [ERROR] npm not found. Install Node.js 18+ ^(or WorkBuddy bundled node^).
  echo.
  pause
  exit /b 1
)

REM ---------- 2. Locate MuMu Player ----------
REM Code default is D:\Program Files\Netease\MuMu, but install drive varies.
REM Respect an externally set SUPERCLAW_MUMU_ROOT if present.
set "MUMU_ROOT="
if defined SUPERCLAW_MUMU_ROOT if exist "%SUPERCLAW_MUMU_ROOT%\nx_main\adb.exe" set "MUMU_ROOT=%SUPERCLAW_MUMU_ROOT%"
if not defined MUMU_ROOT (
  for %%L in (C D E F G H) do (
    if not defined MUMU_ROOT if exist "%%L:\Program Files\Netease\MuMu\nx_main\adb.exe" set "MUMU_ROOT=%%L:\Program Files\Netease\MuMu"
  )
)
if not defined MUMU_ROOT (
  for %%L in (C D E F G H) do (
    if not defined MUMU_ROOT if exist "%%L:\MuMu\nx_main\adb.exe" set "MUMU_ROOT=%%L:\MuMu"
  )
)

if defined MUMU_ROOT (
  set "SUPERCLAW_MUMU_ROOT=!MUMU_ROOT!"
  set "MUMU_ADB=!MUMU_ROOT!\nx_main\adb.exe"
  echo [env] MuMu root: !MUMU_ROOT!
) else (
  echo [WARN] MuMu not found. Instance detection will report 0 online.
  echo        Set SUPERCLAW_MUMU_ROOT manually if MuMu is installed elsewhere.
)

set "SUPERCLAW_CONFIG=%ROOT%config\local.yaml"
set "SUPERCLAW_API_PORT=8987"

REM ---------- 3. Restart ADB and pre-connect MuMu instances ----------
REM MuMu 12 auto-enumerated emulator-5554 often stays "offline";
REM an explicit connect to the instance port is required to get "device".
if defined MUMU_ADB (
  if exist "%MUMU_ADB%" (
    echo [0/2] Restarting ADB daemon ...
    "%MUMU_ADB%" kill-server >nul 2>&1
    timeout /t 2 >nul
    "%MUMU_ADB%" start-server >nul 2>&1
    timeout /t 3 >nul
    REM instance ports: 16384, 16416, 16448 ... step 32
    for /L %%P in (16384,32,16512) do "%MUMU_ADB%" connect 127.0.0.1:%%P >nul 2>&1
    timeout /t 2 >nul
    "%MUMU_ADB%" devices
  ) else (
    echo [WARN] MuMu adb not found: %MUMU_ADB%
  )
)

REM ---------- 4. Check venv ----------
if not exist "%ROOT%.venv-api\Scripts\python.exe" (
  echo.
  echo [ERROR] Python venv missing: %ROOT%.venv-api
  echo         Run deploy_superclaw.ps1 first, or create it manually.
  echo.
  pause
  exit /b 1
)

REM ---------- 5. Start services ----------
echo [1/2] Starting SuperClaw API on port 8987 ...
start "SuperClaw-API" cmd /k ""%ROOT%.venv-api\Scripts\python.exe" run_api.py"

timeout /t 4 >nul

echo [2/2] Starting SuperClaw Web on port 3000 ...
start "SuperClaw-Web" cmd /k "cd /d "%ROOT%frontend" && npm.cmd run dev"

echo.
echo   API health : http://127.0.0.1:8987/health
echo   Web UI     : http://127.0.0.1:3000/hongguo/multi
echo.
echo Two console windows opened. To stop: run stop_superclaw.bat
echo or simply close both windows.
echo.
pause
endlocal
