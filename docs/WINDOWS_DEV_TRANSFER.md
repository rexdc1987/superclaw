# Windows 开发环境迁移

这个开发包用于把 SuperClaw 源码和 Git 历史迁移到另一台 Windows 电脑继续开发。虚拟环境、Node 依赖、数据库、日志、截图和本机密钥不包含在压缩包内，需要在目标电脑重新建立。

## 目标电脑要求

- Windows 10/11 x64
- Git
- Python 3.11 x64，并安装 `py` launcher
- Node.js 22 LTS
- MySQL 8.x
- 需要运行红果自动化时，安装 MuMu 模拟器和红果 App

## 初始化

解压 ZIP 后，在项目根目录打开 PowerShell：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\setup_windows_dev.ps1
```

不需要旧版 Playwright 自动化时，可以跳过 Chromium 下载：

```powershell
.\scripts\setup_windows_dev.ps1 -SkipPlaywright
```

脚本会创建 `.venv`、安装 Python 开发依赖、安装当前项目，并通过 `npm ci` 重建和编译 Vue 前端。

## 本机配置

创建 `config/local.yaml`。该文件已被 Git 忽略，不要提交密码：

```yaml
database:
  engine: mysql
  host: 127.0.0.1
  port: 3306
  name: superclaw
  user: superclaw
  password: replace-me

hongguo:
  device_addr: 127.0.0.1:5555
```

如果 MuMu 不在项目默认位置，设置：

```powershell
$env:SUPERCLAW_MUMU_ROOT = 'D:\Program Files\Netease\MuMu'
```

首次创建管理员：

```powershell
$env:SUPERCLAW_ADMIN_USERNAME = 'admin'
$env:SUPERCLAW_ADMIN_PASSWORD = 'replace-with-a-strong-password'
.\.venv\Scripts\python.exe scripts\create_admin.py
```

## 启动

本机一体化开发模式：

```powershell
$env:SUPERCLAW_AUTH_REQUIRED = 'false'
$env:SUPERCLAW_EXECUTION_MODE = 'embedded'
.\.venv\Scripts\python.exe run_api.py
```

浏览器访问 `http://127.0.0.1:8980`。

单独启动 Windows Worker：

```powershell
$env:SUPERCLAW_DB_HOST = '数据库地址'
$env:SUPERCLAW_DB_PASSWORD = '数据库密码'
.\scripts\start_hongguo_worker.ps1 -WorkerId 'win-dev-01'
```

## 压缩包未包含的内容

- `venv/`、`.venv/`、`venv314/`
- `frontend/node_modules/` 和前端构建产物
- `data/`、数据库导出、运行日志和截图
- `config/local.yaml`、`.env` 和 API 密钥
- `backups/`、`tmp/`、测试缓存和 Python 字节码

如果确实需要迁移现有 MySQL 数据，应单独通过 `mysqldump` 导出，并使用加密渠道传输。不要把数据库导出或 `config/local.yaml` 放进源码包。
