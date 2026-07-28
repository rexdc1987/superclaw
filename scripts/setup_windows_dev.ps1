[CmdletBinding()]
param(
    [switch]$SkipFrontend,
    [switch]$SkipPlaywright
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$VenvPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'

function Require-Command {
    param([Parameter(Mandatory = $true)][string]$Name)

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command was not found: $Name"
    }
}

Require-Command 'py'

Set-Location $ProjectRoot
& py -3.11 -c "import sys; print(sys.version)"
if ($LASTEXITCODE -ne 0) {
    throw 'Python 3.11 is required. Install it from python.org and enable the py launcher.'
}

if (-not (Test-Path -LiteralPath $VenvPython)) {
    & py -3.11 -m venv .venv
}

& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r requirements-dev.txt
& $VenvPython -m pip install -e .

if (-not $SkipPlaywright) {
    & $VenvPython -m playwright install chromium
}

if (-not $SkipFrontend) {
    Require-Command 'node'
    Require-Command 'npm'
    Push-Location (Join-Path $ProjectRoot 'frontend')
    try {
        & npm.cmd ci
        & npm.cmd run build
    }
    finally {
        Pop-Location
    }
}

Write-Host ''
Write-Host 'Development environment is ready.'
Write-Host 'Next: create config/local.yaml, set required environment variables, and run:'
Write-Host '  .\.venv\Scripts\python.exe run_api.py'
