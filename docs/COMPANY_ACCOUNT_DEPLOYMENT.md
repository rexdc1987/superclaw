# SuperClaw 公司账号部署手册

## 1. 推荐架构

公司只部署一套中央控制端：

- 一套 SuperClaw API 和前端。
- 一套 MySQL 8.x，统一保存用户、红果任务、日志、模板和设备租约。
- 每台运行 MuMu 的 Windows 电脑启动一个 Hongguo Worker，并使用唯一的 `WorkerId`。
- 员工在浏览器打开同一个公司 SuperClaw 地址，用管理员分配的个人账号登录。

不要在每台员工电脑创建独立数据库。独立数据库会导致管理员无法统一管理账号，任务和模板也无法按用户隔离。

## 2. 初始化中央控制端

首次安装：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\bootstrap_windows.ps1 -DatabaseMode Auto -Start
```

脚本会启用登录认证、生成仅保存在 `config/local.yaml` 中的签名密钥，并在数据库为空时创建 `admin`。自动生成的初始密码只在安装终端显示一次，首次登录后应立即修改。

使用公司已有 MySQL 时：

```powershell
.\scripts\bootstrap_windows.ps1 `
  -DatabaseMode Existing `
  -DatabaseHost '<mysql-host>' `
  -DatabasePort 3306 `
  -DatabaseName superclaw `
  -DatabaseUser superclaw `
  -Start
```

API 和 Worker 必须连接同一个数据库。不要向员工暴露 MySQL、ADB 或配置文件密码。

## 3. 管理员分配账号

1. 使用管理员账号登录 SuperClaw。
2. 打开左侧“账号管理”。
3. 点击“新增账号”，填写用户名、姓名、初始密码、角色和有效天数。
4. 将用户名和初始密码单独交给员工，并要求员工登录后点击左下角用户名修改密码。

管理员可以续期、重置密码、启用、禁用或删除账号。禁用、删除、改密和角色调整会立即使旧登录失效。系统禁止删除、禁用或降级最后一个可用管理员。

## 4. Windows MuMu 工作节点

每台 MuMu 电脑设置中央数据库连接后启动 Worker：

```powershell
$env:SUPERCLAW_DB_HOST = '<mysql-host>'
$env:SUPERCLAW_DB_PORT = '3306'
$env:SUPERCLAW_DB_NAME = 'superclaw'
$env:SUPERCLAW_DB_USER = 'superclaw'
$env:SUPERCLAW_DB_PASSWORD = '<database-password>'
.\scripts\start_hongguo_worker.ps1 -WorkerId 'mumu-host-01' -WorkerName 'MuMu Host 01'
```

每台电脑的 `WorkerId` 必须唯一，例如 `mumu-host-01`、`mumu-host-02`。中央 API 使用 MySQL 设备租约防止两个员工同时占用同一个实例。

## 5. 权限边界

- 员工只能查看自己的红果任务、批次、日志、执行记录、截图和个人模板。
- 员工可以使用系统默认模板，但不能修改系统默认模板。
- 管理员可以查看全部用户数据、维护账号并配置全局 AI 参数。
- 用户名创建后不可修改；需要更换用户名时应新建账号并停用旧账号。

## 6. 上线检查

```powershell
Invoke-RestMethod http://127.0.0.1:8987/health
.\.venv\Scripts\python.exe scripts\hongguo_dev_smoke.py
```

健康结果必须包含 `status=ok`、`database=true`、`auth_required=true`。正式网络应在 API 前使用 HTTPS 反向代理，不要把 MySQL 或 ADB 端口暴露到公网。

如需让冒烟脚本同时验证登录后的模板接口，可临时设置 `SUPERCLAW_SMOKE_USERNAME` 和 `SUPERCLAW_SMOKE_PASSWORD`；脚本不会输出密码。未设置时，脚本会验证受保护接口正确返回 `401`。
