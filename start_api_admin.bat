@echo off
set PYTHONPATH=
cd /d "E:\Projects\SuperClaw"
echo Starting SuperClaw API on port 8987...
venv\Scripts\python.exe run_api.py
pause
