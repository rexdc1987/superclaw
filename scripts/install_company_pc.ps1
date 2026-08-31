[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$DatabaseHost,
    [int]$DatabasePort = 3306,
    [string]$DatabaseName = 'superclaw',
    [string]$DatabaseUser = 'superclaw',
    [string]$MuMuRoot = '',
    [int]$ApiPort = 8987,
    [int]$FrontendPort = 3000
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Bootstrap = Join-Path $PSScriptRoot 'bootstrap_windows.ps1'

Set-Location $ProjectRoot

$arguments = @{
    DatabaseMode = 'Existing'
    DatabaseHost = $DatabaseHost
    DatabasePort = $DatabasePort
    DatabaseName = $DatabaseName
    DatabaseUser = $DatabaseUser
    ApiPort = $ApiPort
    FrontendPort = $FrontendPort
    Start = $true
}
if ($MuMuRoot) {
    $arguments.MuMuRoot = $MuMuRoot
}

Write-Host 'The database password will be requested securely and stored only in ignored config/local.yaml.'
& $Bootstrap @arguments
if ($LASTEXITCODE -ne 0) {
    throw 'SuperClaw bootstrap failed.'
}

& (Join-Path $ProjectRoot '.venv\Scripts\python.exe') `
    (Join-Path $ProjectRoot 'scripts\hongguo_dev_smoke.py') `
    --api-port $ApiPort `
    --frontend-port $FrontendPort
if ($LASTEXITCODE -ne 0) {
    throw 'SuperClaw startup smoke test failed.'
}

Write-Host ''
Write-Host 'SuperClaw company installation completed.' -ForegroundColor Green
Write-Host "Open: http://127.0.0.1:$FrontendPort/hongguo/multi"
