<#
    Add (or refresh) the Windows Firewall rule that lets other computers on the
    LAN reach the SuperClaw dashboard.

    Self-elevating on purpose: Inno installs SuperClaw with PrivilegesRequired=
    lowest so the install directory stays user-writable and the built-in updater
    can replace app/ without a UAC prompt. Only this one step needs admin, so it
    asks for elevation by itself instead of dragging the whole installer up.

        powershell -NoProfile -ExecutionPolicy Bypass -File allow_firewall.ps1
#>
$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path

function Test-Admin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-Admin)) {
    Write-Host '需要管理员权限来添加防火墙规则，正在申请提升…'
    $args = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSCommandPath`"")
    try {
        Start-Process -FilePath 'powershell.exe' -ArgumentList $args -Verb RunAs -Wait
    } catch {
        Write-Host '已取消提升，未修改防火墙。可稍后右键“以管理员身份运行”本脚本。'
    }
    exit 0
}

# The port is configurable, so read it from the instance settings.
$port = 8987
$instance = Join-Path $root 'data\instance.json'
if (Test-Path $instance) {
    try {
        $configured = (Get-Content $instance -Raw -Encoding UTF8 | ConvertFrom-Json).port
        if ($configured) { $port = [int]$configured }
    } catch {
        Write-Host "instance.json 解析失败，回退到默认端口 8987。"
    }
}

$name = "SuperClaw Dashboard ($port)"
Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue |
    Remove-NetFirewallRule -ErrorAction SilentlyContinue

New-NetFirewallRule `
    -DisplayName $name `
    -Description '允许局域网内其他电脑访问 SuperClaw 控制台' `
    -Direction Inbound `
    -Action Allow `
    -Protocol TCP `
    -LocalPort $port `
    -Profile Domain,Private | Out-Null

Write-Host ""
Write-Host "  已放行 TCP $port 端口（仅域/专用网络配置）。"
Write-Host "  其他电脑现在可以访问 http://<本机IP>:$port/"
Write-Host ""
