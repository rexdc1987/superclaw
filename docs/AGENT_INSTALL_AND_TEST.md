# SuperClaw Windows Agent 安装与测试手册

本文档供另一台 Windows 电脑上的开发 Agent 从 GitHub 获取、安装、启动和测试当前 SuperClaw 红果版本。所有命令都从仓库根目录执行，不依赖固定盘符。

## 1. 当前发布版本

- 仓库：`https://github.com/rexdc1987/superclaw.git`
- 测试分支：`codex/hongguo-server-ready`
- 技术栈：FastAPI + Vue 3 + MySQL 8 + MuMu + uiautomator2
- API：`http://127.0.0.1:8987`
- 前端：`http://127.0.0.1:3000`
- 红果多开：`http://127.0.0.1:3000/hongguo/multi`
- 模板管理：`http://127.0.0.1:3000/hongguo/templates`

不要使用旧文档中的 `8000`、`8890` 或 SQLite 配置测试红果功能。

## 2. 目标电脑前置条件

必需：

- Windows 10/11 x64
- Git
- Python 3.11+ x64
- Node.js 22 LTS
- Docker Desktop（推荐，用于自动创建隔离的 MySQL 8.4）或已有 MySQL 8.x

真实设备测试还需要：

- MuMu 模拟器 12/15，多开实例已启动
- 每个实例安装红果免费短剧并完成登录
- MuMu 设置中开启 ADB 调试

可用 `winget` 安装基础工具：

```powershell
winget install -e --id Git.Git
winget install -e --id Python.Python.3.11
winget install -e --id OpenJS.NodeJS.LTS
winget install -e --id Docker.DockerDesktop
```

安装后重新打开 PowerShell。Docker Desktop 必须已启动并切到 Linux containers。

## 3. Agent 一键执行块

公司员工电脑连接共享 MySQL 时，优先使用 `docs/WORKBUDDY_ONE_CLICK_INSTALL.md` 和 `scripts/install_company_pc.ps1`。下面的 `DatabaseMode Auto` 仅用于创建完全独立的开发环境。

让目标电脑 Agent 执行下面整段：

```powershell
git clone -b codex/hongguo-server-ready --single-branch https://github.com/rexdc1987/superclaw.git
Set-Location superclaw
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\bootstrap_windows.ps1 -DatabaseMode Auto -Start
.\.venv\Scripts\python.exe scripts\hongguo_dev_smoke.py
```

如果目标目录已有仓库，不要重复 clone，改为：

```powershell
Set-Location superclaw
git switch codex/hongguo-server-ready
git pull --ff-only
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\bootstrap_windows.ps1 -DatabaseMode Auto -Start
.\.venv\Scripts\python.exe scripts\hongguo_dev_smoke.py
```

`bootstrap_windows.ps1` 可以重复执行，会完成：

1. 检查 Python、Node、npm 和 Docker。
2. 创建 `.venv` 并安装 Python/开发依赖。
3. 通过 `npm ci` 安装前端依赖并构建。
4. 在 `127.0.0.1:3308` 启动独立 MySQL 容器。
5. 生成被 Git 忽略的 `config/local.yaml`。
6. 执行当前数据库迁移并初始化带名称的默认模板。
7. 运行快速回归测试。
8. 后台启动 API 和 Vue 开发服务器。

首次安装还会启用公司账号认证并创建首个 `admin` 管理员。自动生成的初始密码只显示一次，登录后应立即修改。公司多电脑部署见 `docs/COMPANY_ACCOUNT_DEPLOYMENT.md`。

数据库随机密码只写入本机 `config/local.yaml`、`config/dev-mysql.env` 和 Docker 容器环境，不进入 Git。保留这两个本机文件即可安全地重复执行安装脚本或重建容器。

## 4. 使用已有 MySQL

先创建专用库和账号，字符集必须为 `utf8mb4`：

```sql
CREATE DATABASE superclaw CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'superclaw'@'%' IDENTIFIED BY 'replace-with-strong-password';
GRANT ALL PRIVILEGES ON superclaw.* TO 'superclaw'@'%';
FLUSH PRIVILEGES;
```

然后执行，脚本会安全提示输入密码：

```powershell
.\scripts\bootstrap_windows.ps1 `
  -DatabaseMode Existing `
  -DatabaseHost 127.0.0.1 `
  -DatabasePort 3306 `
  -DatabaseName superclaw `
  -DatabaseUser superclaw `
  -Start
```

不要把数据库密码直接写进聊天、Git 命令或文档。

## 5. 日常启动与停止

```powershell
.\scripts\start_windows_dev.ps1
.\scripts\start_windows_dev.ps1 -Restart
.\scripts\stop_windows_dev.ps1
```

日志位于：

- `logs/api-dev.out.log`
- `logs/api-dev.err.log`
- `logs/frontend-dev.out.log`
- `logs/frontend-dev.err.log`

健康检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8987/health
.\.venv\Scripts\python.exe scripts\hongguo_dev_smoke.py
```

结果必须满足 `status=ok`、`database=true`、`task_execution_ready=true`。

## 6. MuMu 与红果检查

脚本自动查找 `D:\Program Files\Netease\MuMu` 和 `C:\Program Files\Netease\MuMu`。非默认目录：

```powershell
.\scripts\bootstrap_windows.ps1 -DatabaseMode Auto -MuMuRoot 'D:\Apps\Netease\MuMu' -Start
```

打开待测 MuMu 实例，确认红果已登录，然后执行：

```powershell
.\.venv\Scripts\python.exe scripts\hongguo_dev_smoke.py --require-devices
```

也可在红果多开页面点击“检测实例/登录”。首次检测可能需要几十秒。

## 7. 推荐测试顺序

### 7.1 无设备基础测试

1. 打开模板管理页。
2. 新增一个有名称、分类、两行以上内容的模板。
3. 编辑模板名称并刷新，确认名称仍存在。
4. 打开红果多开页，将内容来源切换为“模板抽取”。
5. 确认模板下拉框展示模板名称，不展示整段评论内容。

AI Token 不是基础测试前提。Token 配额不足时可使用模板模式；AI 返回 `429 quota exhausted` 时系统会回退本地评论。

### 7.2 真实设备冒烟

1. 只启动 1 个 MuMu 实例。
2. 使用一个短剧和很短的集数范围。
3. 内容来源选择模板，随机点赞可先设 `0`，收藏设 `0`。
4. 检查任务日志、评论验证截图和完成统计。
5. 单实例通过后再扩大到 2-3 个实例。

不要在代码刚修改后直接运行长达几十集的三实例压力测试。

## 8. 开发验证

后端/RPA：

```powershell
.\.venv\Scripts\python.exe -m py_compile src\rpa\dashboard\routes_hongguo.py
.\.venv\Scripts\python.exe -m pytest `
  tests\test_hongguo_templates.py `
  tests\test_server_security.py `
  tests\test_rpa_engine.py -q
```

前端：

```powershell
Set-Location frontend
npm.cmd run build
Set-Location ..
```

完整 `pytest` 如果在收集阶段出现与本次改动无关的历史模块导入错误，应记录具体错误，但不能用它替代上述红果相关回归。

## 9. 开发注意事项

- 修改前先看 `git status --short`，不得回滚其他人的未提交改动。
- 红果任务必须使用 MySQL，不能切换到 SQLite 后宣称通过。
- API 重启前先检查 `/health` 的 `running_tasks`；非用户明确要求时，不得中断运行任务。
- 集数不可读时不能把 `0` 当作成功；恢复后必须强确认目标集。
- 直播页、广告页和红包雨活动页是不同状态，处理逻辑不可混用。
- 评论成功必须有发送后验证和截图；恢复任务不得重复发送已验证评论。
- 模板名称是下拉框展示值；模板内容按行拆成独立评论候选。
- AI `401` 表示密钥无效，`429 quota exhausted` 表示配额耗尽，两者不能混淆。
- `config/local.yaml`、`.env`、数据库导出、日志、截图、ADB 输出、`tmp/` 和 `backups/` 不得提交。

完整 Agent 规则见仓库根目录 `AGENTS.md`。

## 10. 常见故障

Docker 未运行：启动 Docker Desktop，执行 `docker info`，再重新运行 bootstrap。

端口占用：

```powershell
Get-NetTCPConnection -State Listen | Where-Object LocalPort -in 3308,8987,3000
```

数据库可通过 `-DatabasePort` 修改；API/前端可通过 `-ApiPort`、`-FrontendPort` 修改，脚本会同步调整前端 API 代理。smoke 必须使用相同参数，例如：

```powershell
.\.venv\Scripts\python.exe scripts\hongguo_dev_smoke.py --api-port 8990 --frontend-port 3010
```

数据库连接失败：

```powershell
docker ps --filter name=superclaw-dev-mysql
docker logs superclaw-dev-mysql --tail 100
```

检测不到 MuMu：确认 `MuMuManager.exe` 和 `adb.exe` 存在、实例已启动并开启 ADB；非默认目录传 `-MuMuRoot`。

页面仍是旧代码：

```powershell
Set-Location frontend
npm.cmd run build
Set-Location ..
.\scripts\start_windows_dev.ps1 -Restart
```

然后强制刷新浏览器。
