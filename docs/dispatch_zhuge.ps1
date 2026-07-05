$env:OPENCLAW_STATE_DIR = "E:\Openclaw\.openclaw"
$env:OPENCLAW_CONFIG_PATH = "E:\Openclaw\.openclaw\openclaw.json"
& "C:\Users\Chaos\.workbuddy\binaries\node\versions\22.22.2\node.exe" "E:\Openclaw\npm-global\node_modules\openclaw\dist\index.js" agent --agent main --message "读E:/Projects/SuperClaw/docs/task_zhuge_hongguo_test.md执行测试任务" --json --timeout 600
