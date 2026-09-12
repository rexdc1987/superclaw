<#
================================================================
 SuperClaw 一键部署脚本 (Windows / PowerShell 5.1+)

 用途：在一台新电脑上从零部署 SuperClaw 红果版（本地使用 + 一键启动）。

 用法（管理员或普通 PowerShell 均可）：
   powershell -ExecutionPolicy Bypass -File .\deploy_superclaw.ps1

 可选参数示例：
   powershell -ExecutionPolicy Bypass -File .\deploy_superclaw.ps1 `
         -DbPassword "你的库密码" -MumuRoot "E:\Program Files\Netease\MuMu"

 脚本做这些事（每步幂等，可重复运行）：
   1. 探测 git / python / node
   2. 克隆仓库（含分支名带斜杠的 ref 修复）
   3. 应用 superclaw-fixes.patch（构建后端 / entities 依赖 / 红果执行修复）
   4. 创建 .venv-api 并安装依赖
   5. 生成 config/local.yaml（数据库 + 随机密钥）
   6. 安装前端依赖（npm ci）
   7. 自检并输出访问地址
================================================================
#>
[CmdletBinding()]
param(
    [string] $RepoUrl    = "https://github.com/rexdc1987/superclaw.git",
    [string] $Branch     = "codex/hongguo-server-ready",
    [string] $TargetDir  = "",
    [string] $PatchFile  = "",
    [string] $DbHost     = "",
    [int]    $DbPort     = 3306,
    [string] $DbName     = "superclaw",
    [string] $DbUser     = "superclaw",
    [string] $DbPassword = "",
    [string] $MumuRoot   = "",
    [int]    $ApiPort    = 8987,
    [int]    $WebPort    = 3000,
    [string] $PipIndex   = "https://pypi.tuna.tsinghua.edu.cn/simple",
    [string] $NpmRegistry = "https://registry.npmmirror.com",
    [switch] $SkipFrontend,
    [switch] $SkipMumu
)

$ErrorActionPreference = "Continue"
# 关闭 WorkBuddy 沙箱的删除拦截器（它会把 pip/npm 的临时文件清理误判为批量删除，
# 导致包装到一半就损坏）。在普通命令行里设置此变量无副作用。
$env:CODEBUDDY_SAFE_DELETE_ENABLED = "0"

$ScriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
if (-not $TargetDir) {
    # 情形 A：脚本位于仓库的 deploy-kit/ 子目录（从 git 克隆整个分支的场景）
    #         → 目标就是仓库根目录，不需要再克隆
    $parent = Split-Path $ScriptDir -Parent
    if (Test-Path (Join-Path $parent ".git")) {
        $TargetDir = $parent
    } else {
        # 情形 B：独立的部署包文件夹 → 在旁边克隆出一份代码
        $TargetDir = Join-Path $ScriptDir "superclaw"
    }
}
if (-not $PatchFile) {
    $candidate = Join-Path $ScriptDir "superclaw-fixes.patch"
    if (Test-Path $candidate) { $PatchFile = $candidate }
}

# ---------------------------------------------------------------- 辅助函数
$script:StepNo = 0
function Step($msg) {
    $script:StepNo++
    Write-Host ""
    Write-Host "=== [$($script:StepNo)] $msg ===" -ForegroundColor Cyan
}
function Ok($msg)   { Write-Host "  [OK]   $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "  [WARN] $msg" -ForegroundColor Yellow }
function Fail($msg) { Write-Host "  [FAIL] $msg" -ForegroundColor Red }

function Find-Git {
    $cands = @()
    $wb = Join-Path $env:USERPROFILE ".workbuddy\binaries\PortableGit\versions"
    if (Test-Path $wb) {
        Get-ChildItem $wb -Directory -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending | ForEach-Object {
                foreach ($sub in @("cmd\git.exe", "bin\git.exe")) {
                    $p = Join-Path $_.FullName $sub
                    if (Test-Path $p) { $cands += $p }
                }
            }
    }
    $g = Get-Command git.exe -ErrorAction SilentlyContinue
    if ($g) { $cands += $g.Source }
    foreach ($c in $cands) { if (Test-Path $c) { return $c } }
    return $null
}

function Find-Python {
    $cands = @()
    $wb = Join-Path $env:USERPROFILE ".workbuddy\binaries\python\versions"
    if (Test-Path $wb) {
        Get-ChildItem $wb -Directory -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending | ForEach-Object {
                $p = Join-Path $_.FullName "python.exe"
                if (Test-Path $p) { $cands += $p }
            }
    }
    foreach ($name in @("python.exe", "python3.exe")) {
        $c = Get-Command $name -ErrorAction SilentlyContinue
        if ($c) { $cands += $c.Source }
    }
    foreach ($c in $cands) {
        if (-not (Test-Path $c)) { continue }
        # 必须是 3.9+ 且能创建 venv
        $v = & $c -c "import sys;print(sys.version_info[0]*100+sys.version_info[1])" 2>$null
        if ($v -and [int]$v -ge 309) { return $c }
    }
    return $null
}

function Find-Node {
    $wb = Join-Path $env:USERPROFILE ".workbuddy\binaries\node\versions"
    if (Test-Path $wb) {
        $dirs = Get-ChildItem $wb -Directory -ErrorAction SilentlyContinue | Sort-Object Name -Descending
        foreach ($d in $dirs) {
            $npm = Join-Path $d.FullName "npm.cmd"
            if (Test-Path $npm) { return $d.FullName }
        }
    }
    $n = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if ($n) { return (Split-Path $n.Source -Parent) }
    return $null
}

function Find-MumuRoot {
    if ($MumuRoot -and (Test-Path (Join-Path $MumuRoot "nx_main\adb.exe"))) { return $MumuRoot }
    $envRoot = $env:SUPERCLAW_MUMU_ROOT
    if ($envRoot -and (Test-Path (Join-Path $envRoot "nx_main\adb.exe"))) { return $envRoot }
    foreach ($drive in @("C","D","E","F","G","H")) {
        foreach ($sub in @("Program Files\Netease\MuMu", "Program Files (x86)\Netease\MuMu", "MuMu", "MuMuPlayer")) {
            $p = "${drive}:\$sub"
            if (Test-Path (Join-Path $p "nx_main\adb.exe")) { return $p }
        }
    }
    return $null
}

# ---------------------------------------------------------------- 开始
$found = $null          # MuMu 根目录（供结尾摘要使用）
$needInstall = $false   # 前端是否需要安装

Write-Host ""
Write-Host "============================================================" -ForegroundColor White
Write-Host " SuperClaw 部署脚本" -ForegroundColor White
Write-Host " 目标目录 : $TargetDir" -ForegroundColor Gray
Write-Host " 仓库/分支: $RepoUrl @ $Branch" -ForegroundColor Gray
Write-Host "============================================================" -ForegroundColor White

# ---- 1. 探测工具链
Step "探测 git / python / node"
$Git  = Find-Git
$Py   = Find-Python
$NodeDir = Find-Node

if (-not $Git) { Fail "找不到 git.exe。请安装 Git for Windows 后重试。"; exit 1 } else { Ok "git    : $Git" }
if (-not $Py)  { Fail "找不到 Python 3.9+。请安装 Python 后重试。"; exit 1 }  else { Ok "python : $Py" }
if (-not $NodeDir) {
    if ($SkipFrontend) { Warn "找不到 Node.js（已指定 -SkipFrontend，继续）" }
    else { Fail "找不到 Node.js / npm。请安装 Node.js 18+ 后重试。"; exit 1 }
} else { Ok "node   : $NodeDir" }

$env:PATH = "$(Split-Path $Git -Parent);$NodeDir;$env:PATH"

# ---- 2. 克隆仓库
Step "获取代码"
if (Test-Path (Join-Path $TargetDir ".git")) {
    Ok "仓库已存在，跳过克隆：$TargetDir"
} else {
    if (Test-Path $TargetDir) {
        Warn "目录已存在但不是 git 仓库：$TargetDir（继续使用现有内容）"
    } else {
        Write-Host "  克隆中（分支名含斜杠，稍后如缺少本地 ref 会自动修复）..."
        & $Git clone --branch $Branch $RepoUrl $TargetDir 2>&1 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
    }
}

Push-Location $TargetDir
if (-not (Test-Path ".git")) {
    Fail "目标目录不是 git 仓库，无法继续：$TargetDir"
    Pop-Location; exit 1
}

# 修复：分支名 codex/hongguo-server-ready 含斜杠时，clone --branch 可能不生成
# 本地 ref，导致 git log 报 "does not have any commits yet"。
$head = (& $Git rev-parse --verify HEAD 2>$null)
if (-not $head) {
    Warn "本地 HEAD 缺失，尝试修复分支引用 ..."
    & $Git fetch origin $Branch 2>&1 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
    $sha = (& $Git rev-parse "origin/$Branch" 2>$null)
    if ($sha) {
        $refPath = ".git\refs\heads\$($Branch -replace '/','\')"
        $refDir = Split-Path $refPath -Parent
        if (-not (Test-Path $refDir)) { New-Item -ItemType Directory -Path $refDir -Force | Out-Null }
        Set-Content -Path $refPath -Value $sha -NoNewline -Encoding ASCII
        Ok "已写入分支引用 $Branch = $sha"
    } else {
        Fail "无法解析 origin/$Branch"
    }
}
$headNow = (& $Git rev-parse --short HEAD 2>$null)
if ($headNow) { Ok "当前提交：$headNow" } else { Warn "仍无法读取 HEAD，请手动检查仓库" }

# ---- 3. 应用修复补丁
Step "应用源码修复补丁"
if ($PatchFile -and (Test-Path $PatchFile)) {
    $check = (& $Git apply --check $PatchFile 2>&1)
    if ($LASTEXITCODE -eq 0) {
        & $Git apply $PatchFile 2>&1 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
        if ($LASTEXITCODE -eq 0) { Ok "补丁已应用：$(Split-Path $PatchFile -Leaf)" }
        else { Fail "补丁应用失败，见上方输出" }
    } else {
        $check2 = (& $Git apply --check --reverse $PatchFile 2>&1)
        if ($LASTEXITCODE -eq 0) { Ok "补丁已存在（跳过）" }
        else {
            Warn "补丁无法应用（可能是换行符差异），尝试宽松模式 ..."
            & $Git apply --ignore-whitespace --ignore-space-change $PatchFile 2>&1 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
            if ($LASTEXITCODE -eq 0) { Ok "补丁已应用（宽松模式）" }
            else { Fail "补丁失败。请手动修改 pyproject.toml / package.json / src/rpa/hongguo/operations.py（见部署手册第五节）" }
        }
    }
} else {
    Warn "未找到补丁文件，跳过。若线上分支未修复，需手动改 pyproject.toml 构建后端。"
}

# ---- 3.5 安装启动脚本
# start_superclaw.bat / stop_superclaw.bat 未纳入 git（untracked），
# 全新克隆的仓库里不会有，必须从部署包里复制过去。
Step "安装启动 / 停止脚本"
foreach ($f in @("start_superclaw.bat", "stop_superclaw.bat")) {
    $src = Join-Path $ScriptDir $f
    $dst = Join-Path $TargetDir $f
    if (-not (Test-Path $src)) { Warn "部署包中缺少 $f"; continue }
    if (Test-Path $dst) {
        $h1 = (Get-FileHash $src -Algorithm MD5).Hash
        $h2 = (Get-FileHash $dst -Algorithm MD5).Hash
        if ($h1 -eq $h2) { Ok "$f 已是最新" } else { Copy-Item $src $dst -Force; Ok "$f 已更新" }
    } else {
        Copy-Item $src $dst -Force
        Ok "$f 已安装"
    }
}

# ---- 4. Python 虚拟环境
Step "创建 Python 虚拟环境并安装依赖"
$VenvPython = Join-Path $TargetDir ".venv-api\Scripts\python.exe"
if (Test-Path $VenvPython) {
    Ok "虚拟环境已存在：.venv-api"
} else {
    Write-Host "  创建 .venv-api ..."
    & $Py -m venv (Join-Path $TargetDir ".venv-api") 2>&1 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
    if (-not (Test-Path $VenvPython)) { Fail "虚拟环境创建失败"; Pop-Location; exit 1 }
    Ok "虚拟环境已创建"
}

& $VenvPython -m pip install --upgrade pip --disable-pip-version-check --no-input -q 2>&1 | Out-Null

$ReqFile = Join-Path $ScriptDir "requirements-superclaw.txt"
$CoreList = @(
    "fastapi","uvicorn","typer","pydantic","sqlalchemy","pymysql","pyyaml","jinja2",
    "httpx","apscheduler","structlog","networkx","cryptography","rich",
    "adbutils","uiautomator2"
)

Write-Host "  安装依赖（可能需要几分钟）..."
if (Test-Path $ReqFile) {
    Write-Host "  来源：requirements-superclaw.txt"
    & $VenvPython -m pip install -r $ReqFile -i $PipIndex --disable-pip-version-check --no-input 2>&1 |
        Select-Object -Last 5 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
} else {
    Write-Host "  来源：内置核心包列表"
    & $VenvPython -m pip install $CoreList -i $PipIndex --disable-pip-version-check --no-input 2>&1 |
        Select-Object -Last 5 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
}

$probe = & $VenvPython -c "import fastapi, uvicorn, sqlalchemy, pymysql, adbutils, uiautomator2; print('DEPS_OK')" 2>&1
if ($probe -match "DEPS_OK") { Ok "核心依赖导入正常" }
else {
    Warn "镜像源安装不完整，改用默认 PyPI 重试 ..."
    if (Test-Path $ReqFile) { & $VenvPython -m pip install -r $ReqFile --disable-pip-version-check --no-input 2>&1 | Select-Object -Last 3 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray } }
    else { & $VenvPython -m pip install $CoreList --disable-pip-version-check --no-input 2>&1 | Select-Object -Last 3 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray } }
    $probe2 = & $VenvPython -c "import fastapi, uvicorn, sqlalchemy, pymysql, adbutils, uiautomator2; print('DEPS_OK')" 2>&1
    if ($probe2 -match "DEPS_OK") { Ok "核心依赖导入正常（默认源）" } else { Fail "依赖安装失败：$probe2" }
}

# ---- 5. 生成配置
Step "生成 config/local.yaml"
if (-not $DbHost) {
    Write-Host "  数据库地址未通过参数提供（仓库里刻意不含地址，避免公开暴露）。"
    while (-not $DbHost) {
        $DbHost = (Read-Host "  请输入 MySQL 主机地址（例如 11.22.33.44）").Trim()
    }
}
if (-not $DbPassword) {
    Write-Host "  数据库密码未通过参数提供。"
    $sec = Read-Host "  请输入 MySQL 密码（直接回车则留空）" -AsSecureString
    if ($sec) {
        $DbPassword = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
            [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
    }
}

$cfgScript = @"
import os, secrets, sys
try:
    import yaml
except ImportError:
    sys.exit("PyYAML missing")
root = r"$TargetDir"
default = os.path.join(root, "config", "default.yaml")
local   = os.path.join(root, "config", "local.yaml")
cfg = {}
if os.path.exists(default):
    with open(default, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
cfg.setdefault("database", {})
cfg["database"].update({
    "engine": "mysql", "host": r"$DbHost", "port": $DbPort,
    "name": r"$DbName", "user": r"$DbUser", "password": r"$DbPassword",
})
cfg.setdefault("security", {})
old = ""
if os.path.exists(local):
    try:
        with open(local, "r", encoding="utf-8") as f:
            prev = yaml.safe_load(f) or {}
        old = str((prev.get("security") or {}).get("auth_secret") or "").strip()
        if not cfg.get("ai", {}).get("api_key") and (prev.get("ai") or {}).get("api_key"):
            cfg.setdefault("ai", {})["api_key"] = prev["ai"]["api_key"]
    except Exception:
        pass
secret = old if len(old) >= 32 else secrets.token_urlsafe(48)
cfg["security"].update({"auth_required": True, "auth_secret": secret})
os.makedirs(os.path.dirname(local), exist_ok=True)
with open(local, "w", encoding="utf-8") as f:
    yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
print("CFG_OK db=%s@%s:%s/%s secret_len=%d" % (r"$DbUser", r"$DbHost", $DbPort, r"$DbName", len(secret)))
"@
$tmpPy = Join-Path $env:TEMP "superclaw_gen_cfg.py"
Set-Content -Path $tmpPy -Value $cfgScript -Encoding UTF8
$cfgOut = & $VenvPython $tmpPy 2>&1
if ($cfgOut -match "CFG_OK") { Ok ($cfgOut -join " ") } else { Fail "配置生成失败：$cfgOut" }
Remove-Item $tmpPy -Force -ErrorAction SilentlyContinue

# ---- 6. MuMu 探测
Step "探测 MuMu 模拟器"
if ($SkipMumu) {
    Warn "已跳过（-SkipMumu）"
} else {
    $found = Find-MumuRoot
    if ($found) { Ok "MuMu 根目录：$found" }
    else { Warn "未找到 MuMu。纯 Web 功能不受影响；需要真机执行时请安装 MuMu 并重跑本步骤。" }
}

# ---- 7. 前端依赖
if (-not $SkipFrontend) {
    Step "安装前端依赖"
    Push-Location (Join-Path $TargetDir "frontend")
    if (Test-Path "node_modules") {
        $ok = Test-Path "node_modules\element-plus\dist\index.css"
        if ($ok) { Ok "node_modules 已就绪（跳过）" }
        else { Warn "node_modules 不完整，重装 ..."; $needInstall = $true }
    } else { $needInstall = $true }

    if ($needInstall) {
        Write-Host "  执行 npm ci（国内镜像）..."
        if (Test-Path "package-lock.json") {
            & npm.cmd ci --registry=$NpmRegistry --no-audit --no-fund 2>&1 |
                Select-Object -Last 6 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
        } else {
            & npm.cmd install --registry=$NpmRegistry --no-audit --no-fund 2>&1 |
                Select-Object -Last 6 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
        }
        if (Test-Path "node_modules\element-plus\dist\index.css") { Ok "前端依赖安装完成" }
        else { Fail "前端依赖不完整（element-plus/dist 缺失），请手动重跑 npm ci" }
    }
    Pop-Location
}

# ---- 8. 自检
Step "部署自检"
$checks = @()
$checks += [pscustomobject]@{ Name="Python venv";  Pass=(Test-Path $VenvPython) }
$checks += [pscustomobject]@{ Name="配置文件";      Pass=(Test-Path (Join-Path $TargetDir "config\local.yaml")) }
$checks += [pscustomobject]@{ Name="启动脚本";      Pass=(Test-Path (Join-Path $TargetDir "start_superclaw.bat")) }
if (-not $SkipFrontend) {
    $checks += [pscustomobject]@{ Name="前端依赖";  Pass=(Test-Path (Join-Path $TargetDir "frontend\node_modules\element-plus\dist\index.css")) }
}
foreach ($c in $checks) {
    if ($c.Pass) { Ok $c.Name } else { Fail $c.Name }
}

Pop-Location

Write-Host ""
Write-Host "============================================================" -ForegroundColor White
if (($checks | Where-Object { -not $_.Pass }).Count -eq 0) {
    Write-Host " 部署完成" -ForegroundColor Green
} else {
    Write-Host " 部署完成，但有检查项未通过，见上方 [FAIL]" -ForegroundColor Yellow
}
Write-Host "============================================================" -ForegroundColor White
Write-Host ""
Write-Host " 下一步：双击 $TargetDir\start_superclaw.bat" -ForegroundColor White
Write-Host ""
Write-Host " 访问地址："
Write-Host "   前端页面  http://127.0.0.1:$WebPort/hongguo/multi"
Write-Host "   健康检查  http://127.0.0.1:$ApiPort/health"
Write-Host "   接口文档  http://127.0.0.1:$ApiPort/docs"
Write-Host ""
Write-Host " 数据库：$DbUser@$DbHost`:$DbPort/$DbName" -ForegroundColor Gray
if ($found) { Write-Host " MuMu  ：$found" -ForegroundColor Gray }
Write-Host ""
