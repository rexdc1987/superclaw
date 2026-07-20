param(
    [Parameter(Mandatory = $true)][string]$WorkerId,
    [string]$WorkerName = $WorkerId
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

if (-not $env:SUPERCLAW_DB_HOST) { throw 'SUPERCLAW_DB_HOST is required' }
if (-not $env:SUPERCLAW_DB_PASSWORD) { throw 'SUPERCLAW_DB_PASSWORD is required' }

$env:SUPERCLAW_WORKER_ID = $WorkerId
$env:SUPERCLAW_WORKER_NAME = $WorkerName
$env:SUPERCLAW_EXECUTION_MODE = 'worker'

Set-Location $ProjectRoot
python run_worker.py
