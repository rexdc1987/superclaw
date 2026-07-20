param(
    [int]$Port = 8980,
    [switch]$RequireAuth
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

Set-Location (Join-Path $ProjectRoot 'frontend')
npm run build

Set-Location $ProjectRoot
$env:SUPERCLAW_API_PORT = [string]$Port
$env:SUPERCLAW_EXECUTION_MODE = 'embedded'
if ($RequireAuth) {
    if (-not $env:SUPERCLAW_AUTH_SECRET -or $env:SUPERCLAW_AUTH_SECRET.Length -lt 32) {
        throw 'SUPERCLAW_AUTH_SECRET must contain at least 32 characters'
    }
    $env:SUPERCLAW_AUTH_REQUIRED = 'true'
}

python run_api.py
