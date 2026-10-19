# Windows Scheduled Task notes + script for shared `opencode serve`.
# Bind 127.0.0.1 only. Do not store API keys or serve passwords in this file.
#
# Manual once (elevated PowerShell optional for all-users task):
#   .\opencode-serve-task.ps1 -Install
#   .\opencode-serve-task.ps1 -Ensure   # watchdog-style health + restart
#
# Prefer WSL for full PTY parity; on native Windows without pywinpty,
# Universal Bot falls back to serve-only (see docs/opencode-v2.md).

param(
  [switch]$Install,
  [switch]$Ensure,
  [string]$HostName = "127.0.0.1",
  [int]$Port = 49374,
  [string]$Bin = "opencode",
  [string]$TaskName = "UB-OpenCode-Serve"
)

$ErrorActionPreference = "Stop"

if ($HostName -ne "127.0.0.1" -and $HostName -ne "localhost") {
  Write-Error "refuse non-loopback host: $HostName"
}

$HealthUrl = "http://${HostName}:${Port}/global/health"
$ActionArgs = "serve --hostname $HostName --port $Port"

function Test-ServeHealthy {
  try {
    $r = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 3
    return $r.StatusCode -eq 200
  } catch {
    return $false
  }
}

if ($Install) {
  $action = New-ScheduledTaskAction -Execute $Bin -Argument $ActionArgs
  $trigger = New-ScheduledTaskTrigger -AtLogOn
  $settings = New-ScheduledTaskSettingsSet -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries
  Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
  Start-ScheduledTask -TaskName $TaskName
  Write-Host "installed task $TaskName → $ActionArgs"
  return
}

if ($Ensure) {
  if (Test-ServeHealthy) {
    Write-Host "ok $HealthUrl"
    return
  }
  try {
    Start-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
  } catch {}
  Start-Sleep -Seconds 2
  if (Test-ServeHealthy) {
    Write-Host "restarted ok $HealthUrl"
    return
  }
  # CLI fallback (no password echoed)
  Start-Process -FilePath $Bin -ArgumentList $ActionArgs -WindowStyle Hidden
  Start-Sleep -Seconds 2
  if (Test-ServeHealthy) {
    Write-Host "cli started ok $HealthUrl"
    return
  }
  Write-Error "unhealthy $HealthUrl"
}

Write-Host @"
Usage:
  -Install   Register Scheduled Task at logon (loopback serve)
  -Ensure    Healthcheck + restart hook for a watchdog
Env: UB_OPENCODE_PORT / UB_OPENCODE_HOST (helpers default 49374 / 127.0.0.1)
Password: set via `opencode service set password` on this host; never commit it.
"@
