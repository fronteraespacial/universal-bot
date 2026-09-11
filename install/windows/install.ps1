# Scaffold a Universal Bot instance on Windows Server / PC.
# Does not download secrets. Does not start a Discord gateway.
param(
  [Parameter(Mandatory = $true)]
  [ValidatePattern('^[a-z0-9_-]+$')]
  [string]$Instance,
  [string]$Prefix = "C:\universal-bot"
)

$ErrorActionPreference = "Stop"
$Src = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$Dest = Join-Path $Prefix "instances\$Instance"
$CfgDir = Join-Path $env:USERPROFILE ".config\universal-bot"
$EnvFile = Join-Path $CfgDir "$Instance.env"

New-Item -ItemType Directory -Force -Path $Dest, $CfgDir, (Join-Path $Prefix "logs"), (Join-Path $Prefix "jobs") | Out-Null

$toml = Join-Path $Dest "instance.toml"
if (-not (Test-Path $toml)) {
  $example = Get-Content -Raw (Join-Path $Src "config\instance.example.toml")
  $example = $example -replace "example-site", $Instance
  $example = $example -replace 'host_os = "linux"', 'host_os = "windows"'
  $example = $example -replace 'install_dir = "/opt/universal-bot"', 'install_dir = "C:\\\\universal-bot"'
  $example = $example -replace 'python = "python3"', 'python = "py -3"'
  Set-Content -Path $toml -Value $example -Encoding UTF8
}

if (-not (Test-Path $EnvFile)) {
  @"
# icacls owner-only. Never commit. Never paste in Discord.
DISCORD_BOT_TOKEN=
CONTEXT7_API_KEY=
"@ | Set-Content -Path $EnvFile -Encoding UTF8
  icacls $EnvFile /inheritance:r /grant:r "${env:USERNAME}:(R,W)" | Out-Null
}

Write-Host "instancia: $Dest"
Write-Host "secrets:   $EnvFile  (completar a mano)"
Write-Host "siguiente: editar instance.toml y pegar token en el .env"
Write-Host "luego:     un solo gateway vivo en este host"
Write-Host "Python:    CPython oficial (winget Python.Python.3.12), no alias Store"
