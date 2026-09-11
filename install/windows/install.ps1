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

New-Item -ItemType Directory -Force -Path $Dest, $CfgDir, (Join-Path $Dest "state\logs"), (Join-Path $Dest "state\jobs"), (Join-Path $Dest "state\locks"), (Join-Path $Dest "workspaces") | Out-Null

$toml = Join-Path $Dest "instance.toml"
if (-not (Test-Path $toml)) {
  $example = Get-Content -Raw (Join-Path $Src "config\instance.example.toml")
  $example = $example -replace "example-site", $Instance
  $example = $example -replace 'host_os = "auto"', 'host_os = "windows"'
  $example = $example -replace 'python_cmd = \["python3"\]', 'python_cmd = ["py", "-3"]'
  $escapedEnv = $EnvFile -replace '\\', '\\'
  $example = $example -replace '\./secrets\.env', $escapedEnv
  $utf8NoBom = New-Object System.Text.UTF8Encoding $False
  [System.IO.File]::WriteAllText($toml, $example, $utf8NoBom)
}

if (-not (Test-Path $EnvFile)) {
  $envContent = @"
# icacls owner-only. Never commit. Never paste in Discord.
DISCORD_BOT_TOKEN=
CONTEXT7_API_KEY=
"@
  $utf8NoBom = New-Object System.Text.UTF8Encoding $False
  [System.IO.File]::WriteAllText($EnvFile, $envContent, $utf8NoBom)
  icacls $EnvFile /inheritance:r /grant:r "${env:USERNAME}:(R,W)" | Out-Null
}

Write-Host "instancia: $Dest"
Write-Host "secrets:   $EnvFile  (completar a mano)"
Write-Host "siguiente: editar instance.toml y pegar token en el .env"
Write-Host "luego:     un solo gateway vivo en este host"
Write-Host "Python:    CPython oficial (winget Python.Python.3.12), no alias Store"
