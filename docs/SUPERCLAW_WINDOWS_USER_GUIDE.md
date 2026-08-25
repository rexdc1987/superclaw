# SuperClaw Windows 安装与使用手册

本文档用于在另一台 Windows 电脑上安装和测试当前 SuperClaw 红果多开版本。

## 1. 正确版本

- 仓库：<https://github.com/rexdc1987/superclaw>
- 已验证分支：`codex/hongguo-server-ready`
- 当前版本：`61a2947`

GitHub 仓库首页默认是 `master`，不是当前已验证版本。安装时必须指定上述分支。

## 2. 环境要求

- Windows 10/11 x64
- Git
- Python 3.11+
- Node.js 22 LTS
- Docker Desktop，或已有 MySQL 8.x
- MuMu 模拟器 12/15
- MuMu 实例已安装并登录红果，ADB 调试已开启

基础软件可通过 PowerShell 安装：

```powershell
winget install -e --id Git.Git
winget install -e --id Python.Python.3.11
winget install -e --id OpenJS.NodeJS.LTS
winget install -e --id Docker.DockerDesktop
```

安装后重新打开 PowerShell，并启动 Docker Desktop。

## 3. 一键安装

```powershell
git clone -b codex/hongguo-server-ready --single-branch https://github.com/rexdc1987/superclaw.git
Set-Location superclaw
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\bootstrap_windows.ps1 -DatabaseMode Auto -Start
.\.venv\Scripts\python.exe scripts\hongguo_dev_smoke.py
```

脚本会创建 Python 环境、安装前后端依赖、启动 MySQL 8、初始化数据库，并启动 API 和前端。

默认地址：

- 红果多开：<http://127.0.0.1:3000/hongguo/multi>
- 模板管理：<http://127.0.0.1:3000/hongguo/templates>
- 健康检查：<http://127.0.0.1:8987/health>

健康检查必须满足 `status=ok`、`database=true` 和 `task_execution_ready=true`。

## 4. MuMu 配置

1. 启动需要测试的 MuMu 实例。
2. 确认每个实例可以打开红果并且账号已登录。
3. 确认 MuMu 已开启 ADB 调试。
4. 打开红果多开页面，点击“检测实例/登录”。
5. 首次检测可能需要几十秒，不要连续重复点击。

MuMu 不在默认路径时重新执行：

```powershell
.\scripts\bootstrap_windows.ps1 -DatabaseMode Auto -MuMuRoot 'D:\Apps\Netease\MuMu' -Start
```

设备检查：

```powershell
.\.venv\Scripts\python.exe scripts\hongguo_dev_smoke.py --require-devices
```

## 5. 首次任务测试

1. 先只启动一个 MuMu 实例。
2. 选择短剧和较短集数范围。
3. 内容来源先使用模板模式，确认下拉框显示模板名称。
4. 默认播放倍速为 `1.0x`，随机点赞为 `5`，收藏为 `1`。
5. 检查评论发送、评论验证截图和任务完成截图。
6. 单实例通过后，再扩大到 2-3 个实例。

模板模式不依赖 AI Token。AI 配额耗尽时仍可使用模板模式测试完整设备流程。

## 6. AI 配置

在启动服务的 PowerShell 中设置密钥，不要把密钥写入 Git：

```powershell
$env:XIAOMI_API_KEY = '本机有效密钥'
```

- `401 Invalid API Key` 表示密钥无效或配置错误。
- `429 quota exhausted` 表示配额耗尽。

## 7. 启动、停止和更新

日常启动：

```powershell
Set-Location superclaw
.\scripts\start_windows_dev.ps1
```

停止服务：

```powershell
.\scripts\stop_windows_dev.ps1
```

重启前先检查任务数：

```powershell
Invoke-RestMethod http://127.0.0.1:8987/health
```

仅在 `running_tasks=0` 时重启：

```powershell
.\scripts\start_windows_dev.ps1 -Restart
```

更新版本：

```powershell
Set-Location superclaw
git switch codex/hongguo-server-ready
git pull --ff-only
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\bootstrap_windows.ps1 -DatabaseMode Auto -Start
.\.venv\Scripts\python.exe scripts\hongguo_dev_smoke.py
```

## 8. 端口冲突

默认端口为 MySQL `3308`、API `8987`、前端 `3000`。检查端口：

```powershell
Get-NetTCPConnection -State Listen | Where-Object LocalPort -in 3308,8987,3000
```

如果 `3000` 被 Windows、Docker、WSL 或 VPN 保留，改用 `3100`：

```powershell
.\scripts\bootstrap_windows.ps1 -DatabaseMode Auto -ApiPort 8987 -FrontendPort 3100 -Start
.\.venv\Scripts\python.exe scripts\hongguo_dev_smoke.py --api-port 8987 --frontend-port 3100
```

然后访问 <http://127.0.0.1:3100/hongguo/multi>。

## 9. 常见问题

Docker 未运行：启动 Docker Desktop，执行 `docker info`，再重新运行安装脚本。

检测不到 MuMu：确认实例已启动、红果已登录、ADB 已开启；非默认目录使用 `-MuMuRoot`。

页面显示旧内容：

```powershell
Set-Location frontend
npm.cmd run build
Set-Location ..
.\scripts\start_windows_dev.ps1 -Restart
```

查看后端错误：

```powershell
Get-Content logs\api-dev.err.log -Tail 100
Get-Content logs\api-dev.out.log -Tail 100
```

不要在任务运行时重启 API。先停止任务并确认 `running_tasks=0`。

## 10. 本机数据安全

以下内容不得上传 Git 或发送给其他电脑：

- `config/local.yaml`
- `.env`、`config/dev-mysql.env`
- `config/hongguo_ai_usage.json`
- `data/`、`logs/`、`screenshots/`
- `tmp/`、`backups/`
- 数据库导出、ADB 输出和页面 XML

红果任务必须使用 MySQL，不能使用 SQLite 进行正式测试。

## 11. 开发验证

```powershell
.\.venv\Scripts\python.exe -m py_compile src\rpa\dashboard\routes_hongguo.py
.\.venv\Scripts\python.exe -m pytest tests\test_rpa_engine.py tests\test_server_security.py -q
Set-Location frontend
npm.cmd run build
```

更完整的 Agent 安装和测试说明见 `docs/AGENT_INSTALL_AND_TEST.md`。
