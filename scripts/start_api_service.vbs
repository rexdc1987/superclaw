Option Explicit
' Launch the SuperClaw API hidden and detached from any parent shell.
' Runs through cmd so stdout/stderr still land in the log files; window
' style 0 keeps the console invisible.
Dim shell, root, cmd
root = "E:\Projects\SuperClaw"
Set shell = CreateObject("WScript.Shell")
shell.CurrentDirectory = root
cmd = "cmd /c set PYTHONPATH= && set SUPERCLAW_API_PORT=8987 && set SUPERCLAW_EXECUTION_MODE=embedded && set SUPERCLAW_QUEUE_DISPATCHER=1 && venv\Scripts\python.exe run_api.py 1>>logs\api-dev.out.log 2>>logs\api-dev.err.log"
shell.Run cmd, 0, False
