[CmdletBinding()]
param(
    [int]$ApiPort = 8987,
    [int]$FrontendPort = 3000,
    [switch]$Restart
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$RunDir = Join-Path $ProjectRoot '.run'
$LogDir = Join-Path $ProjectRoot 'logs'

function Test-Port {
    param([int]$Port)
    return [bool](Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
}

function Stop-RecordedProcess {
    param([string]$PidFile)
    if (-not (Test-Path -LiteralPath $PidFile)) { return }
    $processId = [int](Get-Content -LiteralPath $PidFile -Raw)
    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if ($process) { Stop-Process -Id $processId -Force }
    Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
}

if (-not (Test-Path -LiteralPath $Python)) {
    throw 'Python environment is missing. Run .\scripts\bootstrap_windows.ps1 first.'
}
if (-not (Get-Command 'npm.cmd' -ErrorAction SilentlyContinue)) {
    throw 'npm.cmd was not found. Install Node.js 22 LTS.'
}

New-Item -ItemType Directory -Force -Path $RunDir, $LogDir | Out-Null
$ApiPidFile = Join-Path $RunDir 'api.pid'
$FrontendPidFile = Join-Path $RunDir 'frontend.pid'
$configuredMuMuRoot = & $Python -c "import pathlib,yaml; p=pathlib.Path(r'$ProjectRoot')/'config'/'local.yaml'; c=yaml.safe_load(p.read_text(encoding='utf-8')) if p.exists() else {}; print(((c or {}).get('hongguo') or {}).get('mumu_root') or '')"
if ($configuredMuMuRoot) {
    $env:SUPERCLAW_MUMU_ROOT = $configuredMuMuRoot.Trim()
}

if ($Restart) {
    Stop-RecordedProcess $ApiPidFile
    Stop-RecordedProcess $FrontendPidFile
    Start-Sleep -Milliseconds 500
}

if (-not (Test-Port $ApiPort)) {
    $env:SUPERCLAW_API_PORT = [string]$ApiPort
    $env:SUPERCLAW_EXECUTION_MODE = 'embedded'
    $apiProcess = Start-Process -FilePath $Python -ArgumentList 'run_api.py' `
        -WorkingDirectory $ProjectRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $LogDir 'api-dev.out.log') `
        -RedirectStandardError (Join-Path $LogDir 'api-dev.err.log') `
        -PassThru
    Set-Content -LiteralPath $ApiPidFile -Value $apiProcess.Id -Encoding ASCII
}
else {
    Write-Host "API port $ApiPort is already listening; leaving it unchanged."
}

if (-not (Test-Port $FrontendPort)) {
    $frontendDir = Join-Path $ProjectRoot 'frontend'
    $frontendArgs = @('/d', '/s', '/c', "npm.cmd run dev -- --port $FrontendPort")
    $previousApiTarget = $env:VITE_API_TARGET
    $env:VITE_API_TARGET = "http://127.0.0.1:$ApiPort"
    try {
        $frontendProcess = Start-Process -FilePath 'cmd.exe' -ArgumentList $frontendArgs `
            -WorkingDirectory $frontendDir `
            -WindowStyle Hidden `
            -RedirectStandardOutput (Join-Path $LogDir 'frontend-dev.out.log') `
            -RedirectStandardError (Join-Path $LogDir 'frontend-dev.err.log') `
            -PassThru
    }
    finally {
        if ($null -eq $previousApiTarget) {
            Remove-Item Env:VITE_API_TARGET -ErrorAction SilentlyContinue
        }
        else {
            $env:VITE_API_TARGET = $previousApiTarget
        }
    }
    Set-Content -LiteralPath $FrontendPidFile -Value $frontendProcess.Id -Encoding ASCII
}
else {
    Write-Host "Frontend port $FrontendPort is already listening; leaving it unchanged."
}

$deadline = (Get-Date).AddSeconds(60)
$health = $null
do {
    Start-Sleep -Milliseconds 500
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$ApiPort/health" -TimeoutSec 3
    }
    catch {
        $health = $null
    }
} while (-not $health -and (Get-Date) -lt $deadline)

if (-not $health -or $health.status -ne 'ok' -or -not $health.database -or -not $health.task_execution_ready) {
    throw "API did not become healthy. Check logs/api-dev.err.log."
}

Write-Host "API:      http://127.0.0.1:$ApiPort"
Write-Host "Frontend: http://127.0.0.1:$FrontendPort/hongguo/multi"
Write-Host "Health:   status=$($health.status), database=$($health.database), running_tasks=$($health.running_tasks)"
