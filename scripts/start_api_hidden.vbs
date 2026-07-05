Set shell = CreateObject("WScript.Shell")
shell.CurrentDirectory = "E:\Projects\SuperClaw"
shell.Run "cmd /c venv\Scripts\python.exe run_api.py 1>logs\api_bg_stdout.log 2>logs\api_bg_stderr.log", 0, False
