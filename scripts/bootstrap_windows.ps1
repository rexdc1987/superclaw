[CmdletBinding()]
param(
    [ValidateSet('Auto', 'Existing')][string]$DatabaseMode = 'Auto',
    [string]$DatabaseHost = '127.0.0.1',
    [int]$DatabasePort = 3308,
    [string]$DatabaseName = 'superclaw',
    [string]$DatabaseUser = 'superclaw',
    [string]$DatabasePassword = '',
    [string]$DatabaseRootPassword = '',
    [string]$MuMuRoot = '',
    [int]$ApiPort = 8987,
    [int]$FrontendPort = 3000,
    [switch]$SkipPlaywright,
    [switch]$SkipTests,
    [switch]$Start
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$VenvDir = Join-Path $ProjectRoot '.venv'
$VenvPython = Join-Path $VenvDir 'Scripts\python.exe'
$DevMySqlEnvFile = Join-Path $ProjectRoot 'config\dev-mysql.env'

function Require-Command {
    param([string]$Name, [string]$InstallHint)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "$Name was not found. $InstallHint"
    }
}

function Find-Python {
    $py = Get-Command 'py.exe' -ErrorAction SilentlyContinue
    if ($py) {
        & $py.Source -3.11 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'
        if ($LASTEXITCODE -eq 0) {
            return [PSCustomObject]@{ Executable = $py.Source; Arguments = @('-3.11') }
        }
    }
    foreach ($name in @('python.exe', 'python3.exe')) {
        $python = Get-Command $name -ErrorAction SilentlyContinue
        if (-not $python) { continue }
        & $python.Source -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'
        if ($LASTEXITCODE -eq 0) {
            return [PSCustomObject]@{ Executable = $python.Source; Arguments = @() }
        }
    }
    throw 'Python 3.11+ was not found. Install it with: winget install -e --id Python.Python.3.11'
}

function Require-NodeVersion {
    $versionText = (& node.exe --version).Trim().TrimStart('v')
    $majorVersion = [int]($versionText.Split('.')[0])
    if ($majorVersion -lt 22) {
        throw "Node.js 22+ is required; found $versionText. Install it with: winget install -e --id OpenJS.NodeJS.LTS"
    }
}

function New-RandomPassword {
    $bytes = New-Object byte[] 24
    $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generator.GetBytes($bytes) }
    finally { $generator.Dispose() }
    return ([Convert]::ToBase64String($bytes) -replace '[^a-zA-Z0-9]', '').Substring(0, 24)
}

function Wait-MySqlContainer {
    param([string]$ContainerName)
    $deadline = (Get-Date).AddMinutes(3)
    do {
        Start-Sleep -Seconds 2
        $status = (& docker inspect --format '{{.State.Health.Status}}' $ContainerName 2>$null)
        if ($status -eq 'healthy') { return }
    } while ((Get-Date) -lt $deadline)
    & docker logs $ContainerName --tail 80
    throw "MySQL container $ContainerName did not become healthy."
}

function Test-DockerEngine {
    try {
        & docker info 1>$null 2>$null
        return $LASTEXITCODE -eq 0
    }
    catch {
        return $false
    }
}

function Test-LocalPort {
    param([int]$Port)
    return [bool](Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
}

function Read-KeyValueFile {
    param([string]$Path)
    $values = @{}
    if (-not (Test-Path -LiteralPath $Path)) { return $values }
    foreach ($line in Get-Content -LiteralPath $Path) {
        if (-not $line -or $line.TrimStart().StartsWith('#')) { continue }
        $parts = $line.Split('=', 2)
        if ($parts.Count -eq 2) { $values[$parts[0].Trim()] = $parts[1] }
    }
    return $values
}

Set-Location $ProjectRoot
Require-Command 'git.exe' 'Install it with: winget install -e --id Git.Git'
Require-Command 'node.exe' 'Install Node.js 22 LTS with: winget install -e --id OpenJS.NodeJS.LTS'
Require-Command 'npm.cmd' 'Reinstall Node.js 22 LTS.'
Require-NodeVersion

$pythonCommand = Find-Python
if (-not (Test-Path -LiteralPath $VenvPython)) {
    $pythonArguments = @($pythonCommand.Arguments) + @('-m', 'venv', $VenvDir)
    & $pythonCommand.Executable @pythonArguments
    if ($LASTEXITCODE -ne 0) { throw 'Failed to create .venv.' }
}

& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r requirements-dev.txt
& $VenvPython -m pip install -e .
if (-not $SkipPlaywright) {
    & $VenvPython -m playwright install chromium
}

Push-Location (Join-Path $ProjectRoot 'frontend')
try {
    & npm.cmd ci
    & npm.cmd run build
}
finally {
    Pop-Location
}

if ($DatabaseMode -eq 'Auto') {
    Require-Command 'docker.exe' 'Install Docker Desktop, start it, then rerun this script; or use -DatabaseMode Existing.'
    if (-not (Test-DockerEngine)) {
        throw 'Docker Desktop is installed but its Linux engine is not running.'
    }
    if ($DatabaseHost -notin @('127.0.0.1', 'localhost')) {
        throw 'Auto database mode creates a local container; use DatabaseHost 127.0.0.1 or localhost.'
    }

    $savedDatabase = Read-KeyValueFile $DevMySqlEnvFile
    if (-not $DatabasePassword -and $savedDatabase.ContainsKey('SUPERCLAW_DB_PASSWORD')) {
        $DatabasePassword = $savedDatabase['SUPERCLAW_DB_PASSWORD']
    }
    if (-not $DatabaseRootPassword -and $savedDatabase.ContainsKey('SUPERCLAW_DB_ROOT_PASSWORD')) {
        $DatabaseRootPassword = $savedDatabase['SUPERCLAW_DB_ROOT_PASSWORD']
    }
    if (-not $DatabasePassword) {
        $DatabasePassword = (& $VenvPython -c "import pathlib,yaml; p=pathlib.Path(r'$ProjectRoot')/'config'/'local.yaml'; c=yaml.safe_load(p.read_text(encoding='utf-8')) if p.exists() else {}; print(((c or {}).get('database') or {}).get('password') or '')").Trim()
    }
    if (-not $DatabasePassword) { $DatabasePassword = New-RandomPassword }
    if (-not $DatabaseRootPassword) { $DatabaseRootPassword = New-RandomPassword }

    $containerPort = ''
    try {
        $containerPort = (& docker port superclaw-dev-mysql 3306/tcp 2>$null | Select-Object -First 1)
    }
    catch {
        $containerPort = ''
    }
    $portOwnedByContainer = $containerPort -and $containerPort.Trim().EndsWith(":$DatabasePort")
    if ((Test-LocalPort $DatabasePort) -and -not $portOwnedByContainer) {
        throw "Database port $DatabasePort is already used by another process. Stop it or rerun with -DatabasePort <free-port>."
    }

    @(
        "SUPERCLAW_DB_PASSWORD=$DatabasePassword"
        "SUPERCLAW_DB_ROOT_PASSWORD=$DatabaseRootPassword"
    ) | Set-Content -LiteralPath $DevMySqlEnvFile -Encoding ASCII
    $env:SUPERCLAW_DB_PORT = [string]$DatabasePort
    $env:SUPERCLAW_DB_NAME = $DatabaseName
    $env:SUPERCLAW_DB_USER = $DatabaseUser
    $env:SUPERCLAW_DB_PASSWORD = $DatabasePassword
    $env:SUPERCLAW_DB_ROOT_PASSWORD = $DatabaseRootPassword
    & docker compose -f docker/docker-compose.dev.yml up -d
    if ($LASTEXITCODE -ne 0) { throw 'Failed to start the development MySQL container.' }
    Wait-MySqlContainer 'superclaw-dev-mysql'
}
elseif (-not $DatabasePassword) {
    $securePassword = Read-Host 'Existing MySQL password for the SuperClaw user' -AsSecureString
    $credential = New-Object Management.Automation.PSCredential('unused', $securePassword)
    $DatabasePassword = $credential.GetNetworkCredential().Password
}

if (-not $MuMuRoot) {
    foreach ($candidate in @(
        'D:\Program Files\Netease\MuMu',
        'C:\Program Files\Netease\MuMu'
    )) {
        if (Test-Path -LiteralPath (Join-Path $candidate 'nx_main\MuMuManager.exe')) {
            $MuMuRoot = $candidate
            break
        }
    }
}

$env:SUPERCLAW_SETUP_DB_PASSWORD = $DatabasePassword
& $VenvPython scripts/configure_local.py `
    --db-host $DatabaseHost `
    --db-port $DatabasePort `
    --db-name $DatabaseName `
    --db-user $DatabaseUser `
    --mumu-root $MuMuRoot

$env:SUPERCLAW_DB_HOST = $DatabaseHost
$env:SUPERCLAW_DB_PORT = [string]$DatabasePort
$env:SUPERCLAW_DB_NAME = $DatabaseName
$env:SUPERCLAW_DB_USER = $DatabaseUser
$env:SUPERCLAW_DB_PASSWORD = $DatabasePassword
if ($MuMuRoot) { $env:SUPERCLAW_MUMU_ROOT = $MuMuRoot }

& $VenvPython scripts/init_hongguo_mysql.py
if ($LASTEXITCODE -ne 0) { throw 'Database schema initialization failed.' }

if (-not $SkipTests) {
    & $VenvPython -m pytest tests/test_hongguo_templates.py tests/test_server_security.py -q
    if ($LASTEXITCODE -ne 0) { throw 'Quick regression tests failed.' }
}

Write-Host ''
Write-Host 'SuperClaw bootstrap completed.' -ForegroundColor Green
Write-Host "Project:  $ProjectRoot"
Write-Host "Database: ${DatabaseHost}:$DatabasePort/$DatabaseName"
Write-Host ("MuMu:    " + $(if ($MuMuRoot) { $MuMuRoot } else { 'not detected; install MuMu before device tests' }))
Write-Host 'Secrets are stored only in ignored config/local.yaml.'

if ($Start) {
    & (Join-Path $PSScriptRoot 'start_windows_dev.ps1') -ApiPort $ApiPort -FrontendPort $FrontendPort
}
else {
    Write-Host 'Start services with:'
    Write-Host "  .\scripts\start_windows_dev.ps1 -ApiPort $ApiPort -FrontendPort $FrontendPort"
}

foreach ($name in @(
    'SUPERCLAW_SETUP_DB_PASSWORD',
    'SUPERCLAW_DB_PASSWORD',
    'SUPERCLAW_DB_ROOT_PASSWORD'
)) {
    Remove-Item "Env:$name" -ErrorAction SilentlyContinue
}
