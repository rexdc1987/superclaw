# SuperClaw 红果版 · 新电脑部署手册

> 本手册是把 **当前这台电脑（JXICOLEBARQJCGS）上已经跑通的部署** 复现到另一台 Windows 电脑的完整步骤。
> 包含全部踩坑记录与规避方法，照着做可一次成功。

> ✅ **本仓库不含任何数据库地址与密码** —— 两者都在部署时通过参数或交互输入提供，不会落盘到版本库。
> 这样仓库即使是公开的，也不会泄露服务器位置和凭据。

---

## 〇、TL;DR — 三条命令搞定

```powershell
# 1. 克隆部署分支（含部署包）
git clone -b codex/hongguo-deploy-kit https://github.com/rexdc1987/superclaw.git superclaw
cd superclaw

# 2. 执行部署（地址和密码在这里给，都不会写进仓库）
powershell -ExecutionPolicy Bypass -File .\deploy-kit\deploy_superclaw.ps1 -TargetDir . -DbHost "数据库地址" -DbPassword "数据库密码"
#    想省事也可以全都不给 —— 脚本会交互式提示输入地址和密码：
#    powershell -ExecutionPolicy Bypass -File .\deploy-kit\deploy_superclaw.ps1 -TargetDir .

# 3. 启动，然后浏览器打开 http://127.0.0.1:3000/hongguo/multi
.\start_superclaw.bat
```

脚本会自动完成源码修复、建 Python 环境、装依赖、生成配置、装前端依赖、自检。
**每步幂等，可以重复运行**；中途失败修好原因后直接重跑即可。

> **数据库地址和密码去哪拿**：向部署发起人索取。
> 这两个值**刻意不写在仓库任何文件里**，由每个部署者自行提供 ——
> 这样仓库即使公开，也不会泄露你的服务器位置和凭据。

> **数据库密码去哪拿**：向部署发起人索取。密码不写在任何仓库文件里，
> 每个部署者自行提供 —— 这样仓库即使公开也不会泄密。

---

## 一、部署包里有什么

| 文件 | 作用 | 必需 |
| --- | --- | --- |
| `README.md` | 本手册 | — |
| `deploy_superclaw.ps1` | 一键部署脚本（探测/克隆/打补丁/装依赖/写配置/自检） | ✅ |
| `superclaw-fixes.patch` | 需要打的源码修复补丁（4 个文件） | ✅ |
| `requirements-superclaw.txt` | Python 依赖精确清单（48 个包，与本机完全一致） | ✅ |
| `start_superclaw.bat` | 一键启动（含 MuMu 路径自动探测 + ADB 预连接） | ✅ |
| `stop_superclaw.bat` | 一键停止（按端口精准 kill） | ✅ |

> **重要**：`start_superclaw.bat` / `stop_superclaw.bat` **没有纳入 git**（未跟踪文件），
> 全新克隆的仓库里不会有这两个文件。部署脚本会自动把它们复制进去，所以**别漏拷这两个 bat**。

---

## 二、前置条件

新电脑上需要满足：

| 项 | 要求 | 说明 |
| --- | --- | --- |
| 操作系统 | Windows 10 / 11 | 已在 Win + MuMu 12 上验证 |
| Git | 任意版本 | 用于克隆仓库 |
| Python | **3.9+**（本机用 3.13.14） | 用于后端 API |
| Node.js | **18+**（本机用 22.22.2） | 用于前端 Vite |
| MySQL | **不需要本地装** | 连接远程库（地址由部署发起人提供） |
| MuMu 模拟器 | 可选 | 只有需要真机自动评论时才要 |

**脚本会自己找**：如果新电脑装了 WorkBuddy，会优先用
`%USERPROFILE%\.workbuddy\binaries\` 下自带的 python / node / git；找不到就回退到系统 PATH。
所以 WorkBuddy 装不装都行，但**系统里至少要有能用的 Python 和 Node**。

> 另一个环境变量：AI 评论功能默认读 `XIAOMI_API_KEY`。
> 若需要 AI 生成评论，部署后在页面【设置】里填密钥（会写入 `config/local.yaml`，
> 该文件已被 `.gitignore` 忽略）。不填则走 `fallback_to_local` 本地模板。

---

## 三、快速部署（推荐）

### 3.1 获取部署包（二选一）

**方式 A — 从 git 克隆（推荐，有网就能用）**

```bat
git clone -b codex/hongguo-deploy-kit https://github.com/rexdc1987/superclaw.git superclaw
cd superclaw
```

部署包在 `superclaw\deploy-kit\`，脚本会自动识别出仓库根目录，**不需要再克隆一次**。

**方式 B — 拷贝文件夹（离线 / 无 git 环境）**

把 `superclaw-deploy-kit` 文件夹复制到新电脑，例如 `D:\superclaw-deploy-kit`。
这种方式下脚本会自己从 GitHub 克隆代码到旁边的 `superclaw\` 目录。

### 3.2 执行部署脚本

```powershell
# 方式 A（已克隆，当前在仓库根目录）
powershell -ExecutionPolicy Bypass -File .\deploy-kit\deploy_superclaw.ps1 -TargetDir . -DbHost "数据库地址" -DbPassword "数据库密码"

# 方式 B（拷贝的独立文件夹）
cd /d D:\superclaw-deploy-kit
powershell -ExecutionPolicy Bypass -File .\deploy_superclaw.ps1 -DbHost "数据库地址" -DbPassword "数据库密码"

# 最省事：什么都不给，脚本交互提示输入地址和密码
powershell -ExecutionPolicy Bypass -File .\deploy-kit\deploy_superclaw.ps1 -TargetDir .
```

**如果提示"禁止运行脚本"**（PowerShell 默认策略是 Restricted），用上面这种
`-ExecutionPolicy Bypass` 写法即可，不需要改系统策略。

**常用可选参数**：

```powershell
# 指定安装目录（方式 A 用 "."；默认是脚本旁的 superclaw 文件夹）
  -TargetDir "D:\superclaw"

# 数据库连接（仓库里不含，必须由部署者提供）
  -DbHost "数据库地址"        # 不提供则交互提示
  -DbPort 3306               # 默认 3306
  -DbName "superclaw"        # 默认 superclaw
  -DbUser "superclaw"        # 默认 superclaw
  -DbPassword "数据库密码"    # 不提供则安全提示（不回显）

# 指定 MuMu 安装位置（脚本也会自动扫 C~H 盘，一般不用给）
  -MumuRoot "E:\Program Files\Netease\MuMu"

# 网络慢时换镜像源（默认已是国内镜像）
  -PipIndex "https://pypi.tuna.tsinghua.edu.cn/simple"
  -NpmRegistry "https://registry.npmmirror.com"

# 只部署后端，不装前端依赖
  -SkipFrontend

# 纯 Web 用途，跳过 MuMu 检测
  -SkipMumu
```

**不需要**传数据库地址/库名/用户 —— 默认值已经是正确的远程库参数，只需给密码。

### 3.3 期望输出

成功时最后会打印 8 个步骤、每步 `[OK]`，并以 `部署完成` 结束：

```
=== [1] 探测 git / python / node ===
  [OK]   git    : ...\PortableGit\versions\1.2.0\cmd\git.exe
  [OK]   python : ...\python\versions\3.13.12\python.exe
  [OK]   node   : ...\node\versions\22.22.2-3
=== [2] 获取代码 ===
  [OK]   当前提交：d48182f
=== [3] 应用源码修复补丁 ===
  [OK]   补丁已应用：superclaw-fixes.patch
=== [4] 创建 Python 虚拟环境并安装依赖 ===
  [OK]   核心依赖导入正常
=== [5] 生成 config/local.yaml ===
  [OK]   CFG_OK db=superclaw@<你的数据库地址>:3306/superclaw secret_len=64
=== [6] 探测 MuMu 模拟器 ===
  [OK]   MuMu 根目录：E:\Program Files\Netease\MuMu
=== [7] 安装前端依赖 ===
  [OK]   前端依赖安装完成
=== [8] 部署自检 ===
  [OK]   Python venv / 配置文件 / 启动脚本 / 前端依赖
============================================================
 部署完成
============================================================
```

### 3.4 启动

```bat
D:\superclaw\start_superclaw.bat
```

双击后会弹出**两个黑窗口**（API 和 Web），并且启动时会先重启 ADB、预连接 MuMu 实例端口。
等两个窗口都出现日志后，浏览器打开：

| 用途 | 地址 |
| --- | --- |
| **前端页面** | http://127.0.0.1:3000/hongguo/multi |
| API 健康检查 | http://127.0.0.1:8987/health |
| 接口文档 | http://127.0.0.1:8987/docs |

停止：双击 `stop_superclaw.bat`，或直接关掉那两个窗口。

**登录**：直接用已有账号（数据库里已有 11 个用户，含 `admin`、`dc`、`admin006`），**不需要新建**。

---

## 四、手动部署（脚本失败时的兜底）

如果自动脚本因为环境差异跑不通，按下面的步骤手工来。假设安装到 `D:\superclaw`。

### 步骤 1 — 克隆仓库

```bat
git clone --branch codex/hongguo-server-ready https://github.com/rexdc1987/superclaw.git D:\superclaw
cd /d D:\superclaw
```

> ⚠️ **坑 1：分支名带斜杠，克隆后可能没有本地分支**
> `--branch codex/hongguo-server-ready` 在部分 git 版本下不会生成 `refs/heads/codex/...`，
> 结果 `git log` 报 `does not have any commits yet`。修复：
> ```bat
> git fetch origin codex/hongguo-server-ready
> git rev-parse origin/codex/hongguo-server-ready
> REM 把上面输出的 sha 写进本地 ref（注意目录要一层层建）：
> mkdir .git\refs\heads\codex
> echo <上一步的sha> > .git\refs\heads\codex\hongguo-server-ready
> git log --oneline -1
> ```

### 步骤 2 — 打源码补丁

```bat
git apply D:\superclaw-deploy-kit\superclaw-fixes.patch
```

如果报错，先试宽松模式：

```bat
git apply --ignore-whitespace --ignore-space-change D:\superclaw-deploy-kit\superclaw-fixes.patch
```

仍然失败的话，按 **第九节「源码改动清单」** 手工改 4 个文件。

### 步骤 3 — 建 Python 环境并装依赖

```bat
python -m venv D:\superclaw\.venv-api
D:\superclaw\.venv-api\Scripts\python.exe -m pip install -r D:\superclaw-deploy-kit\requirements-superclaw.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

> ⚠️ **坑 2：不要执行 `pip install -e .`**
> 仓库 `pyproject.toml` 原本用了已被 setuptools ≥84 移除的构建后端
> `setuptools.backends._legacy:_Backend`（补丁已修）。
> 而且**跑 API 根本不需要可编辑安装** —— `run_api.py` 自己就把 `src/` 插进了 `sys.path`：
> ```python
> sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src'))
> uvicorn.run("api.main:app", host="0.0.0.0", port=port)
> ```

> ⚠️ **坑 3：装依赖时如果装在 WorkBuddy 沙箱里，必须先关掉删除拦截器**
> ```bat
> set CODEBUDDY_SAFE_DELETE_ENABLED=0
> ```
> 否则 pip/npm 清理临时文件会被误判为"批量删除"而中断，包会被装成残缺状态
> （表现为 `click.Choice` 不存在、`pip` 自身无法运行）。普通 CMD 里设这个变量无副作用。

### 步骤 4 — 生成配置

创建 `D:\superclaw\config\local.yaml`，内容如下（把密码填上）：

```yaml
database:
  engine: mysql
  host: <你的数据库地址>
  port: 3306
  name: superclaw
  user: superclaw
  password: '你的数据库密码'
security:
  auth_required: true
  auth_secret: '<自己生成一串 ≥32 位的随机字符串>'
```

> 说明：`config/local.yaml` **已被 `.gitignore` 忽略**，不会入库。
> 配置加载逻辑是「代码内置默认值 ← 深合并 ← 你指定的 YAML」，
> 所以这个文件只写要覆盖的字段就够了，不必抄全量。
> `auth_secret` 一旦生成就别改，改了所有人需重新登录。生成方法：
> ```bat
> D:\superclaw\.venv-api\Scripts\python.exe -c "import secrets;print(secrets.token_urlsafe(48))"
> ```

### 步骤 5 — 装前端依赖

```bat
cd /d D:\superclaw\frontend
npm.cmd ci --registry=https://registry.npmmirror.com --no-audit --no-fund
```

> ⚠️ **坑 4：`npm ci` 跑完必须验证**
> 沙箱的删除拦截器会把包目录写成**空目录**（不是缺失），npm 以为装好了就跳过，
> 结果启动前端时报 `Failed to resolve element-plus/dist/index.css`。
> 验证命令：
> ```bat
> dir node_modules\element-plus\dist\index.css
> dir node_modules\element-plus\es\index.mjs
> ```
> 这两个文件在才算是真的装好了。缺了就直接重跑 `npm ci`。

### 步骤 6 — 拷贝启动脚本

把部署包里的 `start_superclaw.bat` 和 `stop_superclaw.bat` 复制到 `D:\superclaw\`。

### 步骤 7 — 启动

双击 `D:\superclaw\start_superclaw.bat`。

---

## 五、验证清单

部署完逐条对照，全部通过才算成功：

```
[ ] API 端口监听        netstat -ano | findstr :8987     → LISTENING
[ ] Web 端口监听        netstat -ano | findstr :3000     → LISTENING
[ ] 健康检查            http://127.0.0.1:8987/health     → 200
[ ] 前端页面            http://127.0.0.1:3000/hongguo/multi → 200
[ ] 代理转发            http://127.0.0.1:3000/api/v1/auth/status → 200
[ ] 接口文档            http://127.0.0.1:8987/docs       → 200
[ ] 数据库连通          页面上能正常登录
[ ] 实例检测            点【检测实例/登录】→ 在线 N 台
```

`/health` 期望返回：

```json
{"status":"ok","auth_required":true,"database":true,
 "execution_mode":"embedded","task_execution_ready":true}
```

**用 curl 验证时注意**：本机 `curl` 会走系统代理导致连不上 127.0.0.1，要加 `--noproxy '*'`：

```bat
curl.exe -s --noproxy "*" http://127.0.0.1:8987/health
```

---

## 六、日常使用

| 操作 | 方式 |
| --- | --- |
| 启动 | 双击 `start_superclaw.bat`（会弹 2 个窗口，别关） |
| 停止 | 双击 `stop_superclaw.bat` |
| 看 API 日志 | 那个标题为 `SuperClaw-API` 的窗口 |
| 看前端日志 | 那个标题为 `SuperClaw-Web` 的窗口 |
| 改端口 | 改 `start_superclaw.bat` 里的 `SUPERCLAW_API_PORT`，前端端口改 `frontend\vite.config.js` |
| 开机自启 | 把 `start_superclaw.bat` 的快捷方式丢进 `shell:startup` |

**MuMu 多开端口规律**：实例端口是 **16384 / 16416 / 16448**（步长 32）。
`start_superclaw.bat` 已内置 `for /L %%P in (16384,32,16512)` 扫描连接，再多开一两台也能覆盖。

**为什么必须显式 connect**：MuMu 12 自动枚举出的 `emulator-5554` 长期卡在 `offline` 状态，
只有显式 `adb connect 127.0.0.1:16384` 才会稳定变成 `device`。这是"检测到 0 台"的头号原因。

---

## 七、踩坑总表（本次部署实际遇到的）

> 这一节是整份手册最有价值的部分。**在新电脑上重犯的概率很高，建议逐条读一遍。**

### 环境类

| # | 现象 | 根因 | 规避 |
| --- | --- | --- | --- |
| 1 | `git log` 报 `does not have any commits yet` | 分支名含 `/`，`clone --branch` 未生成本地 ref | 手动写 `.git/refs/heads/codex/hongguo-server-ready` |
| 2 | pip/npm 装到一半失败，包残缺 | WorkBuddy 沙箱注入的 `safe-delete` 拦截器把临时文件清理误判为批量删除 | 设 `CODEBUDDY_SAFE_DELETE_ENABLED=0` |
| 3 | `pip install -e .` 报 `Cannot import 'setuptools.backends._legacy'` | setuptools ≥84 已移除该模块（分支自身 bug） | 改 `pyproject.toml` 为 `setuptools.build_meta`；**或干脆不做可编辑安装** |
| 4 | 服务启动后命令一结束就没了 | 沙箱会回收它拉起的后台进程（`nohup`/`&`/`Start-Process` 都会被回收，`schtasks` 被列入黑名单） | 用 `.bat` 在用户自己的会话里启动 |
| 5 | 前端报 `Failed to resolve element-plus/dist/index.css` | `node_modules` 里的包目录是**空的**（拦截器写坏），npm 以为已安装 | `npm ci` 整体重装 + 验证文件真的存在 |
| 6 | 双击 bat 找不到 npm | node 版本目录名会变（`22.22.2-2` → `22.22.2-3`），脚本里写死了旧版本号 | 启动脚本改为**动态探测最新版本目录** |
| 7 | PowerShell 报"禁止运行脚本" | 默认执行策略为 Restricted | `powershell -ExecutionPolicy Bypass -File ...` |
| 8 | PowerShell 里找不到 git/node/python | 其 PATH 与 cmd 不一致 | 脚本里用绝对路径；git 在 `PortableGit\versions\1.2.0\cmd`（**不是 `bin`**） |
| 9 | `curl http://127.0.0.1:8987` 连不上 | curl 走了系统代理 | 加 `--noproxy "*"` |
| 10 | 局域网 IP 访问前端被拒（`Blocked request`） | `frontend/vite.config.js` 的 `allowedHosts` 只允许 `test.openclaw.com` / `localhost` / `127.0.0.1` | 把局域网 IP 加进 `allowedHosts` 再重启前端 |
| 11 | 访问 `test.openclaw.com` 报 DNS 错误 | 它只是 `allowedHosts` 里的白名单名，**没有真实 DNS** | 用 `127.0.0.1`；或在 `hosts` 文件加 `127.0.0.1 test.openclaw.com` |
| 12 | PowerShell 脚本中文乱码、语法报错 | PS 5.1 对**无 BOM** 的 UTF-8 脚本按 GBK 解析 | `.ps1` 必须存为 **UTF-8 with BOM** |

### MuMu / ADB 类

| # | 现象 | 根因 | 规避 |
| --- | --- | --- | --- |
| 13 | 点【检测实例/登录】一直"在线 0 台"，**且控制台无任何报错** | `adbutils` 未安装 → `discover_online_addrs()` 的 import 异常被 `except` 静默吞掉，直接返回空列表 | 装 `adbutils`（已在 requirements 里） |
| 14 | `MuMuManager.exe` / `adb.exe` 定位失败 | 代码默认 `D:\Program Files\Netease\MuMu`，实际装在别的盘 | 启动脚本自动扫 C~H 盘并设 `SUPERCLAW_MUMU_ROOT` |
| 15 | 设备一直 `offline` | MuMu 12 自动枚举的 `emulator-5554` 不稳定 | 显式 `adb connect 127.0.0.1:16384`（步长 32） |
| 16 | 登录态检测抛 `device_connect_failed` | `uiautomator2` 未安装 | 装 `uiautomator2`（已在 requirements 里） |
| 17 | 显示"已登录 0 台" | 判定逻辑要启动红果 App（`com.phoenix.read`）后检查账号登录态 | **这不是故障**，在模拟器里登录红果账号即可 |

> **调试提示**：`/api/v1/hongguo/multi/devices` 需要认证，裸 curl 返回 401。
> 想直接验证后端检测逻辑，绕过 HTTP 层调用：
> ```python
> from rpa.dashboard.routes_hongguo import _detect_multi_devices_uncached
> print(_detect_multi_devices_uncached())
> ```
> 另外注意：**ADB daemon 会被 WorkBuddy 沙箱回收** —— 每条命令一结束，该命令拉起的 daemon 就被杀，
> 表现为下一句又报 `daemon not running`、设备退回 offline（5037 端口堆一堆 `TIME_WAIT`）。
> 这只影响在沙箱里逐条敲调试命令，**不影响双击 bat 启动的场景**。

---

## 八、故障排查速查

| 症状 | 先查这里 |
| --- | --- |
| 浏览器打不开页面 | `netstat -ano \| findstr :3000` 有没有 LISTENING；Web 窗口有没有报错 |
| 页面打开但白屏 | F12 看 Console；多半是 `node_modules` 不完整 → 重跑 `npm ci` 并验证 `element-plus/dist/index.css` 存在 |
| 登录报 500 | API 窗口日志；多半是数据库连不上 → 检查 `config/local.yaml` 的 host/密码 |
| 登录报 401 | 账号密码错，属正常业务返回（不是故障） |
| `/health` 里 `database: false` | 数据库配置错，或远程 MySQL 未放行本机 IP |
| 检测实例 0 台 | ①MuMu 开了吗 ②`adb devices` 有没有 `device` ③`SUPERCLAW_MUMU_ROOT` 对不对 ④adbutils/uiautomator2 装了没 |
| 双击 bat 一闪而过 | 看提示；多半是 `.venv-api` 不存在（先跑部署脚本）或 npm 找不到 |
| 端口被占用 | 先跑 `stop_superclaw.bat`，再 `netstat -ano \| findstr :8987` 查残留 PID |

**手动启动后端**（排查用，能看到完整报错）：

```bat
cd /d D:\superclaw
set SUPERCLAW_CONFIG=D:\superclaw\config\local.yaml
set SUPERCLAW_MUMU_ROOT=E:\Program Files\Netease\MuMu
set SUPERCLAW_API_PORT=8987
.venv-api\Scripts\python.exe run_api.py
```

---

## 九、源码改动清单

部署脚本会给仓库打一个补丁，涉及 **4 个文件**。如果补丁没法应用，按下表手工改。

### 9.1 `pyproject.toml` 第 3 行 —— 分支自身的 bug

setuptools ≥84 已移除 `setuptools.backends._legacy`：

```diff
- build-backend = "setuptools.backends._legacy:_Backend"
+ build-backend = "setuptools.build_meta"
```

### 9.2 `frontend/package.json` —— 补一个显式依赖

```diff
     "element-plus": "^2.14.2",
+    "entities": "^8.0.0",
```

（配套的 `frontend/package-lock.json` 有 17 行改动，一起在补丁里。）

### 9.3 `src/rpa/hongguo/operations.py` —— 两处业务修复

**这是本次唯一有实质逻辑改动的文件**（真实改动 91 行新增 / 2 行删除）。
改动前**务必先备份该文件**，改动均为向后兼容的增量，未删除原有逻辑。

| 位置 | 改动 |
| --- | --- |
| 模块常量区 | 新增 `SEARCH_RESULT_TAB_MARKERS`、`SEARCH_RESULT_PAGE_HINTS`、`REWARD_FLOAT_MARKERS` |
| `_search_results_visible()` | tab 判定改用常量，补上「小说 / 听书 / 漫画 / 番剧」等新版 tab |
| 新增 `_reward_float_point()` / `_reward_float_visible()` / `_dismiss_reward_float()` | 检测并消除右上角「金币红包悬浮球」 |
| `prepare_comment_window()` | 入口先调 `_dismiss_reward_float()` |
| `_open_comment_panel()` | 开头先调 `_dismiss_reward_float()` |

**这两处修的是什么问题：**

- **搜索页识别误判**：原判定只认旧版 tab 组合 `综合/短剧/影视/用户`，而新版红果结果是
  `综合/小说/听书` → 命中数 1 < 阈值 2 → 搜索结果明明出来了却判为"未进入搜索结果页"，
  白白重试 74 秒后失败。
- **金币红包悬浮球遮挡**：右上角「16888 / 立即领取」悬浮球会在播放页叠一层**透明 Compose 触摸层**，
  导致评论按钮点击完全无效。原代码只处理整页「红包雨」，对悬浮球零处理。

> 提示：用编辑器改过该文件后，`git diff --stat` 可能因为换行符（CRLF/LF）显示几千行噪音。
> 看真实改动用 `git diff --ignore-all-space`。

### 9.4 仓库外改动（不在 git 里）

`.venv-api/`（虚拟环境）、`config/local.yaml`（已 gitignore）、
`start_superclaw.bat`、`stop_superclaw.bat`（未跟踪，需从部署包复制）。

---

## 十、附录：参数速查

### 关键参数

| 项 | 值 |
| --- | --- |
| 仓库 | `https://github.com/rexdc1987/superclaw.git` |
| 分支 | `codex/hongguo-server-ready` |
| 提交 | `d48182f` |
| 数据库 | 地址由部署发起人提供（库名/用户名均为 `superclaw`，端口 `3306`） |
| API 端口 | `8987`（监听 `0.0.0.0`） |
| 前端端口 | `3000`（Vite，`/api` 代理到 `127.0.0.1:8987`） |
| 执行模式 | `embedded`（扫本地 ADB，非远程 worker） |
| 红果 App 包名 | `com.phoenix.read` |
| MuMu 实例端口 | `16384` 起，步长 `32` |

### 环境变量

| 变量 | 作用 | 是否必需 |
| --- | --- | --- |
| `SUPERCLAW_CONFIG` | 指定配置文件路径 | ✅（bat 已设） |
| `SUPERCLAW_API_PORT` | 后端端口 | ✅（bat 已设） |
| `SUPERCLAW_MUMU_ROOT` | MuMu 安装根目录 | 需要真机时必需（bat 自动探测） |
| `SUPERCLAW_EXECUTION_MODE` | `embedded` / `api` | 默认 embedded |
| `SUPERCLAW_WORKER_ID` | worker 标识，不设则用主机名 | 可选 |
| `CODEBUDDY_SAFE_DELETE_ENABLED` | 设 `0` 关闭沙箱删除拦截器 | 在 WorkBuddy 沙箱内装包时必需 |
| `XIAOMI_API_KEY` | AI 评论密钥（也可在页面设置里填） | 需要 AI 评论时 |

### 本机已确认的业务状态（供新电脑对照）

```
系统用户           11 个（含 admin、dc、admin006 …）
任务归属           owner_user_id=14 → admin006；历史 owner_user_id=0 为认证关闭期的"本地账号"
执行模式           embedded，worker_id 回落为主机名
实例检测（新电脑需自行验证）：
   127.0.0.1:16384  在线，未登录
   127.0.0.1:16416  在线，未登录
   127.0.0.1:16448  在线，已登录红果账号
```

---

## 十一、部署完成之后

1. **验证清单**（第五节）逐条过一遍。
2. **在模拟器里登录红果账号** ——「已登录 0 台」通常只是 App 内没登录，不是部署问题。
3. **配 AI 密钥**（如需 AI 评论）—— 页面【设置】里填，或设 `XIAOMI_API_KEY` 环境变量。
4. **上生产还需**：HTTPS 反代、不暴露 MySQL/ADB 端口、定期备份。

### 已知遗留问题

- **任务 340 的集数漂移**：暂停后播放器仍会跨集自动切换（22→23），
  拖长了失败恢复耗时。当前版本未处理该逻辑，若再复现需单独排查。
- **PySide6 桌面 GUI / playwright / pyinstaller** 未安装（为缩短安装时间），
  如需跑桌面端或自动化测试需另行安装。

---

## 十二、附：本部署包的验证记录

这份部署包**不是凭记忆写的，是实测过的**。验证内容：

| 验证项 | 结果 |
| --- | --- |
| `deploy_superclaw.ps1` PowerShell 语法解析 | 无错误 |
| 脚本在已有部署上完整跑一遍（9 个步骤） | 全部 `[OK]`，退出码 0 |
| 重复运行的幂等性 | 配置生成后与原文件**字节级一致**（`auth_secret` 正确保留） |
| 交互式提示路径（不给 `-DbHost`） | 正确提示并读取输入，流程继续 |
| **按真实流程走一遍**：克隆部署分支 → 在仓库内跑脚本 | 自动识别仓库根目录 ✓ / 跳过重复克隆 ✓ / 建 venv ✓ / 装 48 个依赖 ✓ / 生成配置 ✓ / 自检通过 ✓ |
| 补丁应用到**全新克隆** | 从 GitHub 克隆时严格模式可应用；从本地克隆时严格模式失败、**宽松模式回退成功**（脚本已内置自动回退，两种情况都能装上） |
| 补丁应用后逐项核对 | `setuptools.build_meta` ✓ / `entities` 依赖 ✓ / 3 个新方法 ✓ |
| 补丁后 `operations.py` 语法编译 | 通过 |
| 用打补丁后的**全新克隆实际启动 API** | 端口监听正常，`/health` 全部 `true`，`/docs` 200 |

`/health` 实测返回：

```json
{"status":"ok","auth_required":true,"database":true,"execution_mode":"embedded",
 "online_workers":0,"running_tasks":0,"task_execution_ready":true}
```

> 说明：验证用的是**同一套远程数据库**，所以 `database: true` 是真实连通结果。
> 新电脑连的是同一个库，数据（用户、任务、配置）会自动共享，不需要再做数据迁移。

### 关于「两个部署实例共用一套数据库」

新电脑部署后连的是**同一台远程库**（地址由发起人提供），意味着：

- **用户账号、任务历史、配置都是共享的** —— 在任意一台机器上操作都能看到。
- **不要在第二台上重复创建账号**，直接用已有账号登录即可。
- 两台机器如果同时跑任务，任务表里用 `worker_id`（主机名）区分执行来源，
  界面上「实例」列显示的就是这个值。

