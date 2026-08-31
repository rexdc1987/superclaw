# SuperClaw 公司电脑一键安装指南

本文是 SuperClaw 公司版的一键安装指南。WorkBuddy 等电脑助手可以按本文执行安装；也可以由员工直接在 PowerShell 中执行。每台电脑运行自己的前端、API 和 MuMu，账号、任务、模板及日志统一存储在公司 MySQL 中。

## 一、安装前准备

目标电脑必须满足：

- Windows 10/11 x64。
- 已安装 Git、Python 3.11+ 和 Node.js 22 LTS。
- 已安装并启动 MuMu 模拟器，MuMu 中已安装红果免费短剧并登录。
- 电脑可以访问公司 MySQL 的地址和端口。
- 管理员已经在 SuperClaw“账号管理”中为员工创建个人账号。

缺少基础工具时，以管理员 PowerShell 执行：

```powershell
winget install -e --id Git.Git
winget install -e --id Python.Python.3.11
winget install -e --id OpenJS.NodeJS.LTS
```

安装完成后重新打开 PowerShell。

## 二、发给 WorkBuddy 的完整指令

将下面整段发给目标电脑上的 WorkBuddy，并把 `<公司MySQL地址>` 替换为管理员提供的地址。不要把数据库密码写进消息或命令；脚本运行时由电脑使用者在安全密码提示中输入。

```text
请在这台 Windows 电脑安装并验证 SuperClaw 公司版，严格执行以下步骤：

1. 如果当前目录没有 superclaw 仓库，执行：
   git clone -b codex/hongguo-server-ready --single-branch https://github.com/rexdc1987/superclaw.git
   Set-Location superclaw

2. 如果仓库已存在，进入仓库后执行：
   git switch codex/hongguo-server-ready
   git pull --ff-only

3. 执行公司电脑安装脚本：
   Set-ExecutionPolicy -Scope Process Bypass
   .\scripts\install_company_pc.ps1 -DatabaseHost '<公司MySQL地址>' -DatabasePort 3306 -DatabaseName 'superclaw' -DatabaseUser 'superclaw'

4. 脚本提示输入 MySQL 密码时，暂停并让我在本机安全输入，不要把密码写入命令、聊天、日志或 Git。

5. 安装完成后检查：
   Invoke-RestMethod http://127.0.0.1:8987/health
   .\.venv\Scripts\python.exe scripts\hongguo_dev_smoke.py

6. 结果必须满足 status=ok、database=true、auth_required=true、task_execution_ready=true。然后打开：
   http://127.0.0.1:3000/hongguo/multi

7. 使用管理员分配的员工账号登录。先只检测一个 MuMu 实例并创建短集数测试任务，不要直接启动多实例长任务。

不得提交 config/local.yaml、数据库密码、API Key、日志、截图、备份、数据库导出或 tmp 文件。
```

## 三、人工一键安装

电脑使用者也可以直接执行：

```powershell
git clone -b codex/hongguo-server-ready --single-branch https://github.com/rexdc1987/superclaw.git
Set-Location superclaw
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\install_company_pc.ps1 `
  -DatabaseHost '<公司MySQL地址>' `
  -DatabasePort 3306 `
  -DatabaseName superclaw `
  -DatabaseUser superclaw
```

脚本会安全提示输入 MySQL 密码，并自动完成：

1. 创建 Python 虚拟环境并安装依赖。
2. 安装并构建 Vue 前端。
3. 生成被 Git 忽略的 `config/local.yaml`。
4. 启用账号认证并生成每台电脑独立的令牌签名密钥。
5. 检查共享 MySQL 数据库结构。
6. 运行自动化回归测试。
7. 启动 API 和前端并执行冒烟测试。

## 四、日常使用

启动：

```powershell
.\scripts\start_windows_dev.ps1
```

重启：

```powershell
.\scripts\start_windows_dev.ps1 -Restart
```

停止：

```powershell
.\scripts\stop_windows_dev.ps1
```

页面地址：

- 红果多开：`http://127.0.0.1:3000/hongguo/multi`
- 红果模板：`http://127.0.0.1:3000/hongguo/templates`
- 管理员账号管理：`http://127.0.0.1:3000/users`

## 五、常见问题

### 数据库连接失败

确认目标电脑可以访问公司 MySQL：

```powershell
Test-NetConnection '<公司MySQL地址>' -Port 3306
```

不要关闭数据库认证或改用 SQLite。公司账号、任务、日志、模板和设备租约必须使用同一个 MySQL。

### MuMu 检测不到

确认 MuMu 已启动、ADB 调试已开启。非默认安装目录可以传入：

```powershell
.\scripts\install_company_pc.ps1 `
  -DatabaseHost '<公司MySQL地址>' `
  -MuMuRoot 'D:\Apps\Netease\MuMu'
```

### 页面打不开

```powershell
.\scripts\start_windows_dev.ps1 -Restart
Get-Content .\logs\api-dev.err.log -Tail 100
Get-Content .\logs\frontend-dev.err.log -Tail 100
```

不要将日志中的账号、数据库地址、API Key 或其他敏感信息发送到公开渠道。
