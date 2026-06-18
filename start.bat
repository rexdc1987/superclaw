@echo off
cd /d "%~dp0"
echo Starting SuperClaw...
echo Working directory: %CD%

REM Clear PYTHONPATH to avoid conflicts with other venvs
set PYTHONPATH=

echo Activating venv...
call venv\Scripts\activate.bat
if errorlevel 1 (
    echo ERROR: Failed to activate venv!
    pause
    exit /b 1
)

echo Running run.py...
python run.py %*
if errorlevel 1 (
    echo.
    echo Error! Check the log.
    pause
)
